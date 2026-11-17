# run_s4_scalability_pwave.ps1 - Skenario S4B: Skalabilitas P-Wave Detector
param (
    [int]$DurationSec    = 300,
    [int]$Repeat         = 3,
    [switch]$Shuffle,
    [string]$ScenarioName = "All"
)

. "$PSScriptRoot\_common.ps1"

$PythonExe = "python"
$RootDir   = Split-Path -Parent $PSScriptRoot
Set-Location $RootDir

$BaseScenarios = @(
    @{ Name="Kafka2c";      File="docker-compose-s4-pwave-kafka-2c.yml";       OutMetrics="tests/results/s4_pwave_kafka_2c_metrics.csv"       },
    @{ Name="Kafka3c";      File="docker-compose-s4-pwave-kafka-3c.yml";       OutMetrics="tests/results/s4_pwave_kafka_3c_metrics.csv"       },
    @{ Name="Kafka4c";      File="docker-compose-s4-pwave-kafka-4c.yml";       OutMetrics="tests/results/s4_pwave_kafka_4c_metrics.csv"       },
    @{ Name="Kafka5c";      File="docker-compose-s4-pwave-kafka-5c.yml";       OutMetrics="tests/results/s4_pwave_kafka_5c_metrics.csv"       },
    @{ Name="KafkaNginx2c"; File="docker-compose-s4-pwave-kafka-nginx-2c.yml"; OutMetrics="tests/results/s4_pwave_kafka_nginx_2c_metrics.csv" },
    @{ Name="KafkaNginx3c"; File="docker-compose-s4-pwave-kafka-nginx-3c.yml"; OutMetrics="tests/results/s4_pwave_kafka_nginx_3c_metrics.csv" },
    @{ Name="KafkaNginx4c"; File="docker-compose-s4-pwave-kafka-nginx-4c.yml"; OutMetrics="tests/results/s4_pwave_kafka_nginx_4c_metrics.csv" },
    @{ Name="KafkaNginx5c"; File="docker-compose-s4-pwave-kafka-nginx-5c.yml"; OutMetrics="tests/results/s4_pwave_kafka_nginx_5c_metrics.csv" },
    @{ Name="KafkaNginx6c"; File="docker-compose-s4-pwave-kafka-nginx-6c.yml"; OutMetrics="tests/results/s4_pwave_kafka_nginx_6c_metrics.csv" }
)

if ($ScenarioName -ne "All") {
    $BaseScenarios = $BaseScenarios | Where-Object { $_.Name -eq $ScenarioName }
    if (-not $BaseScenarios) {
        Write-Host "Skenario '$ScenarioName' tidak ditemukan." -ForegroundColor Red; exit 1
    }
}

if ($Shuffle) { $BaseScenarios = $BaseScenarios | Get-Random -Count $BaseScenarios.Count }

$ArchiveDir = "tests/results_v1_arsip"

foreach ($s in $BaseScenarios) {
    for ($run = 1; $run -le $Repeat; $run++) {

        $runTag = "$($s.Name)_run${run}"
        Write-Host "============================================================" -ForegroundColor Cyan
        Write-Host "S4B P-Wave | $runTag" -ForegroundColor Cyan
        Write-Host "============================================================" -ForegroundColor Cyan

        $oldOut = $s.OutMetrics
        if (Test-Path $oldOut) {
            if (-not (Test-Path $ArchiveDir)) { New-Item -ItemType Directory -Path $ArchiveDir | Out-Null }
            $archiveName = $ArchiveDir + "/" + [System.IO.Path]::GetFileNameWithoutExtension($oldOut) + "_archived_$(Get-Date -Format 'yyyyMMdd_HHmmss').csv"
            Copy-Item $oldOut $archiveName -Force
        }

        docker compose -f $($s.File) down -v --remove-orphans 2>$null
        docker compose -f $($s.File) up -d --build --remove-orphans

        Wait-SystemReady -TimeoutSec 300

        Write-Host "Stabilisasi 60s..."
        Start-Sleep 60

        $outRun    = $s.OutMetrics -replace '\.csv$', "_run${run}.csv"
        $bucketOut = $outRun -replace '\.csv$', '_buckets.csv'
        $metaOut   = $outRun -replace '\.csv$', '_meta.json'
        Save-RunMetadata -OutputPath $metaOut -ComposeFile $s.File -ScenarioName $s.Name -RunIndex $run

        Write-Host "Mengumpulkan metrik S4B ($DurationSec s)..."
        & $PythonExe tests/collect_metrics.py `
            --scenario s4_pwave `
            --duration $DurationSec `
            --output $outRun `
            --dump-buckets

        Copy-Results -Files @($outRun, $bucketOut, $metaOut) -DestDir $ArchiveDir

        docker compose -f $($s.File) down -v --remove-orphans

        if ($run -lt $Repeat) { Start-Cooldown -Seconds 120 }
    }
}

Write-Host "S4B P-Wave selesai!" -ForegroundColor Green
