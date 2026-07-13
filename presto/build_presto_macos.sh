#!/bin/bash
# build_presto_macos.sh — build PRESTO v6.0.0 from source into a conda env on
# macOS (Apple Silicon / osx-arm64). Companion to build_presto.sh, which does
# the WSL/Ubuntu (linux-64) build.
#
# WHY FROM SOURCE: as of 2026-07 the "first conda-forge release" of PRESTO v6
# has only built for linux-64 — there is NO osx-arm64 (or osx-64) `presto`
# package on conda-forge yet (searching finds only the unrelated `r-rpresto`).
# tempo2 likewise has no osx-arm64 conda-forge build (the recipe gates it to
# `linux or (osx and x86_64)`), so on Apple Silicon it runs via Rosetta from an
# osx-64 package in a separate env.
#
# WHAT v6 CHANGES (vs the v5.3.x we ran before): PRESTO 6 no longer uses classic
# TEMPO at all — barycentering is in-process via ERFA (vendored, built as a meson
# subproject) and polycos come from tempo2. GSL is now a required build dep (the
# last Fortran least-squares solver moved to GSL); the compiled code is otherwise
# Fortran-free. The `$PRESTO` env var is optional (runtime data installs to
# {prefix}/share/presto). prepfold also converts its .ps plot to .png via `gs`
# directly now (no pstoimg needed).
#
# The existing radioconda `presto` env (v5.3.x) is left untouched as a fallback.
set -euo pipefail

RC="${RADIOCONDA:-$HOME/radioconda}"
CONDA="$RC/bin/conda"
ENVDIR="${PRESTO6_ENV:-$RC/envs/presto6}"
SRC="${PRESTO_SRC:-$HOME/presto-v6}"
TAG="v6.0.0"

# 1. Build env from conda-forge: full C toolchain + all build/host/run deps
#    (matches the in-repo conda-recipe/meta.yaml; note GSL is required for v6).
"$CONDA" create -y -p "$ENVDIR" -c conda-forge \
  python=3.11 pip numpy scipy astropy matplotlib-base \
  c-compiler fortran-compiler meson meson-python ninja pkg-config \
  fftw gsl cfitsio glib libpng xorg-libx11 pgplot ghostscript
# (Alternatively, if you already have a working v5 `presto` env, it is faster to
#  `conda create -p "$ENVDIR" --clone "$RC/envs/presto"` — it already has every
#  build dep including gsl — then pick up from step 2.)

# 2. v6.0.0 source. Prefer a worktree off an existing checkout so any other
#    checkout stays put; otherwise clone fresh.
if [ -d "$HOME/presto/.git" ]; then
  git -C "$HOME/presto" fetch --tags origin
  git -C "$HOME/presto" worktree add "$SRC" "$TAG" 2>/dev/null || true
else
  [ -d "$SRC/.git" ] || git clone https://github.com/scottransom/presto "$SRC"
  git -C "$SRC" fetch --tags origin && git -C "$SRC" checkout "$TAG"
fi

# 3. Reproduce the env's compiler environment WITHOUT `conda activate` (source
#    its activation scripts; conda-forge's clang/gfortran export CC/FC/CFLAGS/…).
export CONDA_PREFIX="$ENVDIR"
export PATH="$ENVDIR/bin:$PATH"
for f in "$ENVDIR"/etc/conda/activate.d/*.sh; do source "$f"; done
export PKG_CONFIG_PATH="$ENVDIR/lib/pkgconfig:${PKG_CONFIG_PATH:-}"
export PGPLOT_DIR="$ENVDIR/share/pgplot"

# 4. Build + install the C code and libpresto (meson) into the env prefix.
cd "$SRC"
rm -rf build
meson setup build --prefix="$CONDA_PREFIX"
meson compile -C build
meson install -C build

# 5. Build + install the Python bindings. The python meson does
#    cc.find_library('presto'), so libpresto must be findable at LINK time:
#    that is LIBRARY_PATH (compile-time), not (DY)LD_LIBRARY_PATH.
cd "$SRC/python"
export LIBRARY_PATH="$CONDA_PREFIX/lib:${LIBRARY_PATH:-}"
export DYLD_LIBRARY_PATH="$CONDA_PREFIX/lib:${DYLD_LIBRARY_PATH:-}"
python -m pip install . --no-build-isolation

# 6. Smoke test.
python -c 'import presto; print("PRESTO", presto.__version__)'
"$CONDA_PREFIX/bin/readfile" >/dev/null 2>&1 && echo "readfile OK" || echo "readfile FAILED"

cat <<'NOTE'
Done. PRESTO 6.0.0 is in the presto6 env; the v5 `presto` env is untouched.
For -par / polyco (tempo2) folds, put a tempo2 on PATH and set TEMPO2 first, e.g.
from a Rosetta osx-64 conda-forge tempo2 env:
    export PATH=$HOME/radioconda/envs/timing/bin:$PATH
    export TEMPO2=$HOME/radioconda/envs/timing/share/tempo2
then:  prepfold -par presto/par/J0332+5434.par -noxwin -o <out> <recording>.fil
NOTE
