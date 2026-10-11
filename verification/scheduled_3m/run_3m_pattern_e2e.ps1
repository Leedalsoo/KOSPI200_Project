param(
  [int]$Seed = 0,
  [string]$Pattern = "auto"
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$run = Get-Date -Format "yyyyMMdd_HHmmss"
$outRoot = Join-Path $root "data\synthetic_market_data\scheduled_3m"
$verDir = Join-Path $root "verification\results\scheduled_3m"
New-Item -ItemType Directory -Force $outRoot,$verDir | Out-Null

# Capture the actual checked-out working tree used by this run. Dirty/untracked
# files are recorded, not rejected, so the scheduler validates the current worktree.
$stage = "INITIALIZATION"
$datasetName = $null
$datasetDir = $null
$reportPath = $null
$logPath = $null
$uiLogPath = $null
$gitBranch = ((& git -C $root branch --show-current 2>$null) | Select-Object -First 1)
$gitHead = ((& git -C $root rev-parse HEAD 2>$null) | Select-Object -First 1)
$gitStatusLines = @(& git -C $root status --porcelain 2>$null)
$gitRoot = ((& git -C $root rev-parse --show-toplevel 2>$null) | Select-Object -First 1)
$worktreeDirty = ($gitStatusLines.Count -gt 0)
$worktreeUntrackedCount = @($gitStatusLines | Where-Object { $_ -match '^\?\?' }).Count
$workspaceEvidence = [ordered]@{
  validation_basis = "CURRENT_WORKTREE"
  working_directory = $root
  git_root = [string]$gitRoot
  git_branch = [string]$gitBranch
  git_head = [string]$gitHead
  worktree_dirty = $worktreeDirty
  worktree_changed_files_count = $gitStatusLines.Count
  worktree_untracked_files_count = $worktreeUntrackedCount
  runner_script_path = $PSCommandPath
}
trap {
  $caughtError = $_
  $failedStage = [string]$stage
  $errorText = [string]$caughtError.Exception.Message
  if(-not [string]::IsNullOrWhiteSpace([string]$logPath)){
    try {
      if(Test-Path $logPath){ Add-Content -Encoding UTF8 -Path $logPath -Value ("RUNNER_STAGE_FAILURE stage={0} error={1}" -f $failedStage,$errorText) }
      else { Set-Content -Encoding UTF8 -Path $logPath -Value ("RUNNER_STAGE_FAILURE stage={0} error={1}" -f $failedStage,$errorText) }
    } catch {}
  }
  if(-not [string]::IsNullOrWhiteSpace([string]$reportPath)){
    try {
      $failureSummary = [ordered]@{
        dataset = $datasetName
        data_path = $datasetDir
        log_path = $logPath
        ui_log_path = $uiLogPath
        status = "BLOCKED_E2E_STAGE_FAILURE"
        failure_stage = $failedStage
        error = $errorText
        error_record = [string]$caughtError
        exit_code = 1
        completed_at = (Get-Date).ToString("o")
      }
      foreach($key in $workspaceEvidence.Keys){ $failureSummary[$key] = $workspaceEvidence[$key] }
      $failureSummary | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 $reportPath
    } catch {}
  }
  Write-Output ("BLOCKED_E2E_STAGE_FAILURE stage={0} error={1}" -f $failedStage,$errorText)
  exit 1
}
$gitRootFull = [System.IO.Path]::GetFullPath([string]$gitRoot).Replace('/','\').TrimEnd('\')
$scriptRootFull = [System.IO.Path]::GetFullPath($root).Replace('/','\').TrimEnd('\')
if([string]::IsNullOrWhiteSpace([string]$gitRoot) -or $gitRootFull -ine $scriptRootFull){
  throw "CURRENT_WORKTREE_ROOT_INVALID script_root=$root git_root=$gitRoot"
}

if($Seed -eq 0){ $Seed = [int](Get-Date -Format "HHmmss") }
$patterns = @("trend_up","trend_down","mean_revert","high_volatility","low_volatility","shock")
$patternStatePath = Join-Path $verDir "pattern_rotation_state.json"
$autoPattern = ($Pattern -eq "auto")
if($autoPattern){
  # Runs are serialized by Task Scheduler. Persist the rotation index independently
  # of wall-clock start time so queued executions continue the six-pattern cycle.
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

$stage = "DATASET_INITIALIZATION"
$datasetName = "synthetic-3m-5min-$Pattern-$run"
$datasetDir = Join-Path $outRoot $datasetName
$reportPath = Join-Path $verDir "$datasetName.json"
$logPath = Join-Path $verDir "$datasetName.log"
$generationLogPath = Join-Path $verDir "$datasetName.generation.log"
$uiLogPath = Join-Path $verDir "$datasetName.ui_smoke.log"
New-Item -ItemType Directory -Force $datasetDir | Out-Null
Set-Location $root
$stage = "DATASET_GENERATION"
& py -m scripts.generate_authoritative_option_synthetic_3m --output $datasetDir --pattern $Pattern --seed $Seed 2>&1 | Tee-Object -FilePath $generationLogPath
$generationExit = $LASTEXITCODE
if($generationExit -ne 0){
  $summary=[ordered]@{dataset=$datasetName;pattern=$Pattern;seed=$Seed;data_path=$datasetDir;generation_log_path=$generationLogPath;generation_exit_code=$generationExit;replay_exit_code=$null;ui_smoke_exit_code=$null;exit_code=1;status="BLOCKED_DATA_GENERATION";completed_at=(Get-Date).ToString("o")}
  foreach($key in $workspaceEvidence.Keys){ $summary[$key] = $workspaceEvidence[$key] }
  $summary | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 $reportPath
  exit 1
}
$manifest = Get-Content (Join-Path $datasetDir "manifest.json") -Raw | ConvertFrom-Json
$total = [int]$manifest.events
$days = [int]$manifest.trading_days
$validationLogPath = Join-Path $verDir "$datasetName.dataset_validation.log"
$stage = "DATASET_VALIDATION"
& py -m scripts.validate_authoritative_option_synthetic_3m --dataset $datasetDir 2>&1 | Tee-Object -FilePath $validationLogPath
$datasetValidationExit = $LASTEXITCODE
if($datasetValidationExit -ne 0){
  $summary=[ordered]@{dataset=$datasetName;pattern=$Pattern;seed=$Seed;data_path=$datasetDir;generation_log_path=$generationLogPath;dataset_validation_log_path=$validationLogPath;generation_exit_code=0;dataset_validation_exit_code=$datasetValidationExit;replay_exit_code=$null;ui_smoke_exit_code=$null;exit_code=1;status="BLOCKED_DATASET_VALIDATION";events=$total;trading_days=$days;completed_at=(Get-Date).ToString("o")}
  foreach($key in $workspaceEvidence.Keys){ $summary[$key] = $workspaceEvidence[$key] }
  $summary | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 $reportPath
  exit 1
}
$stage = "MANIFEST_GUARD"
if($total -le 0 -or $days -le 0 -or $manifest.rules_version -ne "project200-synthetic-3m-v3" -or @($manifest.monthly_rollovers).Count -lt 3 -or $null -eq $manifest.strategy_lifecycle.strategy6_daily_tail_insurance -or $null -eq $manifest.strategy_lifecycle.strategy7_weekly_volatility_skew_insurance -or $null -eq $manifest.strategy_lifecycle.strategy8_monthly_macro_strangle -or $null -eq $manifest.initial_underlying_spot -or [double]$manifest.initial_underlying_spot -le 0 -or [string]::IsNullOrWhiteSpace([string]$manifest.underlying_spot_source_path)){
  throw "AUTHORITATIVE_MONTHLY_EXPIRY_DATASET_INVALID events=$total days=$days rules=$($manifest.rules_version) rollovers=$(@($manifest.monthly_rollovers).Count) initial_spot=$($manifest.initial_underlying_spot) spot_source=$($manifest.underlying_spot_source_path)"
}

# Build one canonical observations stream from the exact generated daily files.
# Control Tower consumes a single historical_store_path; this keeps the UI source
# byte-for-byte derived from the same scheduled dataset used by High-Speed Replay.
$stage = "CONTROL_TOWER_STORE_BUILD"
$controlTowerStore = Join-Path $datasetDir 'control_tower_replay.jsonl'
$writer = [System.IO.StreamWriter]::new($controlTowerStore, $false, [System.Text.UTF8Encoding]::new($false))
try {
  foreach($dailyFile in (Get-ChildItem $datasetDir -Filter "????-??-??.jsonl" | Sort-Object Name)){
    foreach($line in [System.IO.File]::ReadLines($dailyFile.FullName)){
      if(-not [string]::IsNullOrWhiteSpace($line)){ $writer.WriteLine($line) }
    }
  }
} finally { $writer.Dispose() }
$controlTowerEventCount = [int]([System.IO.File]::ReadLines($controlTowerStore) | Measure-Object).Count
if($controlTowerEventCount -ne $total){ throw "CONTROL_TOWER_STORE_SHAPE_INVALID events=$controlTowerEventCount expected=$total" }

Set-Location $root
$stage = "HIGH_SPEED_REPLAY"
& py -m environments.high_speed.virtual_runtime_replay --dataset $datasetDir 2>&1 | Tee-Object -FilePath $logPath
$exit=$LASTEXITCODE

# UI smoke is always attempted, including when replay fails.
# The UI check is bound to the SAME generated dataset through a temporary Control Tower
# instance. This prevents an unrelated pre-existing server/run from producing a false PASS.
$stage = "UI_SMOKE"
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
$stage = "FINAL_SUMMARY"
$finalExit = if($exit -eq 0 -and $uiExit -eq 0){0}else{1}
$summary=[ordered]@{dataset=$datasetName;pattern=$Pattern;seed=$Seed;data_path=$datasetDir;generation_log_path=$generationLogPath;dataset_validation_log_path=$validationLogPath;dataset_validation_exit_code=$datasetValidationExit;rules_version=$manifest.rules_version;dataset_validation_status="PASS_WITH_LIMITATION";market_rule_limitations=$manifest.market_rule_limitations;option_master_sha256=$manifest.option_master_sha256;initial_underlying_spot=$manifest.initial_underlying_spot;underlying_spot_source_path=$manifest.underlying_spot_source_path;underlying_spot_source_code=$manifest.underlying_spot_source_code;underlying_spot_source_field=$manifest.underlying_spot_source_field;monthly_rollovers=$manifest.monthly_rollovers;weekly_rollovers=$manifest.weekly_rollovers;strategy_lifecycle=$manifest.strategy_lifecycle;date_start=$manifest.date_start;date_end=$manifest.date_end;date_end_exclusive=$manifest.date_end_exclusive;timezone=$manifest.timezone;contract_multiplier=$manifest.contract_multiplier;pricing_assumptions=$manifest.pricing_assumptions;option_tick_sizes=$manifest.option_tick_sizes;log_path=$logPath;events=$total;trading_days=$days;replay_exit_code=$exit;ui_smoke_exit_code=$uiExit;exit_code=$finalExit;status=if($finalExit -eq 0){"PASS"}else{"FAIL"};ui_log_path=$uiLogPath;completed_at=(Get-Date).ToString("o")}
foreach($key in $workspaceEvidence.Keys){ $summary[$key] = $workspaceEvidence[$key] }
  $summary | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 $reportPath

# A UI smoke failure must not pin the rotation on the failed pattern.
# Replay failure alone keeps the same pattern for retry; replay PASS + UI PASS advances normally.
$advanceRotation = ($uiExit -ne 0) -or ($finalExit -eq 0)
if($autoPattern -and $advanceRotation -and $null -ne $nextIndex -and $Pattern -eq $patterns[[int]$nextIndex]){
  $next = ([int]$nextIndex + 1) % $patterns.Count
  [ordered]@{next_index=$next;last_pattern=$Pattern;updated_at=(Get-Date).ToString("o")} |
    ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 $patternStatePath
}
exit $finalExit
