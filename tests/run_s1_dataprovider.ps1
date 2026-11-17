# run_s1_dataprovider.ps1 - Skenario S1: Strategi Concurrency Data Provider
# Protokol: gerbang kesiapan aktif, 60s stabilisasi, 300s pengukuran,
#            3 pengulangan per konfigurasi, urutan diacak, jeda 120s antar run.
param (
    [int]$DurationSec    = 300,
    [int]$Repeat         = 3,
    [switch]$Shuffle,
    [string]$ScenarioName = "All"
)

. "$PSScriptRoot\_common.ps1"

$RootDir   = Split-Path -Parent $PSScriptRoot
Set-Location $RootDir

$BaseScenarios = @(
    @{ Name="Sequential";   File="docker-compose-s1-sequential.yml";   OutMetrics="tests/results/s1_sequential_metrics.csv"   },
    @{ Name="Multiprocess"; File="docker-compose-s1-multiprocess.yml"; OutMetrics="tests/results/s1_multiprocess_metrics.csv" },
    @{ Name="Multithread";  File="docker-compose-s1-multithread.yml";  OutMetrics="tests/results/s1_multithread_metrics.csv"  },
    @{ Name="Hibrida";      File="docker-compose-s1-hibrida.yml";      OutMetrics="tests/results/s1_hibrida_metrics.csv"      }
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
        Write-Host "S1 | $runTag" -ForegroundColor Cyan
        Write-Host "============================================================" -ForegroundColor Cyan

        # Arsipkan hasil lama bila ada
        $oldOut = $s.OutMetrics
        if (Test-Path $oldOut) {
            if (-not (Test-Path $ArchiveDir)) { New-Item -ItemType Directory -Path $ArchiveDir | Out-Null }
            $archiveName = $ArchiveDir + "/" + [System.IO.Path]::GetFileNameWithoutExtension($oldOut) + "_archived_$(Get-Date -Format 'yyyyMMdd_HHmmss').csv"
            Copy-Item $oldOut $archiveName -Force
        }

        docker compose -f $($s.File) down -v --remove-orphans 2>$null
        docker compose -f $($s.File) up -d --build --remove-orphans

        # Gerbang kesiapan
        Wait-SystemReady -TimeoutSec 300

        Write-Host "Stabilisasi 60s..."
        Start-Sleep 60

        $outRun = $s.OutMetrics -replace '\.csv$', "_run${run}.csv"
        $bucketOut = $outRun -replace '\.csv$', '_buckets.csv'
        $metaOut   = $outRun -replace '\.csv$', '_meta.json'

        Save-RunMetadata -OutputPath $metaOut -ComposeFile $s.File -ScenarioName $s.Name -RunIndex $run

        Write-Host "Mengumpulkan metrik ($DurationSec s)..."
        & $PythonExe tests/collect_metrics.py `
            --scenario s1 `
            --duration $DurationSec `
            --output $outRun `
            --dump-buckets

        # Salin hasil sebelum down
        Copy-Results -Files @($outRun, $bucketOut, $metaOut) -DestDir $ArchiveDir

        docker compose -f $($s.File) down -v --remove-orphans

        if ($run -lt $Repeat) { Start-Cooldown -Seconds 120 }
    }
}

Write-Host "S1 selesai!" -ForegroundColor Green
