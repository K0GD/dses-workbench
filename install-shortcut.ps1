# install-shortcut.ps1 - create a desktop shortcut to the DSES Radio Astronomy Workbench.
# Run once per Windows machine. Re-run after generating an icon to refresh it.
#
# Optional -Suffix (usually a version): names the shortcut "DSES Spectrum
# Analyzer <suffix>" so a second install gets its own icon instead of
# overwriting the first. Used by the in-app updater's "install a new copy" path.
param([string]$Suffix = '')
$ErrorActionPreference = 'Stop'

$ScriptDir    = $PSScriptRoot
$ShortcutName = 'DSES Radio Astronomy Workbench'
if ($Suffix) { $ShortcutName = "DSES Radio Astronomy Workbench $Suffix" }
$DesktopPath  = [Environment]::GetFolderPath('Desktop')
$ShortcutPath = Join-Path $DesktopPath "$ShortcutName.lnk"
$PsLauncher   = Join-Path $ScriptDir 'launcher.ps1'
$IconPath     = Join-Path $ScriptDir 'icons\dses_workbench.ico'

if (-not (Test-Path $PsLauncher)) {
    Write-Host "launcher.ps1 not found alongside this script. Aborting." -ForegroundColor Red
    exit 1
}

$PowerShellExe = (Get-Command powershell.exe).Source

$WScriptShell = New-Object -ComObject WScript.Shell
$Shortcut = $WScriptShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath       = $PowerShellExe
$Shortcut.Arguments        = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$PsLauncher`""
$Shortcut.WorkingDirectory = $ScriptDir
$Shortcut.Description      = 'DSES Radio Astronomy Workbench for pulsar RFI'
$Shortcut.WindowStyle      = 7  # minimized; -WindowStyle Hidden in args takes precedence
if (Test-Path $IconPath) {
    $Shortcut.IconLocation = "$IconPath, 0"
}
$Shortcut.Save()

Write-Host "Created: $ShortcutPath" -ForegroundColor Green
if (-not (Test-Path $IconPath)) {
    Write-Host ""
    Write-Host "Note: no icon at $IconPath - shortcut uses the default PowerShell icon." -ForegroundColor Yellow
    Write-Host "Generate one with icons/generate-icon.py, then re-run this script." -ForegroundColor Yellow
}
