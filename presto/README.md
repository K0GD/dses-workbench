# PRESTO / TEMPO / TEMPO2 for the DSES Spectrum Analyzer (Windows)

PRESTO (Scott Ransom's pulsar toolkit), TEMPO, and TEMPO2 are **Linux/Unix-only**
— there is no native Windows build and no Windows conda package. This folder lets
a Windows machine run them in a Linux userland (WSL2 Ubuntu, or a VMware/native
Ubuntu VM) and lets the Spectrum Analyzer invoke them on its `.fil` recordings.

## Files

- **`build_presto.sh`** — run *inside Ubuntu* (`bash build_presto.sh`). Builds
  PRESTO + TEMPO + TEMPO2 from source against apt libraries, writes
  `~/.presto_env` (exports `PRESTO`/`TEMPO`/`TEMPO2`/`PGPLOT_DIR` and activates
  the PRESTO venv), hooks it into `~/.bashrc`, and smoke-tests
  `readfile`/`tempo`/`tempo2`. **Identical for WSL or a VM.** Re-runnable;
  TEMPO2 is non-fatal (with a conda-forge fallback note in the script).
- **`presto_bridge.py`** — pure-stdlib module for the *Windows* side. Shells out
  to `wsl.exe`, sources `~/.presto_env`, maps `C:\…` → `/mnt/…`, shell-quotes
  args, and returns captured UTF-8 output.
- **`extend_ut1.sh`** — run *inside Ubuntu* (`bash extend_ut1.sh`). Refreshes
  tempo2's UT1 (Earth-orientation) table so barycentric `prepfold -par` folds
  work for recent/near-future observation dates. Re-run ~yearly. See
  "Barycentric (`-par`) folds" below.
- **`par/`** — pulsar `.par` ephemerides for `-par` folds (see `par/README.md`).

## Setup

1. **(admin)** Enable WSL: `wsl --install`, then reboot. (Or install Ubuntu in
   VMware Workstation.)
2. **In Ubuntu:** `bash /mnt/c/Users/rick/Documents/DSES/Science/Spectrum_Analyzer_PY/presto/build_presto.sh`
   (~10–20 min).
3. **From Windows:** `python presto\presto_bridge.py "<path>\obs.fil"` → prints
   the SIGPROC header. No args → an environment report.

## Using the bridge from Python

```python
from presto import presto_bridge as p          # or add presto/ to sys.path
if p.wsl_available():
    print(p.readfile(r"C:\Users\rick\Documents\DSES_SA_Recordings\obs.fil").stdout)
    p.prepfold("-psr", "B0329+54", "-noxwin",
               "-o", r"C:\Users\rick\Documents\DSES_SA_Recordings\fold",
               r"C:\Users\rick\Documents\DSES_SA_Recordings\obs.fil")
```

Any tool: `p.run("accelsearch", "-zmax", "50", r"C:\…\obs_DM26.80.dat")`.

## Fold output convention

**Every fold gets a PDF next to the source `.fil`.** When a recording is folded,
save the prepfold diagnostic plot as a PDF in the *same directory* as the `.fil`,
named after the recording:

- `<recording>_prepfold.pdf` — topocentric fold (`-topo -p … -dm …`)
- `<recording>_prepfold-par.pdf` — barycentric fold (`-par …`)

The `.pfd` / `.bestprof` / PostScript working products stay in a subdir
(`presto_validation/` here; `folds/` on the Mac). PRESTO 6 writes the plot as
**landscape PostScript** (a dot-terminated EPS name, not `.pfd.ps`) — render it
to an upright-landscape PDF (e.g. `gs` → PNG at ~300 dpi + a 90° rotate, or
`ps2pdf` with the page rotated; a plain `ps2pdf`/EPSCrop comes out sideways).

## Barycentric (`-par`) folds

`prepfold -par par/<psr>.par <obs>.fil` folds against a full ephemeris. Two
gotchas — both already handled in this folder:

- **UT1 currency.** PRESTO ≥6 builds polycos with **tempo2**, which reads
  `$TEMPO2/clock/ut1.dat`. That table only forecasts ~1 year, so an observation
  past its end fails (`Problem running tempo2 … for make_polycos()`, empty
  polyco). Fix: `bash extend_ut1.sh` — extends the table from astropy's bundled
  IERS data (offline). Re-run ~yearly. (PRESTO 5 / the Mac use *tempo1* instead,
  whose fix is a stale `$TEMPO/clock/ut1.dat`.)
- **Observatory codes.** tempo2 uses its own site names, not tempo1 codes, so a
  `TZRSITE` like `CH` (CHIME's tempo1 code) makes tempo2 emit an empty polyco.
  The `par/` files here are kept tempo2-safe (no tool-specific `TZRSITE`, which
  only sets the reference-TOA phase zero point and is irrelevant to folding).

## Notes

- The bridge talks to **WSL**, so run `build_presto.sh` in WSL for app
  integration. A VMware/native VM (same script) is great for interactive
  post-processing and trip-report figures, but wiring the app to a VM would use
  SSH instead of `wsl.exe`.
- The `*.sh` scripts and `par/*.par` files **must keep LF line endings** (Linux
  scripts / tempo parsers choke on CRLF — a `\r` on `PSRJ` even leaks into output
  filenames); the `.gitattributes` here enforces LF for both.
- Verified 2026-07 against PRESTO `INSTALL.md` (meson), `nanograv/tempo`, and
  `mattpitkin/tempo2`. TEMPO2 is also on conda-forge (linux-64/osx-64) if you
  prefer `mamba install -c conda-forge tempo2` over the source build.
