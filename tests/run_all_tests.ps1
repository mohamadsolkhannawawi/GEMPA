# Master test runner untuk menguji semua skenario S1-S5 secara berurutan.
# Setiap skrip akan otomatis mem-build Docker, menahan (wait) stabilisasi 60 detik, mengukur metrik 300 detik (5 menit),
# dan menulis hasilnya ke dalam folder tests/results/

param (
    [int]$DurationSec = 300
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $ScriptDir

Write-Host "============================================================" -ForegroundColor Green
Write-Host " MEMULAI SELURUH PENGUJIAN OTOMATIS (DURASI MATRIK: $DurationSec dtk / skenario)" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green

# Buat folder results jika belum ada
if (-not (Test-Path "results")) {
    New-Item -ItemType Directory -Force -Path "results" | Out-Null
}

Write-Host "`n[1/6] Menjalankan Skenario S1 (Data Provider)..." -ForegroundColor Yellow
& "$ScriptDir\run_s1_dataprovider.ps1" -DurationSec $DurationSec

Write-Host "`n[2/6] Menjalankan Skenario S2 (Instrumentasi Overhead)..." -ForegroundColor Yellow
& "$ScriptDir\run_s2_overhead.ps1" -DurationSec $DurationSec

Write-Host "`n[3/6] Menjalankan Skenario S3 (Load Balancer - Kafka vs NGINX)..." -ForegroundColor Yellow
& "$ScriptDir\run_s3_broker.ps1" -DurationSec $DurationSec

Write-Host "`n[4/6] Menjalankan Skenario S4 (Data Archiver Scalability)..." -ForegroundColor Yellow
& "$ScriptDir\run_s4_scalability_archiver.ps1" -DurationSec $DurationSec

Write-Host "`n[5/6] Menjalankan Skenario S4 (P-Wave Detector Scalability)..." -ForegroundColor Yellow
& "$ScriptDir\run_s4_scalability_pwave.ps1" -DurationSec $DurationSec

Write-Host "`n[6/6] Menjalankan Skenario S5 (WebSocket Express vs FastAPI)..." -ForegroundColor Yellow
& "$ScriptDir\run_s5_websocket.ps1" -DurationSec $DurationSec

Write-Host "============================================================" -ForegroundColor Green
Write-Host " SEMUA PENGUJIAN SELESAI! Hasil tersedia di tests/results/" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
