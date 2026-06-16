$ErrorActionPreference = "Stop"

$Workspace = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$TaskName = "TikTokShop Libri Order Automation 17 Uhr"
$ScriptPath = Join-Path $Workspace "scripts\run_order_automation_once.ps1"

$Action = New-ScheduledTaskAction `
  -Execute "powershell.exe" `
  -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`""

$Trigger = New-ScheduledTaskTrigger -Daily -At 17:00
$Settings = New-ScheduledTaskSettingsSet `
  -StartWhenAvailable `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries

Register-ScheduledTask `
  -TaskName $TaskName `
  -Action $Action `
  -Trigger $Trigger `
  -Settings $Settings `
  -Description "Fetch TikTok Shop awaiting-shipment orders and prepare Libri customer-order files." `
  -Force

Write-Host "Installed scheduled task: $TaskName"
