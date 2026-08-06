#!/usr/bin/env python3
"""
pulsar_sim.py -- software-defined pulsar: baseband I/Q synthesis for the
B210 built-in test.

Generates a repeating pulse train that folds like a real pulsar:

  * NOISE carrier, not a tone. Each pulse is band-limited Gaussian noise
    under a smooth profile envelope. A gated sine folds with pathological
    statistics (chi-squared explodes to infinity, as the 2026-08-02 bench
    tests showed); noise bursts give finite, radiometer-like sigma.

  * Real cold-plasma DISPERSION, applied coherently: the whole waveform is
    multiplied in the frequency domain by the exact inverse of the kernel
    coherent DEdispersion uses (Hankins & Rickett), so lower frequencies
    arrive later by

        dt = K_DM * DM * (f1^-2 - f2^-2),   K_DM = 4.148808e3 s MHz^2 pc^-1 cm^3

    exactly as the interstellar medium would do it. This is what makes the
    fold's DM axis testable at all -- the DSES hardware simulator has no
    dispersion, so a DM search against it can only ever find zero.

  * SEAMLESS LOOPING: the buffer holds an integer number of pulse periods
    and the period is quantized onto the sample grid, so repeating the
    buffer end-on-end keeps pulse phase exact forever. This is what lets a
    finite buffer drive an arbitrarily long recording (GNU Radio
    vector_source with repeat=True, or a future AWG).

Ground truth travels with the waveform: `SimSpec` records exactly what was
injected so the analysis side can be graded PASS/FAIL against it.

Pure numpy/scipy -- no GNU Radio import here, so the module is usable for
offline validation, the app's built-in test, and AWG file export alike.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import fft as scipy_fft

K_DM_S_MHZ2 = 4.148808e3       # dispersion constant, s * MHz^2 * (pc cm^-3)^-1


@dataclass
class SimSpec:
    """Everything injected, for later PASS/FAIL grading."""
    samp_rate: float            # Hz (I/Q)
    center_freq_hz: float       # RF center the buffer is built for
    period_s: float             # pulse period AFTER grid quantization
    dm: float                   # pc cm^-3
    duty: float                 # FWHM as a fraction of the period
    n_periods: int              # periods held in the buffer
    amplitude: float            # peak pulse envelope (linear, vs unit noise)
    noise_floor: float          # off-pulse noise amplitude (0 = silence)
    seed: int
    n_samples: int = field(default=0)

    @property
    def dispersion_sweep_s(self):
        """Arrival-time spread across the band (top edge vs bottom edge)."""
        f_lo = (self.center_freq_hz - self.samp_rate / 2.0) / 1e6
        f_hi = (self.center_freq_hz + self.samp_rate / 2.0) / 1e6
        return K_DM_S_MHZ2 * self.dm * (f_lo ** -2 - f_hi ** -2)

    @property
    def dm_resolution(self):
        """DM uncertainty this geometry can honestly resolve: the DM change
        that shifts the cross-band sweep by half the pulse FWHM. A fold
        cannot localize DM tighter than this -- narrow band + fat pulse =
        weak DM leverage (the Haswell B0950+08 lesson, quantified). The
        2026-08-05 round trip measured it directly: 10 ms pulses over a
        5.99 ms sweep (resolution ~22) let prepfold optimize DM 26.76 down
        to 19.2 while period and chi2 stayed dead-on."""
        f_lo = (self.center_freq_hz - self.samp_rate / 2.0) / 1e6
        f_hi = (self.center_freq_hz + self.samp_rate / 2.0) / 1e6
        sweep_per_dm = K_DM_S_MHZ2 * (f_lo ** -2 - f_hi ** -2)
        fwhm_s = self.duty * self.period_s
        return 0.5 * fwhm_s / sweep_per_dm

    def describe(self):
        return (f"P={self.period_s * 1e3:.6f} ms  DM={self.dm:g}  "
                f"duty={self.duty * 100:.1f}%  amp={self.amplitude:g}  "
                f"{self.n_periods} periods @ {self.samp_rate / 1e6:g} MS/s "
                f"({self.n_samples} samples), DM sweep "
                f"{self.dispersion_sweep_s * 1e3:.2f} ms across the band")


def quantize_period(period_s, samp_rate):
    """Snap the period onto the sample grid: P*fs must be an integer or the
    loop seam slips pulse phase a little every repeat and the fold smears."""
    n = max(1, int(round(period_s * samp_rate)))
    return n / samp_rate, n


def disperse(iq, samp_rate, center_freq_hz, dm):
    """Apply cold-plasma dispersion coherently to a baseband waveform.

    Multiplies the spectrum by exp(+j*phi(v)) with the standard chirp

        phi(v) = 2*pi * K_DM*1e6 * DM * v^2 / (fc^2 * (fc + v))   [f in MHz]

    which delays lower frequencies relative to higher ones by exactly the
    catalog dispersion law. Sign convention: scipy's ifft reconstructs with
    exp(+2*pi*j*v*t), so a spectral factor exp(j*theta) imposes group delay
    -theta'(omega); with theta = +phi above that is  +K_DM*DM*(f^-2 - fc^-2)
    -- low frequencies LATE, as the ISM does it. Verified empirically by the
    sub-band arrival-time test in test_pulsar_sim.py.
    Applied over the FULL buffer so the delay wraps circularly at the loop
    seam -- harmless, because the buffer repeats seamlessly anyway.
    """
    n = len(iq)
    v = scipy_fft.fftfreq(n, d=1.0 / samp_rate) / 1e6          # offsets, MHz
    fc = center_freq_hz / 1e6
    # seconds of extra delay for the component at offset v (negative v later)
    phase = 2.0 * np.pi * (K_DM_S_MHZ2 * 1e6) * dm * v * v / (fc * fc * (fc + v))
    spec = scipy_fft.fft(iq, workers=-1)
    spec *= np.exp(1j * phase).astype(np.complex64)
    out = scipy_fft.ifft(spec, workers=-1)
    return out.astype(np.complex64)


def synth(samp_rate, center_freq_hz, period_s, dm, *, duty=0.05,
          n_periods=4, amplitude=1.0, noise_floor=0.0, seed=1):
    """Build the loopable dispersed pulse-train buffer.

    Returns (iq_complex64, SimSpec). Each pulse is complex Gaussian noise
    under a Gaussian envelope of FWHM = duty*period centered in each
    period; the whole train is then dispersed as one coherent waveform.
    Peak envelope is `amplitude`; `noise_floor` adds an ever-present noise
    bed (0 keeps the off-pulse silent -- the receiver adds its own).
    """
    period_s, n_per = quantize_period(period_s, samp_rate)
    n = n_per * n_periods
    rng = np.random.default_rng(seed)

    # envelope: one Gaussian per period, FWHM = duty * period
    t = np.arange(n_per, dtype=np.float64) / samp_rate
    t0 = period_s / 2.0
    sigma = (duty * period_s) / 2.35482        # FWHM -> sigma
    env_one = np.exp(-0.5 * ((t - t0) / sigma) ** 2)
    env = np.tile(env_one, n_periods)

    noise = (rng.standard_normal(n) + 1j * rng.standard_normal(n)) / np.sqrt(2.0)
    iq = (amplitude * env * noise).astype(np.complex64)
    if noise_floor > 0.0:
        bed = (rng.standard_normal(n) + 1j * rng.standard_normal(n)) / np.sqrt(2.0)
        iq += (noise_floor * bed).astype(np.complex64)

    if dm > 0.0:
        iq = disperse(iq, samp_rate, center_freq_hz, dm)

    spec = SimSpec(samp_rate=samp_rate, center_freq_hz=center_freq_hz,
                   period_s=period_s, dm=dm, duty=duty, n_periods=n_periods,
                   amplitude=amplitude, noise_floor=noise_floor, seed=seed,
                   n_samples=n)
    return iq, spec


def grade(spec, result, *, p_tol_frac=0.005, dm_tol_frac=0.25, dm_tol_abs=2.0,
          min_sigma=4.0):
    """PASS/FAIL a fold_analysis result dict against the injected truth.

    Tolerances reflect what a short recording can honestly resolve:
      * period within 0.5% (prepfold search granularity on ~minutes of data)
      * DM within 25%, +/-2 pc cm^-3, or the geometry's own dm_resolution --
        whichever is loosest (narrow bands constrain DM weakly; a tolerance
        tighter than the band can resolve just fails good hardware)
      * significance at least `min_sigma` (or an off-scale chi2)
    Returns (passed, list_of_check_strings).
    """
    checks = []
    ok = True

    best_p = result.get("best_p_s")
    if best_p:
        err = abs(best_p - spec.period_s) / spec.period_s
        good = err <= p_tol_frac
        checks.append(f"{'PASS' if good else 'FAIL'}  period: recovered "
                      f"{best_p * 1e3:.5f} ms vs injected "
                      f"{spec.period_s * 1e3:.5f} ms ({err * 100:.3f}% off)")
        ok &= good
    else:
        checks.append("FAIL  period: none recovered")
        ok = False

    best_dm = result.get("best_dm")
    if spec.dm > 0:
        if best_dm is not None:
            tol = max(spec.dm * dm_tol_frac, dm_tol_abs, spec.dm_resolution)
            good = abs(best_dm - spec.dm) <= tol
            checks.append(f"{'PASS' if good else 'FAIL'}  DM: recovered "
                          f"{best_dm:.2f} vs injected {spec.dm:g} "
                          f"(tolerance +/-{tol:.2f})")
            ok &= good
        else:
            checks.append("FAIL  DM: none recovered")
            ok = False

    chi2 = result.get("chi2_red")
    sigma = result.get("sigma")
    if sigma is not None and np.isfinite(sigma):
        good = sigma >= min_sigma
        checks.append(f"{'PASS' if good else 'FAIL'}  significance: "
                      f"{sigma:.1f} sigma (need >= {min_sigma:g})")
        ok &= good
    elif chi2 is not None:
        good = (not np.isfinite(chi2)) or chi2 >= 1.5
        checks.append(f"{'PASS' if good else 'FAIL'}  chi2_red: {chi2}")
        ok &= good
    else:
        checks.append("WARN  no significance figure in result")

    return ok, checks


# ---------------------------------------------------------------------------
# Geometry solver: "what do I need to measure THIS source's DM?"
# ---------------------------------------------------------------------------
#
# The B0950+08 lesson, generalized (Rick 2026-08-06). Dispersion delay across
# a band goes as f^-2, so DM leverage collapses at high frequency and narrow
# bandwidth: at 420 MHz / 2 MHz, DM 2.97 sweeps only 0.66 ms -- far less than
# a 5 ms pulse -- and a fold can only rail the DM search to zero. The same
# source at 160 MHz / 2 MHz sweeps 12 ms and its DM IS measurable (verified
# on hardware 2026-08-06: recovered 3.42 vs 2.97 injected).
#
# Rather than remember that per source, invert the arithmetic: given a
# catalog period and DM, solve for the geometry that resolves it.

# Frequencies the DSES dish can actually observe (feed-limited); real-
# observation advice is restricted to these. Callers may override.
DSES_BANDS_HZ = (408e6, 680.5e6, 1299.5e6, 1420.406e6)
# Sample rates validated for .fil recording (the B210 reaches 61.44 MS/s but
# the recording chain is proven to 20).
RECORD_RATES_HZ = (0.625e6, 1e6, 1.25e6, 2e6, 4e6, 5e6, 8e6, 10e6, 16e6, 20e6)
# The radio's single-channel ceiling -- reachable, but past the rates the
# recording chain has been proven at.
B210_MAX_RATE_HZ = 61.44e6
# Candidate simulator frequencies: the self test's TX is internal and locked
# at minimum gain, so the only rules are avoiding the FM broadcast band
# (88-108 MHz, where ambient RF swamps the leakage path) and staying high
# enough that internal TX->RX coupling is usable.
SIM_FREQS_HZ = (75e6, 120e6, 160e6, 220e6, 300e6, 420e6, 600e6, 900e6,
                1420.406e6)
# Internal-leakage coupling weakens toward the low end (measured: 420 MHz
# folds at ~10 sigma with 40 dB RX gain; 100 MHz was too weak at that gain,
# and 160 MHz worked at ~70 dB).
_SIM_GAIN_BREAK_HZ = 250e6
# Highest sample rate at which the full-duplex TX loop is known to hold its
# timing (2026-08-05: 4 MS/s underflowed and stretched the pulse spacing;
# 2 MS/s recovered the injected period exactly).
SAFE_DUPLEX_RATE_HZ = 2e6


def sweep_per_dm_s(center_hz, bw_hz):
    """Dispersion delay across the band, per unit DM (seconds)."""
    f_lo = (center_hz - bw_hz / 2.0) / 1e6
    f_hi = (center_hz + bw_hz / 2.0) / 1e6
    if f_lo <= 0:
        return float("inf")
    return K_DM_S_MHZ2 * (f_lo ** -2 - f_hi ** -2)


def dm_resolution_for(center_hz, bw_hz, period_s, duty):
    """Smallest DM difference this geometry can distinguish -- the same rule
    as SimSpec.dm_resolution, with standalone inputs."""
    sweep = sweep_per_dm_s(center_hz, bw_hz)
    if sweep <= 0:
        return float("inf")
    return 0.5 * duty * period_s / sweep


def channel_smear_s(dm, chan_bw_hz, center_hz):
    """Dispersion smearing WITHIN one channel: a floor on time resolution
    that no amount of sampling undoes (8.3 us x DM x dnu_MHz / f_GHz^3)."""
    return 8.3e-6 * dm * (chan_bw_hz / 1e6) / (center_hz / 1e9) ** 3


def channels_for(dm, center_hz, rate_hz, period_s, duty, smear_frac=0.25,
                 samples_per_pulse=8.0, max_chans=4096):
    """(nchans, note) -- the most channels that still sample the pulse.

    The two constraints pull opposite ways: finer channels cut intra-channel
    dispersion smearing, but they slow tsamp (= nchans/rate). So take the
    largest power of two whose tsamp still puts `samples_per_pulse` samples
    across the pulse, which automatically minimizes smearing. That is what
    the validated geometries do in practice -- this rule reproduces the
    Haswell UHF choice (20 MS/s, 35 ms pulse -> 4096 ch, tsamp 205 us
    against the proven 204.8 us). Returns (None, why) when even the coarsest
    usable channelization still smears the pulse away.
    """
    fwhm = duty * period_s
    hi = rate_hz * fwhm / samples_per_pulse
    n = 16
    while n * 2 <= hi and n * 2 <= max_chans:
        n *= 2
    if n > hi:
        return None, (f"the pulse is too narrow for this rate: even "
                      f"{n} channels gives tsamp "
                      f"{n / rate_hz * 1e3:.2f} ms vs a "
                      f"{fwhm * 1e3:.2f} ms pulse")
    smear = channel_smear_s(dm, rate_hz / n, center_hz)
    if smear > smear_frac * fwhm:
        return n, (f"intra-channel smearing {smear * 1e3:.1f} ms is a large "
                   f"fraction of the {fwhm * 1e3:.1f} ms pulse - the pulse "
                   f"arrives blurred no matter how it is sampled")
    return n, ""


def max_center_hz_for(bw_hz, period_s, dm, duty, target_res):
    """Highest center frequency at which `bw_hz` still resolves the DM to
    `target_res` (bisection -- resolution worsens monotonically with
    frequency). None if even the lowest usable frequency cannot."""
    lo, hi = max(20e6, bw_hz / 2.0 + 1e6), 6000e6
    if dm_resolution_for(lo, bw_hz, period_s, duty) > target_res:
        return None
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if dm_resolution_for(mid, bw_hz, period_s, duty) <= target_res:
            lo = mid
        else:
            hi = mid
    return lo


def min_bandwidth_hz_for(center_hz, period_s, dm, duty, target_res):
    """Narrowest bandwidth at `center_hz` that resolves the DM to
    `target_res`, or None if nothing up to a 200 MHz span does."""
    lo, hi = 1e3, min(2.0 * center_hz - 1e6, 200e6)
    if dm_resolution_for(center_hz, hi, period_s, duty) > target_res:
        return None
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if dm_resolution_for(center_hz, mid, period_s, duty) <= target_res:
            hi = mid
        else:
            lo = mid
    return hi


def recommend_geometry(period_s, dm, *, duty=0.02, name="", bands=None,
                       rates=None, sim_freqs=None, target_frac=1.0 / 3.0,
                       target_abs=None, max_capture_s=600.0):
    """Solve for the geometry that makes this source's DM measurable.

    Returns a dict with `real` (one row per observing band: the best rate
    there and whether it resolves the DM), `sim` (a simulator geometry --
    any frequency allowed, since the self test's TX is internal), and
    `lines` (a ready-to-display report). The DM goal is `target_frac` of
    the catalog DM unless `target_abs` is given.
    """
    bands = tuple(bands or DSES_BANDS_HZ)
    rates = tuple(rates or RECORD_RATES_HZ)
    sim_freqs = tuple(sim_freqs or SIM_FREQS_HZ)
    fwhm = duty * period_s
    target = target_abs if target_abs else max(0.2, dm * target_frac)

    def _row(center_hz, rate_hz, duty_):
        res = dm_resolution_for(center_hz, rate_hz, period_s, duty_)
        nch, note = channels_for(dm, center_hz, rate_hz, period_s, duty_)
        return {"center_hz": center_hz, "rate_hz": rate_hz, "duty": duty_,
                "dm_res": res, "resolves": res <= target, "nchans": nch,
                "note": note,
                "smear_s": (channel_smear_s(dm, rate_hz / nch, center_hz)
                            if nch else None),
                "tsamp_s": (nch / rate_hz) if nch else None}

    real = []
    for b in bands:
        best = None
        for r in rates:
            row = _row(b, r, duty)
            if row["nchans"] is None:
                continue
            if best is None:
                best = row
            if row["resolves"]:
                best = row       # cheapest rate that resolves wins
                break
            if row["rate_hz"] > best["rate_hz"]:
                best = row       # else keep the widest attempt, to report
        if best is None:
            best = _row(b, rates[-1], duty)
        best["need_bw_hz"] = min_bandwidth_hz_for(b, period_s, dm, duty,
                                                  target)
        real.append(best)

    # Simulator preference, encoding both hardware lessons at once:
    #   * Internal TX->RX coupling weakens toward the low end (100 MHz was
    #     too weak at 40 dB RX gain; 160 MHz worked at 70 dB), so prefer the
    #     HIGHEST frequency that resolves the DM.
    #   * In full duplex the TX loop starves above ~2 MS/s (4 MS/s
    #     underflowed and stretched the pulse spacing on 2026-08-05; 2 MS/s
    #     recovers the period exactly), so stay within the safe rates unless
    #     nothing there works -- and say so when leaving them.
    #   * Sharpen the duty only if a catalog-like duty cannot get there.
    # For B0950+08 this reproduces the geometry verified on hardware
    # 2026-08-06: 160 MHz, 2 MS/s, 70 dB RX gain.
    safe = [r for r in rates if r <= SAFE_DUPLEX_RATE_HZ] or [rates[0]]
    fast = [r for r in rates if r > SAFE_DUPLEX_RATE_HZ]
    sim = None
    for tier, tier_rates in (("safe", safe), ("fast", fast)):
        for duty_try in (duty, duty / 2.0, duty / 4.0):
            for f in sorted(sim_freqs, reverse=True):
                for r in tier_rates:
                    row = _row(f, r, duty_try)
                    if row["nchans"] and row["resolves"]:
                        sim = row
                        sim["tier"] = tier
                        break
                if sim:
                    break
            if sim:
                break
        if sim:
            break
    if sim:
        sim["rx_gain_db"] = (70.0 if sim["center_hz"] < _SIM_GAIN_BREAK_HZ
                             else 40.0)
        sim["capture_s"] = float(min(max_capture_s,
                                     max(90.0, 40.0 * period_s)))

    # --- readable report --------------------------------------------------
    L = []
    who = name or "this source"
    L.append(f"{who}: P = {period_s * 1e3:.4f} ms, DM = {dm:g}, "
             f"assumed duty {duty * 100:.1f}% (pulse {fwhm * 1e3:.2f} ms)")
    L.append(f"Goal: measure DM to +/-{target:.2f}")
    L.append("")
    L.append("REAL OBSERVING BANDS (what the dish can see):")
    for r in real:
        tag = "YES" if r["resolves"] else "NO "
        line = (f"  {r['center_hz'] / 1e6:9.3f} MHz  "
                f"{r['rate_hz'] / 1e6:>5.4g} MS/s  ->  DM res "
                f"+/-{r['dm_res']:8.2f}  {tag}")
        if r["nchans"]:
            line += f"   {r['nchans']} ch"
        L.append(line)
        if not r["resolves"]:
            need = r["need_bw_hz"]
            if need and need <= max(rates):
                L.append(f"       needs >= {need / 1e6:.1f} MS/s here")
            elif need and need <= B210_MAX_RATE_HZ:
                L.append(f"       needs ~{need / 1e6:.0f} MS/s - the B210 "
                         f"tunes that wide, but .fil recording is validated "
                         f"only to {max(rates) / 1e6:g} MS/s (so this is "
                         f"close, not proven)")
            elif need:
                L.append(f"       would need ~{need / 1e6:.0f} MHz of band "
                         f"- beyond what the radio can deliver")
            else:
                L.append("       no bandwidth at this frequency resolves it")
        if r["note"]:
            L.append(f"       {r['note']}")
    workable = [r for r in real if r["resolves"]]
    L.append("")
    if workable:
        b = min(workable, key=lambda r: r["rate_hz"])
        L.append(f"BEST REAL OPTION: {b['center_hz'] / 1e6:.3f} MHz at "
                 f"{b['rate_hz'] / 1e6:g} MS/s, {b['nchans']} channels "
                 f"(DM to +/-{b['dm_res']:.2f}).")
    else:
        L.append("BEST REAL OPTION: none - at every available feed this "
                 "source's DM is smaller than the geometry can resolve, so "
                 "a DM search will slide toward zero. A detection is still "
                 "valid; only the DM is unconstrained (fold at the catalog "
                 "DM and say so in the report).")
    L.append("")
    if sim:
        L.append("SIMULATOR (self test - any frequency, TX is internal):")
        L.append(f"  {sim['center_hz'] / 1e6:.3f} MHz, "
                 f"{sim['rate_hz'] / 1e6:g} MS/s, duty "
                 f"{sim['duty'] * 100:.1f}%, RX gain "
                 f"{sim['rx_gain_db']:.0f} dB, {sim['nchans']} channels, "
                 f"{sim['capture_s']:.0f} s")
        L.append(f"  -> DM resolution +/-{sim['dm_res']:.2f}"
                 + (f" (pulse sharpened to {sim['duty'] * 100:.1f}% to get "
                    f"there)" if abs(sim["duty"] - duty) > 1e-9 else ""))
        if sim.get("tier") == "fast":
            L.append(f"  NOTE: {sim['rate_hz'] / 1e6:g} MS/s is above the "
                     f"{SAFE_DUPLEX_RATE_HZ / 1e6:g} MS/s the duplex TX loop "
                     f"holds timing at - expect a few tenths of a percent of "
                     f"period wobble from TX underflows.")
    else:
        L.append("SIMULATOR: no geometry in range resolves this DM - it is "
                 "too small, or the period too long, for any B210 band.")
    return {"target": target, "real": real, "sim": sim, "lines": L,
            "period_s": period_s, "dm": dm, "duty": duty, "name": name}
