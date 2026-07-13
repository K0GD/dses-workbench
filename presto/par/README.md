# Pulsar ephemerides (`.par`) for the DSES fold pipeline

TEMPO/PRESTO parameter files for the pulsars we've recorded. Fold with:

```
prepfold -par presto/par/<name>.par  <recording>.fil
```

- **`J0332+5434.par`** — **B0329+54**, the reference pulsar. A timing-grade spin
  ephemeris (F0/F1/F2, PEPOCH 2021, DE200 / TDB). Folds B0329 at ~20σ. Its narrow
  `START/FINISH` is just the original fit window — prepfold extrapolates fine.
  The original CHIME reference-TOA lines (`TZRSITE CH` / `TZRMJD` / `TZRFRQ`) were
  removed: `CH` is a tempo1 code that **tempo2** (PRESTO ≥6) rejects with an empty
  polyco, and `TZRSITE` only sets the phase zero point (irrelevant to folding).
  For real TOA timing, add `TZRSITE` back per tool (`CH` for tempo1, `chime` for
  tempo2).
- **`J0953+0755.par`** — **B0950+08**. A **minimal, detection-grade** par built
  from the ATNF catalogue position + F0/DM because no ephemeris existed anywhere.
  The *position* is accurate (that's what barycentring needs); F0/DM are seeds and
  prepfold's search refines them. **Not** a fitted timing solution — swap in a real
  ephemeris before doing any timing.

Barycentric (`-par`) folds need a **current UT1 (Earth-orientation) table**, or
the polyco comes out empty for recent dates:
- **PRESTO ≥6 (WSL/Windows)** builds polycos with **tempo2** →
  `$TEMPO2/clock/ut1.dat`; refresh with `bash presto/extend_ut1.sh` (~yearly).
- **PRESTO 5 (the Mac)** uses **tempo1** → `$TEMPO/clock/ut1.dat`; extend from
  IERS EOP via TEMPO's `make_ut1`.

See the Haswell trip report §5 for the tempo1 gotchas.
