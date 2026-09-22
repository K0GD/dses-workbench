# DSES Radio Astronomy Workbench

Radio-astronomy workbench for the Deep Space Exploration Society's 60-foot dish
at Haswell, Colorado, and for members' home stations: live spectrum and
waterfall display, pulsar observation planning, science-format recording
(SIGPROC filterbank, SigMF, ezRA drift-scan text), PRESTO folding with
self-contained fold reports, multi-day hydrogen-line drift-scan campaigns, and
a built-in B210 pulsar simulator / self test. Windows, macOS and Linux (it runs
the Haswell drift scan on a Raspberry Pi 5).

Built on GNU Radio with the Ettus USRP B210 as the primary radio; any
SoapySDR-supported receiver (SDRplay, RTL-SDR, HackRF, Airspy, BladeRF, LimeSDR,
PlutoSDR) works too. PySide6 / PyQtGraph user interface. GPL-3.0-or-later.

## Installing

Read **Installing.md** (also shipped as a PDF with every release). In short:
install [Radioconda](https://github.com/radioconda/radioconda-installer/releases)
once, then unzip the release bundle and run the launcher for your platform. The
program checks for updates itself and installs them in place.

Release bundles, the install guide and the update manifest are published at
<https://gpstime.com/sw_distribution/dses-workbench/> — **not** from this
repository. This GitHub repository — <https://github.com/K0GD/dses-workbench> —
is a read-only mirror of the development history (the master lives on a DSES
server); issues and questions are welcome here or by email to the author. The
DSES EVE modem, which shares this program's B210 layer (`dses_radio.py`), is
mirrored the same way at <https://github.com/K0GD/eve-modem>.

## Layout

| File | Role |
|---|---|
| `dses_workbench.py` | the application (single file, plus the modules below) |
| `dses_radio.py` | the shared B210 / UHD layer |
| `pulsar_planner.py`, `pulsar_sim.py` | "Pulsars in View" planner; pulsar simulator and geometry solver |
| `sigproc_fil.py`, `ezra_txt.py` | filterbank and ezRA drift-scan writers |
| `fold_analysis.py`, `fold_pdf.py`, `presto/` | PRESTO post-processing and fold reports |
| `updater.py` | in-app update check and in-place install |
| `test_*.py` | test suites (most run offline, several headless) |
| `Installing.md`, `Release_Workflow.md`, `ROADMAP.md` | install guide, release procedure, feature planning |
| `make-release.ps1`, `make-release.sh` | build the cross-platform release zip |

Richard M Hambly, K0GD — k0gd@cnssys.com
