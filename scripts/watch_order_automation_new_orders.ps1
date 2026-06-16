param(
  [int]$PollMinutes = 5
)

$ErrorActionPreference = "Stop"

if ($PollMinutes -lt 1) {
  throw "PollMinutes must be at least 1."
}

$Workspace = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Python = (Get-Command python -ErrorAction SilentlyContinue).Source
$ScriptArgs = @(
  "$Workspace\scripts\tiktok_order_automation.py",
  "--env", "$Workspace\.env",
  "--output-root", "$Workspace\outputs\order_automation",
  "--state", "$Workspace\outputs\order_automation\state.json",
  "--watch",
  "--poll-minutes", "$PollMinutes",
  "--skip-empty-runs"
)

if (-not $Python) {
  $Python = (Get-Command py -ErrorAction SilentlyContinue).Source
  if (-not $Python) {
    throw "Python was not found on PATH."
  }
  & $Python -3 @ScriptArgs
  exit $LASTEXITCODE
}

& $Python @ScriptArgs
