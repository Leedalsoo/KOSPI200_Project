[CmdletBinding()]
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = 'Stop'
$exitCode = 0
$mutex = $null
$ownsMutex = $false

function Write-WatcherLog {
    param([Parameter(Mandatory = $true)][string]$Message)
    $stamp = Get-Date -Format o
    Add-Content -LiteralPath $script:LogFile -Value "[$stamp] $Message" -Encoding UTF8
}

try {
    $resolvedRoot = (Resolve-Path -LiteralPath $ProjectRoot -ErrorAction Stop).Path
    $rootBytes = [System.Text.Encoding]::UTF8.GetBytes($resolvedRoot.ToLowerInvariant())
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $rootHash = ([BitConverter]::ToString($sha.ComputeHash($rootBytes))).Replace('-', '').Substring(0, 16)
    }
    finally {
        $sha.Dispose()
    }

    $logRoot = Join-Path $env:LOCALAPPDATA 'KOSPI200_Project\graphify-watch'
    $logDir = Join-Path $logRoot $rootHash
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    $script:LogFile = Join-Path $logDir 'watcher.log'

    $mutexName = "Global\KOSPI200_GraphifyWatch_$rootHash"
    $createdNew = $false
    $mutex = [System.Threading.Mutex]::new($false, $mutexName, [ref]$createdNew)
    try {
        $ownsMutex = $mutex.WaitOne(0)
    }
    catch [System.Threading.AbandonedMutexException] {
        $ownsMutex = $true
        Write-WatcherLog 'Recovered abandoned watcher mutex.'
    }

    if (-not $ownsMutex) {
        Write-WatcherLog "Another watcher already owns this project root; exiting without starting a duplicate. Root=$resolvedRoot"
        $exitCode = 0
    }
    else {
        Write-WatcherLog "Watcher starting. Root=$resolvedRoot; PID=$PID"
        $gitRoot = (& git -C $resolvedRoot rev-parse --show-toplevel 2>&1 | Out-String).Trim()
        if ($LASTEXITCODE -ne 0 -or -not $gitRoot) {
            throw "Project root is not a readable Git worktree: $resolvedRoot"
        }
        Write-WatcherLog "GitRoot=$gitRoot"

        $dirtyGraph = @(& git -C $resolvedRoot status --porcelain -- graphify-out/graph.json graphify-out/GRAPH_REPORT.md)
        if ($LASTEXITCODE -ne 0) {
            throw 'Unable to inspect Graphify output state; refusing to start.'
        }
        if ($dirtyGraph.Count -gt 0) {
            Write-WatcherLog 'REFUSED: graphify-out/graph.json or GRAPH_REPORT.md has pre-existing Git changes. Review/backup those artifacts before enabling automatic refresh.'
            $exitCode = 23
        }
        else {
            $graphify = Get-Command graphify -ErrorAction Stop
            $versionOutput = (& $graphify.Source --version 2>&1 | Out-String).Trim()
            if ($LASTEXITCODE -ne 0) {
                throw "Graphify version check failed: $versionOutput"
            }
            Write-WatcherLog "Graphify=$($graphify.Source); Version=$versionOutput"

            $needsUpdate = Join-Path $resolvedRoot 'graphify-out\needs_update'
            if (Test-Path -LiteralPath $needsUpdate) {
                Write-WatcherLog 'NOTICE: semantic/non-code update marker exists. This watcher does not invoke LLM semantic extraction; review and run the approved semantic update separately.'
            }

            Write-WatcherLog 'Starting graphify watch. Code AST refresh is delegated to Graphify; semantic/non-code refresh is not automatic.'
            & $graphify.Source watch $resolvedRoot 2>&1 | ForEach-Object {
                Write-WatcherLog ([string]$_)
            }
            $exitCode = $LASTEXITCODE
            Write-WatcherLog "Graphify watcher exited. ExitCode=$exitCode"
        }
    }
}
catch {
    if ($script:LogFile) {
        Write-WatcherLog "ERROR: $($_.Exception.Message)"
    }
    $exitCode = 1
}
finally {
    if ($ownsMutex -and $mutex) {
        try { $mutex.ReleaseMutex() } catch {}
    }
    if ($mutex) { $mutex.Dispose() }
}

exit $exitCode