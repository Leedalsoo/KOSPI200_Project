param(
  [int]$Seed = 0,
  [string]$Pattern = "auto"
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$baseDir = Join-Path $root "data\synthetic_market_data\3m_5min_baseline_v1"
$run = Get-Date -Format "yyyyMMdd_HHmmss"
$outRoot = Join-Path $root "data\synthetic_market_data\scheduled_3m"
$verDir = Join-Path $root "verification\results\scheduled_3m"
New-Item -ItemType Directory -Force $outRoot,$verDir | Out-Null
if($Seed -eq 0){ $Seed = [int](Get-Date -Format "HHmmss") }
$patterns = @("trend_up","trend_down","mean_revert","high_volatility","low_volatility","shock")
$patternStatePath = Join-Path $verDir "pattern_rotation_state.json"
$autoPattern = ($Pattern -eq "auto")
if($autoPattern){
  # Hourly scheduler uses Queue, so runs are serialized when each 3-month replay takes >1 hour.
  # Persist the rotation index so queued executions advance one pattern at a time,
  # independent of the actual wall-clock start time after queueing.
  $nextIndex = $null
  if(Test-Path $patternStatePath){
    try { $state = Get-Content $patternStatePath -Raw | ConvertFrom-Json; $nextIndex = [int]$state.next_index } catch { $nextIndex = $null }
  }
  if($null -eq $nextIndex -or $nextIndex -lt 0 -or $nextIndex -ge $patterns.Count){
    $nextIndex = (Get-Date).Hour % $patterns.Count
  }
  $Pattern = $patterns[$nextIndex]
}
if($Pattern -notin $patterns){ throw "Unknown pattern: $Pattern" }

$datasetName = "synthetic-3m-5min-$Pattern-$run"
$datasetDir = Join-Path $outRoot $datasetName
$reportPath = Join-Path $verDir "$datasetName.json"
$logPath = Join-Path $verDir "$datasetName.log"
New-Item -ItemType Directory -Force $datasetDir | Out-Null
$rand = [System.Random]::new($Seed)
$timestampFactor = @{}
$total = 0
$days = 0

foreach($baseFile in (Get-ChildItem $baseDir -Filter "????-??-??.jsonl" | Sort-Object Name)) {
  $outFile = Join-Path $datasetDir $baseFile.Name
  $writer = [System.IO.StreamWriter]::new($outFile, $false, [System.Text.UTF8Encoding]::new($false))
  try {
    foreach($line in [System.IO.File]::ReadLines($baseFile.FullName)) {
      if([string]::IsNullOrWhiteSpace($line)){ continue }
      $o = $line | ConvertFrom-Json
      $t = $o.tick
      $total++
      $x = ($total - 1) / 49139.0
      switch($Pattern){
        "trend_up" { $factor = 1.0 + (0.16*$x); $noise=0.002 }
        "trend_down" { $factor = 1.0 - (0.16*$x); $noise=0.002 }
        "mean_revert" { $factor = 1.0 + 0.10*[math]::Sin($x*18); $noise=0.003 }
        "high_volatility" { $factor = 1.0 + 0.08*[math]::Sin($x*31) + 0.035*[math]::Sin($x*97); $noise=0.012 }
        "low_volatility" { $factor = 1.0 + 0.025*[math]::Sin($x*20); $noise=0.0008 }
        "shock" { $factor = if($x -gt 0.52 -and $x -lt 0.58){ 0.82 + 0.36*(($x-0.52)/0.06) } else { 1.0 + 0.025*[math]::Sin($x*15) }; $noise=0.005 }
      }
      $ts = [string]$t.timestamp
      if(-not $timestampFactor.ContainsKey($ts)) {
        $timestampFactor[$ts] = $factor * (1.0 + (($rand.NextDouble()-0.5)*2*$noise))
      }
      $commonFactor = [double]$timestampFactor[$ts]
      $oldU=[double]$t.underlying_price
      $newU=[math]::Round($oldU*$commonFactor,4)
      $strike=[double]$t.strike_price
      $intrinsic=if($t.option_type -eq 'CALL'){[math]::Max(0,$newU-$strike)}else{[math]::Max(0,$strike-$newU)}
      $oldMid=([double]$t.bid_price+[double]$t.ask_price)/2
      $oldIntrinsic=if($t.option_type -eq 'CALL'){[math]::Max(0,$oldU-$strike)}else{[math]::Max(0,$strike-$oldU)}
      $timeValue=[math]::Max(0,$oldMid-$oldIntrinsic)
      $newMid=[math]::Max(0.01,$intrinsic+$timeValue*(1+($commonFactor-1)*0.35))
      $spread=[math]::Max(0.02,([double]$t.ask_price-[double]$t.bid_price)*(1+[math]::Abs($commonFactor-1)*2))
      $t.underlying_price=[math]::Round($newU,4)
      $t.bid_price=[math]::Round([math]::Max(0.01,$newMid-$spread/2),6)
      $t.ask_price=[math]::Round([math]::Max($t.bid_price+0.0001,$newMid+$spread/2),6)
      $t.last_price=[math]::Round(($t.bid_price+$t.ask_price)/2,6)
      $t.volume=[int]([math]::Max(1,[math]::Round([double]$t.volume*(1+[math]::Abs($commonFactor-1)*3))))
      $o.dataset=$datasetName
      $o.source="SYNTHETIC_SCHEDULED_PATTERN:$Pattern"
      $o.provenance="DERIVED_SCENARIO"
      $t.option_source="SYNTHETIC_SCHEDULED_PATTERN:$Pattern"
      $writer.WriteLine(($o | ConvertTo-Json -Compress -Depth 10))
    }
  } finally { $writer.Dispose() }
  $days++
}
if($total -ne 49140 -or $days -ne 63){ throw "DATASET_SHAPE_INVALID events=$total days=$days expected=49140/63" }

$manifest=[ordered]@{
  schema="reference-canonical-market-tick-v1"; dataset=$datasetName; provenance="DERIVED_SCENARIO";
  pattern=$Pattern; seed=$Seed; events=$total; trading_days=$days; bar_interval_minutes=5;
  parent_dataset="synthetic-3m-5min-baseline-v1"; generated_at=(Get-Date).ToString("o")
}
$manifest | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 (Join-Path $datasetDir 'manifest.json')

# Build one canonical observations stream from the exact 63 generated daily files.
# Control Tower consumes a single historical_store_path; this keeps the UI source
# byte-for-byte derived from the same scheduled dataset used by High-Speed Replay.
$controlTowerStore = Join-Path $datasetDir 'control_tower_replay.jsonl'
$writer = [System.IO.StreamWriter]::new($controlTowerStore, $false, [System.Text.UTF8Encoding]::new($false))
try {
  foreach($dailyFile in (Get-ChildItem $datasetDir -Filter "????-??-??.jsonl" | Sort-Object Name)){
    foreach($line in [System.IO.File]::ReadLines($dailyFile.FullName)){
      if(-not [string]::IsNullOrWhiteSpace($line)){ $writer.WriteLine($line) }
    }
  }
} finally { $writer.Dispose() }
$controlTowerEventCount = @(Get-Content $controlTowerStore).Count
if($controlTowerEventCount -ne 49140){ throw "CONTROL_TOWER_STORE_SHAPE_INVALID events=$controlTowerEventCount expected=49140" }

Set-Location $root
& py -m environments.high_speed.virtual_runtime_replay --dataset $datasetDir 2>&1 | Tee-Object -FilePath $logPath
$exit=$LASTEXITCODE

# UI smoke is always attempted, including when replay fails.
# The UI check is bound to the SAME generated dataset through a temporary Control Tower
# instance. This prevents an unrelated pre-existing server/run from producing a false PASS.
$uiExit = 0
$uiLogPath = Join-Path $verDir "$datasetName.ui_smoke.log"
$tempServer = $null
try {
  $env:PROJECT200_HISTORICAL_STORE = $controlTowerStore
  $tempServer = Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoProfile","-ExecutionPolicy","Bypass","-Command","Set-Location '$root'; & py -c ""from interfaces.control_tower.server import run_server; run_server(port=18080)""") -PassThru -WindowStyle Hidden
  $ready = $false
  for($i=0; $i -lt 30; $i++){
    Start-Sleep -Milliseconds 500
    try {
      $probe = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:18080/" -TimeoutSec 2
      if($probe.StatusCode -eq 200){ $ready = $true; break }
    } catch {}
  }
  if(-not $ready){ throw "CONTROL_TOWER_TEMP_SERVER_NOT_READY" }
  & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "verify_control_tower_ui.ps1") -Port 18080 -ExpectedHistoricalStorePath $controlTowerStore -ExpectedDatasetName $datasetName 2>&1 | Tee-Object -FilePath $uiLogPath
  $uiExit = $LASTEXITCODE
} catch {
  $_ | Out-String | Tee-Object -FilePath $uiLogPath -Append | Out-Null
  $uiExit = 1
} finally {
  if($tempServer){ try { Stop-Process -Id $tempServer.Id -Force -ErrorAction SilentlyContinue } catch {} }
  Remove-Item Env:PROJECT200_HISTORICAL_STORE -ErrorAction SilentlyContinue
}
$finalExit = if($exit -eq 0 -and $uiExit -eq 0){0}else{1}
$summary=[ordered]@{dataset=$datasetName;pattern=$Pattern;seed=$Seed;data_path=$datasetDir;log_path=$logPath;events=$total;trading_days=$days;replay_exit_code=$exit;ui_smoke_exit_code=$uiExit;exit_code=$finalExit;ui_log_path=$uiLogPath;completed_at=(Get-Date).ToString("o")}
$summary | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 $reportPath

# A UI smoke failure must not pin the rotation on the failed pattern.
# Replay failure alone keeps the same pattern for retry; replay PASS + UI PASS advances normally.
$advanceRotation = ($uiExit -ne 0) -or ($finalExit -eq 0)
if($autoPattern -and $advanceRotation -and $null -ne $nextIndex -and $Pattern -eq $patterns[[int]$nextIndex]){
  $next = ([int]$nextIndex + 1) % $patterns.Count
  [ordered]@{next_index=$next;last_pattern=$Pattern;updated_at=(Get-Date).ToString("o")} |
    ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 $patternStatePath
}
exit $finalExit
