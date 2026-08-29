param(
  [string]$RunAt = "06:00"
)

$ErrorActionPreference = "Continue"

if ($RunAt -notmatch '^\d{1,2}:\d{2}$') {
  throw "RunAt must use HH:mm format, for example 06:00."
}

$Parts = $RunAt.Split(":")
$Hour = [int]$Parts[0]
$Minute = [int]$Parts[1]
if ($Hour -lt 0 -or $Hour -gt 23 -or $Minute -lt 0 -or $Minute -gt 59) {
  throw "RunAt must be a valid 24-hour time."
}

$Workspace = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Runner = Join-Path $Workspace "scripts\run_inventory_update_once.ps1"
$OutputDirectory = Join-Path $Workspace "outputs\inventory_updates"
$StatePath = Join-Path $OutputDirectory "last_success_date.txt"
$LogPath = Join-Path $OutputDirectory "daily_watch.log"
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null

$CreatedNew = $false
$Mutex = New-Object System.Threading.Mutex($true, "Local\TikTokShopLibriInventoryDaily", [ref]$CreatedNew)
if (-not $CreatedNew) {
  exit 0
}

try {
  while ($true) {
    $Now = Get-Date
    $Scheduled = $Now.Date.AddHours($Hour).AddMinutes($Minute)
    $Today = $Now.ToString("yyyy-MM-dd")
    $LastSuccess = if (Test-Path -LiteralPath $StatePath) {
      (Get-Content -LiteralPath $StatePath -Raw).Trim()
    } else {
      ""
    }

    if ($Now -ge $Scheduled -and $LastSuccess -ne $Today) {
      "[$($Now.ToString('yyyy-MM-dd HH:mm:ss'))] Starting daily inventory update..." |
        Tee-Object -FilePath $LogPath -Append
      try {
        & $Runner 2>&1 | Tee-Object -FilePath $LogPath -Append
        if ($LASTEXITCODE -ne 0) {
          "Inventory update exited with code $LASTEXITCODE." | Tee-Object -FilePath $LogPath -Append
        }
      }
      catch {
        "ERROR: $($_.Exception.Message)" | Tee-Object -FilePath $LogPath -Append
      }
    }

    Start-Sleep -Seconds 300
  }
}
finally {
  if ($CreatedNew) {
    $Mutex.ReleaseMutex()
  }
  $Mutex.Dispose()
}
