param(
  [string]$RunAt = "06:00",
  [switch]$DryRun,
  [int]$Limit = 0,
  [string]$WarehouseId = ""
)

$ErrorActionPreference = "Stop"

if ($RunAt -notmatch '^\d{1,2}:\d{2}$') {
  throw "RunAt must use HH:mm format, for example 06:00."
}

$Parts = $RunAt.Split(":")
$Hour = [int]$Parts[0]
$Minute = [int]$Parts[1]
if ($Hour -lt 0 -or $Hour -gt 23 -or $Minute -lt 0 -or $Minute -gt 59) {
  throw "RunAt must be a valid 24-hour time."
}

$Workspace = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$TaskName = "TikTokShop Libri Inventory Update Daily"
$ScriptPath = Join-Path $Workspace "scripts\run_inventory_update_once.ps1"
$ActionArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`""

if ($DryRun) {
  $ActionArgs += " -DryRun"
}
if ($Limit -gt 0) {
  $ActionArgs += " -Limit $Limit"
}
if ($WarehouseId) {
  $ActionArgs += " -WarehouseId `"$WarehouseId`""
}

$Action = New-ScheduledTaskAction `
  -Execute "powershell.exe" `
  -Argument $ActionArgs

$Trigger = New-ScheduledTaskTrigger -Daily -At $RunAt
$Settings = New-ScheduledTaskSettingsSet `
  -StartWhenAvailable `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -RestartCount 3 `
  -RestartInterval (New-TimeSpan -Minutes 10)

Register-ScheduledTask `
  -TaskName $TaskName `
  -Action $Action `
  -Trigger $Trigger `
  -Settings $Settings `
  -Description "Refresh Libri stock and update matching TikTok Shop LIBRI-* SKU quantities." `
  -Force

Write-Host "Installed scheduled task: $TaskName"
Write-Host "Daily run time: $RunAt"
if ($DryRun) {
  Write-Host "Mode: dry run"
} else {
  Write-Host "Mode: live TikTok inventory updates"
}
