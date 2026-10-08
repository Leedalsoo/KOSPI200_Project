param(
  [int]$Port = 8080,
  [string]$ExpectedHistoricalStorePath = "",
  [string]$ExpectedDatasetName = ""
)
$ErrorActionPreference = "Stop"
$base = "http://127.0.0.1:$Port"
$health = Invoke-WebRequest -UseBasicParsing "$base/" -TimeoutSec 10
if($health.StatusCode -ne 200){ throw "CONTROL_TOWER_UI_HTTP_$($health.StatusCode)" }
$strategies = Invoke-RestMethod "$base/api/strategies"
if($ExpectedHistoricalStorePath){
  $createPayload = @{ run_id = "SCHEDULED-UI-$([guid]::NewGuid().ToString('N'))"; environment = "virtual"; historical_store_path = [IO.Path]::GetFullPath($ExpectedHistoricalStorePath); strategy_keys = @() } | ConvertTo-Json -Depth 5
  $created = Invoke-RestMethod "$base/api/run" -Method Post -ContentType "application/json" -Body $createPayload
  if($created.success -ne $true){ throw "UI_RUN_CREATE_FAILED" }
}
$run = Invoke-RestMethod "$base/api/run"
$html = (New-Object System.Net.WebClient).DownloadString("$base/")
$app = (New-Object System.Net.WebClient).DownloadString("$base/app.js")
foreach($marker in @('op-strategy-grid','op-strategy-count','op-account-detail')){ if($html -notmatch [regex]::Escape($marker)){ throw "UI_HTML_MARKER_MISSING:$marker" } }
foreach($marker in @('MONTHLY TRADE P/L','STRATEGY INTEGRATED P/L','renderOptionProgram')){ if($app -notmatch [regex]::Escape($marker)){ throw "UI_JS_MARKER_MISSING:$marker" } }
$strategyList = if($strategies -is [array]) { @($strategies) } elseif($null -ne $strategies.strategies) { @($strategies.strategies) } else { @() }
if(@($strategyList).Count -lt 1){ throw "UI_STRATEGY_API_EMPTY" }
if($null -eq $run.run_id -or [string]::IsNullOrWhiteSpace([string]$run.run_id)){ throw "UI_RUN_READ_MODEL_MISSING_RUN_ID" }
if($ExpectedHistoricalStorePath){
  $actual = [string]$run.historical_store_path
  if([string]::IsNullOrWhiteSpace($actual)){ throw "UI_RUN_READ_MODEL_MISSING_HISTORICAL_STORE_PATH" }
  if([IO.Path]::GetFullPath($actual) -ne [IO.Path]::GetFullPath($ExpectedHistoricalStorePath)){ throw "UI_HISTORICAL_STORE_MISMATCH:expected=$ExpectedHistoricalStorePath actual=$actual" }
  $actualDataset = Split-Path -Leaf (Split-Path -Parent $ExpectedHistoricalStorePath)
  if($ExpectedDatasetName -and $actualDataset -ne $ExpectedDatasetName){ throw "UI_DATASET_NAME_MISMATCH:expected=$ExpectedDatasetName actual=$actualDataset" }
  $replayed = Invoke-RestMethod "$base/api/run/action" -Method Post -ContentType "application/json" -Body (@{action="REPLAY"} | ConvertTo-Json)
  if($null -eq $replayed.run.replay_tick){ throw "UI_REPLAY_TICK_NOT_OBSERVED" }
  Write-Output "UI_REPLAY_TICK=OBSERVED"
}
if($null -eq $run.account -or $null -eq $run.pnl){ throw "UI_RUN_READ_MODEL_MISSING_ACCOUNT_PNL" }
Write-Output "UI_SMOKE=PASS"
Write-Output "UI_HTTP_STATUS=$($health.StatusCode)"
Write-Output "UI_STRATEGY_COUNT=$(@($strategyList).Count)"
Write-Output "UI_RUN_ID=$($run.run_id)"
Write-Output "UI_RUN_STATE=$($run.runtime_state)"
Write-Output "UI_HISTORICAL_STORE=$($run.historical_store_path)"
Write-Output "UI_READ_MODEL_PNL=AVAILABLE"
exit 0
