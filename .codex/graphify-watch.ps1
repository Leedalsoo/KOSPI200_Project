$ErrorActionPreference = 'Stop'
$ProjectRoot = 'C:\Users\white\Desktop\MovingProject\KOSPI200_Project'
$LogDir = Join-Path $ProjectRoot 'graphify-out'
$LogFile = Join-Path $LogDir 'watcher.log'
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
Set-Location -LiteralPath $ProjectRoot
"[$(Get-Date -Format o)] Graphify watcher starting for $ProjectRoot" | Add-Content -LiteralPath $LogFile
try {
    & graphify watch $ProjectRoot 2>&1 | ForEach-Object {
        $line = "[$(Get-Date -Format o)] $_"
        Add-Content -LiteralPath $LogFile -Value $line
    }
    $exitCode = $LASTEXITCODE
    "[$(Get-Date -Format o)] Graphify watcher exited with code $exitCode" | Add-Content -LiteralPath $LogFile
    exit $exitCode
}
catch {
    "[$(Get-Date -Format o)] ERROR: $_" | Add-Content -LiteralPath $LogFile
    exit 1
}
