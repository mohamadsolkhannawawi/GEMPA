param (
    [int]$DurationSec = 300,
    [string]$ScenarioName = "All"
)

$PythonExecutable = "python"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$RootDir = Split-Path -Parent $ScriptDir

Set-Location $RootDir

$Scenarios = @(
    @{ Name="Kafka2c"; File="docker-compose-s4-pwave-kafka-2c.yml"; OutStats="tests/results/s4_pwave_kafka_2c_stats.csv"; OutMetrics="tests/results/s4_pwave_kafka_2c_metrics.csv" },
    @{ Name="Kafka3c"; File="docker-compose-s4-pwave-kafka-3c.yml"; OutStats="tests/results/s4_pwave_kafka_3c_stats.csv"; OutMetrics="tests/results/s4_pwave_kafka_3c_metrics.csv" },
    @{ Name="Kafka4c"; File="docker-compose-s4-pwave-kafka-4c.yml"; OutStats="tests/results/s4_pwave_kafka_4c_stats.csv"; OutMetrics="tests/results/s4_pwave_kafka_4c_metrics.csv" },
    @{ Name="Kafka5c"; File="docker-compose-s4-pwave-kafka-5c.yml"; OutStats="tests/results/s4_pwave_kafka_5c_stats.csv"; OutMetrics="tests/results/s4_pwave_kafka_5c_metrics.csv" },
    @{ Name="KafkaNginx2c"; File="docker-compose-s4-pwave-kafka-nginx-2c.yml"; OutStats="tests/results/s4_pwave_kafka_nginx_2c_stats.csv"; OutMetrics="tests/results/s4_pwave_kafka_nginx_2c_metrics.csv" },
    @{ Name="KafkaNginx3c"; File="docker-compose-s4-pwave-kafka-nginx-3c.yml"; OutStats="tests/results/s4_pwave_kafka_nginx_3c_stats.csv"; OutMetrics="tests/results/s4_pwave_kafka_nginx_3c_metrics.csv" },
    @{ Name="KafkaNginx4c"; File="docker-compose-s4-pwave-kafka-nginx-4c.yml"; OutStats="tests/results/s4_pwave_kafka_nginx_4c_stats.csv"; OutMetrics="tests/results/s4_pwave_kafka_nginx_4c_metrics.csv" },
    @{ Name="KafkaNginx5c"; File="docker-compose-s4-pwave-kafka-nginx-5c.yml"; OutStats="tests/results/s4_pwave_kafka_nginx_5c_stats.csv"; OutMetrics="tests/results/s4_pwave_kafka_nginx_5c_metrics.csv" }
)

if ($ScenarioName -ne "All") {
    $Scenarios = $Scenarios | Where-Object { $_.Name -eq $ScenarioName }
    if ($Scenarios.Count -eq 0) {
        Write-Host "Scenario '$ScenarioName' not found. Available scenarios:" -ForegroundColor Red
        @("Kafka2c", "Kafka3c", "Kafka4c", "Kafka5c", "KafkaNginx2c", "KafkaNginx3c", "KafkaNginx4c", "KafkaNginx5c") | ForEach-Object { Write-Host " - $_" }
        exit 1
    }
}

foreach ($s in $Scenarios) {
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "Running S4 P-Wave Scenario: $($s.Name)" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    
    docker compose -f $($s.File) down -v --remove-orphans
    docker compose -f $($s.File) up -d --build --remove-orphans
    
    Write-Host "Waiting 60s for stabilization..."
    Start-Sleep -Seconds 60
    
    Write-Host "Collecting Docker Stats and Prometheus Metrics..."
    $proc2 = Start-Process -FilePath $PythonExecutable -ArgumentList "tests/collect_metrics.py --scenario s4_pwave --duration $DurationSec --output $($s.OutMetrics)" -PassThru -NoNewWindow
    Wait-Process -InputObject $proc2

    Write-Host "Tearing down $($s.Name)..."
docker compose -f $($s.File) down -v --remove-orphans
}

Write-Host "S4 P-Wave testing completed!" -ForegroundColor Green
