# run_s3_broker.ps1 - Skenario S3: Kafka Native vs Kafka + NGINX
param (
    [int]$DurationSec    = 300,
    [int]$Repeat         = 1,
    [switch]$Shuffle,
    [string]$ScenarioName = "All"
)

. "$PSScriptRoot\_common.ps1"

$RootDir   = Split-Path -Parent $PSScriptRoot
Set-Location $RootDir

$BaseScenarios = @(
    @{ Name="Kafka"; File="docker-compose-s3-kafka.yml"; OutMetrics="tests/results/s3_broker_kafka_metrics.csv" },
    @{ Name="NGINX"; File="docker-compose-s3-nginx.yml"; OutMetrics="tests/results/s3_broker_nginx_metrics.csv" }
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
        Write-Host "S3 | $runTag" -ForegroundColor Cyan
        Write-Host "============================================================" -ForegroundColor Cyan

        $oldOut = $s.OutMetrics
        if (Test-Path $oldOut) {
            if (-not (Test-Path $ArchiveDir)) { New-Item -ItemType Directory -Path $ArchiveDir | Out-Null }
            $archiveName = $ArchiveDir + "/" + [System.IO.Path]::GetFileNameWithoutExtension($oldOut) + "_archived_$(Get-Date -Format 'yyyyMMdd_HHmmss').csv"
            Copy-Item $oldOut $archiveName -Force
        }

        docker compose -f $($s.File) down -v --remove-orphans 2>$null
        docker compose -f $($s.File) up -d --build --remove-orphans

        Wait-SystemReady -TimeoutSec 300 -RelaxDpRate | Out-Null

        Write-Host "Stabilisasi 60s..."
        Start-Sleep 60

        $outRun    = $s.OutMetrics -replace '\.csv$', "_run${run}.csv"
        $bucketOut = $outRun -replace '\.csv$', '_buckets.csv'
        $metaOut   = $outRun -replace '\.csv$', '_meta.json'
        Save-RunMetadata -OutputPath $metaOut -ComposeFile $s.File -ScenarioName $s.Name -RunIndex $run

        Write-Host "Mengumpulkan metrik S3 ($DurationSec s)..."
        & $PythonExe tests/collect_metrics.py `
            --scenario s3 `
            --duration $DurationSec `
            --output $outRun `
            --dump-buckets

        Copy-Results -Files @($outRun, $bucketOut, $metaOut) -DestDir $ArchiveDir

        docker compose -f $($s.File) down -v --remove-orphans

        if ($run -lt $Repeat) { Start-Cooldown -Seconds 120 }
    }
}

Write-Host "S3 selesai!" -ForegroundColor Green
