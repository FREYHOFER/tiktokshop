param(
  [int]$PollMinutes = 5
)

$ErrorActionPreference = "Stop"

if ($PollMinutes -lt 1) {
  throw "PollMinutes must be at least 1."
}

$Workspace = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$TaskName = "TikTokShop Libri Tracking Sync"
$ScriptPath = Join-Path $Workspace "scripts\watch_libri_tracking_sync.ps1"
$Action = New-ScheduledTaskAction `
  -Execute "powershell.exe" `
  -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$ScriptPath`" -PollMinutes $PollMinutes"
$Trigger = New-ScheduledTaskTrigger -AtLogOn
$Settings = New-ScheduledTaskSettingsSet `
  -StartWhenAvailable `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -RestartCount 3 `
  -RestartInterval (New-TimeSpan -Minutes 5) `
  -ExecutionTimeLimit (New-TimeSpan -Days 0)

try {
  Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description "Check Mein.Libri direct-shipment delivery notes and sync tracking to TikTok Shop." `
    -Force

  Start-ScheduledTask -TaskName $TaskName
  Write-Host "Installed and started scheduled task: $TaskName"
}
catch [Microsoft.Management.Infrastructure.CimException] {
  $Startup = [Environment]::GetFolderPath("Startup")
  $ShortcutPath = Join-Path $Startup "$TaskName.lnk"
  $Shell = New-Object -ComObject WScript.Shell
  $Shortcut = $Shell.CreateShortcut($ShortcutPath)
  $Shortcut.TargetPath = "powershell.exe"
  $Shortcut.Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$ScriptPath`" -PollMinutes $PollMinutes"
  $Shortcut.WorkingDirectory = $Workspace
  $Shortcut.Save()

  Start-Process `
    -FilePath "powershell.exe" `
    -ArgumentList "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$ScriptPath`" -PollMinutes $PollMinutes" `
    -WindowStyle Hidden
  Write-Host "Installed and started user Startup watcher: $ShortcutPath"
}

Write-Host "Polling every $PollMinutes minute(s)."
