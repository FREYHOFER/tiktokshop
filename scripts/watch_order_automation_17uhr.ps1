$ErrorActionPreference = "Stop"

$Workspace = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Python = "C:\Users\User\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

& $Python "$Workspace\scripts\tiktok_order_automation.py" `
  --env "$Workspace\.env" `
  --output-root "$Workspace\outputs\order_automation" `
  --state "$Workspace\outputs\order_automation\state.json" `
  --watch `
  --run-at 17:00 `
  --timezone Europe/Berlin
