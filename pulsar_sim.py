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
