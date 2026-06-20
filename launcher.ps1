# launcher.ps1 - locate a Radioconda/conda env with UHD and launch the spectrum analyzer.
# Invoked by launcher.bat with: powershell -NoProfile -ExecutionPolicy Bypass -File launcher.ps1
$ErrorActionPreference = 'Stop'

$ScriptDir  = $PSScriptRoot
$MainScript = Join-Path $ScriptDir 'dses_spectrum_analyzer.py'
$ConfigDir  = Join-Path $env:APPDATA 'DSES_Analyzer'
$ConfigFile = Join-Path $ConfigDir 'radioconda_root.txt'

function Test-RadiocondaRoot([string]$Path) {
    # A usable env is any conda/Radioconda prefix whose python can import
    # GNU Radio. We deliberately do NOT require the B210 UHD FPGA image:
    # this is a multi-radio app (SDRPlay, RTL-SDR, etc. need no UHD images),
    # and some Radioconda builds don't ship the images by default.
    if (-not $Path) { return $false }
    $py = Join-Path $Path 'python.exe'
    if (-not (Test-Path $py)) { return $false }
    & $py -c "import gnuradio" 2>$null
    return ($LASTEXITCODE -eq 0)
}

function Find-Radioconda {
    # 1. Env var override
    if ($env:RADIOCONDA_ROOT -and (Test-RadiocondaRoot $env:RADIOCONDA_ROOT)) {
        return $env:RADIOCONDA_ROOT
    }
    # 2. Already-activated conda env
    if ($env:CONDA_PREFIX -and (Test-RadiocondaRoot $env:CONDA_PREFIX)) {
        return $env:CONDA_PREFIX
    }
    # 3. Standard install paths
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA 'radioconda'),
        'C:\ProgramData\radioconda',
        (Join-Path $env:USERPROFILE 'radioconda')
    )
    foreach ($c in $candidates) {
        if (Test-RadiocondaRoot $c) { return $c }
    }
    # 4. Cached config (from a previous first-run prompt)
    if (Test-Path $ConfigFile) {
        $cached = (Get-Content $ConfigFile -Raw).Trim()
        if (Test-RadiocondaRoot $cached) { return $cached }
    }
    # 5. conda on PATH
    if (Get-Command conda -ErrorAction SilentlyContinue) {
        try {
            $base = (& conda info --base 2>$null | Out-String).Trim()
            if (Test-RadiocondaRoot $base) { return $base }
        } catch {}
    }
    return $null
}

$root = Find-Radioconda

if (-not $root) {
    Write-Host "Radioconda not found in standard locations." -ForegroundColor Yellow
    Write-Host "Searched:"
    Write-Host "  - `$env:RADIOCONDA_ROOT"
    Write-Host "  - `$env:CONDA_PREFIX"
    Write-Host "  - $env:LOCALAPPDATA\radioconda"
    Write-Host "  - C:\ProgramData\radioconda"
    Write-Host "  - $env:USERPROFILE\radioconda"
    Write-Host "  - $ConfigFile"
    Write-Host "  - conda on PATH"
    Write-Host ""
    $userPath = Read-Host "Enter path to Radioconda install (blank to abort)"
    if (-not $userPath) {
        Write-Host "Aborted. Install Radioconda from https://github.com/radioconda/radioconda-installer/releases" -ForegroundColor Red
        exit 1
    }
    if (-not (Test-RadiocondaRoot $userPath)) {
        Write-Host ("Invalid path: '{0}' is not a GNU Radio environment (its python.exe can't 'import gnuradio')." -f $userPath) -ForegroundColor Red
        exit 1
    }
    if (-not (Test-Path $ConfigDir)) {
        New-Item -ItemType Directory -Path $ConfigDir -Force | Out-Null
    }
    Set-Content -Path $ConfigFile -Value $userPath -Encoding utf8
    $root = $userPath
}

$python = Join-Path $root 'python.exe'

# Preflight: the app needs a few packages that stock Radioconda doesn't ship
# (the GUI/plotting stack). Give a clear instruction instead of a traceback.
& $python -c "import PySide6, pyqtgraph, scipy" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Missing required packages (PySide6, pyqtgraph, and/or scipy)." -ForegroundColor Red
    Write-Host "Install them into Radioconda once, from the Anaconda Prompt (Radioconda):"
    Write-Host "    conda install -c conda-forge pyside6 pyqtgraph scipy"
    Write-Host "(see section 2.4 of the installation guide)."
    exit 1
}

# SDRplay receivers need the "SDRplay API Service" running. It often isn't
# started at boot, so SDRplay users otherwise have to start it by hand each
# time. Start it best-effort here. Non-fatal: users of the B210 / RTL-SDR /
# etc. don't have this service, and a non-elevated shell may lack rights to
# start it — in which case we print the one-time permanent fix.
$sdr = Get-Service -DisplayName '*SDRplay*' -ErrorAction SilentlyContinue | Select-Object -First 1
if ($sdr -and $sdr.Status -ne 'Running') {
    try {
        Start-Service -InputObject $sdr -ErrorAction Stop
        Write-Host ("Started the SDRplay API service ({0})." -f $sdr.Name)
    } catch {
        Write-Host ("SDRplay API service ({0}) isn't running and couldn't be auto-started." -f $sdr.Name) -ForegroundColor Yellow
        Write-Host  "  If you use an SDRplay receiver, make it start automatically (one-time, in an" -ForegroundColor Yellow
        Write-Host  "  Administrator PowerShell):" -ForegroundColor Yellow
        Write-Host ("    Set-Service '{0}' -StartupType Automatic; Start-Service '{0}'" -f $sdr.Name) -ForegroundColor Yellow
    }
}

$argList = @($MainScript) + $args
# Start the console minimized so it doesn't clutter the desktop. The Qt window
# is what the user interacts with, and it un-minimizes itself on launch (see
# _bring_to_front) — Qt's first window would otherwise inherit this minimized
# show-state, so only the console stays minimized. We use python.exe (not
# pythonw.exe) on purpose: the app's overflow monitor redirects FD 2 (stderr),
# which needs a real console allocated; a minimized console keeps FD 2 valid
# and the logs reachable from the taskbar, whereas pythonw.exe has no console.
Start-Process -FilePath $python -ArgumentList $argList -WorkingDirectory $ScriptDir -WindowStyle Minimized
