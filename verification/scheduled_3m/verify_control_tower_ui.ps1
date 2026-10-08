param()

$ErrorActionPreference = "Stop"
$base = "http://127.0.0.1:8080"
$health = Invoke-WebRequest -UseBasicParsing "$base/" -TimeoutSec 10
if($health.StatusCode -ne 200){ throw "CONTROL_TOWER_UI_HTTP_$($health.StatusCode)" }

$strategies = Invoke-RestMethod "$base/api/strategies"
$run = Invoke-RestMethod "$base/api/run"

$html = (New-Object System.Net.WebClient).DownloadString("$base/")
$app = (New-Object System.Net.WebClient).DownloadString("$base/app.js")
$requiredHtml = @('op-strategy-grid','op-strategy-count','op-account-detail')
foreach($marker in $requiredHtml){
  if($html -notmatch [regex]::Escape($marker)){ throw "UI_HTML_MARKER_MISSING:$marker" }
}
$requiredJs = @('MONTHLY TRADE P/L','STRATEGY INTEGRATED P/L','renderOptionProgram')
foreach($marker in $requiredJs){
  if($app -notmatch [regex]::Escape($marker)){ throw "UI_JS_MARKER_MISSING:$marker" }
}

$strategyList = if($strategies -is [array]) { @($strategies) } elseif($null -ne $strategies.strategies) { @($strategies.strategies) } else { @() }
if(@($strategyList).Count -lt 1){ throw "UI_STRATEGY_API_EMPTY" }

if($null -eq $run.run_id -or [string]::IsNullOrWhiteSpace([string]$run.run_id)){ throw "UI_RUN_READ_MODEL_MISSING_RUN_ID" }
if($null -eq $run.account -or $null -eq $run.pnl){ throw "UI_RUN_READ_MODEL_MISSING_ACCOUNT_PNL" }

Write-Output "UI_SMOKE=PASS"
Write-Output "UI_HTTP_STATUS=$($health.StatusCode)"
$strategyCount = @($strategyList | Where-Object { $null -ne $_ }).Count
Write-Output "UI_STRATEGY_COUNT=$strategyCount"
Write-Output "UI_RUN_ID=$($run.run_id)"
Write-Output "UI_RUN_STATE=$($run.runtime_state)"
Write-Output "UI_READ_MODEL_PNL=AVAILABLE"
exit 0
