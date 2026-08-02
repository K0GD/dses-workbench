"""Tests for the canned PRESTO pipeline (v1.1.9 items 1/3/4).

Builds a small synthetic .fil with an injected 0.5 s pulsar, runs the full
pipeline (readfile -> rfifind -> prepfold -> PDF), and checks the verdict,
parsed numbers, and the self-contained PDF. Needs PRESTO (native or WSL).

Run inside the project .conda env:  python test_fold_analysis.py
"""
import os
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import sigproc_fil
from fold_analysis import PrestoRunner, analyze_fil, snapshot_fil

runner = PrestoRunner()
print("PRESTO runner:", runner.describe())
if not runner.available:
    print("SKIP: PRESTO not available on this machine")
    sys.exit(0)

# --- synthetic .fil: 60 s, 64 chans, 1 ms tsamp, P=0.5 s pulsar at ~30 sigma
rng = np.random.default_rng(11)
NCH, TSAMP, NROWS, P_S = 64, 1e-3, 60_000, 0.5
tmpdir = tempfile.mkdtemp()
fil = os.path.join(tmpdir, "SYNTH_pulsar.fil")
hdr = sigproc_fil.sigproc_header(
    source_name="synthetic", fch1=430.0, foff=-20.0 / NCH, nchans=NCH,
    nbits=32, tstart=60000.0, tsamp=TSAMP, telescope_id=12,
    rawdatafile="SYNTH_pulsar.fil")
rows = rng.chisquare(2, size=(NROWS, NCH)).astype(np.float32)
period_rows = int(P_S / TSAMP)
for start in range(0, NROWS, period_rows):
    # 20 ms pulse at +0.75 sigma per sample: far below rfifind's per-block
    # clip threshold (real broadband impulses WOULD be masked), but folded
    # over 120 pulses x 64 channels it is overwhelmingly significant.
    rows[start:start + 20, :] += 1.5
with open(fil, "wb") as f:
    f.write(hdr)
    f.write(rows.tobytes())
print(f"synthetic .fil written: {NROWS} rows, {os.path.getsize(fil)/1e6:.1f} MB")

# --- 1. snapshot: append a partial row, snapshot must trim it -------------
snap = os.path.join(tmpdir, "snap.fil")
with open(fil, "ab") as f:
    f.write(b"\x00" * 100)                  # partial trailing spectrum
info = snapshot_fil(fil, snap)
assert info["rows"] == NROWS, info
assert (os.path.getsize(snap) - info["header"]["_header_bytes"]) % (NCH * 4) == 0
print(f"1. snapshot OK: {info['rows']} complete rows, {info['seconds']:.1f} s")

# --- 2. full pipeline with a manual fold spec -----------------------------
msgs = []
res = analyze_fil(snap, source_name="SYNTH test", fold_p_s=P_S, fold_dm=0.0,
                  runner=runner, progress=msgs.append)
print("   progress:", " | ".join(msgs))
print(f"   verdict={res['verdict']} chi2={res['chi2_red']} "
      f"elapsed={res['elapsed_s']:.0f}s")
assert res["readfile_ok"], "readfile failed"
assert res["mask_ok"], "rfifind failed"
assert res["verdict"] == "DETECTION", res
assert res["chi2_red"] and res["chi2_red"] > 5
assert os.path.exists(res["pdf"])
print(f"2. pipeline OK -> {os.path.basename(res['pdf'])}")

# --- 3. the PDF is self-contained (chart + commentary) --------------------
from pypdf import PdfReader
r = PdfReader(res["pdf"])
txt = "".join((p.extract_text() or "") for p in r.pages)
assert "Verdict: DETECTION" in txt
assert "rfifind" in txt and "prepfold" in txt
print(f"3. PDF OK: {len(r.pages)} pages, verdict + commands embedded")

# --- 4. no source name -> data-check-only verdict -------------------------
res2 = analyze_fil(snap, source_name="", runner=runner)
assert res2["verdict"] == "DATA CHECK", res2
assert os.path.exists(res2["pdf"])
print("4. data-check-only path OK (no fold target)")

print("\nALL FOLD-ANALYSIS TESTS PASSED")
