# wsl_service_tripwire.ps1 — fires on System event 7040 (service start-type
# changed). AUTO-HEALS WslService: if something set it to Disabled (Avast
# Cleanup / Driver Updater sweeps keep doing this — see the log history),
# restore StartupType=Manual immediately, then log the event + a process
# snapshot so the culprit stays identifiable. The scheduled task runs as
# SYSTEM (re-registered 2026-08-03), so Set-Service works without UAC.
# NOTE: log path is hardcoded — under SYSTEM, $env:USERPROFILE is the
# system profile, not rick's.
# Remove with: schtasks /delete /tn "DSES WSL tripwire" /f
$log = "C:\Users\rick\Documents\wsl_service_tripwire.log"
$stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'

# --- Heal FIRST, log second: the point is minimizing broken-WSL time. ---
$healed = ""
try {
    $svc = Get-Service WslService -ErrorAction Stop
    if ($svc.StartType -eq 'Disabled') {
        Set-Service WslService -StartupType Manual -ErrorAction Stop
        $healed = "AUTO-HEALED: WslService was Disabled -> restored to Manual."
    }
} catch {
    $healed = "AUTO-HEAL FAILED: $($_.Exception.Message)"
}

$ev = Get-WinEvent -FilterHashtable @{LogName='System'; Id=7040} -MaxEvents 3 |
      ForEach-Object { "$($_.TimeCreated)  $($_.Message -replace "`r`n", ' ')" }
Add-Content $log "===== $stamp ====="
if ($healed) { Add-Content $log $healed }
Add-Content $log ($ev -join "`n")
# Snapshot only when something actually touched WslService — the 7040 trigger
# also fires for unrelated services (Google Updater etc.) and full snapshots
# for those just bloat the log.
if ($healed) {
    Add-Content $log "--- processes at trigger time ---"
    Get-Process | Sort-Object CPU -Descending |
        Select-Object -First 40 Name, Id, Path |
        ForEach-Object { Add-Content $log ("{0,-30} {1,7}  {2}" -f $_.Name, $_.Id, $_.Path) }
}
Add-Content $log ""
