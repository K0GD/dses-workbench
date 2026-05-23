# launcher.ps1 - locate a Radioconda/conda env with UHD and launch the spectrum analyzer.
# Invoked by launcher.bat with: powershell -NoProfile -ExecutionPolicy Bypass -File launcher.ps1
$ErrorActionPreference = 'Stop'

$ScriptDir  = $PSScriptRoot
$MainScript = Join-Path $ScriptDir 'dses_spectrum_analyzer.py'
$ConfigDir  = Join-Path $env:APPDATA 'DSES_Analyzer'
$ConfigFile = Join-Path $ConfigDir 'radioconda_root.txt'
$Marker     = 'Library\share\uhd\images\usrp_b210_fpga.bin'

function Test-RadiocondaRoot([string]$Path) {
    if (-not $Path) { return $false }
    return (Test-Path (Join-Path $Path 'python.exe')) -and `
           (Test-Path (Join-Path $Path $Marker))
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
        Write-Host ("Invalid path: '{0}' does not contain python.exe and the B210 FPGA image." -f $userPath) -ForegroundColor Red
        exit 1
    }
    if (-not (Test-Path $ConfigDir)) {
        New-Item -ItemType Directory -Path $ConfigDir -Force | Out-Null
    }
    Set-Content -Path $ConfigFile -Value $userPath -Encoding utf8
    $root = $userPath
}

$python = Join-Path $root 'python.exe'
$argList = @($MainScript) + $args
# Start the console minimized so it doesn't clutter the desktop — the Qt
# window is what the user interacts with. We use python.exe (not pythonw.exe)
# on purpose: the app's overflow monitor redirects FD 2 (stderr), which needs
# a real console allocated; a minimized console keeps FD 2 valid and the logs
# reachable from the taskbar, whereas pythonw.exe has no console at all.
Start-Process -FilePath $python -ArgumentList $argList -WorkingDirectory $ScriptDir -WindowStyle Minimized
