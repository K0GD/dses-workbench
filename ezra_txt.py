#!/usr/bin/env python3
"""
ezra_txt.py -- DSES ezRA drift-scan data writer.

Writes integrated frequency-spectrum rows in the ezRA ``.txt`` data-file
format consumed by Ted Cline's ezRA suite (ezCon -> ezPlot/ezSky/ezGal;
https://github.com/tedcline/ezRA), so the Spectrum Analyzer can act as the
drift-scan data collector for radios ezCol does not drive (the 60-ft dish's
Ettus B210 via UHD).

Format (validated byte-for-byte against the dish's own Nov-2025 ezCol output
and the Aug/Sep-2025 ezColG GNU Radio files in
``~/Documents/DSES/Science/HI_and_Drift_Scan/ezRABase/``):

    from <provenance string>
    lat <deg> long <deg> amsl <m-or-ft> name <observatory>
    freqMin <MHz> freqMax <MHz> freqBinQty <bins>
    azDeg <deg> elDeg <deg>
    # times are in UTC
    # gain <text>
    # frequency spectrums of RMS power in dB
    <YYYY-MM-DDTHH:MM:SS> <bin0dB> <bin1dB> ... <binN-1dB>

Rows are ascending in frequency: bin 0 = freqMin, last bin = freqMax edge.
No trailing flags (4096-bin reference rows have exactly 4097 fields).

Like ezCol (which keeps the central 8 MHz of a 10 MS/s capture), the writer
can trim the anti-alias filter skirts via ``keep_fraction``; freqMin/Max and
freqBinQty always describe the bins actually written.

Pure Python/numpy; the GNU Radio sink is defined only when gnuradio imports,
mirroring sigproc_fil.py.
"""

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy import fft as scipy_fft


def ezra_filename(prefix, utc=None):
    """ezCol-convention file name: <prefix>YYMMDD_HH.txt (UTC)."""
    utc = utc or datetime.now(timezone.utc)
    return f"{prefix}{utc:%y%m%d_%H}.txt"


class EzraTxtWriter:
    """Append ezRA .txt spectrum rows to an open file.

    Feed already-integrated linear-power spectra (ascending frequency,
    ``bin_qty`` bins) via :meth:`write_row`; they are stored as dB.
    """

    def __init__(self, path, *, lat_deg, lon_deg, amsl, site_name,
                 freq_min_mhz, freq_max_mhz, bin_qty, az_deg, el_deg,
                 gain_text="", provenance="DSES_Spectrum_Analyzer"):
        self.path = Path(path)
        self.bin_qty = int(bin_qty)
        self.nrows = 0
        # ezCon.py hard-gates on the first line starting with the literal
        # bytes "from ezCol" (that's why the group's GNU Radio predecessor
        # called itself "ezColG"). Guarantee compatibility regardless of the
        # provenance text supplied.
        if not provenance.startswith("ezCol"):
            provenance = "ezCol-compatible " + provenance
        self._fh = open(self.path, "w", newline="\n")
        self._fh.write(f"from {provenance}\n")
        self._fh.write(f"lat {lat_deg:g} long {lon_deg:g} "
                       f"amsl {amsl:g} name {site_name}\n")
        self._fh.write(f"freqMin {freq_min_mhz:g} freqMax {freq_max_mhz:g} "
                       f"freqBinQty {self.bin_qty}\n")
        self._fh.write(f"azDeg {az_deg:g} elDeg {el_deg:g}\n")
        self._fh.write("# times are in UTC\n")
        self._fh.write(f"# gain {gain_text or 'xx'}\n")
        self._fh.write("# frequency spectrums of RMS power in dB\n")
        self._fh.flush()

    def write_row(self, power_linear, utc=None):
        """Append one spectrum row. `power_linear` is an ascending-frequency
        mean-power array of bin_qty bins; stored as 10*log10(power) dB."""
        p = np.asarray(power_linear, dtype=np.float64)
        if p.size != self.bin_qty:
            raise ValueError(f"expected {self.bin_qty} bins, got {p.size}")
        db = 10.0 * np.log10(np.maximum(p, 1e-30))
        utc = utc or datetime.now(timezone.utc)
        stamp = utc.strftime("%Y-%m-%dT%H:%M:%S")
        self._fh.write(stamp + " " + " ".join(f"{v:.4f}" for v in db) + "\n")
        self.nrows += 1

    def close(self):
        if self._fh is not None:
            self._fh.flush()
            self._fh.close()
            self._fh = None
        return {"path": str(self.path), "nrows": self.nrows,
                "bin_qty": self.bin_qty}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class EzraIntegrator:
    """Channelize live I/Q and hand completed integration rows to a callback.

    FFTs of ``fft_bins`` (no window, matching ezCol), accumulated over
    ``integ_frames`` frames; the central ``keep_fraction`` of the band is
    kept (ezCol practice: central 8 MHz of a 10 MS/s capture) and passed to
    ``on_row(power_linear)`` as ascending-frequency mean power.
    """

    def __init__(self, *, fft_bins, integ_frames, on_row, keep_fraction=1.0):
        self.fft_bins = int(fft_bins)
        self.integ_frames = max(1, int(integ_frames))
        self.keep_fraction = float(keep_fraction)
        keep = int(round(self.fft_bins * self.keep_fraction / 2)) * 2
        keep = max(2, min(self.fft_bins, keep))
        self._lo = (self.fft_bins - keep) // 2
        self._hi = self._lo + keep
        self.kept_bins = keep
        self._on_row = on_row
        self._acc = np.zeros(self.fft_bins, dtype=np.float64)
        self._nacc = 0
        self._resid = np.empty(0, dtype=np.complex64)

    @staticmethod
    def kept_span_mhz(center_mhz, samp_rate, kept_bins, fft_bins):
        """freqMin/freqMax (MHz) of the kept central bins."""
        bw = samp_rate / 1e6
        half_kept = bw * kept_bins / fft_bins / 2.0
        return center_mhz - half_kept, center_mhz + half_kept

    def push(self, iq):
        iq = np.asarray(iq, dtype=np.complex64).ravel()
        if self._resid.size:
            iq = np.concatenate([self._resid, iq])
        nfull = (len(iq) // self.fft_bins) * self.fft_bins
        if nfull:
            # Local channelizer (NOT sigproc_fil.channelize_detect, whose
            # numpy FFT is byte-validated for the .fil path and must not
            # change): scipy's pocketfft with workers=-1 releases the GIL
            # and spreads across cores, which matters here — this runs on
            # the sink's worker thread beside the GNU Radio Python
            # callbacks, and a GIL-bound FFT starved them into RX
            # overflows at 16 MS/s (observed live 2026-08-02).
            blocks = iq[:nfull].reshape(-1, self.fft_bins)
            spec = scipy_fft.fft(blocks, axis=1, workers=-1)
            power = np.fft.fftshift(
                (spec.real.astype(np.float64) ** 2
                 + spec.imag.astype(np.float64) ** 2), axes=1)
            # Bulk accumulation: one vectorized sum per push (plus one per
            # row boundary, which at ~31e3 frames/row is rare). The original
            # per-frame Python loop could not keep up at 16 MS/s and caused
            # RX overflows during recording.
            i, nfr = 0, power.shape[0]
            while i < nfr:
                take = min(self.integ_frames - self._nacc, nfr - i)
                self._acc += power[i:i + take].sum(axis=0, dtype=np.float64)
                self._nacc += take
                i += take
                if self._nacc >= self.integ_frames:
                    mean = self._acc[self._lo:self._hi] / self._nacc
                    self._on_row(mean)
                    self._acc[:] = 0.0
                    self._nacc = 0
        self._resid = iq[nfull:].copy()


try:
    from gnuradio import gr
    import threading
    import time as _time
    _HAVE_GR = True
except Exception:              # pragma: no cover
    _HAVE_GR = False


if _HAVE_GR:
    class EzraTxtSink(gr.sync_block):
        """GNU Radio sink: complex baseband in -> ezRA ``.txt`` rows on disk.

        One output row per ``integ_frames`` FFTs of ``fft_bins`` bins,
        timestamped at row completion (UTC), central ``keep_fraction`` of
        the band kept.

        Threaded: ``work()`` only copies the incoming buffer into a bounded
        queue; a daemon worker does the FFT/integration/writing. Doing the
        DSP inline on the GNU Radio thread caused RX overflows at 16 MS/s
        (observed live 2026-08-02). If the worker ever falls behind the
        queue bound, excess samples are counted in ``dropped_samples``
        (each drop only shortens one ~13 s integration slightly).
        """

        MAX_QUEUE_SAMPLES = 1 << 23    # 8 M samples ≈ 64 MB of backlog

        def __init__(self, path, *, fft_bins, integ_frames, samp_rate,
                     center_freq_mhz, lat_deg, lon_deg, amsl, site_name,
                     az_deg, el_deg, gain_text="", keep_fraction=1.0,
                     provenance="DSES_Spectrum_Analyzer"):
            gr.sync_block.__init__(self, name="ezra_txt_sink",
                                   in_sig=[np.complex64], out_sig=None)
            self._integ = EzraIntegrator(
                fft_bins=fft_bins, integ_frames=integ_frames,
                on_row=self._emit_row, keep_fraction=keep_fraction)
            fmin, fmax = EzraIntegrator.kept_span_mhz(
                center_freq_mhz, samp_rate, self._integ.kept_bins, fft_bins)
            self._writer = EzraTxtWriter(
                path, lat_deg=lat_deg, lon_deg=lon_deg, amsl=amsl,
                site_name=site_name, freq_min_mhz=fmin, freq_max_mhz=fmax,
                bin_qty=self._integ.kept_bins, az_deg=az_deg, el_deg=el_deg,
                gain_text=gain_text, provenance=provenance)
            self.dropped_samples = 0
            self._q = []
            self._q_samples = 0
            self._lock = threading.Lock()
            self._stopping = threading.Event()
            self._closed = False
            self._worker = threading.Thread(
                target=self._worker_loop, name="ezra-txt-worker", daemon=True)
            self._worker.start()

        def _emit_row(self, power_linear):
            if self._writer._fh is not None:
                self._writer.write_row(power_linear)

        @property
        def path(self):
            return self._writer.path

        @property
        def nrows(self):
            return self._writer.nrows

        def work(self, input_items, output_items):
            buf = input_items[0]
            n = len(buf)
            with self._lock:
                if self._q_samples + n <= self.MAX_QUEUE_SAMPLES:
                    self._q.append(np.array(buf, dtype=np.complex64))
                    self._q_samples += n
                else:
                    self.dropped_samples += n
            return n

        def _drain(self):
            with self._lock:
                batch, self._q = self._q, []
                self._q_samples = 0
            if not batch:
                return False
            # One big slab per pass: fewer, larger FFT/ufunc calls hold the
            # GIL far less than many small ones (the GR Python callbacks
            # must stay responsive or the radio overflows).
            self._integ.push(np.concatenate(batch) if len(batch) > 1
                             else batch[0])
            return True

        def _worker_loop(self):
            while not self._stopping.is_set():
                if not self._drain():
                    _time.sleep(0.005)
            self._drain()          # final drain so no queued samples are lost

        def stop(self):
            self.close()
            return True

        def close(self):
            if self._closed:
                return self._writer.close()
            self._closed = True
            self._stopping.set()
            self._worker.join(timeout=10.0)
            return self._writer.close()
