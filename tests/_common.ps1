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
        [int]$PollSec = 5,
        # Bila $true, lolos jika target UP cukup meski dp_rate masih 0
        # (berguna untuk S5 yang data_provider butuh waktu connect SeedLink)
        [switch]$RelaxDpRate
    )

    $startTime    = Get-Date
    $deadline     = $startTime.AddSeconds($TimeoutSec)
    # Waktu pertama kali target UP mencapai threshold (untuk RelaxDpRate)
    $upSince      = $null
    $upThreshold  = 10   # minimal target UP agar dianggap "cukup naik"
    $upStableSec  = 60   # harus stabil selama ini sebelum lanjut tanpa dp_rate

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

            # Kondisi siap penuh: ada target UP dan data sudah mengalir
            if ($upTargets -gt 0 -and $dpRate -gt 0) {
                Write-Host "Sistem siap: $upTargets target UP, dp_rate=$([math]::Round($dpRate,2)) trace/s" -ForegroundColor Green
                return $true
            }

            # Kondisi relax: target UP cukup, dp_rate belum ada tapi sudah stabil cukup lama
            if ($RelaxDpRate -and $upTargets -ge $upThreshold) {
                if ($null -eq $upSince) { $upSince = Get-Date }
                $upDuration = ((Get-Date) - $upSince).TotalSeconds
                if ($upDuration -ge $upStableSec) {
                    Write-Host "Sistem siap (relax): $upTargets target UP selama $([math]::Round($upDuration))s, dp_rate masih 0 (SeedLink belum konek)" -ForegroundColor Yellow
                    return $true
                }
                Write-Host "  Menunggu... UP=$upTargets, dp_rate=$([math]::Round($dpRate,3)) (stabil $([math]::Round($upDuration))s / ${upStableSec}s)"
            } else {
                if ($upTargets -lt $upThreshold) { $upSince = $null }
                Write-Host "  Menunggu... UP=$upTargets, dp_rate=$([math]::Round($dpRate,3))"
            }

        } else {
            # --- Mode NoMetrics ---
            # Tidak cek offset Kafka (Kafka butuh ~90s untuk fully ready,
            # sehingga partitions_for_topic selalu None di awal).
            # Cukup pastikan container UP dan sudah berjalan minimal 90 detik.
            $pwaveUp = (docker ps --format "{{.Names}} {{.Status}}" 2>$null) |
                Where-Object { $_ -match 'p_wave_detector' -and $_ -match 'Up' }
            $dpUp = (docker ps --format "{{.Names}} {{.Status}}" 2>$null) |
                Where-Object { $_ -match 'data_provider' -and $_ -match 'Up' }

            if (-not $pwaveUp -or -not $dpUp) {
                Write-Host "  Menunggu (NoMetrics)... container belum siap"
                Start-Sleep $PollSec
                continue
            }

            $elapsed = ((Get-Date) - $startTime).TotalSeconds
            if ($elapsed -lt 90) {
                Write-Host "  Menunggu (NoMetrics)... container UP, stabilisasi awal ($([math]::Round($elapsed))s / 90s)"
                Start-Sleep $PollSec
                continue
            }

            Write-Host "Sistem siap (NoMetrics): semua container UP selama $([math]::Round($elapsed))s" -ForegroundColor Green
            return $true
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
