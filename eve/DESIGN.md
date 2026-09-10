# EVE modem — module layout and porting plan

Status: PROPOSAL (2026-09-08, Windows session). No modem code written yet.
Target event: Venus inferior conjunction, 2026-10-24. Reference design:
Pete Wyckoff KA3WCA (ORI), "Spiral #2", `signal_design/` in
https://github.com/OpenResearchInstitute/EVE (GPL-3.0). This app is
GPL-3.0-or-later, so the port ships under the same license with Pete/ORI
attribution in every ported file — no license conflict.

---

## 1. What the reference actually does (pinned numbers)

Read from EveDemo.m / modulate.m / channel.m / runTest.m. These are the
facts the port must match exactly; several are subtle.

| Item | Value | Where |
|---|---|---|
| FFT length | 8192 complex samples | modulate.m, runTest.m |
| FFT bin spacing = block rate | f_bin = 2.67 Hz (the Doppler spread) | EveDemo `fDop`; README |
| Modem sample rate (implied) | fs_mod = 8192 × 2.67 = **21,872.64 S/s** | derived |
| Block duration | T_blk = 1/2.67 = 0.374532 s | README |
| Alphabet | M = 4096 tones on **every other** FFT bin → tone spacing 5.34 Hz | modulate.m |
| Tone for symbol s (0-based) | FFT bin k = 2s; bins ≥ 4096 are negative frequencies; **s = 0 is DC** | modulate.m (`2*(symbol-1)+1`, 1-based) |
| Occupied bandwidth | the full 21.87 kHz, symmetric about the modem centre | derived |
| Non-coherent combining | NC = 540 blocks per symbol, summing **|FFT|** (linear magnitude, not power) | runTest.m `xr + abs(fft(r))` |
| Symbol duration | 540 × 0.374532 = **202.25 s** | derived |
| FEC | BCH(127,106), t = 3, MATLAB `bchenc` default (systematic: 106 message bits then 21 parity) | runTest.m |
| Bits → symbols | 11 symbols; symbol j takes coded bits 12j..12j+11, **LSB first** (`2.^(0:11)`); symbol 11 carries bits 121..127 + 5 zero pad | runTest.m |
| Message (one codeword) | 11 × 202.25 s = **2224.7 s ≈ 37.1 min** of symbol time | derived |
| User bit rate | 12 × 2.67 / 540 × 106/127 = **0.0495 bit/s** | EveDemo |
| Operating point | C/N0 = 0 dB-Hz → SNR in one bin = −4.26 dB | EveDemo |
| Channel per block | unit-variance complex AWGN; signal amp 10^((Es/N0 − 1.05)/20)·√8192·e^{jφ}·R, φ ~ U[0,2π), R Rayleigh with σ = √(2/π) (mean 1; −1.05 dB puts mean *power* at 1) | channel.m |
| Sim shortcut | one 8192-sample tone block is *re-used* for all 540 blocks of a symbol, each pass with fresh phase/fade/noise | runTest.m comment |
| Curve in EveDemo | NC = 540, 500, …, 140 (11 points), 100 trials each, y = % codewords decoded | EveDemo |
| Known TODO | the 5 pad bits of symbol 11 could be forced to zero (restrict its argmax to 128 tones) | runTest.m |

Why the sim shortcut matters for us: because every tone is an exact integer
number of cycles per 8192-sample block, repeating the block **is** a
phase-continuous CW tone. A streaming modulator that holds one tone for 540
blocks and hops at block boundaries (phase restarting at 0 on each symbol)
produces exactly what the reference receiver expects.

## 2. What the reference leaves to us (the real-link gaps)

1. **Doppler.** The sim has zero Doppler. At 2304 MHz the link budget's
   two-way Doppler rate reaches ~0.4 Hz/s near conjunction: ~80 Hz across
   one 202 s symbol, i.e. 15 tone spacings. Uncorrected, the energy smears
   across tones and nothing decodes. Both a TX pre-compensation (send so the
   echo lands on nominal) and an RX residual NCO are needed, driven by an
   ephemeris. Residual over a symbol must stay well under one bin (2.67 Hz),
   so the prediction must be good to ~1e-3 Hz/s and the frequency reference
   to ~1e-10.
2. **Frequency reference.** The B210 TCXO is ±2 ppm (±4.6 kHz at 2304 MHz,
   and it drifts tens of Hz over a session). An external 10 MHz + PPS from a
   GPSDO into the B210 REF IN / PPS IN is mandatory; the app has never
   touched `set_clock_source` / `set_time_source` — new, opt-in code.
3. **Sample-rate bridge.** The modem wants 21,872.64 S/s; the B210 does not
   stream that low and the app's clean rates start at 625 kS/s. Bridge with
   an exact integer factor: radio rate = fs_mod × 64 = 1,399,848.96 S/s
   (MCR 44.8 MHz, half-band chain) and a polyphase ÷64 FIR on RX; on TX no
   interpolation is needed at all — a tone is generated directly at the
   radio rate by an NCO.
4. **Zero-IF DC.** Symbol 0 is DC in modem coordinates. Put the modem centre
   at an IF offset from the LO using the app's existing verified LO-offset
   tune path (same mechanism the HI preset uses to move the DC spike out of
   band): e.g. +100 kHz, far outside the 21.9 kHz comb, not a multiple of
   the rate.
5. **Synchronization and duty cycle.** No sync in the reference; and our TX
   is ~5 min on / ~4 min off. 300 s = **exactly 801 blocks** (300 × 2.67), a
   symbol is 540, a message is 5940 blocks → 7.4 key-downs. Symbols must
   straddle cooldown gaps, which non-coherent combining tolerates *if* the
   receiver knows which received block belongs to which symbol. That is a
   timing problem, not a phase problem — GPS time solves it (§5).
6. **Round-trip overlap (monostatic).** RTT at 0.27–0.28 AU is ≈ 4.5–4.7 min.
   A 5-min key-down's echo returns from t ≈ 4.6 to 9.6 min; a 4-min cooldown
   re-keys at 9.0 min and tramples the last ~40 s of echo. Either lengthen the
   cooldown to ≥ RTT or shorten the key-down; the schedule module computes
   it from the ephemeris rather than hard-coding 5/4.
7. **TX drive policy.** The self test locks TX gain at 0 dB by design. EVE
   needs real drive into the PA chain, so the modem gets its own explicitly
   armed TX mode with interlocks (max key-down timer, cooldown enforcement,
   abort) — a deliberate policy change, called out for Rick to approve.
8. **Message format.** 106 bits per codeword is all we get. A small codec
   (e.g. 17 × 6-bit characters = 102 bits + 4 spare, or a callsign/grid
   packing) lives in its own module so the modem stays format-agnostic.
9. **Parameterization the reference hard-codes.** `f_bin`, `N_fft`, `M`,
   `NC`, `n`, `k` become an `EveParams` dataclass with the reference values
   as defaults. Needed for EveDemo's NC sweep, for the EME test (lunar
   libration spread at 1296 MHz can exceed 5.34 Hz — the test picks `f_bin`
   from the predicted spread), and for `runTest`'s "hard-coded mapping"
   TODO (the bit→symbol packer becomes general: ceil(n / log2 M) symbols).

## 3. Proposed module layout

New package `eve/` at the repo root (pure numpy/scipy core, GNU Radio only
in the two flowgraph blocks). Every file that ports Pete's code carries:

```
# Ported from EVE/signal_design/<file>.m — Pete Wyckoff, KA3WCA, Open
# Research Institute, 2026. GPL-3.0-or-later. Python port: DSES, 2026.
```

| File | Ports / role | Depends on |
|---|---|---|
| `eve/params.py` | `EveParams` (f_bin 2.67, N_fft 8192, M 4096, NC 540, BCH 127/106, IF offset, radio decimation 64) + derived properties (fs_mod, T_blk, symbol_s, symbols_per_codeword, bit_rate). One source of truth. | — |
| `eve/bch.py` | BCH(127,106) encoder/decoder over GF(2^7), primitive poly x^7+x^3+1 (MATLAB's default), generator = lcm of minimal polys of α, α³, α⁵ (Lin & Costello table: octal 11554743). Systematic [msg ‖ parity] like `bchenc`. Decoder: syndromes → Berlekamp–Massey → Chien search, t = 3. Pure Python/numpy, no `galois` dependency. | — |
| `eve/modem.py` | **The faithful core.** `pack_symbols(coded_bits)` (LSB-first 12-bit groups, zero pad), `modulate_block(symbol)` = `modulate.m` (8192-sample IFFT tone), `modulate_message(bits)` → symbol list + reference IQ at fs_mod; `Demodulator`: block FFT bank, per-symbol |FFT| accumulators on even bins, argmax, `unpack_bits`, BCH decode. Optional flag `force_pad_zero` (off = reference behaviour). No Doppler, no sync — exactly the reference. | params, bch |
| `eve/channel.py` | `channel.m` port (AWGN + random phase + Rayleigh, −1.05 dB convention) **plus** a streaming extension: Doppler ramp f0 + ḟ·t, timing offset, key-down gaps, delay. Extensions are separate functions so the reference model stays byte-comparable. | params |
| `eve/montecarlo.py` | `runTest.m` + `EveDemo.m`: the NC sweep 540→140 and the success-vs-bit-rate curve; CLI, CSV + PNG out. | modem, channel |
| `eve/doppler.py` | Two-way topocentric Doppler + RTT vs UTC for target `venus` or `moon` from the Plishner site: primary = pre-fetched JPL Horizons table (CSV, the CAMRAS approach — works offline at the site); fallback = astropy + jplephem (DE440s). Returns f(t), ḟ(t), RTT(t). Also the visibility window (reuse `pulsar_planner`'s site/alt code). | astropy, jplephem |
| `eve/schedule.py` | The block-slot timeline: epoch (UTC), slot i → symbol ⌊i/NC⌋, TX on-windows from (key_down_s, cooldown_s, RTT), RX windows = TX windows + RTT(t), overlap check, optional pilot slots. Same file drives TX and RX; serializable to JSON so a second station can use it. | doppler, params |
| `eve/sync.py` | Everything non-reference: timing search (slide the block grid ±N blocks, pick alignment maximizing accumulator contrast), residual-frequency search (±1 tone, fine NCO), pilot-tone detection, `combine_repeats()` (README fallback: sum accumulators across message repeats before decision). | modem, schedule |
| `eve/message.py` | 106-bit payload codec (text ↔ bits), CRC-free by design (BCH already has t = 3; a decode that flips >3 bits is caught by comparing repeats, see sync). | — |
| `eve/gr_blocks.py` | GNU Radio blocks: `EveToneSource` (sync_block source: schedule-driven NCO at the radio rate, phase 0 at each symbol start, silence in off-windows, TX pre-Doppler applied; streams indefinitely — no vector_source loop) and `EveRxSink` (sync_block sink: ÷64 polyphase FIR → fs_mod → RX Doppler NCO → writes `.eve.iq` complex64 + JSON sidecar with USRP-time start, fs, centre, Doppler model; keeps live per-symbol accumulators for the dialog). Mirrors `sigproc_fil.FilterbankSink`. | gnuradio, modem, schedule |
| `eve/radio.py` | Thin B210 helpers used by the app and the bench tool: external ref/PPS setup + `ref_locked` sensor readback, `set_time_next_pps` from GPS UTC, rate readback check (actual vs fs_mod×64), IF-offset tune via the existing `UhdB200Source._tune` path. | uhd |
| `tools/eve_bench.py` | Headless harness like `tools/b210_bit.py`: loopback soak (TX→RX internal leakage, min gain, 5-min key-down, underrun/gap counters), offline-noise injection to C/N0 = 0 dB, EME/Venus run modes with `--target moon|venus`. | eve/* |
| `test_eve_modem.py` | Repo-style `check()` suite: BCH (round trip, ≤3 errors corrected, 4 errors detected/failed, generator poly vs table), modulator IQ vs MATLAB reference vectors, demod on the reference channel at −4.26 dB, EveDemo curve regression (fewer trials), streaming channel with Doppler + gaps through sync. | eve/* |
| App: `dses_workbench.py` | `EveModemDialog` (Observe menu, next to the Self Test; non-modal — a message takes an hour), TX/RX splice using the self-test pattern, new recording format entry. Kept thin; all logic in `eve/`. | eve/* |
| `eve/matlab_ref/` | Pete's four `.m` files verbatim (GPL, attributed) + `make_reference_vectors.m` + the generated `.mat`/`.npz` golden vectors. | MATLAB |

Ship lists in `make-release.ps1` / `make-release.sh` gain the `eve/`
package (lazy import from the app, so the completeness guard will not see
it — add explicitly, as for `pulsar_sim.py`). `environment.yml` gains
`jplephem` (and `astroquery` only if we choose live Horizons fetches; the
pre-fetched-CSV route needs neither at the site).

## 4. Hooks into the existing B210 code

Reuse, not a parallel stack. Concretely:

- **Device + RX stream:** `UhdB200Source` (`dses_workbench.py:4060`)
  stays the one RX object. Add to it, opt-in: `set_reference(clock, time)`,
  `ref_locked()`, `get_time_now()`, `set_time_next_pps()`. Nothing changes
  for normal users.
- **Tuning:** the verified LO-offset path `UhdB200Source._tune`
  (`:4202`) parks the LO at centre + IF offset and verifies
  `actual_dsp_freq`. The modem centre = the app's centre frequency; the comb
  sits at the IF offset. Same code the HI drift-scan preset already trusts.
- **TX splice:** `_selftest_begin` (`:8825`) is the template: save the radio
  state, `uhd.usrp_sink` on the same serial, `TX/RX` port, RX moved to
  `RX2`, `lock()/connect()/unlock()`, `_begin_realtime_mode()`. Differences:
  `EveToneSource` instead of `vector_source_c` (a 5-min key-down is 420 M
  samples — nothing to loop, generate on the fly; the NCO at 1.4 MS/s is a
  trivial numpy load), deep `set_min_output_buffer` kept, TX gain from the
  dialog (armed), and teardown/restore reused as-is.
- **RX capture:** `EveRxSink` connects to `self.uhd_usrp_source_0` exactly
  like `FilterbankSink` in `_start_recording` (`:8448`); the SigMF raw path
  remains available to record the full 1.4 MS/s stream alongside when we
  want to re-run the demod offline with other Doppler/sync hypotheses (the
  CAMRAS reprocessing precedent).
- **Display:** untouched. The spectrum display keeps showing the 1.4 MHz
  band; the EVE dialog draws its own 4096-tone accumulator strip.
- **Planner/visibility:** `pulsar_planner`'s site + altitude machinery gives
  the Venus/Moon window at Plishner for the schedule.
- **Bench harness:** `tools/eve_bench.py` follows `tools/b210_bit.py`
  (device discovery, `_ensure_uhd_images`, gap/underrun readout).

## 5. Sync proposal (task 3) — separate module, core untouched

Non-coherent 4096-FSK needs no phase reference between stations; what it
needs is (a) which 0.375 s block goes into which symbol accumulator, and
(b) the tone landing within a fraction of 2.67 Hz of where the FFT expects
it for the whole 202 s. The maser at Dwingeloo/Stockert buys both; GPS buys
both cheaply for Plishner:

1. **Time (block assignment):** GPSDO PPS + 10 MHz into the B210; USRP time
   set to UTC on a PPS edge; the schedule defines block boundaries in UTC
   from a published epoch; RX applies the ephemeris RTT to map arrival time
   → slot. Tolerance is a fraction of 0.375 s; GPS gives ≪ 1 ms. Gaps
   (cooldowns) are just slots with no energy. This is what lets symbols
   straddle key-downs.
2. **Frequency (Doppler):** ephemeris pre-compensation at TX so the echo
   arrives at nominal, residual NCO at RX from the same model. Frequency
   accuracy from the GPSDO (1e-11 → 0.02 Hz at 2304 MHz).
3. **Pilot (optional, cheap insurance):** the schedule reserves a known
   tone for the first ~40 blocks (15 s) of each key-down. The receiver
   locates it (search ±2 tones, ±3 blocks) to *verify* the timing/Doppler
   model live and to trim residual frequency. Cost ≈ 5 % of throughput;
   selectable per run.
4. **Fallback (README's suggestion):** repeat the codeword K times on the
   schedule; `combine_repeats()` sums accumulators per symbol before
   deciding. Plus a coarse block-grid search when the epoch is uncertain.

Monostatic vs bistatic: for DSES hearing its own echo everything is on one
clock; for a partner station (Dwingeloo/Stockert receiving DSES, or the
reverse) the schedule JSON + epoch is the whole contract.

## 6. Porting and validation plan (tasks 1, 2, 4)

**Stage 0 — reference vectors (before porting).** MATLAB R2023a is on this
box *without* the Communications Toolbox, so `modulate.m` (core IFFT) runs
here but `gf`/`bchenc`/`bchdec` do not. Plan: (a) `make_reference_vectors.m`
runs `modulate.m` for every symbol and a fixed test message; (b) ask Pete
for one golden `bchenc` vector (message bits → 127 coded bits) and, ideally,
his EveDemo `store`/`bitRate` arrays; (c) until then, the BCH generator
polynomial is checked against Lin & Costello's table and MATLAB's
documented `bchgenpoly(127,106)`.

**Stage 1 — modulator (task 1).** `bch.py` + `modem.py` modulate side.
Gate: IQ bit-exact (to float tolerance) against the MATLAB vectors for the
same test message; BCH round trip; symbol packing verified against the
`runTest.m` arithmetic by hand-computed cases.

**Stage 2 — demodulator + Monte Carlo (task 2).** `modem.py` demod side,
`channel.py` reference model, `montecarlo.py`. Gate: reproduce the
EveDemo curve (11 NC points × 100 trials at −4.26 dB) and compare with
Pete's plot/numbers; cross-check against a semi-analytic prediction
(non-coherent M-FSK with NC-fold combining in Rayleigh, then BCH t = 3).
This is the "before touching hardware" checkpoint.

**Stage 3 — streaming realism (still software).** Extended channel with
Doppler ramp, gaps, timing offset → `schedule.py` + `sync.py`. Gate: decode
at the reference operating point with a 0.4 Hz/s ramp, 801/≥RTT-block
duty cycle, and a deliberately wrong epoch recovered by the block search.
Also run the FFT bank over the **real CAMRAS Venus echoes** (March 2025,
public, 5 kS/s SigMF + Doppler CSV): validates `doppler.py` against their
CSV and measures the actual spread against the 2.67 Hz assumption on real
data.

**Stage 4 — B210 loopback.** `tools/eve_bench.py`: internal TX→RX leakage
at min gain (the self-test trick), a full 5-min key-down soak watching
underruns ('U') and RX gaps, external-ref lock readback, rate readback vs
fs_mod × 64, and frequency accuracy of the B210 TX with the E4438C / 53230A
on the bench (both on the lab GPS reference). Noise to reach C/N0 = 0 dB is
added offline to the captured `.eve.iq` — a leakage path cannot be made
that weak on purpose.

**Stage 5 — EME at very low power.** `--target moon`. Differences from
Venus, all parameterized: RTT ≈ 2.5 s (so TX/RX must *alternate at ~RTT*
inside a key-down — the schedule handles it; the PA/sequencer keying rate
is the item to confirm), Doppler ±kHz with small rate, libration spread
that can exceed the 5.34 Hz tone spacing at 1296 MHz (pick a low-libration
window or set `f_bin` from the predicted spread), and a link so strong
that the power must be cut to milliwatts to land near C/N0 ≈ 0 dB and
actually exercise the design. Proves: schedule/keying, GPS time, Doppler
module, sync, demod, the whole chain end-to-end.

**Stage 6 — Venus, 2026-10-24 (± a few days).** Schedule from the
visibility window at Plishner; solar proximity at conjunction is a Tsys
item to check in the link budget.

## 7. Open questions for Rick / Pete

1. Frequency: 2304 MHz per the link budget's DSES dataclass (1296 commented
   out). Confirm, and confirm the 2304 PA/feed status (link budget assumes
   1500 W, η 0.69, 0.4 dB LNA).
2. GPSDO at Plishner for the B210 REF/PPS — what is on site?
3. Monostatic (own echo) or bistatic with Dwingeloo/Stockert? Affects
   the schedule contract and whether RX-during-TX matters.
4. Key-down 5 / cooldown 4 min: can the cooldown stretch to ≥ RTT
   (~4.7 min), or should the key-down shrink to ~4.3 min?
5. Message content and format (106 bits).
6. Pete: golden `bchenc` vector + EveDemo numbers; is he open to
   `force_pad_zero` and the pilot as documented options?

## 8. Library note (standing request)

Rick's shelf already covers the coding side (Lin & Costello 2nd ed. has
the BCH generator table; Clark & Cain) and radar (Skolnik). The gap for
this project is deep-space link synchronization and non-coherent
detection at low C/N0. Suggested addition: *Deep Space Communications*
(JPL DESCANSO series, Joseph Yuen, ed.; free PDF from JPL) — the reference
for exactly this regime; and Mengali & D'Andrea, *Synchronization
Techniques for Digital Receivers*, for the sync module.

---

## Update 2026-09-09 — ORI's Python implementation found; decisions

**Found.** Michelle re-published `signal_design/Python_Implementation/`
in the EVE repo on 2026-09-08 (permissions had hidden it). It is a
**transmit-only SigMF generator** (`eve_tx_sigmf.py`: text → 90 bits +
CRC-16 → BCH(127,106) via `galois` → 11 MSB-first 12-bit symbols →
continuous-phase tone per symbol → cf32 SigMF at 250 kS/s, comb offset
25 kHz above the tune) plus an **AWGN analytic link check**
(`eve_link_check.py`). Written by Michelle from Pete's June 2026 slide,
not ported from the MATLAB. No demodulator, channel model, Doppler, or
sync. "Tested" = tones land on d×5.74 Hz, BCH round-trips, SigMF
validates, 22 s smoke file played through a B210. Never received over
the air. The smoke SigMF pair named in its README is not in the repo.

**It is a different waveform from the MATLAB** (section 1 above):

| Parameter | MATLAB (May) | Python (June slide) |
|---|---|---|
| bin / spread | 2.67 Hz | 2.87 Hz |
| tone spacing | 5.34 Hz | 5.74 Hz |
| frames per symbol | 540 | 473 (slide ≈ 440) |
| symbol | 202.25 s | 164.794 s (= 472.96 frames, not integer) |
| bit order | LSB first | MSB first |
| comb | symmetric about DC | one-sided 0–23.5 kHz |
| payload | 106 random bits | 90 msg + CRC-16 |

BCH generator polynomial is the same in both (Lin & Costello octal
11554743 = galois default = MATLAB `bchenc`), so the golden-vector gap
in Stage 0 is closed.

**Decisions (Rick, 2026-09-09).**
1. Treat the Python conventions as the interoperability spec (it is what
   the other stations get); keep `EveParams` switchable to the MATLAB set
   for reproducing Pete's curve. Confirmation of 2.87 Hz / frame count
   requested from Pete and Michelle (email sent 2026-09-09 18:10 MDT,
   NAS DSES archive; also asks monostatic vs bistatic and whether ORI
   wants the receiver contributed back).
2. The modulator port shrinks to adopting the generator's conventions
   plus our streaming/schedule layer; the demodulator, Rayleigh channel,
   Doppler, schedule, sync and validation stages are unchanged and still
   ours to build. `galois` becomes a dependency (environment.yml).
3. **Separate project, not inside the Workbench.** EVE is a station
   controller (real TX drive, key-down/cooldown interlocks, ephemeris
   schedule, 30-min frames) and ships to nobody who runs the Workbench;
   the Workbench keeps its TX-locked-at-minimum policy and its release
   train. Reuse is by factoring the B210 radio classes out of
   `dses_workbench.py` into an importable module (a refactor the
   Workbench benefits from too) plus copying the small proven pieces.
   One B210 = one process, so the EVE tool owns the radio during a run.
4. Constant envelope confirmed for the Class-C PAs: one tone at a time at
   fixed amplitude; only the ten symbol-hop phase steps are non-constant,
   and our streaming source will make hops phase-continuous.
