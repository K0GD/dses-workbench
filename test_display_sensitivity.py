"""Headless verification of the v1.1.7 display sensitivity fix.

Exercises SpectrumProcessor._tick directly (no flowgraph, no GUI event loop)
through a stub sink, checking:
  1. dBFS calibration unchanged: a full-scale tone reads ~0 dBFS via the
     Welch path, matching the legacy single-frame path.
  2. Sensitivity: the Welch frame's noise-floor variance shrinks ~1/Nblocks
     vs the single-frame path (the actual fix).
  3. Fallback: empty queue -> legacy latest() path still paints.
  4. reset_averaging() flushes the sink queue (retune staleness guard).
  5. Adaptive stride sheds blocks when the budget is exceeded.
"""
import os, sys
os.environ["PYQTGRAPH_QT_LIB"] = "PySide6"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
from PySide6.QtCore import QCoreApplication

app = QCoreApplication([])

import dses_workbench as A

rng = np.random.default_rng(42)
N = 1024
CHUNK = A.CHUNK_SIZE


class StubSink:
    def __init__(self):
        self.pending = []
        self.buf = None
        self.flushed = 0
    def set_capacity(self, n): pass
    def drain(self):
        p, self.pending = self.pending, []
        return p, 0
    def latest(self, n):
        return None if self.buf is None else self.buf[-n:].copy()
    def flush(self):
        self.flushed += 1
        self.pending = []


def make_proc(sink):
    p = A.SpectrumProcessor(sink, fft_size=N, window_name="blackman-harris",
                            update_hz=10.0, power_avg=True, unit='dbfs')
    p._timer.stop()          # drive _tick manually
    p.set_average_alpha(1.0)  # no EMA: inspect single-tick frames
    return p


captured = []

def grab(avg, mx, mn):
    captured.append(np.asarray(avg))


# --- 1. calibration: full-scale complex tone at +fs/8 ---
sink = StubSink()
proc = make_proc(sink)
proc.frame_ready.connect(grab)
t = np.arange(CHUNK, dtype=np.float64)
tone = np.exp(2j * np.pi * (N // 8) / N * t).astype(np.complex64)  # bin-centered
sink.pending = [tone.copy() for _ in range(8)]
proc._tick()
frame = captured[-1]
peak_db = frame.max()
assert abs(peak_db) < 0.1, f"calibration broke: peak {peak_db:+.3f} dBFS (want ~0)"
print(f"1. calibration OK: full-scale tone -> {peak_db:+.4f} dBFS, "
      f"blocks integrated = {proc._last_blocks_used} (expect {8*CHUNK//N})")
assert proc._last_blocks_used == 8 * CHUNK // N

# --- 2. sensitivity: noise-floor variance, Welch vs single-frame ---
captured.clear()
noise = (rng.standard_normal(20*CHUNK) + 1j*rng.standard_normal(20*CHUNK)).astype(np.complex64) * 0.01
sink.pending = [noise[i*CHUNK:(i+1)*CHUNK] for i in range(20)]
proc._tick()
welch = captured[-1]                       # dB frame from 1280 blocks
captured.clear()
sink.pending = []
sink.buf = noise[:CHUNK]
proc._tick()                               # fallback single-frame path
single = captured[-1]
sd_w, sd_s = np.std(welch), np.std(single)
nblk = 20 * CHUNK // N
# dB-domain std of chi^2: single-frame ~5.57 dB; Welch ~4.34/sqrt(nblk) dB
print(f"2. noise-floor scatter: single-frame {sd_s:.2f} dB vs Welch {sd_w:.3f} dB "
      f"({nblk} blocks; ratio {sd_s/sd_w:.0f}x, sqrt(N)={np.sqrt(nblk):.0f})")
assert sd_w < sd_s / 10, "Welch averaging did not reduce noise variance as expected"

# --- 3. fallback path exercised above (single) — verify it emitted ---
assert single.shape == (N,)
print("3. fallback single-frame path OK")

# --- 4. reset_averaging flushes the sink ---
before = sink.flushed
proc.reset_averaging()
assert sink.flushed == before + 1, "reset_averaging did not flush the sink"
print("4. reset_averaging flushes sink queue OK")

# --- 5. proactive budget cap: tiny budget -> large stride BEFORE the math ---
proc._tick_budget_frac = 1e-6
sink.pending = [noise[i*CHUNK:(i+1)*CHUNK] for i in range(8)]
proc._tick()
s1, used1 = proc._stride, proc._last_blocks_used
assert s1 > 1 and used1 < 8 * CHUNK // N, f"cap did not bound the math (stride {s1}, used {used1})"
proc._tick_budget_frac = 10.0
proc._sec_per_block = 1e-9
sink.pending = [noise[i*CHUNK:(i+1)*CHUNK] for i in range(8)]
proc._tick()
assert proc._stride == 1, "generous budget should give stride 1"
print(f"5. proactive budget cap OK (starved: stride {s1}, {used1} blocks; generous: stride 1)")

# --- 6. real SampleBufferSink: flush blanks the next drain and kills latest() ---
real = A.SampleBufferSink()
class FakeItems(list): pass
chunkA = (rng.standard_normal(CHUNK) + 1j*rng.standard_normal(CHUNK)).astype(np.complex64)
real.work([ [chunkA, chunkA] ], None)
real.flush()                              # retune barrier armed
assert real.latest(N) is None, "flush must invalidate latest()"
real.work([ [chunkA] ], None)             # in-flight stale chunk arrives late
got, _ = real.drain()
assert got == [], "first non-empty drain after flush must be blanked"
real.work([ [chunkA] ], None)             # first genuinely fresh chunk
got, _ = real.drain()
assert len(got) == 1, "post-blank drain must deliver"
print("6. retune barrier OK (latest invalidated, first drain blanked, second delivers)")

# --- 7. max hold is a per-block peak detector ---
proc2 = make_proc(StubSink())
captured.clear()
proc2.frame_ready.connect(grab)
proc2.set_max_hold(True)
proc2._tick_budget_frac = 10.0
proc2._sec_per_block = 1e-9
burst = noise[:8*CHUNK].copy()
burst[3*CHUNK + 5*N : 3*CHUNK + 6*N] += tone[:N] * 0.5   # one loud block (~ -6 dBFS)
proc2._sink.pending = [burst[i*CHUNK:(i+1)*CHUNK] for i in range(8)]
proc2._tick()
mx = proc2._base_db(proc2._max)
avg_frame = captured[-1]
nblocks = 8 * CHUNK // N
dilution = 10*np.log10(nblocks)
assert mx.max() > avg_frame.max() + dilution - 6, (
    f"max hold diluted: hold {mx.max():.1f} vs avg {avg_frame.max():.1f} (expected ~{dilution:.0f} dB gap)")
print(f"7. per-block max hold OK: burst reads {mx.max():.1f} dB on hold vs {avg_frame.max():.1f} dB "
      f"on the tick mean ({nblocks} blocks -> {dilution:.0f} dB dilution avoided)")

# --- 8. hold detector toggle: 'average' mode tracks the tick mean ---
proc2.set_hold_detector('average')          # resets holds, switches source
assert proc2._max is None, "switching detector mode must reset holds"
captured.clear()
proc2._sink.pending = [burst[i*CHUNK:(i+1)*CHUNK] for i in range(8)]
proc2._tick()
mx_avg = proc2._base_db(proc2._max)
frame = captured[-1]
gap = abs(mx_avg.max() - frame.max())
assert gap < 1.0, f"average-mode max hold should hug the tick mean (gap {gap:.1f} dB)"
proc2.set_hold_detector('peak')
assert proc2._max is None, "switching back must reset holds too"
print(f"8. hold detector toggle OK: average mode gap {gap:.2f} dB from tick mean; "
      f"mode switches reset holds")

print("\nALL DISPLAY-FIX TESTS PASSED")
