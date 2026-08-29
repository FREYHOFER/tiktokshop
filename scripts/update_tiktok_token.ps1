param(
  [string]$EnvPath = "",
  [string]$GitHubRepo = "FREYHOFER/tiktokshop",
  [string]$GitHubEnvironment = "shop",
  [switch]$SkipGitHubSecret
)

$ErrorActionPreference = "Stop"

$Workspace = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
if (-not $EnvPath) {
  $EnvPath = Join-Path $Workspace ".env"
}

function Get-EnvValue {
  param(
    [Parameter(Mandatory=$true)][string]$Path,
    [Parameter(Mandatory=$true)][string]$Key
  )
  if (-not (Test-Path -LiteralPath $Path)) {
    return ""
  }
  $line = Select-String -LiteralPath $Path -Pattern "^$([regex]::Escape($Key))=" -ErrorAction SilentlyContinue |
    Select-Object -First 1
  if (-not $line) {
    return ""
  }
  return ($line.Line -split "=", 2)[1].Trim()
}

$Python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $Python) {
  $Python = (Get-Command py -ErrorAction SilentlyContinue).Source
  if (-not $Python) {
    throw "Python was not found on PATH."
  }
}

Write-Host ""
Write-Host "TikTok Shop token update"
Write-Host "Do not paste the auth_code into chat. Paste it here in this local window."
Write-Host "If you have a TikTok authorize link, paste it once; this helper will open it."
Write-Host ""
$Code = Read-Host "TikTok auth_code or final callback URL"
if (-not $Code.Trim()) {
  throw "No auth_code entered."
}

if ($Code -match '^https?://services\.tiktokshop\.com/open/authorize\?') {
  Write-Host ""
  Write-Host "That is the authorize link, not the auth_code yet."
  Write-Host "Opening it in your browser. Authorize the shop, then paste the final redirected URL or the code value."
  Start-Process $Code
  Write-Host ""
  $Code = Read-Host "Final callback URL or auth_code"
  if (-not $Code.Trim()) {
    throw "No final callback URL or auth_code entered."
  }
}

$ExchangeScript = Join-Path $Workspace "scripts\exchange_tiktok_code.py"
$Code | & $Python $ExchangeScript --code-stdin --env $EnvPath
if ($LASTEXITCODE -ne 0) {
  throw "Token exchange failed with exit code $LASTEXITCODE."
}

$AccessToken = Get-EnvValue -Path $EnvPath -Key "TIKTOK_ACCESS_TOKEN"
$RefreshToken = Get-EnvValue -Path $EnvPath -Key "TIKTOK_REFRESH_TOKEN"
if (-not $AccessToken) {
  throw "TIKTOK_ACCESS_TOKEN was not written to $EnvPath."
}

if (-not $SkipGitHubSecret) {
  $Gh = (Get-Command gh -ErrorAction SilentlyContinue).Source
  if (-not $Gh) {
    Write-Warning "GitHub CLI not found. Local .env was updated, but GitHub secret was not."
  } else {
    $AccessToken | & $Gh secret set TIKTOK_ACCESS_TOKEN --env $GitHubEnvironment --repo $GitHubRepo
    if ($LASTEXITCODE -ne 0) {
      throw "Failed to update GitHub secret TIKTOK_ACCESS_TOKEN."
    }
    if ($RefreshToken) {
      $RefreshToken | & $Gh secret set TIKTOK_REFRESH_TOKEN --env $GitHubEnvironment --repo $GitHubRepo
      if ($LASTEXITCODE -ne 0) {
        Write-Warning "Access token was updated, but TIKTOK_REFRESH_TOKEN secret update failed."
      }
    }
  }
}

Write-Host ""
Write-Host "Token update complete."
Write-Host "Local .env updated: $EnvPath"
if (-not $SkipGitHubSecret) {
  Write-Host "GitHub environment updated: $GitHubRepo / $GitHubEnvironment"
}
