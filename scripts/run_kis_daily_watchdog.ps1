$ErrorActionPreference = 'Continue'
$ProjectRoot = 'C:\Users\white\Desktop\MovingProject\KOSPI200_Project'
$env:PROJECT200_MARKET_DATA_DIR = 'kis_market_data_restart'
$LogPath = Join-Path $ProjectRoot 'data\kis_realtime\watchdog.log'
$Python = 'C:\WINDOWS\py.exe'
$Module = 'infrastructure.kis.kis_vts_weekday_collector'
$RestartSeconds = 10

New-Item -ItemType Directory -Force -Path (Split-Path $LogPath) | Out-Null
function Write-Log([string]$Message) {
    Add-Content -LiteralPath $LogPath -Value ("{0} {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss K'), $Message)
}
function Find-Collector {
    @(Get-CimInstance Win32_Process | Where-Object {
        $_.Name -eq 'py.exe' -and $_.CommandLine -like "*$Module*"
    } | Sort-Object ProcessId | Select-Object -First 1)
}

$mutex = New-Object System.Threading.Mutex($false, 'Project200-KIS-Daily-Market-Collector-Watchdog')
if (-not $mutex.WaitOne(0)) { exit 0 }
try {
    Write-Log 'WATCHDOG_STARTED'
    while ($true) {
        $existing = Find-Collector
        if ($existing) {
            $collectorPid = [int]$existing.ProcessId
            Write-Log ("COLLECTOR_ADOPTED pid={0}" -f $collectorPid)
            $process = Get-Process -Id $collectorPid -ErrorAction SilentlyContinue
        } else {
            $process = Start-Process -FilePath $Python -ArgumentList '-m', $Module -WorkingDirectory $ProjectRoot -PassThru -WindowStyle Hidden
            Write-Log ("COLLECTOR_STARTED pid={0}" -f $process.Id)
        }
        if ($process) { $process.WaitForExit() }
        Write-Log 'COLLECTOR_EXITED_OR_UNAVAILABLE'
        Start-Sleep -Seconds $RestartSeconds
    }
}
finally {
    $mutex.ReleaseMutex() | Out-Null
    $mutex.Dispose()
    Write-Log 'WATCHDOG_STOPPED'
}
