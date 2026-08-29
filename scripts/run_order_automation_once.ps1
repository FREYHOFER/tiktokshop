param(
  [switch]$SkipEmptyRuns
)

$ErrorActionPreference = "Stop"

$Workspace = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Python = (Get-Command python -ErrorAction SilentlyContinue).Source
$ScriptArgs = @(
  "$Workspace\scripts\tiktok_order_automation.py",
  "--env", "$Workspace\.env",
  "--output-root", "$Workspace\outputs\order_automation",
  "--state", "$Workspace\outputs\order_automation\state.json",
  "--hours-back", "0",
  "--auto-submit-libri",
  "--allow-existing-libri-basket"
)
if ($SkipEmptyRuns) {
  $ScriptArgs += "--skip-empty-runs"
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
