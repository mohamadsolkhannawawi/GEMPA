# _common.ps1 — Fungsi-fungsi bersama untuk seluruh skrip pengujian EEWS.
# Disertakan (dot-source) oleh run_s*.ps1.

# ==============================================================================
# Gerbang kesiapan: tunggu hingga semua target Prometheus UP dan Data Provider
# sudah mengirim minimal 1 trace ke Kafka.
# ==============================================================================
function Wait-SystemReady {
    param(
        [string]$PrometheusUrl = "http://localhost:9090",
        [int]$TimeoutSec = 300,
        [int]$PollSec = 5
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    Write-Host "Menunggu sistem siap (timeout ${TimeoutSec}s)..." -ForegroundColor Yellow

    while ((Get-Date) -lt $deadline) {
        # 1. Periksa apakah Prometheus merespons
        try {
            $r = Invoke-RestMethod "$PrometheusUrl/api/v1/query?query=up" -TimeoutSec 5 -ErrorAction Stop
            $upTargets = ($r.data.result | Where-Object { $_.value[1] -eq "1" }).Count
        } catch {
            $upTargets = 0
        }

        # 2. Periksa apakah Data Provider sudah mengirim trace
        try {
            $r2 = Invoke-RestMethod "$PrometheusUrl/api/v1/query?query=sum(rate(data_provider_traces_sent_total%5B30s%5D))" -TimeoutSec 5 -ErrorAction Stop
            $dpRate = [double]($r2.data.result[0].value[1])
        } catch {
            $dpRate = 0.0
        }

        if ($upTargets -gt 0 -and $dpRate -gt 0) {
            Write-Host "Sistem siap: $upTargets target UP, laju Data Provider = $([math]::Round($dpRate,2)) trace/s" -ForegroundColor Green
            return $true
        }

        Write-Host "  Menunggu... UP=$upTargets, dp_rate=$([math]::Round($dpRate,3))"
        Start-Sleep $PollSec
    }

    Write-Host "[PERINGATAN] Gerbang kesiapan timeout setelah ${TimeoutSec}s. Melanjutkan..." -ForegroundColor Red
    return $false
}


# ==============================================================================
# Simpan metadata run (JSON)
# ==============================================================================
function Save-RunMetadata {
    param(
        [string]$OutputPath,
        [string]$ComposeFile,
        [string]$ScenarioName,
        [int]$RunIndex
    )

    $gitHash = ""
    try { $gitHash = (git rev-parse --short HEAD 2>$null) } catch {}

    $composeHash = ""
    try { $composeHash = (Get-FileHash $ComposeFile -Algorithm SHA256).Hash.Substring(0,12) } catch {}

    $envHash = ""
    try { $envHash = (Get-FileHash ".env" -Algorithm SHA256).Hash.Substring(0,12) } catch {}

    $kafkaTopics = ""
    try {
        $kafkaTopics = (docker exec gempa-kafka1-1 kafka-topics.sh --bootstrap-server localhost:9092 --describe 2>$null) -join "`n"
    } catch {}

    $meta = @{
        timestamp     = (Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ")
        scenario      = $ScenarioName
        run_index     = $RunIndex
        git_commit    = $gitHash
        compose_file  = $ComposeFile
        compose_hash  = $composeHash
        env_hash      = $envHash
        kafka_describe = $kafkaTopics
    }

    $meta | ConvertTo-Json -Depth 5 | Set-Content -Path $OutputPath -Encoding UTF8
    Write-Host "Metadata run disimpan ke $OutputPath"
}


# ==============================================================================
# Salin semua hasil sebelum `down -v`
# ==============================================================================
function Copy-Results {
    param(
        [string[]]$Files,
        [string]$DestDir
    )
    if (-not (Test-Path $DestDir)) {
        New-Item -ItemType Directory -Path $DestDir | Out-Null
    }
    foreach ($f in $Files) {
        if (Test-Path $f) {
            Copy-Item $f $DestDir -Force
        }
    }
}


# ==============================================================================
# Jeda pendinginan antar run
# ==============================================================================
function Start-Cooldown {
    param([int]$Seconds = 120)
    Write-Host "Jeda pendinginan ${Seconds}s antara run..." -ForegroundColor DarkCyan
    Start-Sleep $Seconds
}
