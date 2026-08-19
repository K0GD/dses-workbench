"""Bench validation of LO-offset tuning on the real B210 (production path).

Uses the app's own UhdB200Source wrapper — the exact code path the app runs —
to capture spectra at the HI preset geometry (1420.406 MHz, 2 MS/s) with
LO offset 0 and +1.5 MHz (0.75x rate; a full-rate offset raises a B210 spur — see the preset comment), and measures the DC artefact in each.

PASS criteria:
  * offset 0:   DC spike clearly visible at band center (the known artefact)
  * offset 1.5M: center-bin excess < 1 dB (spike gone)
  * no spur GROWTH anywhere off-center between the runs (pre-existing
    external carriers sit in the same RF bin both times and cancel; anything
    the offset introduces — including a quadrature image of a real carrier —
    shows up as growth)
  * tuned RF frequency unchanged (readback)
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("PYQTGRAPH_QT_LIB", "PySide6")

import numpy as np


def _ensure_uhd_images():
    # Same probe as tools/b210_bit.py: the .conda env ships UHD without
    # firmware images; radioconda has them.
    if os.environ.get("UHD_IMAGES_DIR"):
        return
    home = Path.home()
    for cand in (Path(sys.prefix) / "Library" / "share" / "uhd" / "images",
                 home / "radioconda" / "Library" / "share" / "uhd" / "images",
                 Path("C:/ProgramData/radioconda/Library/share/uhd/images")):
        if (cand / "usrp_b200_fw.hex").is_file():
            os.environ["UHD_IMAGES_DIR"] = str(cand)
            return


_ensure_uhd_images()

from gnuradio import gr, blocks, uhd          # noqa: E402

import dses_spectrum_analyzer as sa           # noqa: E402

RATE = 2e6
FREQ = 1420.406e6
GAIN = 40.0
NFFT = 4096
AVG = 200          # FFT frames to average per measurement


def capture_psd(tb, snk):
    """Average AVG FFTs of the newest samples from a vector sink."""
    snk.reset()
    time.sleep(0.2)          # flush retune transient
    snk.reset()
    need = NFFT * AVG
    while len(snk.data()) < need:
        time.sleep(0.05)
    x = np.array(snk.data()[:need], dtype=np.complex64).reshape(AVG, NFFT)
    w = np.hanning(NFFT)
    p = (np.abs(np.fft.fftshift(np.fft.fft(x * w, axis=1), axes=1)) ** 2).mean(0)
    return 10 * np.log10(p + 1e-30)


def excess(db):
    """Per-bin excess over a median-smoothed baseline."""
    from scipy.ndimage import median_filter
    return db - median_filter(db, 101)


def main():
    devs = sa.find_b200_uhd()          # the app's own discovery helper
    if not devs:
        sys.exit("no B210 found")
    serial = devs[0]['serial']
    print(f"B210 s/n {serial}")

    src = sa.UhdB200Source(serial=serial, samp_rate=RATE,
                           center_freq=FREQ, gain=GAIN)
    tb = gr.top_block()
    snk = blocks.vector_sink_c(reserve_items=NFFT * AVG * 4)
    tb.connect(src.block, snk)
    tb.start()

    results = {}
    for off in (0.0, 1.5e6):
        ok = src.set_lo_offset(off)
        print(f"\nLO offset {off / 1e6:+.1f} MHz  (accepted={ok})")
        db = capture_psd(tb, snk)
        exc = excess(db)
        c = NFFT // 2
        center = exc[c - 2:c + 3].max()
        rf = src.block.get_center_freq(0)
        print(f"  RF readback {rf / 1e6:.6f} MHz (delta {rf - FREQ:+.1f} Hz)")
        print(f"  center-bin excess {center:+.2f} dB")
        results[off] = (center, exc, rf)

    tb.stop()
    tb.wait()

    c0, exc0, rf0 = results[0.0]
    c2, exc2, rf2 = results[1.5e6]
    grow = exc2 - exc0
    c = NFFT // 2
    mask = np.ones(NFFT, bool)
    mask[c - 6:c + 7] = False          # center: spike SUPPOSED to vanish
    mask[:50] = mask[-50:] = False     # filter skirts
    # Bins already hot at offset 0 are live external carriers; their
    # snapshot-to-snapshot flicker (~2 dB on the bench) is not our artefact.
    # A genuinely NEW spur appears in a bin that was quiet before.
    mask &= exc0 < 3.0
    k = int(np.argmax(np.where(mask, grow, -99.0)))
    print(f"\n  worst spur growth off-center: {grow[k]:+.2f} dB at "
          f"{(k - c) * RATE / NFFT / 1e3:+.1f} kHz")

    checks = [
        ("DC spike present at offset 0", c0 > 1.0),
        ("center clean at offset 1.5 MHz", c2 < 1.0),
        ("no new spur at offset 1.5 MHz", grow[k] < 1.5),
        ("RF unchanged (offset 0)", abs(rf0 - FREQ) < 1.0),
        ("RF unchanged (offset 1.5M)", abs(rf2 - FREQ) < 1.0),
    ]
    print()
    ok = True
    for name, good in checks:
        print(f"  [{'PASS' if good else 'FAIL'}] {name}")
        ok &= good
    print("\nRESULT:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
