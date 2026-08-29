param(
  [switch]$DryRun,
  [int]$Limit = 0
)

$ErrorActionPreference = "Stop"

$Workspace = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Python = (Get-Command python -ErrorAction SilentlyContinue).Source
$ScriptArgs = @(
  "$Workspace\scripts\sync_libri_tracking_to_tiktok.py",
  "--env", "$Workspace\.env",
  "--output-root", "$Workspace\outputs\libri_tracking_sync",
  "--state", "$Workspace\outputs\libri_tracking_sync\state.json"
)

if (-not $DryRun) {
  $ScriptArgs += "--live"
}
if ($Limit -gt 0) {
  $ScriptArgs += @("--limit", "$Limit")
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
