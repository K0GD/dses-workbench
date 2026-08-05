#!/usr/bin/env python3
"""Tests for pulsar_sim.py.

Fast checks validate the synthesis mathematically (pulse timing, the
dispersion law measured from channelized arrival times, loop-seam
continuity). The slow optional check (--presto) runs the full offline
round trip: synth -> .fil -> PRESTO fold -> grade() against the injected
truth — the same grading the built-in test will use on hardware.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pulsar_sim as ps
import sigproc_fil as sf

FAILURES = []


def check(cond, label, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{'  — ' + detail if detail else ''}")
    if not cond:
        FAILURES.append(label)


def test_grid():
    print("\n1. period quantization / loop seam")
    p, n = ps.quantize_period(0.1000003, 1e6)
    check(n == 100000, "period snaps to sample grid", f"n={n}")
    check(abs(p - 0.1) < 1e-12, "quantized period exact on grid", f"{p}")
    iq, spec = ps.synth(1e6, 420e6, 0.1, 0.0, n_periods=3, seed=7)
    check(spec.n_samples == 300000, "buffer holds integer periods",
          f"{spec.n_samples}")
    # loop-seam: pulse spacing measured ACROSS the seam of two repeats must
    # equal the period exactly
    two = np.concatenate([iq, iq])
    env = np.abs(two) ** 2
    n_per = 100000
    # centroid of power per period: noise-robust (argmax of a noise-carrier
    # pulse jitters anywhere inside the envelope), and phase-exact
    idx = np.arange(n_per)
    cents = []
    for i in range(6):
        w = env[i * n_per:(i + 1) * n_per]
        cents.append(i * n_per + float((idx * w).sum() / w.sum()))
    gaps = np.diff(cents)
    check(float(np.max(np.abs(gaps - n_per))) < 50.0,
          "pulse spacing exact across the loop seam",
          f"max deviation {np.max(np.abs(gaps - n_per)):.1f} samples")


def test_pulse_shape():
    print("\n2. pulse shape and statistics")
    iq, spec = ps.synth(2e6, 420e6, 0.25, 0.0, duty=0.04, n_periods=2,
                        amplitude=3.0, seed=3)
    env = np.abs(iq) ** 2
    n_per = int(0.25 * 2e6)
    # on-pulse power near the center, off-pulse silence at the period edge
    mid = env[n_per // 2 - 500:n_per // 2 + 500].mean()
    edge = env[:1000].mean()
    check(mid > 100 * (edge + 1e-12), "pulse >> off-pulse",
          f"mid={mid:.3f} edge={edge:.2e}")
    # noise carrier: on-pulse samples should NOT be a constant-amplitude tone
    on = iq[n_per // 2 - 2000:n_per // 2 + 2000]
    cv = np.std(np.abs(on)) / np.mean(np.abs(on))
    check(cv > 0.3, "carrier is noise, not a tone",
          f"|iq| coefficient of variation {cv:.2f}")
    # FWHM of the recovered envelope ~ duty * period
    sm = np.convolve(env[:n_per], np.ones(256) / 256.0, mode="same")
    half = sm.max() / 2.0
    above = np.where(sm >= half)[0]
    fwhm_s = (above[-1] - above[0]) / 2e6
    expect = 0.04 * 0.25 / np.sqrt(2.0)   # POWER FWHM = envelope FWHM/sqrt(2)
    check(abs(fwhm_s - expect) / expect < 0.25,
          "power-envelope FWHM matches duty",
          f"{fwhm_s * 1e3:.2f} ms vs {expect * 1e3:.2f} ms expected")


def test_dispersion():
    print("\n3. dispersion law (the point of the whole exercise)")
    # UHF geometry gives a big, measurable sweep: 2 MHz @ 420 MHz, DM 26.76
    fs, fc, dm = 2e6, 420e6, 26.76
    sweep_pred = ps.K_DM_S_MHZ2 * dm * (((fc - fs / 2) / 1e6) ** -2
                                        - ((fc + fs / 2) / 1e6) ** -2)
    print(f"      predicted band sweep: {sweep_pred * 1e3:.2f} ms")
    check(sweep_pred > 0.001, "geometry produces a resolvable sweep",
          f"{sweep_pred * 1e3:.2f} ms")

    # PRIMARY (exact): disperse a lone impulse, extract brick-wall sub-bands
    # directly from the spectrum (zero leakage), measure each sub-band's
    # envelope centroid = group delay. Deterministic, so tolerance is tight.
    from scipy import fft as sfft
    n = int(0.25 * fs)
    imp = np.zeros(n, np.complex64)
    imp[n // 2] = 1.0
    d = ps.disperse(imp, fs, fc, dm)
    spec_f = sfft.fft(d.astype(np.complex128))
    v = sfft.fftfreq(n, d=1.0 / fs)
    nch = 16
    bw = fs / nch
    t = np.arange(n) / fs
    worst_us = 0.0
    arrivals = []
    for c in range(nch):
        lo = -fs / 2 + c * bw
        sub = np.where((v >= lo) & (v < lo + bw), spec_f, 0)
        w = np.abs(sfft.ifft(sub)) ** 2
        cen = float((t * w).sum() / w.sum())
        f_c = (fc + lo + bw / 2) / 1e6
        theory = n / 2 / fs + ps.K_DM_S_MHZ2 * dm * (f_c ** -2 - (fc / 1e6) ** -2)
        worst_us = max(worst_us, abs(cen - theory) * 1e6)
        arrivals.append(cen)
    check(worst_us < 5.0,
          "sub-band group delays match the cold-plasma law",
          f"max error {worst_us:.2f} us over a {sweep_pred * 1e3:.2f} ms sweep")
    check(arrivals[0] > arrivals[-1],
          "low channels arrive LATER (sign of the sweep is physical)",
          f"low {arrivals[0] * 1e3:.2f} ms vs high {arrivals[-1] * 1e3:.2f} ms")

    # SECONDARY (loose): the same law must survive the app's REAL path — a
    # noise-carrier pulsar through channelize_detect. Centroid arrivals are
    # biased toward the band mean by window leakage, so only sign and rough
    # magnitude are asserted here; the exact check above owns the physics.
    n_periods = 16
    iq, spec = ps.synth(fs, fc, 0.25, dm, duty=0.03, n_periods=n_periods, seed=5)
    power = sf.channelize_detect(iq, nch)          # (ntime, nch), low->high
    rows_per = power.shape[0] // n_periods
    folded = power[:rows_per * n_periods].reshape(n_periods, rows_per, nch).mean(axis=0)
    idx = np.arange(rows_per)
    ch_arr = []
    for c in range(nch):
        prof = np.clip(folded[:, c] - np.median(folded[:, c]), 0.0, None)
        ch_arr.append(float((idx * prof).sum() / prof.sum()) * nch / fs)
    freqs = (fc + (np.arange(nch) - nch / 2) * (fs / nch) + fs / nch / 2) / 1e6
    slope, _ = np.polyfit(freqs ** -2.0, np.array(ch_arr), 1)
    dm_rec = slope / ps.K_DM_S_MHZ2
    check(0.5 * dm < dm_rec < 1.5 * dm,
          "sweep survives the app channelizer (noise carrier)",
          f"apparent DM {dm_rec:.1f} vs {dm:g} injected (leakage biases low)")

    # dm=0 leaves the waveform aligned
    iq0, _ = ps.synth(fs, fc, 0.25, 0.0, duty=0.03, n_periods=n_periods, seed=5)
    p0 = sf.channelize_detect(iq0, nch)
    f0 = p0[:rows_per * n_periods].reshape(n_periods, rows_per, nch).mean(axis=0)
    a0 = []
    for c in range(nch):
        prof = np.clip(f0[:, c] - np.median(f0[:, c]), 0.0, None)
        a0.append(float((idx * prof).sum() / prof.sum()))
    spread_ms = (max(a0) - min(a0)) * nch / fs * 1e3
    check(spread_ms < 1.0, "DM=0 arrivals aligned",
          f"spread {spread_ms:.2f} ms")


def test_grade():
    print("\n4. grading")
    # Geometry with real DM leverage (dm_resolution ~1) so the DM checks
    # below exercise the fractional/absolute tolerances, not the geometry
    # floor: 4 MHz band, 1 ms pulses.
    _, spec = ps.synth(4e6, 420e6, 0.1, 10.0, duty=0.01, n_periods=2, seed=1)
    print(f"      dm_resolution for this geometry: {spec.dm_resolution:.2f}")
    ok, checks = ps.grade(spec, {"best_p_s": spec.period_s * 1.001,
                                 "best_dm": 10.5, "sigma": 12.0})
    check(ok, "good result passes", "; ".join(c.split()[0] for c in checks))
    ok2, _ = ps.grade(spec, {"best_p_s": spec.period_s * 1.02,
                             "best_dm": 10.0, "sigma": 12.0})
    check(not ok2, "2% period error fails")
    ok3, _ = ps.grade(spec, {"best_p_s": spec.period_s,
                             "best_dm": 40.0, "sigma": 12.0})
    check(not ok3, "wildly wrong DM fails")
    ok4, _ = ps.grade(spec, {"best_p_s": spec.period_s,
                             "best_dm": 10.0, "sigma": 2.0})
    check(not ok4, "weak significance fails")


def test_presto_roundtrip():
    print("\n5. offline PRESTO round trip (--presto; slow)")
    if "--presto" not in sys.argv:
        print("  SKIP  (pass --presto to run)")
        return
    import tempfile, os, time
    import fold_analysis
    # BIT geometry: 2 ms pulses against an 11 ms sweep gives prepfold real
    # DM leverage (dm_resolution ~4.5) — the first-round 10 ms/6 ms attempt
    # was geometrically DM-blind and prepfold wandered to 19 of 26.76.
    fs, fc = 2e6, 420e6
    period, dm = 0.1, 50.0
    iq, spec = ps.synth(fs, fc, period, dm, duty=0.02, n_periods=10,
                        amplitude=0.35, noise_floor=1.0, seed=11)
    print(f"      dm_resolution: {spec.dm_resolution:.2f}")
    # repeat the buffer to ~90 s of data
    reps = int(np.ceil(90.0 * fs / spec.n_samples))
    print(f"      {spec.describe()}")
    print(f"      repeating x{reps} -> {reps * spec.n_samples / fs:.0f} s")
    d = tempfile.mkdtemp()
    path = os.path.join(d, "SIM_bit.fil")
    w = sf.FilterbankWriter(path, nchans=128, samp_rate=fs,
                            center_freq_mhz=fc / 1e6,
                            tstart_mjd=sf.unix_to_mjd(time.time()),
                            integrate=1, source_name="SIMBIT")
    for _ in range(reps):
        w.push(iq)
    w.close()
    res = fold_analysis.analyze_fil(path, source_name="SIMBIT",
                                    fold_p_s=spec.period_s, fold_dm=spec.dm,
                                    progress=lambda m: None)
    print("      verdict:", res.get("verdict"), "| chi2:", res.get("chi2_red"),
          "| P:", res.get("best_p_s"), "| DM:", res.get("best_dm"))
    ok, checks = ps.grade(spec, res)
    for c in checks:
        print("     ", c)
    check(ok, "PRESTO round trip grades PASS")


if __name__ == "__main__":
    print("PULSAR SIM TESTS")
    test_grid()
    test_pulse_shape()
    test_dispersion()
    test_grade()
    test_presto_roundtrip()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): " + ", ".join(FAILURES))
        sys.exit(1)
    print("ALL PULSAR-SIM TESTS PASSED")
