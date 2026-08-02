"""Tests for the ezRA .txt drift-scan writer (v1.1.8).

Validates against the structure of the REAL dish reference files in
~/Documents/DSES/Science/HI_and_Drift_Scan/ezRABase/, then runs a GNU Radio
flowgraph with a known tone and checks the frequency mapping, and finally
feeds a generated file to the LOCAL ezCon.py as the acceptance test.

Run inside the project .conda env:  python test_ezra_txt.py
"""
import os
import re
import sys
import tempfile
from datetime import datetime, timezone

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ezra_txt import EzraTxtWriter, EzraIntegrator, ezra_filename

# --- 1. header + row structure mirrors the dish reference -------------------
tmp = tempfile.mktemp(suffix=".txt")
w = EzraTxtWriter(tmp, lat_deg=38.3808, lon_deg=-103.156, amsl=4400.0,
                  site_name="DSES", freq_min_mhz=1414.4, freq_max_mhz=1422.4,
                  bin_qty=256, az_deg=180, el_deg=45, gain_text="40",
                  provenance="DSES_Spectrum_Analyzer test")
w.write_row(np.full(256, 1e-10),
            utc=datetime(2026, 8, 2, 12, 0, 0, tzinfo=timezone.utc))
w.close()
lines = open(tmp).read().splitlines()
assert lines[0].startswith("from ")
assert re.fullmatch(r"lat 38\.3808 long -103\.156 amsl 4400 name DSES", lines[1])
assert re.fullmatch(r"freqMin 1414\.4 freqMax 1422\.4 freqBinQty 256", lines[2])
assert re.fullmatch(r"azDeg 180 elDeg 45", lines[3])
assert lines[4] == "# times are in UTC"
assert lines[5] == "# gain 40"
assert lines[6] == "# frequency spectrums of RMS power in dB"
fields = lines[7].split()
assert len(fields) == 257, len(fields)          # timestamp + 256 bins
assert fields[0] == "2026-08-02T12:00:00"
assert abs(float(fields[1]) - (-100.0)) < 1e-6  # 1e-10 -> -100 dB
os.remove(tmp)
print("1. header + row structure matches the dish reference format")

# --- 2. filename convention -------------------------------------------------
n = ezra_filename("DSES", datetime(2025, 11, 13, 19, 53, 8, tzinfo=timezone.utc))
assert n == "DSES251113_19.txt", n
print("2. ezCol filename convention OK:", n)

# --- 3. integrator: tone lands in the right ascending-frequency bin ---------
rows = []
integ = EzraIntegrator(fft_bins=256, integ_frames=4, on_row=rows.append,
                       keep_fraction=0.8)
assert integ.kept_bins == 204  # central 80% of 256, even
RATE = 1e6
# tone at +100 kHz from center: ascending bin = kept/2 + 100k/(1e6/256) ~ 127.6
t = np.arange(8 * 256) / RATE
iq = np.exp(2j * np.pi * 100e3 * t).astype(np.complex64)
integ.push(iq)
assert len(rows) == 2, len(rows)                  # 8 frames / 4 per row
peak = int(np.argmax(rows[0]))
full_bin = round(100e3 / (RATE / 256))            # +26 bins from center
expect = 256 // 2 + full_bin - integ._lo
assert abs(peak - expect) <= 1, (peak, expect)
fmin, fmax = EzraIntegrator.kept_span_mhz(1420.0, RATE, integ.kept_bins, 256)
assert abs((fmax - fmin) - 0.8 * RATE / 1e6 * 204/204.8) < 0.01
print(f"3. integrator OK: tone at kept-bin {peak} (expected ~{expect}), "
      f"kept span {fmin:.3f}-{fmax:.3f} MHz")

# --- 4. GR flowgraph end-to-end ---------------------------------------------
from gnuradio import gr, blocks
import ezra_txt

rng = np.random.default_rng(3)
data = (0.01 * (rng.standard_normal(64 * 256 * 10)
                + 1j * rng.standard_normal(64 * 256 * 10))).astype(np.complex64)
tone = np.exp(2j * np.pi * 100e3 * np.arange(data.size) / RATE).astype(np.complex64)
data += 0.5 * tone
tmp2 = tempfile.mktemp(suffix=".txt")
src = blocks.vector_source_c(data.tolist(), False)
sink = ezra_txt.EzraTxtSink(
    tmp2, fft_bins=256, integ_frames=64, samp_rate=RATE,
    center_freq_mhz=1420.0, lat_deg=38.3808, lon_deg=-103.156, amsl=4400.0,
    site_name="DSES", az_deg=180, el_deg=45, gain_text="40",
    keep_fraction=0.8)
tb = gr.top_block()
tb.connect(src, sink)
tb.run()
info = sink.close()
assert info["nrows"] == 10, info
lines = open(tmp2).read().splitlines()
assert len(lines) == 7 + 10
vals = np.array([float(v) for v in lines[7].split()[1:]])
assert vals.size == sink._integ.kept_bins
assert vals.max() - np.median(vals) > 20, "tone should stand >20 dB proud"
print(f"4. GR flowgraph OK: 10 rows, tone {vals.max()-np.median(vals):.1f} dB "
      f"above the noise floor")

# --- 5. acceptance: the LOCAL ezCon parses our file --------------------------
# (headless matplotlib; run in a temp cwd so ezCon's outputs land there)
import subprocess
ezcon = r"C:/Users/rick/Documents/DSES/Science/HI_and_Drift_Scan/ezRABase/ezRA/ezCon.py"
if os.path.exists(ezcon):
    workdir = tempfile.mkdtemp()
    dst = os.path.join(workdir, "DSES260802_12.txt")
    # A realistic mini drift scan: 20 rows spaced 13 s (the dish cadence),
    # noise floor + a persistent "hydrogen line" 3 bins wide.
    from datetime import timedelta
    w2 = EzraTxtWriter(dst, lat_deg=38.3808, lon_deg=-103.156, amsl=4400.0,
                       site_name="DSES", freq_min_mhz=1419.6,
                       freq_max_mhz=1420.4, bin_qty=204, az_deg=180,
                       el_deg=45, gain_text="40")
    t0 = datetime(2026, 8, 2, 12, 0, 0, tzinfo=timezone.utc)
    for i in range(20):
        row = 1e-10 * (1.0 + 0.01 * rng.standard_normal(204))
        row[100:103] *= 3.0        # the "line"
        w2.write_row(row, utc=t0 + timedelta(seconds=13 * i))
    w2.close()
    env = dict(os.environ, MPLBACKEND="Agg")
    r = subprocess.run([sys.executable, ezcon, os.path.basename(dst)],
                       cwd=workdir, env=env, capture_output=True, text=True,
                       timeout=600)
    produced = [f for f in os.listdir(workdir) if f.endswith(".ezb")]
    ok = (r.returncode == 0) and produced
    print(f"5. ezCon acceptance: exit={r.returncode}, "
          f"ezb produced={produced or 'NONE'}")
    if not ok:
        print("--- ezCon stdout (tail) ---")
        print("\n".join(r.stdout.splitlines()[-15:]))
        print("--- ezCon stderr (tail) ---")
        print("\n".join(r.stderr.splitlines()[-15:]))
        sys.exit(1)
else:
    print("5. ezCon acceptance SKIPPED (local ezRA install not found)")
os.remove(tmp2)

print("\nALL EZRA-TXT TESTS PASSED")
