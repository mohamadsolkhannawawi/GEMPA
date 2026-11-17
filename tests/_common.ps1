# _common.ps1 - Fungsi-fungsi bersama untuk seluruh skrip pengujian EEWS.
# Disertakan (dot-source) oleh run_s*.ps1.

# ==============================================================================
# Resolve Python executable yang memiliki semua dependensi yang dibutuhkan.
# Dicek sekali saat dot-source; hasilnya disimpan di $PythonExe supaya semua
# script langsung bisa menggunakan variabel ini tanpa hardcode path.
# ==============================================================================
function Resolve-PythonExe {
    $candidates = @(
        "C:\Users\HP\AppData\Local\Programs\Python\Python312\python.exe",
        "python3",
        "python"
    )
    $required = @("kafka", "requests", "numpy")

    foreach ($candidate in $candidates) {
        try {
            $exePath = (Get-Command $candidate -ErrorAction Stop).Source
        } catch {
            # Jika bukan perintah di PATH, cek langsung sebagai path file
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
# Gerbang kesiapan: tunggu hingga semua target Prometheus UP dan Data Provider
# sudah mengirim minimal 1 trace ke Kafka.
# Bila Prometheus tidak tersedia (kondisi NoMetrics), fallback ke pengecekan
# offset Kafka langsung.
# ==============================================================================
function Wait-SystemReady {
    param(
        [string]$PrometheusUrl = "http://localhost:9090",
        [int]$TimeoutSec = 300,
        [int]$PollSec = 5
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    Write-Host "Menunggu sistem siap (timeout ${TimeoutSec}s)..." -ForegroundColor Yellow

    # Deteksi apakah Prometheus tersedia di stack ini
    $prometheusAvailable = $false
    try {
        $check = Invoke-RestMethod "$PrometheusUrl/-/ready" -TimeoutSec 5 -ErrorAction Stop
        $prometheusAvailable = $true
    } catch {}

    while ((Get-Date) -lt $deadline) {

        if ($prometheusAvailable) {
            # --- Mode normal: cek via Prometheus ---
            try {
                $r = Invoke-RestMethod "$PrometheusUrl/api/v1/query?query=up" -TimeoutSec 5 -ErrorAction Stop
                $upTargets = ($r.data.result | Where-Object { $_.value[1] -eq "1" }).Count
            } catch { $upTargets = 0 }

            try {
                $r2 = Invoke-RestMethod "$PrometheusUrl/api/v1/query?query=sum(rate(data_provider_traces_sent_total%5B30s%5D))" -TimeoutSec 5 -ErrorAction Stop
                $dpRate = [double]($r2.data.result[0].value[1])
            } catch { $dpRate = 0.0 }

            if ($upTargets -gt 0 -and $dpRate -gt 0) {
                Write-Host "Sistem siap: $upTargets target UP, laju Data Provider = $([math]::Round($dpRate,2)) trace/s" -ForegroundColor Green
                return $true
            }
            Write-Host "  Menunggu... UP=$upTargets, dp_rate=$([math]::Round($dpRate,3))"

        } else {
            # --- Fallback NoMetrics: cek offset Kafka langsung ---
            try {
                $rawLines = docker exec gempa-kafka1-1 kafka-run-class.sh kafka.tools.GetOffsetShell `
                    --broker-list localhost:9092 --topic trace_topic --time -1 2>$null
                $offset = $rawLines `
                    | ForEach-Object {
                        $parts = $_ -split ':'
                        if ($parts.Count -ge 3) { [long]$parts[2] }
                      } `
                    | Where-Object { $_ -ne $null } `
                    | Measure-Object -Sum -ErrorAction SilentlyContinue `
                    | Select-Object -ExpandProperty Sum
                if ($null -eq $offset) { $offset = 0 }
                if ($offset -gt 0) {
                    Write-Host "Sistem siap (NoMetrics): offset trace_topic = $offset" -ForegroundColor Green
                    return $true
                }
                Write-Host "  Menunggu (NoMetrics)... offset trace_topic = $offset"
            } catch {
                Write-Host "  Menunggu (NoMetrics)... kafka belum siap"
            }
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

    $envHash = ""
    $envContent = ""
    try {
        $envHash    = (Get-FileHash ".env" -Algorithm SHA256).Hash.Substring(0,12)
        $envContent = (Get-Content ".env" -Raw -ErrorAction Stop)
    } catch {}

    $kafkaTopics = ""
    try {
        $kafkaTopics = (docker exec gempa-kafka1-1 kafka-topics.sh --bootstrap-server localhost:9092 --describe 2>$null) -join "`n"
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
