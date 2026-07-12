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

## Notes

- The bridge talks to **WSL**, so run `build_presto.sh` in WSL for app
  integration. A VMware/native VM (same script) is great for interactive
  post-processing and trip-report figures, but wiring the app to a VM would use
  SSH instead of `wsl.exe`.
- `build_presto.sh` **must keep LF line endings** (it's a Linux script); a
  `.gitattributes` here enforces that.
- Verified 2026-07 against PRESTO `INSTALL.md` (meson), `nanograv/tempo`, and
  `mattpitkin/tempo2`. TEMPO2 is also on conda-forge (linux-64/osx-64) if you
  prefer `mamba install -c conda-forge tempo2` over the source build.
