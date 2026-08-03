#!/usr/bin/env bash
# make-release.sh — build a distributable zip of the DSES Spectrum Analyzer.
#
# Reads APP_VERSION from dses_spectrum_analyzer.py, copies the runtime files
# into dist/dses-spectrum-analyzer-<version>/, zips the folder, prints the
# path to the resulting archive.
#
# Run from the project root:    ./make-release.sh
#
# See make-release.ps1 for the matching Windows version. Both produce
# bit-identical bundle contents (modulo file timestamps).
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -f dses_spectrum_analyzer.py ]; then
    echo "dses_spectrum_analyzer.py not found in $(pwd)" >&2
    exit 1
fi

version="$(grep -oE '^APP_VERSION[[:space:]]*=[[:space:]]*"[^"]+"' dses_spectrum_analyzer.py \
            | head -n1 | sed -E 's/.*"([^"]+)".*/\1/')"
if [ -z "$version" ]; then
    echo "Could not find APP_VERSION in dses_spectrum_analyzer.py" >&2
    exit 1
fi

bundle="dses-spectrum-analyzer-$version"
dist="dist"
stage="$dist/$bundle"
archive="$dist/$bundle.zip"

echo "Building release for version $version"

rm -rf "$stage" "$archive"
mkdir -p "$stage/icons"

copy_if_present() {
    local src="$1" dst="$2"
    if [ -e "$src" ]; then
        cp "$src" "$dst"
    else
        echo "  (missing, skipped) $src" >&2
    fi
}

# Runtime files
for f in \
    dses_spectrum_analyzer.py \
    sigproc_fil.py \
    ezra_txt.py \
    fold_analysis.py \
    fold_pdf.py \
    iq_to_fil.py \
    updater.py \
    LICENSE \
    launcher.bat \
    launcher.ps1 \
    launcher.sh \
    install-shortcut.ps1 \
    install-shortcut.command \
    dses-spectrum-analyzer.desktop \
    environment.yml ; do
    copy_if_present "$f" "$stage/"
done
copy_if_present icons/dses_sa.ico "$stage/icons/"
copy_if_present icons/dses_sa.png "$stage/icons/"
copy_if_present icons/dses_sa.icns "$stage/icons/"

# Pre-built SoapySDRPlay3 module for Windows (SDRplay support). Not on
# conda-forge, so we ship it; install guide §1A says where to copy it.
mkdir -p "$stage/sdrplay"
copy_if_present vendor/windows/sdrPlaySupport.dll "$stage/sdrplay/"
copy_if_present vendor/windows/README.txt "$stage/sdrplay/"

# Install guide PDF (the DSES-styled PDF is the deliverable; the .docx
# is a developer-side intermediate and stays out of the bundle).
copy_if_present DSES_RFI_Spectrum_Analyzer_Installation.pdf "$stage/"

# Default SigMF playback sample (large, ~500+ MB) — lets users without any
# SDR attached launch the program and see live spectrum from a recorded file.
copy_if_present sample.sigmf-data "$stage/"
copy_if_present sample.sigmf-meta "$stage/"

# PRESTO bridge + build recipes (the app's Analyze/Quick-look features shell
# out to these; Help points users at presto/build_presto.sh).
mkdir -p "$stage/presto"
copy_if_present presto/presto_bridge.py "$stage/presto/"
copy_if_present presto/build_presto.sh "$stage/presto/"
copy_if_present presto/build_presto_macos.sh "$stage/presto/"
copy_if_present presto/extend_ut1.sh "$stage/presto/"
copy_if_present presto/README.md "$stage/presto/"
[ -d presto/par ] && cp -R presto/par "$stage/presto/"

# Local-import completeness check (guards against the 1.1.8 incident: the
# app grew module files that never made it into the ship list, and the
# published zip died at startup with ModuleNotFoundError). Fail the build if
# any staged .py does a top-level import of a repo-local module that is not
# itself staged.
fail=0
repo_mods="$(ls *.py | sed 's/\.py$//')"
staged_mods="$(find "$stage" -name '*.py' -exec basename {} .py \;)"
for py in "$stage"/*.py; do
    while read -r mod; do
        [ -z "$mod" ] && continue
        if echo "$repo_mods" | grep -qx "$mod" && ! echo "$staged_mods" | grep -qx "$mod"; then
            echo "ERROR: $(basename "$py") imports '$mod' but $mod.py is not staged" >&2
            fail=1
        fi
    done < <(grep -oE '^[[:space:]]*(import|from)[[:space:]]+[A-Za-z_][A-Za-z0-9_]*' "$py" \
             | awk '{print $2}')
done
if [ "$fail" -ne 0 ]; then
    echo "Staging tree is missing local modules - add them to the ship list." >&2
    exit 1
fi
echo "Local-import completeness check passed."

# Make the Unix launcher + the macOS shortcut installer executable inside the
# bundle so a fresh install can run them (a plain unzip preserves these bits;
# the .command must be +x to run from a Finder double-click).
chmod +x "$stage/launcher.sh"
[ -f "$stage/install-shortcut.command" ] && chmod +x "$stage/install-shortcut.command"

# Zip — use python's zipfile so we don't depend on a system zip binary.
python3 -c "
import os, zipfile
stage='$stage'; archive='$archive'
with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
    for root, dirs, files in os.walk(stage):
        for name in files:
            full = os.path.join(root, name)
            arc = os.path.relpath(full, '$dist')
            z.write(full, arc)
"

size=$(stat -c %s "$archive" 2>/dev/null || stat -f %z "$archive")
echo ""
echo "Wrote $archive ($((size / 1024)) KB)"
echo "Staging tree retained at $stage"
