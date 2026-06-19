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
    iq_to_fil.py \
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

# Make launcher.sh executable inside the bundle
chmod +x "$stage/launcher.sh"

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
