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

ONE FRONTEND PER PROCESS (--side A / --side B): remapping the streamer to
the other frontend mid-run via lock()/set_subdev_spec/unlock() does NOT
take effect — the 2026-09-14 first runs reported side-B rows that were
still listening on side A (identical numbers gave it away; the app itself
does a full flowgraph restart, so the app is unaffected). The subdev is
now fixed before streaming starts. Also one device open per process (the
B210 reopen access-violation fault, 2026-09-12).
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
# Tune the RECEIVER this far below the carrier so the carrier lands well
# away from the zero-IF DC artefact (first run confounded them: carrier
# 200 Hz from DC read as "the same small peak on every port").
TUNE_BELOW = 250e3


def capture_carrier_db(tb, snk):
    """Carrier level (dB, uncalibrated): the peak bin OUTSIDE the DC region,
    plus the median floor, from an averaged PSD of the newest samples."""
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
    c = NFFT // 2
    db_masked = db.copy()
    db_masked[c - 10:c + 11] = -300.0      # exclude the DC artefact
    db_masked[:64] = db_masked[-64:] = -300.0   # and the filter skirts
    k = int(np.argmax(db_masked))
    floor = float(np.median(db))
    return db[k], (k - c) * RATE / NFFT, floor


def run_app_path(freq, gain, side):
    import dses_workbench as sa
    devs = sa.find_b200_uhd()
    if not devs:
        sys.exit("no B210 found")
    serial = devs[0]['serial']
    print(f"B210 s/n {serial} — APP path (UhdB200Source, the Workbench's own "
          f"code), frontend {side} only")
    center = freq - TUNE_BELOW
    print(f"tuned {center/1e6:.4f} MHz; carrier expected at "
          f"{TUNE_BELOW/1e3:+.0f} kHz")
    src = sa.UhdB200Source(serial=serial, samp_rate=RATE,
                           center_freq=center, gain=gain,
                           antenna=f"{side} : TX/RX")
    tb = gr.top_block()
    snk = blocks.vector_sink_c(reserve_items=NFFT * AVG * 4)
    tb.connect(src.block, snk)
    tb.start()
    rows = []
    names = [a for a in src.antennas if a.startswith(f"{side} ")]
    for name in names:
        if src.antenna_needs_restart(name):
            raise RuntimeError(f"{name} needs a frontend remap — run with "
                               f"--side {name.split(' ')[0]} instead")
        src.set_antenna(name)
        pk, off, floor = capture_carrier_db(tb, snk)
        rows.append((name, pk, off, floor))
        print(f"  {name:12s}  carrier {pk:7.1f} dB at {off/1e3:+7.1f} kHz   "
              f"floor {floor:7.1f} dB   (C/N {pk-floor:5.1f} dB)")
    tb.stop()
    tb.wait()
    return rows


def run_raw_path(freq, gain, side):
    print(f"RAW gr-uhd path (no Workbench wrapper), frontend {side} only")
    dev = uhd.usrp_source(",".join(("", "")),
                          uhd.stream_args(cpu_format="fc32", channels=[0]))
    subdevs = dev.get_subdev_spec(0).split()
    labels = ['A', 'B', 'C', 'D'][:len(subdevs)]
    if side not in labels:
        sys.exit(f"frontend {side} not present (device has {labels})")
    # Subdev must be fixed BEFORE streaming starts — a mid-run remap via
    # lock()/unlock() silently does not take (see module docstring).
    dev.set_subdev_spec(subdevs[labels.index(side)], 0)
    ports = list(dev.get_antennas(0))
    dev.set_samp_rate(RATE)
    center = freq - TUNE_BELOW
    print(f"tuned {center/1e6:.4f} MHz; carrier expected at "
          f"{TUNE_BELOW/1e3:+.0f} kHz")
    dev.set_center_freq(center, 0)
    dev.set_gain(gain, 0)
    tb = gr.top_block()
    snk = blocks.vector_sink_c(reserve_items=NFFT * AVG * 4)
    tb.connect(dev, snk)
    tb.start()
    rows = []
    for port in ports:
        name = f"{side} : {port}"
        dev.set_antenna(port, 0)
        pk, off, floor = capture_carrier_db(tb, snk)
        rows.append((name, pk, off, floor))
        print(f"  {name:12s}  carrier {pk:7.1f} dB at {off/1e3:+7.1f} kHz   "
              f"floor {floor:7.1f} dB   (C/N {pk-floor:5.1f} dB)")
    tb.stop()
    tb.wait()
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--freq", type=float, default=1420.5e6,
                    help="carrier frequency (Hz) the signal generator is set to")
    ap.add_argument("--gain", type=float, default=60.0)
    ap.add_argument("--path", choices=("app", "raw"), default="app")
    ap.add_argument("--side", choices=("A", "B"), default="A",
                    help="which RX frontend to test (one per process)")
    args = ap.parse_args()

    rows = (run_app_path if args.path == "app" else run_raw_path)(
        args.freq, args.gain, args.side)

    # Sanity: the carrier must actually be visible somewhere, or the
    # summary is meaningless (the first run measured only the DC artefact).
    best = max(r[1] - r[3] for r in rows)
    if best < 15:
        print(f"\nNO CARRIER SEEN (best C/N {best:.1f} dB) — check the "
              "generator is keyed, on the expected frequency, and into the "
              "port under test. The summary below is NOT meaningful.")
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
