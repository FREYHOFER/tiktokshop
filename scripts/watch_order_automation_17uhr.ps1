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
    --output-root "$Workspace\outputs\order_automation" `
    --state "$Workspace\outputs\order_automation\state.json" `
    --watch `
    --run-at 17:00 `
    --timezone Europe/Berlin
  exit $LASTEXITCODE
}

& $Python "$Workspace\scripts\tiktok_order_automation.py" `
  --env "$Workspace\.env" `
  --output-root "$Workspace\outputs\order_automation" `
  --state "$Workspace\outputs\order_automation\state.json" `
  --watch `
  --run-at 17:00 `
  --timezone Europe/Berlin
