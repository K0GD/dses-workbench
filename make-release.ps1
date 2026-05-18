# make-release.ps1 — build a distributable zip of the B210 Spectrum Analyzer.
#
# Reads APP_VERSION from b210_spectrum_analyzer.py, copies the runtime files
# into dist\b210-spectrum-analyzer-<version>\, zips the folder, prints the
# path to the resulting archive.
#
# Run from the project root:    .\make-release.ps1
#
# Files included in the bundle:
#   b210_spectrum_analyzer.py     — the application
#   LICENSE                       — GPL-3.0
#   launcher.bat / .ps1           — Windows launcher
#   launcher.sh                   — Linux / macOS launcher
#   install-shortcut.ps1          — Windows desktop-shortcut installer
#   b210-spectrum-analyzer.desktop — Linux desktop file (template)
#   icons\b210.ico / b210.png     — icons
#   environment.yml               — reference for env reproducibility
#   Installing.docx               — install / update guide (if built)
#
# Excluded: .conda\, .git\, .vscode\, __pycache__, CLAUDE.md,
#           icons\generate-icon.py, make-release.*, settings files.

$ErrorActionPreference = 'Stop'

$root = $PSScriptRoot
Push-Location $root
try {
    # --- Pull version from the source file ---
    $main = Join-Path $root 'b210_spectrum_analyzer.py'
    if (-not (Test-Path $main)) {
        throw "b210_spectrum_analyzer.py not found in $root"
    }
    $verMatch = Select-String -Path $main -Pattern '^APP_VERSION\s*=\s*"([^"]+)"' | Select-Object -First 1
    if (-not $verMatch) {
        throw "Could not find APP_VERSION in $main"
    }
    $version = $verMatch.Matches[0].Groups[1].Value
    Write-Host "Building release for version $version"

    # --- Lay out the staging dir ---
    $bundle = "b210-spectrum-analyzer-$version"
    $dist   = Join-Path $root 'dist'
    $stage  = Join-Path $dist $bundle
    $zip    = Join-Path $dist "$bundle.zip"

    if (Test-Path $stage) { Remove-Item -Recurse -Force $stage }
    if (Test-Path $zip)   { Remove-Item -Force $zip }
    New-Item -ItemType Directory -Force -Path $stage | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $stage 'icons') | Out-Null

    # --- Copy runtime files ---
    $files = @(
        'b210_spectrum_analyzer.py',
        'LICENSE',
        'launcher.bat',
        'launcher.ps1',
        'launcher.sh',
        'install-shortcut.ps1',
        'b210-spectrum-analyzer.desktop',
        'environment.yml'
    )
    foreach ($f in $files) {
        if (Test-Path $f) {
            Copy-Item $f -Destination $stage
        } else {
            Write-Warning "Missing (skipped): $f"
        }
    }
    foreach ($f in @('icons\b210.ico', 'icons\b210.png')) {
        if (Test-Path $f) { Copy-Item $f -Destination (Join-Path $stage 'icons') }
        else { Write-Warning "Missing (skipped): $f" }
    }
    # Install guide PDF (the DSES-styled PDF is the deliverable; the .docx
    # is a developer-side intermediate and stays out of the bundle).
    foreach ($doc in @('DSES_RFI_Spectrum_Analyzer_Installation.pdf')) {
        if (Test-Path $doc) { Copy-Item $doc -Destination $stage }
        else { Write-Warning "Missing (skipped): $doc — run build_install_docx.py first" }
    }
    # Default SigMF playback sample — ships so users without a B210 can
    # still launch and see live spectrum. Large (~500+ MB).
    foreach ($f in @('sample.sigmf-data', 'sample.sigmf-meta')) {
        if (Test-Path $f) {
            Copy-Item $f -Destination $stage
        } else {
            Write-Warning "Missing playback sample (skipped): $f"
        }
    }

    # --- Zip ---
    Compress-Archive -Path $stage -DestinationPath $zip -Force
    $size = (Get-Item $zip).Length
    Write-Host ""
    Write-Host "Wrote $zip ($([math]::Round($size/1KB, 1)) KB)"
    Write-Host "Staging tree retained at $stage"
} finally {
    Pop-Location
}
