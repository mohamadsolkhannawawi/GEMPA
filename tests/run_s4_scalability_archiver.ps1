param (
    [int]$DurationSec = 300,
    [string]$ScenarioName = "All"
)

$PythonExecutable = "python"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$RootDir = Split-Path -Parent $ScriptDir

Set-Location $RootDir

$Scenarios = @(
    @{ Name="1c"; File="docker-compose-s4-archiver-1c.yml"; OutStats="tests/results/s4_archiver_1_container_stats.csv"; OutMetrics="tests/results/s4_archiver_1_container_metrics.csv" },
    @{ Name="2c"; File="docker-compose-s4-archiver-2c.yml"; OutStats="tests/results/s4_archiver_2_container_stats.csv"; OutMetrics="tests/results/s4_archiver_2_container_metrics.csv" },
    @{ Name="3c"; File="docker-compose-s4-archiver-3c.yml"; OutStats="tests/results/s4_archiver_3_container_stats.csv"; OutMetrics="tests/results/s4_archiver_3_container_metrics.csv" },
    @{ Name="4c"; File="docker-compose-s4-archiver-4c.yml"; OutStats="tests/results/s4_archiver_4_container_stats.csv"; OutMetrics="tests/results/s4_archiver_4_container_metrics.csv" },
    @{ Name="5c"; File="docker-compose-s4-archiver-5c.yml"; OutStats="tests/results/s4_archiver_5_container_stats.csv"; OutMetrics="tests/results/s4_archiver_5_container_metrics.csv" }
)

if ($ScenarioName -ne "All") {
    $Scenarios = $Scenarios | Where-Object { $_.Name -eq $ScenarioName }
    if ($Scenarios.Count -eq 0) {
        Write-Host "Scenario '$ScenarioName' not found. Available scenarios:" -ForegroundColor Red
        @("1c", "2c", "3c", "4c", "5c") | ForEach-Object { Write-Host " - $_" }
        exit 1
    }
}

foreach ($s in $Scenarios) {
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "Running S4 Archiver Scenario: $($s.Name)" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    
    docker compose -f $($s.File) down -v --remove-orphans
    docker compose -f $($s.File) up -d --build --remove-orphans
    
    Write-Host "Waiting 60s for stabilization..."
    Start-Sleep -Seconds 60
    
    Write-Host "Collecting Docker Stats and Prometheus Metrics..."
    $proc2 = Start-Process -FilePath $PythonExecutable -ArgumentList "tests/collect_metrics.py --scenario s4_archiver --duration $DurationSec --output $($s.OutMetrics)" -PassThru -NoNewWindow
    Wait-Process -InputObject $proc2

    Write-Host "Tearing down $($s.Name)..."
docker compose -f $($s.File) down -v --remove-orphans
}

Write-Host "S4 Archiver testing completed!" -ForegroundColor Green
