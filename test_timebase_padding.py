"""Tests for the v1.1.8 recording timebase-integrity feature: RX-overflow
gaps measured from gr-uhd `rx_time` tags and zero-padded live so the .fil
sample clock tracks real time.

Run inside the project .conda env (needs gnuradio):
    python test_timebase_padding.py
"""
import json
import os
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import sigproc_fil
from sigproc_fil import compute_gap_samples

# --- 1. pure gap arithmetic -------------------------------------------------
# reference: sample 0 at t=100 s, rate 1 MS/s. Tag at input sample 50_000
# carrying t=100.1 s: real time says 100_000 samples elapsed -> 50_000 missing.
g = compute_gap_samples(0, 100.0, 50_000, 100.1, 1e6, 0)
assert g == 50_000, g
# with 50_000 already padded since the reference, no further gap:
g = compute_gap_samples(0, 100.0, 100_000, 100.15, 1e6, 50_000)
assert g == 0, g
# tiny re-timing jitter -> ~0, not a gap:
g = compute_gap_samples(0, 100.0, 70_000, 100.070001, 1e6, 0)
assert g == 1, g
print("1. compute_gap_samples arithmetic OK")

# --- 2. end-to-end: flowgraph with injected rx_time tags --------------------
from gnuradio import gr, blocks
import pmt


def rx_time_tag(offset, seconds):
    t = gr.tag_t()
    t.offset = offset
    t.key = pmt.intern("rx_time")
    frac, full = np.modf(seconds)
    t.value = pmt.make_tuple(pmt.from_uint64(int(full)), pmt.from_double(float(frac)))
    return t


def run_sink(data, tags, samp_rate=1e5, nchans=64):
    tmp = tempfile.mktemp(suffix=".fil")
    src = blocks.vector_source_c(data.tolist(), False, 1, tags)
    sink = sigproc_fil.FilterbankSink(
        tmp, nchans=nchans, samp_rate=samp_rate, center_freq_mhz=420.0,
        tstart_mjd=60000.0, integrate=1, source_name="gap-test")
    tb = gr.top_block()
    tb.connect(src, sink)
    tb.run()
    info = sink.close()
    return tmp, sink, info


rng = np.random.default_rng(7)
RATE, NCH = 1e5, 64
data = (rng.standard_normal(100_000) + 1j * rng.standard_normal(100_000)).astype(np.complex64)

# One 0.5 s gap (50_000 samples) at input sample 50_000.
tags = [rx_time_tag(0, 1000.0),
        rx_time_tag(50_000, 1000.0 + 50_000 / RATE + 0.5)]
path, sink, info = run_sink(data, tags)
expected_rows = (100_000 + 50_000) // NCH
assert info["ntime"] == expected_rows, (info["ntime"], expected_rows)
assert info["gap_events"] == 1 and info["gap_samples"] == 50_000, info
sidecar = path + ".gaps.json"
assert os.path.exists(sidecar), "gaps sidecar missing"
side = json.load(open(sidecar))
assert side["events"][0]["missing_samples"] == 50_000
assert not side["timebase_broken"]
os.remove(path); os.remove(sidecar)
print(f"2. single-gap flowgraph OK: {info['ntime']} rows "
      f"(= data + 0.5 s pad), sidecar records the event")

# --- 3. no tags -> classic behavior, no sidecar -----------------------------
path, sink, info = run_sink(data, [])
assert info["ntime"] == 100_000 // NCH
assert info["gap_events"] == 0
assert not os.path.exists(path + ".gaps.json")
os.remove(path)
print("3. untagged stream (Soapy-style source) records exactly as before")

# --- 4. per-event cap + truncation flag -------------------------------------
# 20 s gap at 1e5 S/s = 2_000_000 missing; per-event cap 10 s -> 1_000_000.
tags = [rx_time_tag(0, 0.0),
        rx_time_tag(50_000, 50_000 / RATE + 20.0)]
path, sink, info = run_sink(data, tags)
assert info["gap_samples"] == int(10.0 * RATE), info
side = json.load(open(path + ".gaps.json"))
assert side["events"][0]["truncated"] is True
os.remove(path); os.remove(path + ".gaps.json")
print("4. per-event pad cap + truncated flag OK")

# --- 5. jitter below threshold -> ignored ----------------------------------
tags = [rx_time_tag(0, 0.0),
        rx_time_tag(50_000, 50_000 / RATE + 0.00005)]  # 50 us << 100 us min
path, sink, info = run_sink(data, tags)
assert info["gap_events"] == 0 and info["ntime"] == 100_000 // NCH
assert not os.path.exists(path + ".gaps.json")
os.remove(path)
print("5. sub-threshold jitter ignored OK")

print("\nALL TIMEBASE-PADDING TESTS PASSED")
