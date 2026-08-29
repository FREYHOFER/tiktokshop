param(
  [int]$PollMinutes = 5
)

$ErrorActionPreference = "Continue"

if ($PollMinutes -lt 1) {
  throw "PollMinutes must be at least 1."
}

$Workspace = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Runner = Join-Path $Workspace "scripts\run_libri_tracking_sync_once.ps1"
$LogDirectory = Join-Path $Workspace "outputs\libri_tracking_sync"
$LogPath = Join-Path $LogDirectory "watch.log"
New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null

$CreatedNew = $false
$Mutex = New-Object System.Threading.Mutex($true, "Local\TikTokShopLibriTrackingSync", [ref]$CreatedNew)
if (-not $CreatedNew) {
  exit 0
}

try {
  while ($true) {
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "[$stamp] Checking Libri delivery notes..." | Tee-Object -FilePath $LogPath -Append
    try {
      & $Runner 2>&1 | Tee-Object -FilePath $LogPath -Append
    }
    catch {
      "[$stamp] ERROR: $($_.Exception.Message)" | Tee-Object -FilePath $LogPath -Append
    }
    Start-Sleep -Seconds ($PollMinutes * 60)
  }
}
finally {
  if ($CreatedNew) {
    $Mutex.ReleaseMutex()
  }
  $Mutex.Dispose()
}
