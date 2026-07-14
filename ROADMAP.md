# DSES Spectrum Analyzer — Roadmap

Feature ideas and planned work, by target version. This file is the shared
cross-machine record (Mac + Windows) — keep it committed and pushed.

Conventions: `[ ]` planned, `[x]` shipped (note the commit), `[-]` dropped
(note why). Move items between versions freely until they ship.

## v1.1.7 (planned)

- [ ] **Quick-look PRESTO analysis during a long recording** — while a
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

- [ ] **Pulsar visibility planner ("what's up now?")** — a built-in subset of
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

- [ ] **One-click post-processing at end of recording ("is it good?")** —
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

- [ ] **Self-contained fold PDFs: interpretation text INSIDE the PDF** —
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
      - Az/el + set-time math is plain sidereal-time + spherical trig (numpy,
        no astropy dependency): cos(HA_set) = (sin el_min − sin lat · sin dec)
        / (cos lat · cos dec); circumpolar → "always up".

## Backlog / unscheduled

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
