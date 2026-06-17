param(
  [switch]$DryRun,
  [int]$Limit = 0,
  [string]$WarehouseId = ""
)

$ErrorActionPreference = "Stop"

$Workspace = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Python = (Get-Command python -ErrorAction SilentlyContinue).Source
$ScriptArgs = @(
  "$Workspace\scripts\update_tiktok_quantities_from_libri.py",
  "--env", "$Workspace\.env",
  "--output-root", "$Workspace\outputs\inventory_updates"
)

if ($DryRun) {
  $ScriptArgs += "--dry-run"
}
if ($Limit -gt 0) {
  $ScriptArgs += @("--limit", "$Limit")
}
if ($WarehouseId) {
  $ScriptArgs += @("--warehouse-id", "$WarehouseId")
}

if (-not $Python) {
  $Python = (Get-Command py -ErrorAction SilentlyContinue).Source
  if (-not $Python) {
    throw "Python was not found on PATH."
  }
  & $Python -3 @ScriptArgs
  exit $LASTEXITCODE
}

& $Python @ScriptArgs
exit $LASTEXITCODE
