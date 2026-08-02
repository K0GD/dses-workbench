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

import json
import re
import struct
import threading
import time as _time
from datetime import datetime, timezone
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


def compute_gap_samples(ref_offset, ref_time, tag_offset, tag_time,
                        samp_rate, pads_since_ref):
    """Samples MISSING from the stream at `tag_offset`, given a reference
    (`ref_offset` arrived at radio time `ref_time`) and the total padding
    already inserted since that reference.

    gr-uhd stamps an ``rx_time`` tag on the first sample after every RX
    overflow: real time advanced but the sample index did not, so
        missing = (elapsed real time) * rate - (elapsed input samples)
                  - (already-inserted padding)
    Pure function so the timebase arithmetic is unit-testable without a
    GNU Radio runtime."""
    real_elapsed = (tag_time - ref_time) * samp_rate
    input_elapsed = tag_offset - ref_offset
    return int(round(real_elapsed - input_elapsed - pads_since_ref))


if _HAVE_GR:
    import pmt

    def _parse_rx_time(value):
        """(full_secs, frac_secs) pmt tuple -> float seconds, or None."""
        try:
            if pmt.is_tuple(value) and pmt.length(value) >= 2:
                return (pmt.to_uint64(pmt.tuple_ref(value, 0))
                        + pmt.to_double(pmt.tuple_ref(value, 1)))
        except Exception:
            pass
        return None

    class FilterbankSink(gr.sync_block):
        """GNU Radio sink: complex baseband in -> SIGPROC ``.fil`` on disk.

        A thin adapter over :class:`FilterbankWriter` so a flowgraph (live SDR
        or a File Source) can record a filterbank directly. The channelize and
        write logic lives entirely in :class:`FilterbankWriter`, so the
        standalone analyzer and ``engine/capture.py`` share identical DSP.

        Timebase integrity (v1.1.8): RX overflows silently DROP samples,
        which shortens the file's sample-count clock relative to real time —
        the Haswell B0329+54 recording drifted ~1.2 pulse rotations that way
        (a 0.56 s gap split the folded profile until it was hand-padded, see
        ROADMAP). gr-uhd stamps an ``rx_time`` tag on the first sample after
        each overflow; this sink measures every gap from those tags and
        inserts the exact number of zero samples, so the ``.fil`` timebase
        tracks real time. Sources that never tag (gr-soapy: HackRF, RTL,
        SDRplay) simply record as before — gaps there are counted only via
        the app-level overflow monitor. Gap events are exposed live
        (``gap_events`` / ``gap_seconds``) and written to a ``.gaps.json``
        sidecar on close.

        Threaded (v1.1.9): ``work()`` only reads tags, does the (cheap) gap
        arithmetic, and enqueues data/pad commands; a daemon worker performs
        the channelize/integrate/write DSP. Inline DSP on the GNU Radio
        thread could not keep up at 16 MS/s and caused the very overflows
        this sink exists to survive. If the worker ever falls behind the
        queue bound, the overflowing DATA is replaced by an equivalent-length
        pad command — signal is lost (zeros), but the sample clock NEVER
        breaks (``queue_padded_samples`` counts the loss).

        The file is finalized when :meth:`stop` runs (flowgraph stop) or when
        :meth:`close` is called explicitly.
        """

        # Ignore sub-100 µs "gaps": re-timing jitter, not real drops.
        GAP_MIN_SECONDS = 1e-4
        # Bound on queued DATA samples awaiting the worker (~64 MB).
        MAX_QUEUE_SAMPLES = 1 << 23
        # Per-event and per-recording padding caps: a wedged source must not
        # inflate the file without bound. Beyond the total cap the sink
        # keeps recording but stops padding and flags the timebase broken.
        GAP_EVENT_CAP_SECONDS = 10.0
        GAP_TOTAL_CAP_SECONDS = 60.0
        MAX_EVENTS_LOGGED = 1000

        def __init__(self, path, *, nchans, samp_rate, center_freq_mhz,
                     total_bw_mhz=None, tstart_mjd, integrate=1,
                     source_name="capture", window=True, telescope_id=12,
                     pad_gaps=True):
            gr.sync_block.__init__(self, name="filterbank_sink",
                                   in_sig=[np.complex64], out_sig=None)
            self._writer = FilterbankWriter(
                path, nchans=nchans, samp_rate=samp_rate,
                center_freq_mhz=center_freq_mhz, total_bw_mhz=total_bw_mhz,
                tstart_mjd=tstart_mjd, integrate=integrate,
                source_name=source_name, window=window,
                telescope_id=telescope_id)
            self._pad_gaps = bool(pad_gaps)
            self._rx_time_key = pmt.intern("rx_time")
            self._time_ref = None       # (abs input offset, radio seconds)
            self._pads_since_ref = 0    # samples inserted since the reference
            self._gap_min = max(1, int(round(
                self.GAP_MIN_SECONDS * self._writer.samp_rate)))
            # Live stats (read from the GUI thread; int reads are atomic).
            self.gap_events = 0
            self.gap_samples = 0
            self.timebase_broken = False
            self.queue_padded_samples = 0   # data lost to worker overload
            self._events = []           # dicts for the .gaps.json sidecar
            # Worker-thread queue: ('data', ndarray) / ('pad', nsamples).
            self._q = []
            self._q_samples = 0
            self._qlock = threading.Lock()
            self._stopping = threading.Event()
            self._closed = False
            self._worker = threading.Thread(
                target=self._worker_loop, name="fil-sink-worker", daemon=True)
            self._worker.start()

        @property
        def path(self):
            return self._writer.path

        @property
        def nrows(self):
            return self._writer.nrows

        @property
        def gap_seconds(self):
            return self.gap_samples / self._writer.samp_rate

        # ---- queue plumbing (GR thread side: cheap; worker does the DSP) --
        def _enqueue_data(self, arr):
            n = len(arr)
            if n == 0:
                return
            with self._qlock:
                if self._q_samples + n > self.MAX_QUEUE_SAMPLES:
                    # Worker overloaded: substitute an equivalent-length pad
                    # so the sample clock stays intact (signal lost, counted).
                    self._q.append(('pad', n))
                    self.queue_padded_samples += n
                else:
                    self._q.append(('data', np.array(arr, dtype=np.complex64)))
                    self._q_samples += n

        def _enqueue_pad(self, n):
            if n > 0:
                with self._qlock:
                    self._q.append(('pad', int(n)))   # pads cost no memory

        def _worker_loop(self):
            while not self._stopping.is_set():
                if not self._drain():
                    _time.sleep(0.005)
            self._drain()      # final drain: nothing queued is ever lost

        def _drain(self):
            with self._qlock:
                batch, self._q = self._q, []
                self._q_samples = 0
            if not batch:
                return False
            for kind, item in batch:
                if self._writer._fh is None:
                    break
                if kind == 'data':
                    self._writer.push(item)
                else:
                    self._write_zeros(item)
            return True

        def _write_zeros(self, nsamples):
            """Insert nsamples of complex zeros, chunked to bound memory.
            Worker-thread side."""
            CHUNK = 1 << 20
            remaining = int(nsamples)
            zeros = np.zeros(min(CHUNK, remaining), dtype=np.complex64)
            while remaining > 0:
                take = min(CHUNK, remaining)
                self._writer.push(zeros[:take])
                remaining -= take

        def _handle_gap(self, gap, abs_offset):
            """Account for a measured gap and return the number of samples
            to pad (capped). Runs on the GR thread; the pad itself is
            enqueued for the worker."""
            cap = int(self.GAP_EVENT_CAP_SECONDS * self._writer.samp_rate)
            total_cap = int(self.GAP_TOTAL_CAP_SECONDS * self._writer.samp_rate)
            truncated = gap > cap
            pad = min(gap, cap)
            if self.gap_samples + pad > total_cap:
                pad = max(0, total_cap - self.gap_samples)
                self.timebase_broken = True
            self.gap_events += 1
            self.gap_samples += pad
            if len(self._events) < self.MAX_EVENTS_LOGGED:
                self._events.append({
                    "input_sample": int(abs_offset),
                    "missing_samples": int(gap),
                    "padded_samples": int(pad),
                    "missing_ms": round(gap / self._writer.samp_rate * 1e3, 3),
                    "truncated": bool(truncated),
                    "utc": datetime.now(timezone.utc).isoformat(
                        timespec="seconds"),
                })
            return pad

        def work(self, input_items, output_items):
            buf = input_items[0]
            n = len(buf)
            if self._writer._fh is None or self._closed:
                return n
            if not self._pad_gaps:
                self._enqueue_data(buf)
                return n
            start = self.nitems_read(0)
            tags = self.get_tags_in_window(0, 0, n, self._rx_time_key)
            if not tags:
                self._enqueue_data(buf)
                return n
            seg = 0   # start of the not-yet-enqueued segment (window-relative)
            for tag in sorted(tags, key=lambda t: t.offset):
                t = _parse_rx_time(tag.value)
                if t is None:
                    continue
                if self._time_ref is None:
                    # Stream-start tag: establish the reference, no gap.
                    self._time_ref = (tag.offset, t)
                    self._pads_since_ref = 0
                    continue
                ref_off, ref_t = self._time_ref
                gap = compute_gap_samples(ref_off, ref_t, tag.offset, t,
                                          self._writer.samp_rate,
                                          self._pads_since_ref)
                if gap >= self._gap_min:
                    rel = tag.offset - start
                    self._enqueue_data(buf[seg:rel])
                    seg = rel
                    padded = self._handle_gap(gap, tag.offset)
                    self._enqueue_pad(padded)
                    self._pads_since_ref += padded
            self._enqueue_data(buf[seg:])
            return n

        def stop(self):
            self.close()
            return True

        def close(self):
            if self._closed:
                return getattr(self, '_close_info', None) \
                    or self._writer.close()
            self._closed = True
            self._stopping.set()
            self._worker.join(timeout=15.0)
            info = self._writer.close()
            if info is not None:
                info = dict(info)
                info.update(gap_events=self.gap_events,
                            gap_samples=self.gap_samples,
                            timebase_broken=self.timebase_broken,
                            queue_padded_samples=self.queue_padded_samples)
            if self._events or self.timebase_broken \
                    or self.queue_padded_samples:
                try:
                    sidecar = self._writer.path.with_suffix(
                        self._writer.path.suffix + ".gaps.json")
                    with open(sidecar, "w") as f:
                        json.dump({
                            "file": self._writer.path.name,
                            "samp_rate": self._writer.samp_rate,
                            "gap_events": self.gap_events,
                            "gap_samples_padded": self.gap_samples,
                            "queue_padded_samples": self.queue_padded_samples,
                            "timebase_broken": self.timebase_broken,
                            "note": ("Gaps measured from gr-uhd rx_time "
                                     "overflow tags; each gap zero-padded "
                                     "so the sample clock tracks real "
                                     "time."),
                            "events": self._events,
                        }, f, indent=1)
                except OSError:
                    pass
            self._close_info = info
            return info
