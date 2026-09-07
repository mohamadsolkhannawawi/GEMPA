param (
    [int]$DurationSec = 300,
    [string]$ScenarioName = "All"
)

$PythonExecutable = "python"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$RootDir = Split-Path -Parent $ScriptDir

Set-Location $RootDir

$Scenarios = @(
    @{ Name="Express1c"; File="docker-compose-s5-express.yml"; TargetURI="ws://localhost:3333/socket.io/?EIO=4&transport=websocket"; Clients=1; OutStats="tests/results/s5_websocket_express_1c_stats.csv"; OutMetrics="tests/results/s5_websocket_express_1c_metrics.csv" },
    @{ Name="Express5c"; File="docker-compose-s5-express.yml"; TargetURI="ws://localhost:3333/socket.io/?EIO=4&transport=websocket"; Clients=5; OutStats="tests/results/s5_websocket_express_5c_stats.csv"; OutMetrics="tests/results/s5_websocket_express_5c_metrics.csv" },
    @{ Name="FastAPI1c"; File="docker-compose-s5-fastapi.yml"; TargetURI="ws://localhost:3334/ws"; Clients=1; OutStats="tests/results/s5_websocket_fastapi_1c_stats.csv"; OutMetrics="tests/results/s5_websocket_fastapi_1c_metrics.csv" },
    @{ Name="FastAPI5c"; File="docker-compose-s5-fastapi.yml"; TargetURI="ws://localhost:3334/ws"; Clients=5; OutStats="tests/results/s5_websocket_fastapi_5c_stats.csv"; OutMetrics="tests/results/s5_websocket_fastapi_5c_metrics.csv" }
)

if ($ScenarioName -ne "All") {
    $Scenarios = $Scenarios | Where-Object { $_.Name -eq $ScenarioName }
    if ($Scenarios.Count -eq 0) {
        Write-Host "Scenario '$ScenarioName' not found. Available scenarios:" -ForegroundColor Red
        @("Express1c", "Express5c", "FastAPI1c", "FastAPI5c") | ForEach-Object { Write-Host " - $_" }
        exit 1
    }
}

foreach ($s in $Scenarios) {
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "Running S5 WebSocket Scenario: $($s.Name)" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    
    docker compose -f $($s.File) down -v --remove-orphans
    docker compose -f $($s.File) up -d --build --remove-orphans
    
    Write-Host "Waiting 60s for stabilization..."
    Start-Sleep -Seconds 60
    
    Write-Host "Starting WebSocket Load Generator ($($s.Clients) clients) to $($s.TargetURI)..."
    $procLoad = Start-Process -FilePath $PythonExecutable -ArgumentList "tests/ws_load_generator.py --uri $($s.TargetURI) --clients $($s.Clients) --duration $DurationSec" -PassThru -NoNewWindow
    
    Write-Host "Collecting Docker Stats and Prometheus Metrics..."
    $proc2 = Start-Process -FilePath $PythonExecutable -ArgumentList "tests/collect_metrics.py --scenario s5 --duration $DurationSec --output $($s.OutMetrics)" -PassThru -NoNewWindow
    
    Wait-Process -InputObject $procLoad
    Wait-Process -InputObject $proc2

    Write-Host "Tearing down $($s.Name)..."
    docker compose -f $($s.File) down -v --remove-orphans
}

Write-Host "S5 WebSocket testing completed!" -ForegroundColor Green
