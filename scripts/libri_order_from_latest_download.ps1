$ErrorActionPreference = "Stop"

$Workspace = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Python = "C:\Users\User\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

& $Python "$Workspace\scripts\build_libri_order_from_tiktok_csv.py" `
  --reference buyer_username
