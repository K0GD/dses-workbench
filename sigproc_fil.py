#!/usr/bin/env python3
"""
sigproc_fil.py -- DSES shared SIGPROC filterbank core.

This is the single, OS-neutral home for the validated I/Q -> SIGPROC ``.fil``
logic. It is imported identically by:

  * ``iq_to_fil.py``        -- the offline ``.cf32`` -> ``.fil`` converter
                               (and, later, PulsarLab's ``engine/convert.py``);
  * the RFI spectrum analyzer -- which records ``.fil`` *live* alongside its
                               existing raw-I/Q (SigMF) recording;
  * ``engine/capture.py``   -- the future real-dish capture front-end.

Everything here is pure Python / numpy with explicit little-endian packing and
no OS-specific calls, so the same bytes come out on Linux, macOS, and Windows.

Two ways to produce a ``.fil`` from the same channelizer:

  * :func:`write_fil` -- offline, whole-array: channelize an entire I/Q buffer
    and write the file in one shot (what ``iq_to_fil.py`` has always done).
  * :class:`FilterbankWriter` -- streaming: push I/Q chunks as they arrive and
    the channelized power is appended to an already-open ``.fil``. With
    ``integrate=1`` and ``nbits=32`` the streamed bytes are *identical* to the
    offline :func:`write_fil` output on the same input, which is what pins the
    live analyzer path to the validated offline converter.

A thin GNU Radio sink (:class:`FilterbankSink`) wraps :class:`FilterbankWriter`
so a flowgraph can write a ``.fil`` straight off an SDR (or a File Source). It
is only defined when GNU Radio is importable, so this module stays usable for
pure offline conversion in environments without GNU Radio.

The header is tagged ``telescope_id = 12`` so the DSES processing side routes
it VLA -> observatory 'c' -> Haswell.
"""

import re
import struct
from pathlib import Path

import numpy as np

# MJD of the Unix epoch (1970-01-01T00:00:00 UTC).
_UNIX_EPOCH_MJD = 40587.0


def unix_to_mjd(unix_seconds):
    """Convert a Unix timestamp (seconds) to Modified Julian Date (UTC)."""
    return unix_seconds / 86400.0 + _UNIX_EPOCH_MJD


# ---------------------------------------------------------------------------
# SIGPROC header writing / reading
# ---------------------------------------------------------------------------
def _str(s):
    b = s.encode("ascii")
    return struct.pack("<i", len(b)) + b


def _kv_int(name, val):
    return _str(name) + struct.pack("<i", int(val))


def _kv_dbl(name, val):
    return _str(name) + struct.pack("<d", float(val))


_PSR_DESIG_RE = re.compile(
    r'^(?:PSR[\s_]*)?[BJ][\s_]*'
    r'(\d{2})(\d{2})(\d{2}(?:\.\d+)?)?'    # RA:  HH MM [SS[.s]]
    r'[\s_]*([+-])[\s_]*'                      # sign
    r'(\d{2})(\d{2})?(\d{2}(?:\.\d+)?)?',   # Dec: DD [MM [SS[.s]]]
    re.IGNORECASE)


def radec_from_name(name):
    """Best-effort (src_raj, src_dej) in SIGPROC packed sexagesimal from a pulsar
    designation -- the name encodes its own position (IAU convention):

        'B0329+54'          -> (32900.0,  540000.0)      # 03:29,      +54
        'J0332+5434'        -> (33200.0,  543400.0)      # 03:32,      +54:34
        'J033259.37+543443' -> (33259.37, 543443.0)      # 03:32:59.37, +54:34:43
        'J1935-1408'        -> (193500.0, -140800.0)

    SIGPROC packs RA as HHMMSS.sss and Dec as (+/-)DDMMSS.sss into a float, which
    is exactly the name's digit layout. Returns (0.0, 0.0) for anything that
    isn't a recognizable B/J designation (e.g. 'capture', 'Sun', ''). B-name
    coordinates are B1950 (approximate read as J2000) -- enough to give
    PRESTO/prepfold a pointing without a catalog; pass src_raj/src_dej explicitly
    to override with exact (e.g. catalog) coordinates."""
    m = _PSR_DESIG_RE.match((name or "").strip())
    if not m:
        return (0.0, 0.0)
    hh, mm, ss, sign, dd, dm, ds = m.groups()
    raj = float(hh) * 1e4 + float(mm) * 1e2 + (float(ss) if ss else 0.0)
    dej = float(dd) * 1e4 + (float(dm) if dm else 0.0) * 1e2 + (float(ds) if ds else 0.0)
    return (raj, -dej if sign == '-' else dej)


def sigproc_header(*, source_name, fch1, foff, nchans, nbits, tstart, tsamp,
                   telescope_id=12, machine_id=0, src_raj=0.0, src_dej=0.0,
                   rawdatafile="sim.fil"):
    """Build a SIGPROC filterbank header byte string.

    telescope_id defaults to 12 (VLA) -- the value the DSES processing side
    maps to observatory 'c' = Haswell. data_type=1 means filterbank, nifs=1
    means one IF/polarization in the written data (pols already summed).
    """
    # If coordinates weren't supplied, derive an approximate RA/Dec from the
    # source name (pulsar B/J designations encode their own position) so
    # PRESTO/prepfold get a pointing. Explicit non-zero coordinates win.
    if not src_raj and not src_dej:
        src_raj, src_dej = radec_from_name(source_name)
    h = _str("HEADER_START")
    h += _kv_int("telescope_id", telescope_id)   # 12 -> VLA -> Haswell
    h += _kv_int("machine_id", machine_id)        # 0
    h += _kv_int("data_type", 1)                   # 1 = filterbank
    h += _str("rawdatafile") + _str(rawdatafile)
    h += _str("source_name") + _str(source_name)
    h += _kv_int("barycentric", 0)                 # topocentric
    h += _kv_int("pulsarcentric", 0)
    h += _kv_dbl("src_raj", src_raj)               # 00:00:00 for the simulator
    h += _kv_dbl("src_dej", src_dej)
    h += _kv_dbl("az_start", 0.0)
    h += _kv_dbl("za_start", 0.0)
    h += _kv_dbl("fch1", fch1)                      # MHz, first (highest) channel
    h += _kv_dbl("foff", foff)                      # MHz, negative => band high->low
    h += _kv_int("nchans", nchans)
    h += _kv_int("nbits", nbits)
    h += _kv_int("nbeams", 1)
    h += _kv_int("ibeam", 1)
    h += _kv_dbl("tstart", tstart)                  # MJD of first sample
    h += _kv_dbl("tsamp", tsamp)                    # seconds
    h += _kv_int("nifs", 1)
    h += _str("HEADER_END")
    return h


def read_sigproc_header(path):
    """Minimal reader so we can verify what we wrote (no PRESTO needed)."""
    out = {}
    with open(path, "rb") as f:
        def rd_str():
            (n,) = struct.unpack("<i", f.read(4))
            return f.read(n).decode("ascii")
        assert rd_str() == "HEADER_START"
        int_keys = {"telescope_id", "machine_id", "data_type", "barycentric",
                    "pulsarcentric", "nchans", "nbits", "nbeams", "ibeam", "nifs"}
        dbl_keys = {"src_raj", "src_dej", "az_start", "za_start", "fch1",
                    "foff", "tstart", "tsamp"}
        str_keys = {"rawdatafile", "source_name"}
        while True:
            key = rd_str()
            if key == "HEADER_END":
                out["_header_bytes"] = f.tell()
                break
            if key in int_keys:
                (out[key],) = struct.unpack("<i", f.read(4))
            elif key in dbl_keys:
                (out[key],) = struct.unpack("<d", f.read(8))
            elif key in str_keys:
                out[key] = rd_str()
            else:
                raise ValueError(f"unknown header key: {key}")
    return out


# ---------------------------------------------------------------------------
# Frequency-axis geometry (shared by the offline and streaming writers)
# ---------------------------------------------------------------------------
def channel_geometry(center_freq_mhz, total_bw_mhz, nchans):
    """Return (fch1, foff) for a band centered at ``center_freq_mhz``.

    SIGPROC stores channel 0 = highest frequency (fch1) and steps *down* by
    foff (< 0). fch1 is the center of the highest channel.
    """
    foff = -total_bw_mhz / nchans                      # negative: band high->low
    fch1 = center_freq_mhz + (nchans / 2 - 0.5) * (total_bw_mhz / nchans)
    return fch1, foff


# ---------------------------------------------------------------------------
# Channelize + detect
# ---------------------------------------------------------------------------
def channelize_detect(iq, nchans, window=True):
    """FFT channelizer: each output time sample is one nchans-point FFT of
    nchans consecutive complex samples, then |.|^2 (power detection).

    Output rate per channel = samp_rate / nchans, so tsamp = nchans/samp_rate,
    matching the memo exactly. Returns float32 array shape (ntime, nchans)
    with channels ordered LOW->HIGH frequency.
    """
    n = (len(iq) // nchans) * nchans
    blocks = iq[:n].reshape(-1, nchans)
    if window:
        blocks = blocks * np.hanning(nchans).astype(np.complex64)
    spec = np.fft.fftshift(np.fft.fft(blocks, axis=1), axes=1)  # low->high freq
    power = (spec.real**2 + spec.imag**2).astype(np.float32)
    return power


def _detect_to_payload(power_low_to_high, nbits):
    """Convert a (ntime, nchans) low->high power block into SIGPROC-ordered
    (channel 0 = highest freq) little-endian bytes.

    nbits=32 is the lossless float path used everywhere validated. nbits=8 uses
    a per-block median/MAD scale -- only meaningful for a whole-file offline
    write (see :func:`write_fil`); it is not used by the streaming writer.
    """
    data_hi_to_lo = power_low_to_high[:, ::-1]        # SIGPROC channel order
    if nbits == 32:
        return data_hi_to_lo.astype("<f4")
    if nbits == 8:
        med = np.median(data_hi_to_lo)
        mad = np.median(np.abs(data_hi_to_lo - med)) + 1e-9
        scaled = (data_hi_to_lo - med) / (8 * mad) * 64 + 96
        return np.clip(scaled, 0, 255).astype(np.uint8)
    raise ValueError("nbits must be 8 or 32")


def write_fil(path, power_low_to_high, *, source_name, center_freq_mhz,
              total_bw_mhz, tstart_mjd, tsamp, nbits=32, telescope_id=12):
    """Write a SIGPROC .fil from an already-channelized (ntime, nchans) power
    array (channels LOW->HIGH; this flips them to SIGPROC's high->low order).
    """
    path = str(path)
    ntime, nchans = power_low_to_high.shape
    fch1, foff = channel_geometry(center_freq_mhz, total_bw_mhz, nchans)
    payload = _detect_to_payload(power_low_to_high, nbits)

    hdr = sigproc_header(source_name=source_name, fch1=fch1, foff=foff,
                         nchans=nchans, nbits=nbits, tstart=tstart_mjd,
                         tsamp=tsamp, telescope_id=telescope_id,
                         rawdatafile=Path(path).name)
    with open(path, "wb") as f:
        f.write(hdr)
        f.write(payload.tobytes())
    return {"fch1": fch1, "foff": foff, "nchans": nchans, "tsamp": tsamp,
            "ntime": ntime, "nbits": nbits}


# ---------------------------------------------------------------------------
# Streaming writer: I/Q chunks in -> .fil grows on disk
# ---------------------------------------------------------------------------
class FilterbankWriter:
    """Channelize live I/Q and append SIGPROC filterbank rows to an open file.

    Feed complex baseband in arbitrary-sized chunks via :meth:`push`; the
    writer channelizes on ``nchans``-sample block boundaries (carrying any
    sub-block remainder to the next push), optionally integrates ``integrate``
    consecutive power frames into one output row, and appends the result.

    With ``integrate == 1`` and ``nbits == 32`` the bytes produced are
    identical to :func:`write_fil` (hence to the offline ``iq_to_fil.py``) on
    the same I/Q -- block boundaries fall at fixed multiples of ``nchans`` from
    sample 0 regardless of how the stream is chunked.

    Streaming is float32-only: the 8-bit path needs whole-file statistics that
    are not available incrementally.

      tsamp = integrate * nchans / samp_rate
    """

    def __init__(self, path, *, nchans, samp_rate, center_freq_mhz,
                 total_bw_mhz=None, tstart_mjd, integrate=1, nbits=32,
                 source_name="capture", window=True, telescope_id=12):
        if nbits != 32:
            raise ValueError("FilterbankWriter supports only nbits=32 "
                             "(8-bit needs whole-file statistics)")
        if integrate < 1:
            raise ValueError("integrate must be >= 1")
        self.path = Path(path)
        self.nchans = int(nchans)
        self.samp_rate = float(samp_rate)
        self.integrate = int(integrate)
        self.window = bool(window)
        self.nbits = nbits
        if total_bw_mhz is None:
            total_bw_mhz = self.samp_rate / 1e6
        self.total_bw_mhz = float(total_bw_mhz)
        self.tsamp = self.integrate * self.nchans / self.samp_rate
        self.fch1, self.foff = channel_geometry(center_freq_mhz,
                                                 self.total_bw_mhz, self.nchans)
        self.nrows = 0
        self._resid = np.empty(0, dtype=np.complex64)
        # Number of input samples that map to exactly one output row.
        self._block = self.nchans * self.integrate

        hdr = sigproc_header(source_name=source_name, fch1=self.fch1,
                             foff=self.foff, nchans=self.nchans, nbits=nbits,
                             tstart=tstart_mjd, tsamp=self.tsamp,
                             telescope_id=telescope_id,
                             rawdatafile=self.path.name)
        self._fh = open(self.path, "wb")
        self._fh.write(hdr)

    def push(self, iq):
        """Channelize and append as many complete output rows as ``iq`` (plus
        any carried remainder) allows. Returns the number of rows written."""
        if self._fh is None:
            raise ValueError("push() after close()")
        iq = np.asarray(iq, dtype=np.complex64).ravel()
        if self._resid.size:
            iq = np.concatenate([self._resid, iq])
        nfull = (len(iq) // self._block) * self._block
        rows = 0
        if nfull:
            power = channelize_detect(iq[:nfull], self.nchans,
                                      window=self.window)   # (frames, nchans)
            if self.integrate > 1:
                nout = power.shape[0] // self.integrate
                power = power[:nout * self.integrate].reshape(
                    nout, self.integrate, self.nchans).sum(axis=1)
            self._fh.write(_detect_to_payload(power, self.nbits).tobytes())
            rows = power.shape[0]
            self.nrows += rows
        self._resid = iq[nfull:].copy()
        return rows

    def close(self):
        """Flush and close. The sub-block remainder is dropped -- exactly what
        the offline whole-array channelizer does with its trailing samples."""
        if self._fh is not None:
            self._fh.flush()
            self._fh.close()
            self._fh = None
        return {"fch1": self.fch1, "foff": self.foff, "nchans": self.nchans,
                "tsamp": self.tsamp, "ntime": self.nrows, "nbits": self.nbits}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


# ---------------------------------------------------------------------------
# Optional GNU Radio sink (only when GNU Radio is importable)
# ---------------------------------------------------------------------------
try:
    from gnuradio import gr  # noqa: E402
    _HAVE_GR = True
except Exception:             # pragma: no cover - environments without GNU Radio
    _HAVE_GR = False


if _HAVE_GR:
    class FilterbankSink(gr.sync_block):
        """GNU Radio sink: complex baseband in -> SIGPROC ``.fil`` on disk.

        A thin adapter over :class:`FilterbankWriter` so a flowgraph (live SDR
        or a File Source) can record a filterbank directly. The channelize and
        write logic lives entirely in :class:`FilterbankWriter`, so the
        standalone analyzer and ``engine/capture.py`` share identical DSP.

        The file is finalized when :meth:`stop` runs (flowgraph stop) or when
        :meth:`close` is called explicitly.
        """

        def __init__(self, path, *, nchans, samp_rate, center_freq_mhz,
                     total_bw_mhz=None, tstart_mjd, integrate=1,
                     source_name="capture", window=True, telescope_id=12):
            gr.sync_block.__init__(self, name="filterbank_sink",
                                   in_sig=[np.complex64], out_sig=None)
            self._writer = FilterbankWriter(
                path, nchans=nchans, samp_rate=samp_rate,
                center_freq_mhz=center_freq_mhz, total_bw_mhz=total_bw_mhz,
                tstart_mjd=tstart_mjd, integrate=integrate,
                source_name=source_name, window=window,
                telescope_id=telescope_id)

        @property
        def path(self):
            return self._writer.path

        @property
        def nrows(self):
            return self._writer.nrows

        def work(self, input_items, output_items):
            n = len(input_items[0])
            if self._writer._fh is not None:
                self._writer.push(input_items[0])
            return n

        def stop(self):
            self.close()
            return True

        def close(self):
            return self._writer.close()
