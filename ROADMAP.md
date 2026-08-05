# DSES Spectrum Analyzer — Roadmap

Feature ideas and planned work, by target version. This file is the shared
cross-machine record (Mac + Windows) — keep it committed and pushed.

Conventions: `[ ]` planned, `[x]` shipped (note the commit), `[-]` dropped
(note why). Move items between versions freely until they ship.

## v1.1.8 — SHIPPED 2026-08-03 (cut + published from Windows)

**Release plan (Rick, 2026-08-02):** no point release for the two Ray UI
fixes — everything below ships together as 1.1.8 when the timebase and
ezRA work are done.

**Ray's hardware (for reference):** an old **HackRF** product, not a B210.
Implications: his "best-ever H-line" validation of 1.1.7 was on an 8-bit
zero-IF SDR via the Soapy path; and the timebase/gap-padding design must
NOT assume UHD — gr-uhd emits precise `rx_time` tags on overflow (exact
gap length), while the Soapy path (HackRF/SDRplay/RTL) may only give us
overflow 'O' counts, so precise padding for UHD + best-effort counting/
flagging for Soapy sources.

- [x] **Ray's weak-signal A/B verification — CLOSED 2026-08-01 by field
      results:** on 1.1.7, Ray's morning data was "the best Hydrogen line
      measurements he has ever made" (via Rick). No further A/B needed; the
      1420.5/1418/1425.6 sig-gen ground truth stays on record above.

- [x] **Ray bug: RX gain slider clipped on his screen — FIXED 2026-08-02:**
      the sidebar scroll area forced its horizontal scrollbar OFF, so when
      the content minimum exceeded the viewport (bigger fonts / narrow
      window) the right edge clipped with no recourse. Policy is now
      AsNeeded — a scrollbar appears only when needed; verified no bar at
      normal widths. Ray's screen is the acceptance test. (Original
      symptom notes below.)
      Original report: the right end of
      the gain slider is cut off so he cannot drag to max gain. Likely a
      sidebar layout/minimum-width (or DPI/scaling) issue. Workaround NOW:
      type the value into the RX Gain spin box next to the slider. Fix:
      make sure the slider stretches/shrinks with the panel and the max is
      always reachable; test at small window sizes + 125/150% display
      scaling.

- [x] **Ray bug: waterfall doesn't track spectrum x-axis zoom/pan — FIXED
      2026-08-02:** waterfall ViewBox x-axis now linked to the spectrum
      plot's (`link_x_to` / pyqtgraph setXLink; the waterfall image was
      already in true frequency coordinates). Verified live on the B210:
      zooming the spectrum to 1.4185–1.4225 GHz moved the waterfall to the
      identical span with carrier stripes aligned under the spectrum
      peaks; retunes propagate through the link. (Original symptom notes
      below.)
      Original report: when
      the spectrum plot's horizontal scale changes (interactive zoom/pan),
      the waterfall keeps showing the full band, so rows no longer line up
      with the spectrum above — "useless in that case." Fix: link the
      waterfall ViewBox x-range to the spectrum plot's (pyqtgraph
      setXLink or an x-range-changed handler), so both views always show
      the same frequency span. Check the axis stays correct in Sweep mode
      and after retune/sample-rate changes.

- [x] **① Display sensitivity fix — integrate the full stream — SHIPPED in
      release 1.1.7 (2026-07-18, commit 0cf1648).** History:
      What shipped in the working tree: SampleBufferSink queues every chunk
      (bounded, drop-oldest, counted); keep_one_in_n target 20→400 vec/s
      (N=1 below ~26 MS/s); SpectrumProcessor Welch-averages every block per
      tick (scipy.fft batch, workers=-1; float64 accumulation); proactive
      per-tick CPU budget via a learned per-block cost (no GUI stalls, slow
      boxes shed coverage gracefully); max/min holds are now TRUE per-block
      peak/min detectors (a 51 µs burst reads full amplitude, not −27 dB);
      retune barrier (flush + one-drain blanking) keeps stale-frequency
      samples out of live view AND sweep tiles; sweep capture retries until
      a clean post-retune frame exists. Verified: 7-test suite in
      `test_display_sensitivity.py` (0 dBFS calibration exact; 34× noise-
      floor scatter reduction ≈ √N; barrier; budget cap; peak holds) +
      benchmarked 34–40 ms/tick at 26 MS/s for all FFT sizes (= stride 1,
      full coverage, on the dev box). Adversarially reviewed (15-agent
      workflow): 9 findings confirmed, all fixed. **Release note needed:**
      default averaging is now linear power, so the displayed noise floor
      reads ~+2.5 dB vs ≤1.1.6 (the old dB-domain average was biased low —
      this is a correction, not a regression).
      **GUI smoke test PASSED 2026-07-18 in playback mode** (B210 was NOT
      connected to the dev PC — plug it in for the live-RF leg): app
      launches, razor-flat Welch floor at 65536-pt/152.6 Hz RBW, max hold
      verified as a per-block peak detector with quantitatively correct
      order statistics (~+4 dB gap at ~15 blocks/tick vs ~+9 dB at ~9700),
      FFT-size change 65536→1024 instant and clean, GUI responsive
      throughout. (Dev note: launching outside the launcher needs
      UHD_IMAGES_DIR pointed at radioconda's images for live B210 use.)
      **LIVE B210 leg PASSED 2026-07-18** (serial 8003886, 1422 MHz,
      16 MS/s, RX2, 40 dB): razor-flat Welch floor at −116 dBm with sub-dB
      scatter, three weak narrowband signals clearly visible above it (the
      Ray demonstration), max hold ~+10 dB with correct order statistics,
      waterfall smooth, ~242% of one core used (64-core box → huge
      headroom; scipy workers spreading the batch FFT). Remaining for this
      item: only the A/B against other SDR software on Ray's exact
      scenario (need his app/settings/signal details).
      **SHIPPED in release 1.1.7 (2026-07-18, commit 0cf1648)** — cut
      fast-track (including the hold-detector toggle) so Ray can test
      tonight; the other roadmap items below continue toward a later
      release. Sig-gen ground truth from Rick's bench for the A/B: at
      1422 MHz center only the 1420.5 MHz line follows the generator
      on/off; 1418 and 1425.6 MHz are internal B210 spurs.
      Ray Uberecken (AA0L) reports (verbal)
      that in a different application the Spectrum Analyzer receives weak
      signals WORSE than other software on the SAME hardware.
      **PRIME SUSPECT FOUND (code inspection 2026-07-17):** the display FFT
      processes only the latest `fft_size` samples per timer tick
      (`_tick()` → `self._sink.latest(n)`) — at 20 MS/s / 1024-pt / ~30-60 Hz
      that is ~0.3% of the stream; the rest never reaches the display.
      Software that Welch-averages EVERY frame between screen updates shows
      a far deeper-averaged noise floor (up to ~18x lower sigma at 20 MS/s),
      which is exactly "weak signals better in other apps, same hardware."
      **Fix: accumulate/Welch-average all (or a sizable fraction of) the
      blocks since the last tick before the EMA.** NOTE: display-only — the
      .fil recording path processes every sample, so pulsar recordings and
      the B0950+08 noise limit are unaffected. Precision itself audited
      clean: display FFT is float64, linear-power averaging already default,
      ENBW-aware scaling; recording float32 is standard for 12-bit ADC data.
      Verify the fix (and rule out secondary causes) with an A/B vs
      SDR# / GQRX / SDRangel, one antenna + calibrated weak signal:
      - RF gain defaults / AGC: are we leaving front-end gain on the table?
      - Receive-chain config: antenna port selection, LNA path, bandwidth
        vs sample-rate filter rolloff at band edges.
      - FFT processing: window choice, FFT size vs RBW, averaging depth vs
        other apps' defaults.
      - **RX overflows**: dropped samples discard integration time — ties
        into the timebase item; heavy drops = real sensitivity loss.
      - Wire format sc8 vs sc16 on the USB link, DC-offset / IQ-balance
        correction settings.
      Get the exact scenario from Ray (app, mode, signal type, hardware,
      settings) and reproduce with a calibrated weak signal first.

- [x] **Field-analysis cluster (quick-look + auto post-processing +
      self-contained PDFs) — SHIPPED in 1.1.8 (2026-08-03):**
      one pipeline (`fold_analysis.py` + `fold_pdf.py`) serves all three:
      readfile sanity → rfifind mask → band-edge zap → catalog prepfold
      (or manual -p/-dm for magnetars/tests) → parse → verdict →
      self-contained PDF next to the `.fil` (chart + commands + numbers +
      plain-language verdict per the fold-PDF convention). PRESTO runs
      native (Mac/Linux) or via WSL (Windows, presto_bridge) with a
      graceful "not installed" path. App UI: "Analyze when done" checkbox
      (default on) + "Quick look" button (snapshots the growing file
      mid-recording, min 60 s), worker thread, results dialog with
      Open-PDF. **Verdict RFI guards encode the review lessons:** a
      catalog fold whose periodicity optimizes to DM≈0 reports
      TERRESTRIAL SIGNAL (verified live: the bench carrier produced
      χ²=17,275 and was correctly rejected); DM far from catalog →
      SUSPECT; "no detection ≠ bad recording" wording for weak sources.
      Tests: `test_fold_analysis.py` (synthetic 0.5-s pulsar → DETECTION
      χ²≈293 with 2-page PDF; snapshot truncation; data-check-only path) +
      live GUI round-trip on the B210 (record → auto-analysis → dialog →
      PDF). Bonus live proof: the recording's 54 real overflow gaps were
      rx_time-measured and padded (3.4 s) by the 1.1.8 timebase feature —
      the live tag round-trip we couldn't previously induce.
      **Follow-up found:** FilterbankSink still does inline DSP on the GR
      thread and overflows at 16 MS/s/2044ch (padding compensates, but it
      should get the ezRA-style worker-thread treatment — prevention over
      cure).
      Original item:
      Quick-look PRESTO analysis during a long recording — while a
      multi-hour recording runs, let the user (or a timer) trigger a draft
      PRESTO fold on the data captured so far WITHOUT interrupting the
      recording. Feasible because `FilterbankWriter` appends whole spectra
      and flushes, so the on-disk `.fil` is always valid up to the last
      complete spectrum, and SIGPROC headers don't encode sample count
      (PRESTO infers it from file size). Design sketch:
      1. Snapshot: copy the header + an integer number of complete spectra
         (`floor((size - hdr_len) / (nchans * nbits/8))`) to
         `<basename>_quicklook.fil` so PRESTO never reads a file mid-append.
      2. Run `readfile` + `prepfold -psr <source_name>` on the snapshot via
         `presto/presto_bridge.py` (WSL on Windows, native on Mac/Linux) in a
         low-priority background subprocess — recording thread untouched.
      3. Show the result in the recording panel: sigma / χ²_red readout and
         the prepfold plot (PNG/PDF), per the fold-PDF convention.
      Uses the source name + RA/Dec already wired into the header (1.1.6).
      Caveats: needs ~10+ min of data before a fold is meaningful; on the
      Pi 5, nice/ionice the PRESTO job to avoid UHD overflows; Windows
      requires the WSL PRESTO stack from `presto/build_presto.sh`.

- [x] **Pulsar visibility planner ("what's up now?") — BUILT 2026-08-04 for
      1.2.0** (`pulsar_planner.py`, Observe menu / Ctrl+P; ATNF psrcat
      cached locally, flux follows the tuned band, magnetars marked and
      never flux-filtered, exact catalog RA/Dec into the .fil header,
      set-before-finish warning). Original notes: a built-in subset of
      the Murmur/ATNF planning step from
      `DSES_PulsarGuide_Planning_2026.pdf` (Training Part 1):
      1. *In-view list on request:* a "Pulsars in view" button/dialog showing
         pulsars currently above the horizon at the observing site — name,
         RA/Dec, current az/el, P0, DM, S400 flux, and **time remaining above
         the elevation mask**. Selecting one fills the recording Source field
         (and gives exact catalog RA/Dec for the `.fil` header, upgrading the
         current approximate parse-from-name in `sigproc_fil.py`).
      2. *Availability warning:* when a Source + "record for" duration are
         set, warn at recording start (and live in the panel) if the pulsar
         sets below the mask before the recording would finish.
      Design notes:
      - Needs a new `[site]` settings group: lat/lon/elevation + minimum
        elevation mask (deg). Preset dropdown for known DSES sites (Haswell,
        home QTHs) plus custom entry.
      - Catalog: ATNF psrcat (internet assumed OK) — fetch via the psrcat web
        query or `psrqpy`, but CACHE the catalog locally (~few MB) so the
        field boxes work offline after first fetch; filter by dec reachable
        from the site.
      - Flux column must follow the tuned band: DSES records pulsars anywhere
        from 0.1–2 GHz (400 MHz and 1400 MHz bands most common), so sort by
        S400 or S1400 (or nearest available Sxxx) based on the current center
        frequency, not a hardcoded band.
      - Include **magnetars**: psrcat carries them (TYPE AXP/SGR) but flux
        fields are often sparse — don't let a flux filter silently hide them;
        consider a "show magnetars" toggle or a TYPE column, and the McGill
        Magnetar Catalog as a supplementary source if psrcat coverage proves
        too thin.

- [x] **One-click post-processing at end of recording — DONE, absorbed
      into the field-analysis cluster above (2026-08-02).** Original notes:
      PRESTO v6 + tempo2 will always demand expertise for *real* analysis,
      but the app can run a canned, reasonably-good pipeline automatically
      when a recording finishes (opt-in checkbox, e.g. "Analyze when done"),
      so the on-site team gets an immediate good/marginal/no-detection
      verdict. Pipeline = what we hand-ran for the Haswell validation:
      1. `readfile` sanity check (header parses, byte-exact spectra count).
      2. `rfifind` to build an RFI mask (this is the step field crews most
         often skip and most often need).
      3. `prepfold -psr <source>` with the mask (catalog fold; topocentric
         first — no par file or tempo2 knowledge required of the user; a
         `-par` bary fold via tempo2 as an "advanced" option).
      4. Results card in the app: detection sigma, χ²_red, best DM vs
         catalog DM, and the prepfold plot; PDF written next to the `.fil`
         per the fold-PDF convention (`<basename>_prepfold.pdf`).
      5. Verdict heuristic from sigma/χ² thresholds, with the caveat text
         explaining "no detection ≠ bad recording" for weak sources.
      Shares all infrastructure with the mid-recording quick-look item
      (snapshot not needed here — file is closed) and the visibility planner
      (source name + catalog params already known). Design notes:
      - Gate on PRESTO availability per platform: Windows → WSL bridge
        (`presto/presto_bridge.py`); Mac → `presto6` radioconda env; Linux
        site box → conda-forge `presto` v6 (linux-64). The current Pi 5 is
        aarch64 (no conda-forge build — would need a source build), but Rick
        plans to REPLACE the on-site Pi with a powerful multi-core x86-64
        Linux machine in the near future, where conda-forge v6 installs
        directly — so don't invest in an aarch64 build; just show a clear
        "PRESTO not installed" message when it's absent.
      - Long recordings → long folds: run niced in the background with
        progress + cancel; the app must stay usable (or start a new
        recording) while analysis runs.
      - Magnetars / sources without catalog ephemerides: offer a manual
        P0/DM entry or par-file picker instead of `-psr`.

- [x] **Self-contained fold PDFs — DONE, absorbed into the field-analysis
      cluster above (2026-08-02, fold_pdf.py).** Original notes:
      whenever a PRESTO chart is written to PDF (the auto post-processing
      item above, the quick-look, or a manual fold), the PDF must carry the
      interpretive commentary with it, not just the raw prepfold plot, so
      the results never have to be chased down "somewhere else". Contents:
      - Page 1: the prepfold chart as today.
      - A commentary page (or header block): recording metadata (source,
        site, center freq/BW, tsamp, duration, start MJD), the exact PRESTO
        commands run, a results table (sigma, χ²_red, best DM vs catalog DM,
        best P vs catalog P), and plain-language verdict + caveats — the
        kind of notes from the Haswell validation (e.g. "DM rails to 0 at
        20 MHz BW — narrow-band artifact, not RFI").
      - Implementation: no new dependency needed — PySide6 can render a
        QTextDocument to PDF (QPdfWriter) and append/merge with the chart;
        numbers parse from prepfold's `.bestprof`.
      - Same rule applies to agent-produced fold PDFs (see CLAUDE.md fold
        convention).

- [ ] **System-1 antenna-steering integration (preload pulsar target)** —
      *status: WAITING ON the System-1 team* (they own the antenna-steering
      software + hardware). Rick has asked them (2026-07) for an API so the
      spectrum analyzer can push the selected pulsar's data (name, RA/Dec,
      ideally the catalog ephemeris) into their steering software — the
      operator picks a target once in the SA and the dish knows where to
      point, saving time and flattening the site-operator learning curve.
      Cooperation task — do not let it drop; follow up with System-1 on the
      API spec. Design notes for when the API exists:
      - Natural trigger point: the pulsar visibility planner's "pick" action
        (which already yields name + exact catalog RA/Dec) gains a
        "Send to antenna" button.
      - Keep the client thin and optional: a small module speaking whatever
        System-1 exposes (REST/socket/file drop TBD), enabled via settings
        (endpoint/host), silently absent when not configured so non-System-1
        sites see no change.
      - Open questions for System-1: API transport + schema, coordinate
        epoch (J2000 assumed), one-shot slew vs. tracking handoff, and
        whether the SA should also read BACK the current az/el to display.

- [ ] **Demodulators + audio chain for RFI identification** — click a
      suspect signal on the spectrum/waterfall and LISTEN to it: an ear
      identifies FM broadcast, hum-modulated power-line buzz, pager bursts,
      digital chatter, etc. far faster than staring at the waterfall.
      1. Secondary channel: a small DDC (freq-xlating filter/decimator) that
         tunes within the already-streaming band — no interruption to the
         main display or an in-progress recording.
      2. Demodulators, GNU Radio built-ins to start: AM, NFM, WFM, SSB
         (USB/LSB), CW (BFO), plus raw envelope. Squelch + volume + audio
         bandwidth controls.
      3. Audio out via the GR audio sink (portaudio is already in the conda
         env); optionally record the demodulated audio to WAV (libsndfile
         also present) for RFI reports.
      4. **AI auto-detect of the right demodulator (stretch):** phase it —
         (a) cheap classical heuristics first (occupied BW, envelope
         variance, FM deviation, cyclostationary hints → suggest AM/FM/SSB/
         digital), (b) then a small trained modulation classifier
         (RadioML-style CNN on IQ snippets) if the heuristics disappoint.
         Run it on the DDC output, suggest — don't force — the demod.
      UI sketch: right-click a signal → "Listen here", a compact demod
      panel (mode, squelch, volume, audio-record), tuned marker shown on
      the spectrum. Settings persist in a new `[audio]`/`[demod]` group.

- [x] **Recording timebase integrity — SHIPPED in 1.1.8 (2026-08-03):** `FilterbankSink` now reads gr-uhd `rx_time` overflow tags,
      measures each gap exactly, and zero-pads it live (100 µs threshold;
      10 s/event and 60 s/recording caps → beyond that the file keeps
      recording but is flagged TIMEBASE BROKEN); live gap readout in the
      REC counter, summary in the saved-status line, full event log in a
      `.gaps.json` sidecar; Soapy sources (Ray's HackRF etc.) record
      classically with the overflow panel as their indicator. 5-test suite
      `test_timebase_padding.py` incl. an end-to-end GR flowgraph with
      injected rx_time tags. Remaining before checking off: a live-B210
      recording with induced overflows (CPU-stress during capture) to see
      a real tag round-trip, and a Help/guide PDF sync at release time.
      Original notes: — root-caused 2026-07-17 while re-folding the Haswell
      B0329+54 recording per Dan Layne's review: a rigid no-search
      ephemeris fold exposes a smooth ~1.2-rotation phase drift over the
      36.6-min recording ≈ **3.9×10⁻⁴ fractional timebase error** — five
      orders beyond pulsar/Doppler physics, so it's OUR clock. The header
      tsamp already uses `get_actual_samp_rate()` (checked), so the prime
      suspect is **dropped samples at RX overflow**: each drop silently
      shortens the sample-count clock vs real time (the app SHOWS 'O's
      live in the overflow sidebar but doesn't count or log them). The
      drift is why prepfold searches report unphysical P/P-dot; detection
      sigma survives (search absorbs it) but absolute timing/TOAs don't.
      Fixes, in order of value:
      1. Count overflow events (timestamped) during a recording; write
         them into the `.fil`-adjacent metadata/SigMF and surface them in
         the recording panel + results card ("N overflows ≈ X ms lost").
      2. Gap-padding: on detected drops, insert the missing number of
         samples (zeros or noise) so the sample clock tracks wall time —
         the standard professional fix. **PROVEN 2026-07-17 by manual
         repair:** the drift function was mapped with 22 fixed-period
         window folds (smooth drip + ONE +0.219-rotation step at
         t≈550 s); padding 0.558 s of noise at the step in a copy of the
         `.fil` took the fold from 22.4σ (split profile, DM artifact 36)
         to **28.0σ, textbook single profile, DM back at 25.3**. Padding
         works; the app should do it automatically at overflow time
         (where the true gap length is knowable from UHD timestamps —
         post-hoc repair only recovers it modulo the pulse period).
      3. Optional: external/GPSDO reference support for absolute clock
         accuracy at the site (doesn't fix drops, fixes rate).
      Full analysis with plots: `DSES_SA_Recordings/…B0329+54…_prepfold-
      par-refined.pdf` (2026-07-17 re-fold).
      - Az/el + set-time math is plain sidereal-time + spherical trig (numpy,
        no astropy dependency): cos(HA_set) = (sin el_min − sin lat · sin dec)
        / (cos lat · cos dec); circumpolar → "always up".

- [x] **Drift-scan recording support (ezRA `.txt` format) — SHIPPED in
      1.1.8 (2026-08-03), field-verified 2026-08-02:** third recording format
      "Drift scan (ezRA .txt)" with Az/El fields in the recording panel,
      `[site]` settings (Haswell defaults), ezCol filename convention with
      same-hour letter suffixes, dish-proven geometry defaults (4096 bins,
      31e3 integrations, central-80% band trim). Threaded sink (GR callback
      only copies; scipy-FFT worker integrates). VERIFIED with three live
      B210 GUI captures: format/rows/header correct, and the group's own
      ezCon.py produced a `.ezb` from a real off-air capture (exit 0).
      **Bonus root-cause fix for the systemic RX overflows:** the GR default
      source-edge buffer gives a Python sink only a few ms of slack at
      16 MS/s, so any GIL pause overflowed the radio (this is what plagued
      the Haswell .fil recordings). `set_min_output_buffer(4 Mi samples)`
      on the UHD source (~260 ms cushion) + a display-CPU throttle while
      recording → THIRD live capture ran overflow-free at full 7.9 s/row
      cadence. Remaining: release-time docs sync only.
      Original notes: incorporate
      the role of **ezCol** (the data-collection module of Ted Cline's free
      open-source **ezRA** — Easy Radio Astronomy — suite,
      https://github.com/tedcline/ezRA) so the Spectrum Analyzer can serve
      as the drift-scan data collector: record integrated frequency spectra
      in the **ezRA `.txt` data-file format**, feeding the rest of the suite
      (ezCon → .ezb condensed files → ezPlot/ezSky/ezGal/ezGLon analysis &
      sky maps). Notes:
      - Primary use: 1420 MHz hydrogen-line drift scans on the
        DSES-Drift-Scan box; complements (not replaces) the `.fil`/SigMF
        pulsar recording modes — this is a third recording format targeting
        long-timescale integrated spectra rather than fast time series.
      - **Recon done 2026-08-01 (GitHub):** the whole suite is Python3 on
        **Windows AND Linux** (numpy/matplotlib), so the downstream chain
        (ezCon/ezPlot/ezSky) runs on our dev boxes, WSL, and the site box —
        install it there and use it as the acceptance test on our output.
        **ezCol itself is RTL-SDR-only (pyrtlsdr)** — it cannot drive the
        B210 at all, which is exactly the gap our collector fills for the
        drift-scan dish.
      - Format is fully recoverable from `ezCol.py` source (no spec-only
        development needed): header = `from <rev> <cmd>`, `lat/long/amsl/
        name`, `freqMin/freqMax/freqBinQty`, a coordinate line (azDeg/elDeg
        or raH/decDeg …), `# times are in UTC`, `# gain`, then one row per
        integration: `<UTC timestamp> <RMS power per bin> <flags>`; RMS
        power = sqrt(mean of squares) over ezColIntegQty FFTs; filename
        `data/<prefix>YYMMDD_HH<letter>.txt`.
      - **LOCAL TREASURE (found 2026-08-01):**
        `~/Documents/DSES/Science/HI_and_Drift_Scan/ezRABase/` holds a full
        ezRA install (incl. doc PDFs for ezCon/ezPlot/ezSky), the site's
        actual collector variant `ezColS251110aP.py` (SoapySDR-based — CAN
        drive the B210 via Soapy's uhd factory; `ezColS251110a_B210.py` is
        its B210 copy), the exact dish command line (`ezCol Command.txt`:
        center 1418.405 MHz, 10 MS/s, 4096 bins, integQty 31e3 → ~12.7 s
        per row, lat 38.3808 lon -103.156 amsl 4400 name DSES, az 180
        el 45), and TWO real reference datasets: Nov 2025 dish drift scans
        in `ezRA_Data_Collected_with_ezCol/` (4096-bin, "RMS power in dB")
        and Aug-Sep 2025 in `ezRA_Data_Collected_with_GNURadio/` (2048-bin,
        stamped `from ezColG.py` — a prior GNU Radio collector whose source
        is NOT on this machine, maybe on the site box; its output shows the
        downstream tools tolerate header variations). Correction to the
        note above: stock ezCol is RTL-only, but the group's Soapy variant
        did drive the B210 — our in-app writer is the BETTER path (one
        tool, Welch integrator, timebase fix, recording panel), not the
        only one.
      - Validation plan: clone the real Nov-2025 header verbatim (swap
        provenance line), match its dB-RMS row format and cadence, and diff/
        run through the local ezCon/ezPlot against those reference files.
      - Natural fit with the existing recording panel (Source name, timed
        recording, elapsed counter) and the site/az-el metadata from the
        visibility-planner item (drift scans want LST + pointing recorded).

## Observation presets + consequences readout — IN 1.1.8, DONE 2026-08-03

- [x] **"Observation" preset selector** — Rick chose 1.1.8; shipped 2026-08-03. Answers "what are you trying
      to do tonight?" with a coherent, validated parameter bundle; every knob
      stays adjustable after (combo drops to Manual on deviation, like the
      sample-rate combo):
      | Preset | Sets | Basis |
      |---|---|---|
      | Pulsar — L-band | 16 MS/s, .fil, 2044 ch, Int 1, 1422 band | validated Haswell geometry (127.7 µs; 28σ B0329+54) |
      | Pulsar — UHF | 20 MS/s, .fil, 256 ch, Int 16, 408 band | proven 204.8 µs UHF geometry |
      | Magnetar / high-DM | L-band, max channels, Int 1 | narrow channels beat DM smearing |
      | H-line drift scan | ezRA fmt, ~2 MS/s @ 1420.405, Az 0/El 87 | existing ez defaults |
      | RFI survey | Sweep mode | exists |
      | Manual (expert) | touches nothing | today's behavior |
      Non-B210 radios: preset adapts (clamp rate, keep ratios) instead of
      making it the user's problem.
- [x] **Live "consequences" line** under the recording controls: time
      resolution, channel width, DM smearing @ example DM, GB/hr, host
      headroom; turns red on self-defeating combos (formulas:
      tsamp = ch×int/rate; Δν = rate/ch; disk B/s = 4×rate/int).
- [x] **Label the display group as display-only** (FFT size/window/avg do NOT
      affect recordings — rename "Spectrum Controls" to say so).
- Full expression (Observation menu, first-run wizard, visibility-planner
  tie-in "B0329+54 rises 21:40 → Observe") belongs to the 1.2.0 redesign.

## v1.2.0 — SHIPPED 2026-08-05 (cut + published from Windows)

**Group announcement SENT (Rick, 2026-08-05):** email to the six DSES radio
astronomers covering both recent releases — 1.1.8 (presets, recording
integrity, auto-analysis PDFs, ezRA drift scan, true sample rates, Ray's
fixes) and 1.2.0 (dockable-panels redesign, pulsar visibility planner,
hot-plug detection, waterfall new-at-top, macOS Qt fix) — plus
getting-started steps (Radioconda + conda one-liner + zip + launcher;
playback mode needs no radio) for members who haven't installed yet.

Landed: QMainWindow shell, four dockable panels (rearrange/tab/tear-off/
hide, persisted via saveState), menu bar (File/View/Radio/Recording/Help),
full-width status bar with recording-status mirroring. Verified live on
the B210 incl. persistence of a floating panel across relaunch.
REMAINING before the 1.2.0 cut: Rick's hands-on pass; macOS test (native
menu bar!) + drift-scan box test (dock behavior on headless Openbox/xrdp
— re-check the 0x0-screen guards); docs sync + PDF; version bump; cut.


- [x] **Replace the fixed two-column sidebar with a menu bar + dockable
      panels — CORE LANDED on main 2026-08-04 (not yet cut).** DECIDED: dockable panels (PyCharm/Chirp style), not MDI.
      Rationale — the ~300 px sidebar is the root cause of a recurring
      class of bugs, not a cosmetic preference: Ray's unreachable gain
      slider (clipped), status messages truncated below the Record combo,
      the QToolBar-overflow workaround already in the code (Integrate
      would vanish into a "»" menu), and every new feature (Az/El,
      analysis row) fighting for pixels. Three recording formats + sweep +
      analysis have outgrown the space.
      Design targets:
      - Menu bar: File / View / Radio / Recording / Analysis / Help.
        Rarely-touched settings (site coordinates, calibration, FFT
        window, updater) move into roomy dialogs where they can be
        EXPLAINED, not abbreviated.
      - Main window keeps only what you watch while observing: spectrum,
        waterfall, and a slim toolbar for frequency / gain / record.
      - Qt QDockWidget panels: dock, tab, tear off, or hide; layout
        persisted per user (`saveState`/`restoreState`), so a laptop and
        the Haswell projector can each have a fitting layout.
      - A real QStatusBar at the bottom: full width, no truncation,
        details-on-click for long messages.
      Cautions: substantial refactor of a ~6k-line single file; will
      churn the geometry-persistence code that was hard-won on
      Linux/Openbox (frame-vs-client coords, empty-screen guard); test on
      Windows, macOS, and the headless site box. Estimate ~2 focused days.
      **Sequencing: ship 1.1.8 and 1.1.9 FIRST** (that work is done and
      the field wants it), then do this as the headline of 1.2.0 with
      nothing else competing.

## v1.1.9 items — ROLLED INTO 1.2.0 (Rick, 2026-08-04); both LANDED on main 2026-08-04

- [x] **Hot-plug receiver detection (Rick, 2026-08-03) — DONE 2026-08-04, verified live end-to-end:** when the SA opens
      with no receiver detected (today: playback mode or the exit dialog),
      allow the receiver to be connected or powered on later and get
      detected WITHOUT restarting the app. Design sketch: in playback/
      no-radio mode, poll `find_all_radios()` on a slow timer (~5 s; USB
      enumeration is cheap when empty) or offer a "Rescan for radios"
      button on the Device row + picker dialog; on detection, offer to
      switch (tear down the playback graph, build the live source —
      the flowgraph rebuild machinery already exists in the device-switch
      path). Also covers the B210 powered off at session start at Haswell.

- [x] **Waterfall scroll direction (Rick, 2026-08-03) — DONE 2026-08-04 (new-at-top, axis reads age):** new rows currently
      appear at the BOTTOM and history scrolls up; the convention Rick is
      used to (SDR#/GQRX/SDRangel) is new-at-top, history flowing down.
      WHY it is this way: `WaterfallPlotWidget.on_frame` does
      `np.roll(self._data, -1, axis=0)` + writes the new row at
      `self._data[-1, :]`, and the ImageItem rect maps row order directly —
      an implementation accident, not a choice. Fix: roll +1 and write row
      0 (or flip the rect/y-axis), and make the Time axis read as age
      (newest at top). Check both: normal frames AND the first_frame
      reset path, plus Sweep mode's waterfall behavior. Consider a
      settings toggle only if anyone defends the current direction;
      otherwise just adopt the convention.

## Validation tooling (after 1.1.8 ships, possibly after 1.2.0)

- [ ] **B210-TX pulsar simulator = BUILT-IN TEST (DECIDED 2026-08-03; BIT
      framing Rick 2026-08-03):**
      **BENCH-PROVEN 2026-08-05 (Windows, B210 s/n 8003886) — core built,
      hardware PASS; remaining: the in-app "Self test" UI.** What landed:
      `pulsar_sim.py` (synthesis core: SimSpec ground truth incl. a
      `dm_resolution` honesty metric, grid-quantized seamless loop,
      Gaussian-envelope NOISE carrier, coherent cold-plasma dispersion —
      sign convention derived AND verified to 0.06 us against the law;
      `grade()` PASS/FAIL vs injected truth), `test_pulsar_sim.py`
      (fast math suite + `--presto` offline round trip: synth -> app
      channelizer -> .fil -> WSL prepfold = DETECTION, P exact, DM 48.0
      vs 50 injected — the FIRST end-to-end DM validation ever on this
      pipeline), and `tools/b210_bit.py` (bench harness: one B210 full
      duplex, TX loops the waveform out TX/RX-A at MIN gain, RX2-A ->
      FilterbankSink .fil -> analyze_fil -> grade). HEADLINE: **internal
      TX->RX leakage alone carries the test — NO cable, NO pad, NO
      accessories** (15 s probe: pulse ~10 sigma AND the dispersion sweep
      visibly marching across the band). Full 90 s graded run: DETECTION,
      chi2_red 1118, P recovered 100.00000 ms (0.000% off), **DM 51.45
      vs 50 injected (3% on real hardware)**, 0 gap events. GEOMETRY
      LESSON (quantified B0950+08 physics): DM leverage = sweep vs pulse
      width; 10 ms pulses over a 6 ms sweep -> +/-22 DM slack (prepfold
      wandered to 19 of 26.76); BIT default is now P=100 ms, duty 2%,
      DM 50 @ 420 MHz/2 MS/s -> 11.2 ms sweep vs 2 ms pulses =
      dm_resolution +/-4.5. Defaults deliberately far from 1420 MHz.
      TODO to close this item: host the same TX branch in the app as the
      "Self test" action with the PASS/FAIL readout (harness code is the
      blueprint), and a site variant note (B-side RX while the feed stays
      on A). synthesize the pulsar in software and
      transmit it from the SAME B210's TX side (full duplex; no second
      unit needed) while the app records — but as an APP FEATURE, not a
      standalone tool: a B210 is single-process, so the app must host the
      TX chain, which is what a self-test wants anyway. UI: a "Self test"
      action (candidate: 7th Observation entry or button) → TX/RX port A
      plays the dispersed pulsar → pad/cable → RX2 (site: cable into the
      B-side RX while the feed stays on A; characterize internal TX→RX
      leakage as a possible no-cable mode on the bench first; ALWAYS
      minimum TX gain — 1420 MHz is a protected band, no radiating next
      to the dish) → record a few min .fil → existing analysis pipeline →
      compare recovered (P, DM, sigma) to injected ground truth → plain
      PASS/FAIL with numbers. Run it before each Haswell session: proves
      SDR→channelizer→writer→timebase→PRESTO→verdict healthy before
      spending telescope time. LIMIT: TX/RX share the B210 clock, so
      clock faults cancel — the E4438C leg below is the independent-clock
      test. Implementation core: (a) generate
      baseband I/Q of a dispersed, profile-shaped, NOISE-carrier pulse
      train from parameters (P, DM, duty, profile, band, level) — noise
      bursts fold with realistic statistics, unlike the gated carrier
      that produced chi2=inf; (b) add a uhd.usrp_sink TX branch to the
      app's flowgraph while testing (loop must hold an integer
      pulse-period count with seamless phase — choose fs so P*fs is
      integer); (c) auto-compare fold results to the injected ground
      truth for the PASS/FAIL. Unlocks, in value order: END-TO-END
      DM validation (inject DM 26.8, require the pipeline to RECOVER it —
      L-band/16 MHz sweep 1.2 ms; 420 MHz/20 MHz sweep ~60 ms; the
      hardware sim box has no dispersion so the DM dimension has never
      been testable), realistic chi2/sigma statistics, B0329+54's actual
      double-peaked profile at its exact 714.5 ms period, later
      p-dot/orbital/RFI-injection cases. TX and RX share the B210 clock —
      good for controlled tests; use the E4438C leg below when clock
      independence matters. ~1 day incl. bench verification.
      HISTORY: the original plan was the E4438C's internal ARB, but
      interrogation over SCPI (2026-08-03, s/n MY49071480, fw C.05.82)
      showed options 506/UNB/UNJ only — NO 601/602 baseband generator,
      and Rick's serial is in the license-key range where a bare eBay A7
      board may not enable (E4400-60761 + entitlement needed). Rick
      decided NOT to swap units; the B210 TX is the simulator.
- [ ] **E4438C precision leg (kept, reduced role):** the unit's internal
      pulse generator + UNB attenuator still contribute what the B210
      can't: gated pulses at an EXACT catalog period with the ESG locked
      to the GPS 10 MHz reference (period recovery becomes a timing
      test with an independent clock), and calibrated absolute-level
      threshold sweeps (0.01 dB steps to -136 dBm) for a proper
      sensitivity curve. Script over LAN SCPI at 192.168.10.66:5025.
      UPGRADE PATH (2026-08-03): the front-panel I/Q inputs are the
      STANDARD analog vector modulator (601/602 only adds the internal
      digital source) — drive them from a dual-channel phase-synchronous
      AWG playing precomputed I/Q (DC-coupled, ~0.5 Vrms/50 ohm, null
      I/Q offsets from the front panel; P*fs integer for the loop) and
      this unit becomes a FULL independent-clock vector pulsar sim with
      calibrated level. Memory math: full B0329 period @25 MSa/s ~18
      Mpts/ch (deep-memory AWG), but a 4 MHz test bandwidth @5-10 MSa/s
      is a few Mpts and still gives a ~12 ms DM sweep at UHF. No AWG on
      hand (2026-08-03). AFFORDABLE PICK (verified specs): Siglent
      SDG2042X ~$400 — 2 ch, 16-bit, 8 Mpts/ch, TrueArb point-by-point
      1 uSa/s-75 MSa/s (exact fs control for the P*fs-integer loop
      seam), rear-panel 10 MHz In/Out with external clock select (GPS
      lock), LAN SCPI. 8 Mpts is adequate via the PULSAR-CHOICE TRICK
      (memory = P*fs, and we control both): B0950+08 (253 ms, a real
      DSES target) fits a FULL period at 31 MSa/s = full 16-20 MHz RF
      BW; B0329 fits at 11 MSa/s (~9 MHz); UHF DM tests fit multiple
      periods. NOTE 18 Mpts is NOT the ceiling: magnetar-period sims
      (P=2-12 s) need 30-60 Mpts even at reduced BW, multi-period
      trains N*18, p-dot drift records more still.
      RECOMMENDED (2026-08-03, datasheet-verified): **SDG3082X +
      SDG-3000X-40MPTS memory option** (~$1-1.3k, get quote) — 2 ch,
      16-bit, 1.2 GSa/s, TrueArb 10 mSa/s-600 MSa/s, rear 10 MHz ref
      IN/OUT, 20 Mpts std -> 40 Mpts WITH THE OPTION (order it
      installed — ESG lesson), plus Sequence playback (chain segments:
      multi-period trains without linear memory cost). 40 Mpts = 2.2x
      the B0329 full-BW case, fits a 6 s magnetar at 4 MHz BW, 6 unique
      B0950 periods at full BW. SKIP the SDG6000X (costs more than
      3000X, only 20 Mpts — sells analog BW we don't need). Premium
      fallback if the wall is ever hit: SDG7032A (512 Mpts, vector/IQ
      mode, ~$4k) or used Keysight 33622A + 336MEM2U (64 Mpts/ch).

## Backlog / unscheduled

- [ ] **B0950+08 re-observation plan (observing, not software):** processing
      gains on the 2026-07-11 recording are exhausted (see
      `…B0950+08…_prepfold-refined.pdf`, 2026-07-17): cleanup lands best-fit
      P/DM on catalog values but sigma is noise-limited at ~9. To reach a
      publishable detection: 90+ min integration (~20σ), several sessions to
      catch scintillation maxima, wider capture BW if the feed allows, and
      record only after the v1.1.7 overflow/gap-padding fix ships.

- [ ] Website version of the Haswell trip report (derive from the finished
      `.docx`, do not rebuild — see CLAUDE.md handoff notes)
- [ ] **On-site computer upgrade (hardware, not app):** replace the
      Raspberry Pi 5 drift-scan box with a powerful multi-core x86-64 Linux
      machine (planned, near future). App implications: conda-forge PRESTO
      v6 installs directly (enables on-site post-processing), multi-core
      folds are fast, and the headless/0×0-screen + aarch64 constraints go
      away. Keep the existing headless safeguards regardless — the new box
      will likely also run headless over xrdp/VNC.

## Shipped

### v1.1.6 (2026-07-12, commit 3a1aa2d)

- [x] Sweep mode restored (recovered from dangling commits; ported to HEAD)
- [x] Recording panel: Source name, elapsed counter, red REC indicator,
      "record for" duration with auto-stop
- [x] RA/Dec (`src_raj`/`src_dej`) in the `.fil` header via pulsar-name lookup
- [x] Launcher headless virtual-monitor support (Linux)
- [x] Geometry safeguard for empty/0×0 screens
- [x] LF line-ending enforcement for shipped scripts (post-release CRLF fix,
      a5ba701)
