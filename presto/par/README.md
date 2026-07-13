# Pulsar ephemerides (`.par`) for the DSES fold pipeline

TEMPO/PRESTO parameter files for the pulsars we've recorded. Fold with:

```
prepfold -par presto/par/<name>.par  <recording>.fil
```

- **`J0332+5434.par`** — **B0329+54**, the reference pulsar. A timing-grade
  ephemeris (F0/F1/F2, PEPOCH 2021, DE200 / TDB). Folds B0329 at ~20σ. Its narrow
  `START/FINISH` is just the original fit window — prepfold extrapolates fine.
- **`J0953+0755.par`** — **B0950+08**. A **minimal, detection-grade** par built
  from the ATNF catalogue position + F0/DM because no ephemeris existed anywhere.
  The *position* is accurate (that's what barycentring needs); F0/DM are seeds and
  prepfold's search refines them. **Not** a fitted timing solution — swap in a real
  ephemeris before doing any timing.

Barycentric (`-par`) folds need `tempo` on `PATH` and a **current**
`$TEMPO/clock/ut1.dat` (extend it from IERS EOP roughly yearly). See the Haswell
trip report §5 for the exact TEMPO gotchas.
