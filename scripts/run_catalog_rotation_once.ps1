param(
  [switch]$Live,
  [string]$NewWorkbook = "",
  [int]$ReplaceCount = 10,
  [switch]$Listing,
  [switch]$AllowCreateWithoutRetire
)

$ErrorActionPreference = "Stop"

$Workspace = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Python = (Get-Command python -ErrorAction SilentlyContinue).Source
$ScriptArgs = @(
  "$Workspace\scripts\rotate_tiktok_catalog.py",
  "--env", "$Workspace\.env",
  "--output-root", "$Workspace\outputs\catalog_rotation",
  "--replace-count", "$ReplaceCount"
)

if ($NewWorkbook) {
  $ScriptArgs += @("--new-workbook", "$NewWorkbook")
}
if ($Live) {
  $ScriptArgs += "--live"
}
if ($Listing) {
  $ScriptArgs += @("--save-mode", "LISTING")
}
if ($AllowCreateWithoutRetire) {
  $ScriptArgs += "--allow-create-without-retire"
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
