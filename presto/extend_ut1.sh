#!/usr/bin/env bash
# extend_ut1.sh — refresh tempo2's UT1 (Earth-orientation) table so barycentric
# `prepfold -par` folds work for recent / near-future observation dates.
#
# WHY: PRESTO (>=6) generates polycos with tempo2, which reads
# $TEMPO2/clock/ut1.dat. That table ships with only ~1 year of forecast, so an
# observation past its end hits "MJD outside UT1 table range" and the polyco
# comes out empty (prepfold then aborts with "Problem running tempo2 ...").
# This extends the table from current IERS Earth-orientation data using the
# astropy + astropy-iers-data already installed in the PRESTO venv — no separate
# download if that package is reasonably current (pip-install it fresh to pull
# newer EOP). Re-run roughly yearly as observations pass the table's end.
#
# SAFETY: verifies astropy reproduces the table's settled (non-predicted) region
# to <=0.5 ms before writing, and backs the original up to ut1.dat.bak.
#
# Usage (inside the Ubuntu/WSL shell):  bash extend_ut1.sh
set -euo pipefail
# shellcheck disable=SC1090
source "$HOME/.presto_env" 2>/dev/null || true
: "${TEMPO2:?TEMPO2 is not set — source ~/.presto_env (run build_presto.sh first)}"
export _UT1="$TEMPO2/clock/ut1.dat"
[ -f "$_UT1" ] || { echo "No ut1.dat at $_UT1"; exit 1; }

python - <<'PY'
import os, sys, re, shutil
import numpy as np
from astropy.time import Time
from astropy.utils import iers
from astropy.utils.iers import IERS_Auto
iers.conf.auto_download = False          # use bundled astropy-iers-data (offline)

UT1 = os.environ["_UT1"]
SCALE, NPER, STEP = 1e-4, 6, 5            # values are TAI-UT1 in 1e-4 s, 6/line, 5-day step
TAI_UTC = 37.0                           # leap seconds; constant since 2017 (verify step guards it)

tab = IERS_Auto.open()
mjd_max = int(np.floor(np.max(np.asarray(tab['MJD']))))
print("astropy IERS table reaches MJD", mjd_max)

def units(mjds):
    t = Time(np.asarray(mjds, float), format='mjd', scale='utc')
    return np.round((TAI_UTC - np.asarray(t.delta_ut1_utc, float)) / SCALE).astype(int)

raw = open(UT1).read().splitlines()
header = raw[:2]
data = []
for ln in raw[2:]:
    if ln.strip() == "END":
        break
    m = re.match(r"\s*(\d{5})\b", ln)
    if m:
        data.append((int(m.group(1)), ln))
first, last_start = data[0][0], data[-1][0]
print("current file coverage: MJD %d .. ~%d" % (first, last_start + STEP*NPER))

# --- verify the method against the settled (non-predicted) region ---
maxdiff = checked = 0
for mjd, ln in data:
    if not (58000 <= mjd <= 60000):
        continue
    vals = [int(x) for x in ln.split()[1:1+NPER]]
    got = units([mjd + STEP*j for j in range(len(vals))])
    maxdiff = max(maxdiff, max(abs(int(g)-v) for g, v in zip(got, vals)))
    checked += 1
print("verified %d lines against astropy; max |diff| = %d (0.1 ms units)" % (checked, maxdiff))
if maxdiff > 5:
    print("ABORT: astropy disagrees with the existing table by >0.5 ms."); sys.exit(1)

EXTEND_TO = mjd_max - STEP*NPER           # extend to the end of astropy's bundled data
if EXTEND_TO <= last_start:
    print("Nothing to add: table already reaches MJD %d (astropy has %d)."
          % (last_start + STEP*NPER, mjd_max)); sys.exit(0)

keep = [ln for mjd, ln in data if mjd < last_start]
new = []
mjd = last_start
while mjd <= EXTEND_TO:
    new.append("     %5d" % mjd + "".join("%7d " % v for v in units([mjd + STEP*j for j in range(NPER)])))
    mjd += STEP*NPER
shutil.copy(UT1, UT1 + ".bak")
open(UT1, "w").write("\n".join(header + keep + new + ["END"]) + "\n")
print("wrote %s (backup %s.bak)" % (UT1, UT1))
print("new coverage: MJD %d .. %d" % (first, EXTEND_TO + STEP*(NPER-1)))
PY
