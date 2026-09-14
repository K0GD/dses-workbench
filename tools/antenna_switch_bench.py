"""Bench check of the B210 RX antenna switching (side A leak report,
2026-09-14: a carrier fed into A:RX2 shows identically with A:TX/RX
selected; the LEDs follow the selection; side B behaves).

Feed a steady carrier into ONE RX port (say A:RX2), then run:

    .conda\\python.exe tools\\antenna_switch_bench.py --freq 1420.5e6
    .conda\\python.exe tools\\antenna_switch_bench.py --freq 1420.5e6 --path raw

The first pass drives the app's own UhdB200Source (the exact code the
Workbench runs, including the subdev remap for side B); the second
bypasses the wrapper entirely with raw gr-uhd calls. Each prints the
carrier level seen through all four selections. Interpretation:

  * selected-port level minus other-port level = the switch isolation.
    A healthy B210 switch gives 40+ dB; "identical" (< a few dB) means
    the switch did not move.
  * leak present in BOTH passes  -> hardware (switch / control line on
    that side), not the app.
  * leak only in the --path app pass -> our wrapper; file it.

One device open per process (the B210 reopen access-violation fault,
2026-09-12) — hence two invocations rather than one script doing both.
"""
import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("PYQTGRAPH_QT_LIB", "PySide6")

import numpy as np


def _ensure_uhd_images():
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

RATE = 2e6
NFFT = 4096
AVG = 100


def capture_carrier_db(tb, snk):
    """Peak-bin level (dB, uncalibrated) + total band power of an averaged
    PSD from the newest samples."""
    snk.reset()
    time.sleep(0.3)            # flush the switch/retune transient
    snk.reset()
    need = NFFT * AVG
    t0 = time.time()
    while len(snk.data()) < need:
        time.sleep(0.05)
        if time.time() - t0 > 15:
            raise RuntimeError("no samples — streamer stalled")
    x = np.array(snk.data()[:need], dtype=np.complex64).reshape(AVG, NFFT)
    w = np.hanning(NFFT)
    p = (np.abs(np.fft.fftshift(np.fft.fft(x * w, axis=1), axes=1)) ** 2).mean(0)
    db = 10 * np.log10(p + 1e-30)
    k = int(np.argmax(db))
    tot = 10 * np.log10(p.sum() + 1e-30)
    return db[k], (k - NFFT // 2) * RATE / NFFT, tot


def run_app_path(freq, gain):
    import dses_workbench as sa
    devs = sa.find_b200_uhd()
    if not devs:
        sys.exit("no B210 found")
    serial = devs[0]['serial']
    print(f"B210 s/n {serial} — APP path (UhdB200Source, the Workbench's own code)")
    src = sa.UhdB200Source(serial=serial, samp_rate=RATE,
                           center_freq=freq, gain=gain)
    tb = gr.top_block()
    snk = blocks.vector_sink_c(reserve_items=NFFT * AVG * 4)
    tb.connect(src.block, snk)
    tb.start()
    rows = []
    for name in src.antennas:
        if src.antenna_needs_restart(name):
            tb.lock()
            src.set_antenna(name)
            tb.unlock()
        else:
            src.set_antenna(name)
        pk, off, tot = capture_carrier_db(tb, snk)
        rows.append((name, pk, off, tot))
        print(f"  {name:12s}  peak {pk:7.1f} dB at {off/1e3:+7.1f} kHz   "
              f"band {tot:7.1f} dB")
    tb.stop()
    tb.wait()
    return rows


def run_raw_path(freq, gain):
    print("RAW gr-uhd path (no Workbench wrapper)")
    dev = uhd.usrp_source(",".join(("", "")),
                          uhd.stream_args(cpu_format="fc32", channels=[0]))
    subdevs = dev.get_subdev_spec(0).split()
    ports = list(dev.get_antennas(0))
    dev.set_samp_rate(RATE)
    tb = gr.top_block()
    snk = blocks.vector_sink_c(reserve_items=NFFT * AVG * 4)
    tb.connect(dev, snk)
    tb.start()
    rows = []
    labels = ['A', 'B', 'C', 'D'][:len(subdevs)]
    cur = subdevs[0]
    for lab, spec in zip(labels, subdevs):
        for port in ports:
            name = f"{lab} : {port}"
            if spec != cur:
                tb.lock()
                dev.set_subdev_spec(spec, 0)
                dev.set_center_freq(freq, 0)
                dev.set_gain(gain, 0)
                tb.unlock()
                cur = spec
            elif not rows:
                dev.set_center_freq(freq, 0)
                dev.set_gain(gain, 0)
            dev.set_antenna(port, 0)
            pk, off, tot = capture_carrier_db(tb, snk)
            rows.append((name, pk, off, tot))
            print(f"  {name:12s}  peak {pk:7.1f} dB at {off/1e3:+7.1f} kHz   "
                  f"band {tot:7.1f} dB")
    tb.stop()
    tb.wait()
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--freq", type=float, default=1420.5e6,
                    help="carrier frequency (Hz) the signal generator is set to")
    ap.add_argument("--gain", type=float, default=40.0)
    ap.add_argument("--path", choices=("app", "raw"), default="app")
    args = ap.parse_args()

    rows = (run_app_path if args.path == "app" else run_raw_path)(
        args.freq, args.gain)

    # Per-side isolation summary (assumes the carrier is on ONE port; the
    # hotter selection of a side is taken as the fed port).
    print("\nisolation summary (hotter port of each side minus the other):")
    by_side = {}
    for name, pk, _, _ in rows:
        side = name.split(' : ')[0]
        by_side.setdefault(side, []).append((name, pk))
    for side, pair in by_side.items():
        if len(pair) == 2:
            (n1, p1), (n2, p2) = pair
            hot, cold = (n1, n2) if p1 >= p2 else (n2, n1)
            iso = abs(p1 - p2)
            verdict = "OK (switch moves)" if iso > 20 else \
                      "SUSPECT — ports look the same, switch likely not moving"
            print(f"  side {side}: {hot} is hotter by {iso:.1f} dB  -> {verdict}")


if __name__ == "__main__":
    main()
