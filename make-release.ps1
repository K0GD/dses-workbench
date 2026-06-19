# make-release.ps1 - build a distributable zip of the DSES Spectrum Analyzer.
#
# Reads APP_VERSION from dses_spectrum_analyzer.py, copies the runtime files
# into dist\dses-spectrum-analyzer-<version>\, zips the folder, prints the
# path to the resulting archive.
#
# Run from the project root:    .\make-release.ps1
#
# Files included in the bundle:
#   dses_spectrum_analyzer.py     - the application
#   LICENSE                       - GPL-3.0
#   launcher.bat / .ps1           - Windows launcher
#   launcher.sh                   - Linux / macOS launcher
#   install-shortcut.ps1          - Windows desktop-shortcut installer
#   dses-spectrum-analyzer.desktop - Linux desktop file (template)
#   icons\dses_sa.ico / dses_sa.png - icons
#   environment.yml               - reference for env reproducibility
#   DSES_RFI_..._Installation.pdf - install / update guide (if built)
#
# Excluded: .conda\, .git\, .vscode\, __pycache__, CLAUDE.md,
#           icons\generate-icon.py, make-release.*, settings files.

$ErrorActionPreference = 'Stop'

$root = $PSScriptRoot
Push-Location $root
try {
    # --- Pull version from the source file ---
    $main = Join-Path $root 'dses_spectrum_analyzer.py'
    if (-not (Test-Path $main)) {
        throw "dses_spectrum_analyzer.py not found in $root"
    }
    $verMatch = Select-String -Path $main -Pattern '^APP_VERSION\s*=\s*"([^"]+)"' | Select-Object -First 1
    if (-not $verMatch) {
        throw "Could not find APP_VERSION in $main"
    }
    $version = $verMatch.Matches[0].Groups[1].Value
    Write-Host "Building release for version $version"

    # --- Lay out the staging dir ---
    $bundle = "dses-spectrum-analyzer-$version"
    $dist   = Join-Path $root 'dist'
    $stage  = Join-Path $dist $bundle
    $zip    = Join-Path $dist "$bundle.zip"

    if (Test-Path $stage) { Remove-Item -Recurse -Force $stage }
    if (Test-Path $zip)   { Remove-Item -Force $zip }
    New-Item -ItemType Directory -Force -Path $stage | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $stage 'icons') | Out-Null

    # --- Copy runtime files ---
    $files = @(
        'dses_spectrum_analyzer.py',
        'sigproc_fil.py',
        'iq_to_fil.py',
        'LICENSE',
        'launcher.bat',
        'launcher.ps1',
        'launcher.sh',
        'install-shortcut.ps1',
        'install-shortcut.command',
        'dses-spectrum-analyzer.desktop',
        'environment.yml'
    )
    foreach ($f in $files) {
        if (Test-Path $f) {
            Copy-Item $f -Destination $stage
        } else {
            Write-Warning "Missing (skipped): $f"
        }
    }
    foreach ($f in @('icons\dses_sa.ico', 'icons\dses_sa.png', 'icons\dses_sa.icns')) {
        if (Test-Path $f) { Copy-Item $f -Destination (Join-Path $stage 'icons') }
        else { Write-Warning "Missing (skipped): $f" }
    }
    # Pre-built SoapySDRPlay3 module for Windows (SDRplay support). Not on
    # conda-forge, so we ship it; the install guide section 1A tells the user where
    # to copy it. README.txt records the ABI it was built against.
    New-Item -ItemType Directory -Force -Path (Join-Path $stage 'sdrplay') | Out-Null
    foreach ($f in @('vendor\windows\sdrPlaySupport.dll', 'vendor\windows\README.txt')) {
        if (Test-Path $f) { Copy-Item $f -Destination (Join-Path $stage 'sdrplay') }
        else { Write-Warning "Missing (skipped): $f" }
    }
    # Install guide PDF (the DSES-styled PDF is the deliverable; the .docx
    # is a developer-side intermediate and stays out of the bundle).
    foreach ($doc in @('DSES_RFI_Spectrum_Analyzer_Installation.pdf')) {
        if (Test-Path $doc) { Copy-Item $doc -Destination $stage }
        else { Write-Warning "Missing (skipped): $doc - run build_doc.py first" }
    }
    # Default SigMF playback sample - ships so users without any SDR
    # attached can still launch and see live spectrum. Large (~500+ MB).
    foreach ($f in @('sample.sigmf-data', 'sample.sigmf-meta')) {
        if (Test-Path $f) {
            Copy-Item $f -Destination $stage
        } else {
            Write-Warning "Missing playback sample (skipped): $f"
        }
    }

    # --- Zip ---
    # Retry: a real-time AV scan (Defender) or a just-launched copy of the app
    # can briefly lock a freshly-staged file, making Compress-Archive throw
    # "being used by another process". Retry a few times before giving up.
    $maxAttempts = 5
    for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
        try {
            Compress-Archive -Path $stage -DestinationPath $zip -Force -ErrorAction Stop
            break
        } catch {
            if ($attempt -eq $maxAttempts) { throw }
            Write-Warning ("Zip attempt {0}/{1} failed (file locked?); retrying in 3s..." -f $attempt, $maxAttempts)
            if (Test-Path $zip) { Remove-Item -Force $zip -ErrorAction SilentlyContinue }
            Start-Sleep -Seconds 3
        }
    }
    $size = (Get-Item $zip).Length
    Write-Host ""
    Write-Host "Wrote $zip ($([math]::Round($size/1KB, 1)) KB)"
    Write-Host "Staging tree retained at $stage"
} finally {
    Pop-Location
}
