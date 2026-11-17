# run_s5_websocket.ps1 - Skenario S5: FastAPI vs Express.js WebSocket
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
    @{ Name="Express1c"; File="docker-compose-s5-express.yml"; TargetURI="ws://localhost:3333/socket.io/?EIO=4&transport=websocket"; Clients=1; OutMetrics="tests/results/s5_websocket_express_1c_metrics.csv" },
    @{ Name="Express5c"; File="docker-compose-s5-express.yml"; TargetURI="ws://localhost:3333/socket.io/?EIO=4&transport=websocket"; Clients=5; OutMetrics="tests/results/s5_websocket_express_5c_metrics.csv" },
    @{ Name="FastAPI1c"; File="docker-compose-s5-fastapi.yml"; TargetURI="ws://localhost:3334/ws";                                   Clients=1; OutMetrics="tests/results/s5_websocket_fastapi_1c_metrics.csv" },
    @{ Name="FastAPI5c"; File="docker-compose-s5-fastapi.yml"; TargetURI="ws://localhost:3334/ws";                                   Clients=5; OutMetrics="tests/results/s5_websocket_fastapi_5c_metrics.csv" }
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
        Write-Host "S5 | $runTag" -ForegroundColor Cyan
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

        # Load generator
        Write-Host "Memulai load generator WebSocket ($($s.Clients) klien)..."
        $procLoad = Start-Process -FilePath $PythonExe `
            -ArgumentList "tests/ws_load_generator.py --uri $($s.TargetURI) --clients $($s.Clients) --duration $DurationSec" `
            -PassThru -NoNewWindow

        Write-Host "Mengumpulkan metrik S5 ($DurationSec s)..."
        & $PythonExe tests/collect_metrics.py `
            --scenario s5 `
            --duration $DurationSec `
            --output $outRun `
            --dump-buckets

        # Tunggu load generator selesai
        Wait-Process -InputObject $procLoad -Timeout ($DurationSec + 30) -ErrorAction SilentlyContinue

        Copy-Results -Files @($outRun, $bucketOut, $metaOut) -DestDir $ArchiveDir

        docker compose -f $($s.File) down -v --remove-orphans

        if ($run -lt $Repeat) { Start-Cooldown -Seconds 120 }
    }
}

Write-Host "S5 selesai!" -ForegroundColor Green
