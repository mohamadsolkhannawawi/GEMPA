# run_s2_overhead.ps1 - Skenario S2: Overhead Instrumentasi Prometheus
# Ketiga kondisi diukur dengan Telegraf (/metrics di :9273) sebagai alat ukur
# yang seragam. Throughput diukur dari offset Kafka via collect_kafka_offsets.py.
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
    @{ Name="NoMetricsCLI"; File="docker-compose-s2-no_metrics.yml"; OutMetrics="tests/results/s2_overhead_no_metrics_cli_metrics.csv"  },
    @{ Name="NoMetricsAPI"; File="docker-compose-s2-no_metrics.yml"; OutMetrics="tests/results/s2_overhead_no_metrics_api_metrics.csv"  },
    @{ Name="WithMetrics";  File="docker-compose-s2-with_metrics.yml"; OutMetrics="tests/results/s2_overhead_with_metrics_metrics.csv" }
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
        Write-Host "S2 | $runTag" -ForegroundColor Cyan
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

        Write-Host "Stabilisasi 120s (TensorFlow warm-up)..."
        Start-Sleep 120

        $outRun  = $s.OutMetrics -replace '\.csv$', "_run${run}.csv"
        $metaOut = $outRun -replace '\.csv$', '_meta.json'
        Save-RunMetadata -OutputPath $metaOut -ComposeFile $s.File -ScenarioName $s.Name -RunIndex $run

        Write-Host "Mengumpulkan metrik S2 ($DurationSec s) - kondisi: $($s.Name)..."

        if ($s.Name -eq "NoMetricsCLI") {
            & $PythonExe tests/collect_docker_stats_cli.py --duration $DurationSec --output $outRun
        } elseif ($s.Name -eq "NoMetricsAPI") {
            & $PythonExe tests/collect_docker_stats_api.py --duration $DurationSec --output $outRun
        } else {
            # WithMetrics: jalankan Prometheus collector + Docker API collector
            # secara paralel agar CPU/RAM bisa dibandingkan apple-to-apple
            # dengan kondisi NoMetrics
            $dockerOut = $outRun -replace '\.csv$', '_docker_api.csv'
            $procDocker = Start-Process -FilePath $PythonExe `
                -ArgumentList "tests/collect_docker_stats_api.py --duration $DurationSec --output $dockerOut" `
                -PassThru -NoNewWindow

            & $PythonExe tests/collect_metrics.py `
                --scenario s2 `
                --duration $DurationSec `
                --output $outRun `
                --dump-buckets

            Wait-Process -InputObject $procDocker -Timeout ($DurationSec + 30) -ErrorAction SilentlyContinue
            Write-Host "Data Docker API (pembanding native) disimpan ke $dockerOut"
        }

        $kafkaOut  = $outRun -replace '\.csv$', '_kafka_offsets.csv'
        $dockerOut = $outRun -replace '\.csv$', '_docker_api.csv'

        Copy-Results -Files @($outRun, $kafkaOut, $metaOut, $dockerOut) -DestDir $ArchiveDir

        docker compose -f $($s.File) down -v --remove-orphans

        if ($run -lt $Repeat) { Start-Cooldown -Seconds 120 }
    }
}

Write-Host "S2 selesai!" -ForegroundColor Green
