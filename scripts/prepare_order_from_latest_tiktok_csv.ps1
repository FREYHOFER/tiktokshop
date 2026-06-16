$ErrorActionPreference = "Stop"

$Workspace = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $Python) {
  $Python = (Get-Command py -ErrorAction SilentlyContinue).Source
  if (-not $Python) {
    throw "Python was not found on PATH."
  }
  & $Python -3 "$Workspace\scripts\tiktok_order_automation.py" `
    --env "$Workspace\.env" `
    --input-csv latest `
    --output-root "$Workspace\outputs\order_automation" `
    --state "$Workspace\outputs\order_automation\state.json" `
    --ignore-state
  exit $LASTEXITCODE
}

& $Python "$Workspace\scripts\tiktok_order_automation.py" `
  --env "$Workspace\.env" `
  --input-csv latest `
  --output-root "$Workspace\outputs\order_automation" `
  --state "$Workspace\outputs\order_automation\state.json" `
  --ignore-state
