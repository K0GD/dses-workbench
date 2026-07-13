#!/usr/bin/env bash
# build_presto.sh — install PRESTO + TEMPO + TEMPO2 into a fresh Ubuntu/Debian
# Linux userland. IDENTICAL whether that userland is WSL2 Ubuntu or a VMware /
# native Ubuntu VM. Everything is built from source against apt-provided
# libraries; the environment (PRESTO / TEMPO / TEMPO2 / PGPLOT_DIR + the PRESTO
# venv) is written to ~/.presto_env and hooked into ~/.bashrc; readfile / tempo
# / tempo2 are smoke-tested at the end.
#
# Usage (inside the Ubuntu shell):
#     bash build_presto.sh
#
# Re-runnable: existing clones are reused. Needs sudo for the apt step.
# Override the install location with:  PRESTO_ROOT=/some/path bash build_presto.sh
#
# Verified 2026-07 against: PRESTO INSTALL.md (meson build),
# github.com/nanograv/tempo (./prepare;./configure;make;make install),
# github.com/mattpitkin/tempo2 (./bootstrap;./configure;make;make install;
# make plugins). TEMPO2 is on conda-forge too (see the note near the tempo2
# section) if you'd rather not build it from source.
set -euo pipefail

# ---------------------------------------------------------------- config ---
ROOT="${PRESTO_ROOT:-$HOME/pulsar}"
PRESTO_SRC="$ROOT/presto"
PRESTO_VENV="$ROOT/presto-venv"
TEMPO_SRC="$ROOT/tempo"
TEMPO2_SRC="$ROOT/tempo2"
ENVFILE="$HOME/.presto_env"
JOBS="$(nproc)"

say()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\n\033[1;33m!!  %s\033[0m\n' "$*"; }
mkdir -p "$ROOT"

if grep -qi microsoft /proc/version 2>/dev/null; then
  say "Running under WSL — your Windows C: drive is at /mnt/c (recordings read in place)."
else
  say "Running under a regular Linux VM/host."
fi

# --------------------------------------------------- 1. system packages ---
say "Installing build dependencies (sudo apt) ..."
sudo apt-get update
sudo apt-get install -y --no-install-recommends \
  git build-essential gfortran tcsh autoconf automake libtool libltdl-dev pkg-config \
  meson ninja-build ghostscript \
  libfftw3-bin libfftw3-dev libgsl-dev liberfa-dev \
  pgplot5 libx11-dev libpng-dev libcfitsio-bin libcfitsio-dev libglib2.0-dev \
  python3-dev python3-venv python3-pip python3-numpy
export PGPLOT_DIR="${PGPLOT_DIR:-/usr/lib/pgplot5}"

# ------------------------------------------------- 2. PRESTO (meson build) -
say "Building PRESTO (meson) ..."
[ -d "$PRESTO_SRC/.git" ] || git clone --depth 1 https://github.com/scottransom/presto.git "$PRESTO_SRC"
[ -d "$PRESTO_VENV" ]     || python3 -m venv "$PRESTO_VENV"
# shellcheck disable=SC1091
source "$PRESTO_VENV/bin/activate"
pip install --upgrade pip wheel meson meson-python ninja numpy
cd "$PRESTO_SRC"
export PRESTO="$PRESTO_SRC"
[ -d build ] || meson setup build --prefix="$VIRTUAL_ENV"
meson compile -C build
meson install -C build
# The python package's meson build calls cc.find_library('presto') with NO
# explicit search dir, and the just-installed libpresto.so lives in the venv's
# libdir (not a default linker path). Point the linker there for BOTH the build
# and runtime, or `pip install .` fails with "library 'presto' not found".
_prlib="$VIRTUAL_ENV/lib/$(gcc -dumpmachine 2>/dev/null || echo x86_64-linux-gnu)"
export LIBRARY_PATH="$_prlib${LIBRARY_PATH:+:$LIBRARY_PATH}"
export LD_LIBRARY_PATH="$_prlib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export PKG_CONFIG_PATH="$_prlib/pkgconfig${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"
( cd python && pip install . ) \
  || warn "PRESTO python package didn't install (CLI tools still work; 'import presto' and the python-based scripts need it — see the error above)."
say "PRESTO CLI + python -> $VIRTUAL_ENV/bin"

# --------------------------------------------------------- 3. TEMPO (src) --
say "Building TEMPO ..."
[ -d "$TEMPO_SRC/.git" ] || git clone --depth 1 https://github.com/nanograv/tempo.git "$TEMPO_SRC"
cd "$TEMPO_SRC"
export TEMPO="$TEMPO_SRC"     # $TEMPO must point at the dir holding obsys.dat / tempo.cfg / clock/
[ -x ./prepare ] && ./prepare
./configure --prefix="$TEMPO_SRC"
make -j"$JOBS"
make install
say "TEMPO built ; \$TEMPO=$TEMPO_SRC"

# -------------------------------------------------------- 4. TEMPO2 (src) --
# NOTE: TEMPO2 is also on conda-forge (linux-64/osx-64). If this source build
# gives trouble, an alternative is a miniforge env:  mamba create -n psr -c
# conda-forge tempo2  (then $TEMPO2 is set by the package). We build from
# source here to keep the stack self-contained. Non-fatal: a tempo2 failure
# still leaves you a working PRESTO + TEMPO.
build_tempo2() {
  [ -d "$TEMPO2_SRC/.git" ] || git clone --depth 1 https://github.com/mattpitkin/tempo2.git "$TEMPO2_SRC"
  cd "$TEMPO2_SRC"
  export TEMPO2="$TEMPO2_SRC/T2runtime"   # must be exported BEFORE configure
  # bootstrap needs libltdl's LT_LIB_DLLOAD macro (from libltdl-dev); if the
  # packaged bootstrap still can't regenerate configure, force a full autoreconf
  # (also re-adds install-sh/config.guess/config.sub/compile).
  ./bootstrap || autoreconf -fi
  [ -x ./configure ] || autoreconf -fi
  ./configure --prefix="$TEMPO2_SRC/local"
  make -j"$JOBS"
  make install
  make plugins -j"$JOBS" || warn "some tempo2 plugins did not build (core tempo2 is fine)."
  make plugins-install   || true
}
say "Building TEMPO2 ..."
if build_tempo2; then
  say "TEMPO2 built ; \$TEMPO2=$TEMPO2_SRC/T2runtime"
else
  warn "TEMPO2 source build FAILED — PRESTO + TEMPO are still installed. Try the conda-forge route (see note above)."
fi

# ------------------------------------- 5. environment file + ~/.bashrc hook -
say "Writing $ENVFILE ..."
cat > "$ENVFILE" <<EOF
# PRESTO / TEMPO / TEMPO2 environment — generated by build_presto.sh
export PGPLOT_DIR="$PGPLOT_DIR"
export PRESTO="$PRESTO_SRC"
export TEMPO="$TEMPO_SRC"
export TEMPO2="$TEMPO2_SRC/T2runtime"
# Activate the PRESTO venv (puts readfile/prepfold/accelsearch + the presto
# python package on PATH). Remove this line if you prefer not to auto-activate.
[ -f "$PRESTO_VENV/bin/activate" ] && source "$PRESTO_VENV/bin/activate"
# libpresto.so lives in the venv libdir; the CLI binaries AND 'import presto'
# need it on the runtime linker path.
export LD_LIBRARY_PATH="$_prlib\${LD_LIBRARY_PATH:+:\$LD_LIBRARY_PATH}"
# TEMPO / TEMPO2 binaries (search both bin/ and src/ in case of layout diffs):
export PATH="$TEMPO_SRC/bin:$TEMPO_SRC/src:$TEMPO2_SRC/local/bin:\$PATH"
EOF
grep -q 'presto_env' "$HOME/.bashrc" 2>/dev/null || \
  printf '\n[ -f ~/.presto_env ] && source ~/.presto_env\n' >> "$HOME/.bashrc"

# ------------------------------------------------------- 6. smoke tests ----
say "Smoke tests ..."
# shellcheck disable=SC1090
source "$ENVFILE"
set +e
echo "-- tools on PATH:"; command -v readfile prepfold accelsearch rfifind tempo tempo2
echo "-- readfile (usage banner confirms it runs):"; readfile 2>&1 | head -2
echo "-- tempo:";  tempo  -v 2>&1 | head -1
echo "-- tempo2:"; tempo2 -h 2>&1 | head -1
echo "-- presto python:"; python -c "import presto; print('  presto python import OK')" 2>&1 | tail -1
set -e

say "DONE."
echo "Open a NEW shell (~/.presto_env is now auto-sourced), then e.g.:"
echo "   readfile /mnt/c/Users/rick/Documents/DSES_SA_Recordings/<file>.fil     # WSL path"
echo "   prepfold -psr B0329+54 -nosearch -noxwin -o /mnt/c/.../fold /mnt/c/.../<file>.fil"
