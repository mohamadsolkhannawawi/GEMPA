# _common.ps1 - Fungsi-fungsi bersama untuk seluruh skrip pengujian EEWS.
# Disertakan (dot-source) oleh run_s*.ps1.

# ==============================================================================
# Resolve Python executable yang memiliki semua dependensi yang dibutuhkan.
# ==============================================================================
function Resolve-PythonExe {
    $candidates = @(
        "C:\Users\user\miniconda3\python.exe",
        "C:\Users\HP\AppData\Local\Programs\Python\Python312\python.exe",
        "python3",
        "python"
    )
    $required = @("kafka", "requests", "numpy")

    foreach ($candidate in $candidates) {
        try {
            $exePath = (Get-Command $candidate -ErrorAction Stop).Source
        } catch {
            if (-not (Test-Path $candidate)) { continue }
            $exePath = $candidate
        }

        $missing = @()
        foreach ($mod in $required) {
            $check = & $exePath -c "import $mod" 2>&1
            if ($LASTEXITCODE -ne 0) { $missing += $mod }
        }

        if ($missing.Count -eq 0) {
            Write-Host "Python OK: $exePath" -ForegroundColor DarkGray
            return $exePath
        }
    }

    Write-Host "[ERROR] Tidak ada Python dengan modul lengkap (kafka, requests, numpy)." -ForegroundColor Red
    Write-Host "        Jalankan: pip install kafka-python-ng requests numpy docker websockets" -ForegroundColor Red
    exit 1
}

$PythonExe = Resolve-PythonExe

# ==============================================================================
# Gerbang kesiapan sistem.
# - Mode Prometheus : tunggu target UP dan data_provider rate > 0.
# - Mode NoMetrics  : dua lapis —
#     Lapis 1: container p_wave_detector dan data_provider harus Running.
#     Lapis 2: offset trace_topic > 0 (data sudah mengalir).
#   Jika setelah 2/3 timeout offset masih 0 tapi container sudah UP, lanjut
#   saja — data_provider butuh waktu ekstra untuk connect ke SeedLink eksternal.
# ==============================================================================
function Wait-SystemReady {
    param(
        [string]$PrometheusUrl = "http://localhost:9090",
        [int]$TimeoutSec = 300,
        [int]$PollSec = 5
    )

    $startTime = Get-Date
    $deadline  = $startTime.AddSeconds($TimeoutSec)
    Write-Host "Menunggu sistem siap (timeout ${TimeoutSec}s)..." -ForegroundColor Yellow

    # Deteksi apakah Prometheus tersedia
    $prometheusAvailable = $false
    try {
        $null = Invoke-RestMethod "$PrometheusUrl/-/ready" -TimeoutSec 5 -ErrorAction Stop
        $prometheusAvailable = $true
    } catch {}

    while ((Get-Date) -lt $deadline) {

        if ($prometheusAvailable) {
            # --- Mode Prometheus ---
            try {
                $r = Invoke-RestMethod "$PrometheusUrl/api/v1/query?query=up" -TimeoutSec 5 -ErrorAction Stop
                $upTargets = ($r.data.result | Where-Object { $_.value[1] -eq "1" }).Count
            } catch { $upTargets = 0 }

            try {
                $r2 = Invoke-RestMethod "$PrometheusUrl/api/v1/query?query=sum(rate(data_provider_traces_sent_total%5B30s%5D))" -TimeoutSec 5 -ErrorAction Stop
                $dpRate = [double]($r2.data.result[0].value[1])
            } catch { $dpRate = 0.0 }

            if ($upTargets -gt 0 -and $dpRate -gt 0) {
                Write-Host "Sistem siap: $upTargets target UP, dp_rate=$([math]::Round($dpRate,2)) trace/s" -ForegroundColor Green
                return $true
            }
            Write-Host "  Menunggu... UP=$upTargets, dp_rate=$([math]::Round($dpRate,3))"

        } else {
            # --- Mode NoMetrics ---

            # Lapis 1: cek container Running
            $pwaveUp = (docker ps --format "{{.Names}} {{.Status}}" 2>$null) |
                Where-Object { $_ -match 'p_wave_detector' -and $_ -match 'Up' }
            $dpUp = (docker ps --format "{{.Names}} {{.Status}}" 2>$null) |
                Where-Object { $_ -match 'data_provider' -and $_ -match 'Up' }

            if (-not $pwaveUp -or -not $dpUp) {
                Write-Host "  Menunggu (NoMetrics)... container belum siap"
                Start-Sleep $PollSec
                continue
            }

            # Lapis 2: cek offset Kafka via Python
            $pyOneLiner = 'from kafka import KafkaConsumer; from kafka.structs import TopicPartition; c=KafkaConsumer(bootstrap_servers=["localhost:9092"],request_timeout_ms=5000); p=c.partitions_for_topic("trace_topic"); print(sum(c.end_offsets([TopicPartition("trace_topic",x) for x in p]).values()) if p else 0); c.close()'
            $offsetStr = & $PythonExe -c $pyOneLiner 2>$null
            $offset = 0
            if ($offsetStr -match '^\d+$') { $offset = [long]($offsetStr.Trim()) }

            if ($offset -gt 0) {
                Write-Host "Sistem siap (NoMetrics): container UP, offset trace_topic = $offset" -ForegroundColor Green
                return $true
            }

            # Setelah 2/3 timeout, container UP sudah cukup
            $elapsed = ((Get-Date) - $startTime).TotalSeconds
            if ($elapsed -gt ($TimeoutSec * 0.67)) {
                Write-Host "Sistem siap (NoMetrics): container UP, SeedLink masih connect..." -ForegroundColor Yellow
                return $true
            }

            Write-Host "  Menunggu (NoMetrics)... offset trace_topic = $offset (container UP)"
        }

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

    $envHash    = ""
    $envContent = ""
    try {
        $envHash    = (Get-FileHash ".env" -Algorithm SHA256).Hash.Substring(0,12)
        $envContent = (Get-Content ".env" -Raw -ErrorAction Stop)
    } catch {}

    $kafkaTopics = ""
    try {
        $kafkaContainer = (docker ps --format "{{.Names}}" 2>$null) |
            Where-Object { $_ -match 'kafka1' } |
            Select-Object -First 1
        if ($kafkaContainer) {
            $kafkaTopics = (docker exec $kafkaContainer kafka-topics.sh `
                --bootstrap-server localhost:9092 --describe 2>$null) -join "`n"
        }
    } catch {}

    $meta = @{
        timestamp      = (Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ")
        scenario       = $ScenarioName
        run_index      = $RunIndex
        git_commit     = $gitHash
        compose_file   = $ComposeFile
        compose_hash   = $composeHash
        env_hash       = $envHash
        env_snapshot   = $envContent
        python_exe     = $PythonExe
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
