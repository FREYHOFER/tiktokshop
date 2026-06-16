param(
  [int]$PollMinutes = 5
)

$ErrorActionPreference = "Stop"

if ($PollMinutes -lt 1) {
  throw "PollMinutes must be at least 1."
}

$Workspace = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$TaskName = "TikTokShop Libri Order Automation New Orders"
$ScriptPath = Join-Path $Workspace "scripts\watch_order_automation_new_orders.ps1"

$Action = New-ScheduledTaskAction `
  -Execute "powershell.exe" `
  -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`" -PollMinutes $PollMinutes"

$Trigger = New-ScheduledTaskTrigger -AtLogOn
$Settings = New-ScheduledTaskSettingsSet `
  -StartWhenAvailable `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -RestartCount 3 `
  -RestartInterval (New-TimeSpan -Minutes 5) `
  -ExecutionTimeLimit (New-TimeSpan -Days 0)

Register-ScheduledTask `
  -TaskName $TaskName `
  -Action $Action `
  -Trigger $Trigger `
  -Settings $Settings `
  -Description "Poll TikTok Shop for new awaiting-shipment orders and prepare Libri customer-order files." `
  -Force

Start-ScheduledTask -TaskName $TaskName

Write-Host "Installed and started scheduled task: $TaskName"
Write-Host "Polling every $PollMinutes minute(s)."
