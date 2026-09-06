# Panduan Pengujian Observabilitas EEWS — Skenario S1 hingga S4

Dokumen ini adalah panduan langkah-demi-langkah untuk melaksanakan seluruh pengujian BAB IV, mulai dari persiapan awal hingga semua file CSV output berhasil dikumpulkan. Skenario S1–S4 sesuai dengan Tabel 3.3 pada BAB III.

---

## Daftar Isi

1. [Prasyarat dan Persiapan Awal](#1-prasyarat-dan-persiapan-awal)
2. [Mengambil Source Code](#2-mengambil-source-code)
3. [Pemasangan Dependensi Python](#3-pemasangan-dependensi-python)
4. [Validasi Sistem Sebelum Pengujian](#4-validasi-sistem-sebelum-pengujian)
5. [Panduan Pengambilan Screenshot](#5-panduan-pengambilan-screenshot)
6. [S1 — Overhead Instrumentasi Prometheus](#6-s1--overhead-instrumentasi-prometheus)
7. [S2 — Skalabilitas Multi-Container](#7-s2--skalabilitas-multi-container)
8. [S3 — Perbandingan WebSocket Server](#8-s3--perbandingan-websocket-server)
9. [S4 — Kafka vs Kafka+NGINX Load Balancer](#9-s4--kafka-vs-kafkanginx-load-balancer)
10. [Menjalankan Semua Skenario Sekaligus](#10-menjalankan-semua-skenario-sekaligus)
11. [Checklist Output yang Harus Dikumpulkan](#11-checklist-output-yang-harus-dikumpulkan)
12. [Troubleshooting](#12-troubleshooting)
13. [Analisis Hasil Pengujian (Otomatis)](#13-analisis-hasil-pengujian-otomatis)
14. [Menjalankan Aplikasi Dasbor Desktop Seismik (seismic_app)](#14-menjalankan-aplikasi-dasbor-desktop-seismik-seismic_app)
15. [Verifikasi dan Pengecekan Environment Variables Container](#15-verifikasi-dan-pengecekan-environment-variables-container)

---

## 1. Prasyarat dan Persiapan Awal

### Software yang Wajib Terinstal

| Software                 | Versi Minimum | Cara Cek                    |
| ------------------------ | ------------- | --------------------------- |
| Docker Desktop (Windows) | 4.x           | `docker --version`          |
| Docker Compose Plugin    | 2.x           | `docker compose version`    |
| Python                   | 3.10+         | `python --version`          |
| Git                      | 2.x           | `git --version`             |
| PowerShell               | 5.1+          | `$PSVersionTable.PSVersion` |

### Spesifikasi Mesin yang Direkomendasikan

- RAM: minimum **16 GB** (seluruh stack berjalan bersamaan bisa menggunakan 8–12 GB)
- Penyimpanan kosong: minimum **30 GB**
- CPU: minimum 4 core (8 core untuk skenario multi-container)

### Izin PowerShell (lakukan sekali saja)

```powershell
Set-ExecutionPolicy RemoteSigned -Scope CurrentUser
```

---

## 2. Mengambil Source Code

### Clone pertama kali

```powershell
git clone https://github.com/mohamadsolkhannawawi/GEMPA.git
cd GEMPA
```

### Update jika sudah pernah clone

```powershell
cd GEMPA
git pull origin main
```

### Siapkan file environment

```powershell
Copy-Item .env.example .env
Copy-Item influxDB\.env.example influxDB\.env
```

> **Catatan:** Jangan pernah meng-commit file `.env`. File ini berisi credential yang bersifat rahasia.

### Validasi konfigurasi

```powershell
docker compose config
```

Perintah ini harus selesai tanpa error. Jika ada error, periksa apakah file `.env` dan `influxDB/.env` sudah tersedia.

---

## 3. Pemasangan Dependensi Python

Semua skrip pengumpul metrik membutuhkan library berikut. Pasang sekali saja:

```powershell
pip install requests websockets
```

### Verifikasi

```powershell
python -c "import requests, websockets; print('OK')"
```

---

## 4. Validasi Sistem Sebelum Pengujian

Sebelum menjalankan skenario apapun, pastikan sistem berjalan dengan benar menggunakan langkah berikut.

### Langkah 4.1 — Jalankan docker compose utama

```powershell
cd GEMPA
docker compose up -d --build
```

Tunggu **60 detik** agar Kafka selesai startup dan memilih leader.

### Langkah 4.2 — Periksa status container

```powershell
docker compose ps
```

Container berikut **wajib** berstatus `Up (healthy)` atau `Up`:

| Container                      | Status Wajib |
| ------------------------------ | ------------ |
| `zookeeper`                    | Up           |
| `kafka1`, `kafka2`, `kafka3`   | Up           |
| `data_provider`                | Up           |
| `p_wave_detector` (instance-1) | Up           |
| `loc_mag_detector`             | Up           |
| `data_archiver` (instance-1)   | Up           |
| `api_server`                   | Up           |
| `fast_api`                     | Up           |
| `prometheus`                   | Up           |
| `grafana`                      | Up           |

### Langkah 4.3 — Periksa Prometheus

```powershell
# Prometheus harus menjawab "Prometheus Server is Ready."
curl.exe http://localhost:9090/-/ready

# Semua target utama harus bernilai 1
curl.exe "http://localhost:9090/api/v1/query?query=up" |
    ConvertFrom-Json |
    ConvertTo-Json -Depth 100
```

Buka `http://localhost:9090/targets` di browser. Semua service EEWS harus berstatus **UP** (hijau).

### Langkah 4.4 — Periksa Grafana

Buka `http://localhost:4000`. Login dengan `admin` / `12345678`. Pastikan dashboard **EEWS Observability** muncul dan panelnya menampilkan data.

### Langkah 4.5 — Periksa endpoint WebSocket dan metrik

```powershell
curl.exe http://localhost:3333
curl.exe http://localhost:3334/health
curl.exe http://localhost:8107/metrics
```

### URL Lengkap untuk Validasi

| Komponen             | URL                             | Login                |
| -------------------- | ------------------------------- | -------------------- |
| Express WebSocket UI | `http://localhost:3333`         | —                    |
| FastAPI WebSocket UI | `http://localhost:3334`         | —                    |
| Express Metrics      | `http://localhost:8107/metrics` | —                    |
| FastAPI Metrics      | `http://localhost:8108/metrics` | —                    |
| Prometheus Targets   | `http://localhost:9090/targets` | —                    |
| Prometheus Graph     | `http://localhost:9090/graph`   | —                    |
| Grafana              | `http://localhost:4000`         | `admin` / `12345678` |
| InfluxDB             | `http://localhost:8086`         | `admin` / `12345678` |
| Mongo Express        | `http://localhost:8081`         | `admin` / `password` |

---

## 5. Panduan Pengambilan Screenshot

Screenshot berikut wajib diambil **satu kali** setelah validasi sistem berhasil (Langkah 4), dan dapat dipakai untuk semua skenario.

| No  | Yang Difoto                             | Cara Mengambil                                                            |
| --- | --------------------------------------- | ------------------------------------------------------------------------- |
| 1   | Hasil `docker compose ps`               | Buka PowerShell, jalankan perintah, screenshot terminal                   |
| 2   | Halaman `http://localhost:3333`         | Browser, tampilkan data trace                                             |
| 3   | Halaman `http://localhost:3334`         | Browser, tampilkan koneksi WebSocket                                      |
| 4   | Halaman `http://localhost:8107/metrics` | Browser, tampilkan teks metrik mentah Prometheus                          |
| 5   | Halaman `http://localhost:9090/targets` | Browser, semua target harus UP (hijau)                                    |
| 6   | Prometheus Graph dengan query `up`      | Ketik `up` di kotak query, klik Execute                                   |
| 7   | Prometheus Graph CPU                    | Query: `100 - (avg(rate(node_cpu_seconds_total{mode="idle"}[1m])) * 100)` |
| 8   | Grafana dashboard EEWS                  | Pilih time range **Last 15 minutes**                                      |
| 9   | InfluxDB Data Explorer                  | Buka bucket `eews`                                                        |
| 10  | Mongo Express                           | Buka collection data                                                      |

> **Penting:** Jangan tampilkan password, token, atau isi file `.env` pada screenshot manapun.

---

## 6. S1 — Strategi Konkurensi Data Provider

**Tujuan:** Mengevaluasi mekanisme konkurensi (sekuensial, multi-thread, multi-process, atau gabungan) pada tahap ingesti data.

**Compose file yang digunakan:** `docker-compose-s1-sequential.yml` hingga `docker-compose-s1-mp_mt.yml`

**Output yang dihasilkan:**
- `tests/results/s1_sequential_stats.csv`
- `tests/results/s1_multithread_stats.csv`
- `tests/results/s1_multiprocess_stats.csv`
- `tests/results/s1_mp_mt_stats.csv`

### Cara Menjalankan S1 (Otomatis)

```powershell
cd tests

# Menjalankan seluruh variasi S1 sekaligus secara berurutan:
.\run_s1_dataprovider.ps1

# ATAU, jalankan salah satu variasi berikut secara spesifik:
.\run_s1_dataprovider.ps1 -ScenarioName Sequential
.\run_s1_dataprovider.ps1 -ScenarioName Multithread
.\run_s1_dataprovider.ps1 -ScenarioName Multiprocess
.\run_s1_dataprovider.ps1 -ScenarioName MP_MT
```

*(Untuk eksekusi manual per skenario, silakan merujuk ke Bagian 17 - Sub S1).*

---

## 7. S2 — Overhead Instrumentasi Prometheus

**Tujuan:** Mengukur selisih CPU (%), memori (MB), dan latensi (ms) antara sistem _tanpa_ instrumentasi Prometheus dan sistem _dengan_ instrumentasi Prometheus.

**Compose file yang digunakan:** `docker-compose-s2-no_metrics.yml` (tanpa metrik) dan `docker-compose-s2-with_metrics.yml` (dengan metrik)

**Output yang dihasilkan:**

- `tests/results/s2_overhead_no_metrics_stats.csv`
- `tests/results/s2_overhead_with_metrics_stats.csv`

### Cara Menjalankan S2 (Otomatis)

```powershell
cd tests
# Jalankan salah satu dari parameter berikut sesuai kebutuhan:
.\run_s2_overhead.ps1 -ScenarioName NoMetrics
.\run_s2_overhead.ps1 -ScenarioName WithMetrics
```

*(Untuk eksekusi manual per skenario, silakan merujuk ke Bagian 17 - Sub S2).*

---

## 8. S3 — Skalabilitas Worker Node (Multi-Container)

**Tujuan:** Mengukur pengaruh jumlah _instance_ (1 hingga 5 container) terhadap performa modul **Data Archiver** dan **P-Wave Detector**.

**Compose file yang digunakan:**
- Data Archiver (1–5 container): `docker-compose-s3-archiver-1c.yml` hingga `docker-compose-s3-archiver-5c.yml`
- P-Wave Detector Kafka native (2–5 container): `docker-compose-s3-pwave-kafka-2c.yml` hingga `docker-compose-s3-pwave-kafka-5c.yml`
- P-Wave Detector Kafka-NGINX (2–5 container): `docker-compose-s3-pwave-kafka-nginx-2c.yml` hingga `docker-compose-s3-pwave-kafka-nginx-5c.yml`

**Output yang dihasilkan:**
- Data Archiver: `tests/results/s3_archiver_1_container_stats.csv` hingga `s3_archiver_5_container_stats.csv` (serta file metrics)
- P-Wave Kafka: `tests/results/s3_pwave_kafka_2c_stats.csv` hingga `s3_pwave_kafka_5c_stats.csv` (serta file metrics)
- P-Wave Kafka-NGINX: `tests/results/s3_pwave_kafka_nginx_2c_stats.csv` hingga `s3_pwave_kafka_nginx_5c_stats.csv` (serta file metrics)

### Cara Menjalankan S3 (Otomatis)

```powershell
cd tests

# Menjalankan seluruh variasi Archiver sekaligus secara berurutan:
.\run_s3_scalability_archiver.ps1
# Menjalankan seluruh variasi P-Wave sekaligus secara berurutan:
.\run_s3_scalability_pwave.ps1

# ATAU, jalankan salah satu variasi berikut secara spesifik:

# Archiver (Pilih salah satu)
.\run_s3_scalability_archiver.ps1 -ScenarioName 1c
.\run_s3_scalability_archiver.ps1 -ScenarioName 2c
.\run_s3_scalability_archiver.ps1 -ScenarioName 3c
.\run_s3_scalability_archiver.ps1 -ScenarioName 4c
.\run_s3_scalability_archiver.ps1 -ScenarioName 5c

# P-Wave Kafka (Pilih salah satu)
.\run_s3_scalability_pwave.ps1 -ScenarioName Kafka2c
.\run_s3_scalability_pwave.ps1 -ScenarioName Kafka3c
.\run_s3_scalability_pwave.ps1 -ScenarioName Kafka4c
.\run_s3_scalability_pwave.ps1 -ScenarioName Kafka5c

# P-Wave Kafka-NGINX (Pilih salah satu)
.\run_s3_scalability_pwave.ps1 -ScenarioName KafkaNginx2c
.\run_s3_scalability_pwave.ps1 -ScenarioName KafkaNginx3c
.\run_s3_scalability_pwave.ps1 -ScenarioName KafkaNginx4c
.\run_s3_scalability_pwave.ps1 -ScenarioName KafkaNginx5c
```

*(Untuk eksekusi manual per skenario, silakan merujuk ke Bagian 17 - Sub S3).*

---

## 9. S4 — Perbandingan WebSocket Server

**Tujuan:** Membandingkan performa Express.js/Socket.IO versus FastAPI dalam menangani koneksi WebSocket pada 1 client dan 5 client konkuren.

**Compose file yang digunakan:**
- Express.js: `docker-compose-s4-express.yml`
- FastAPI: `docker-compose-s4-fastapi.yml`

**Output yang dihasilkan:**
- `tests/results/s4_websocket_express_1c_stats.csv` (dan metrics)
- `tests/results/s4_websocket_express_5c_stats.csv` (dan metrics)
- `tests/results/s4_websocket_fastapi_1c_stats.csv` (dan metrics)
- `tests/results/s4_websocket_fastapi_5c_stats.csv` (dan metrics)

### Cara Menjalankan S4 (Otomatis)

```powershell
cd tests
# Jalankan salah satu dari parameter berikut sesuai kebutuhan:
.\run_s4_websocket.ps1 -ScenarioName Express1c
.\run_s4_websocket.ps1 -ScenarioName Express5c
.\run_s4_websocket.ps1 -ScenarioName KafkaNginx1c
.\run_s4_websocket.ps1 -ScenarioName KafkaNginx5c
```

*(Untuk eksekusi manual per skenario, silakan merujuk ke Bagian 17 - Sub S4).*

---

## 10. S5 — Load Balancer (Kafka vs Kafka+NGINX)

**Tujuan:** Membandingkan konfigurasi _message broker_ Kafka native (3 broker) versus Kafka+NGINX sebagai _load balancer_ eksternal.

**Compose file yang digunakan:**
- Kafka 3 Container: `docker-compose-s5-kafka.yml`
- Kafka 3 Container + NGINX: `docker-compose-s5-nginx.yml`

**Output yang dihasilkan:**
- `tests/results/s5_broker_kafka_stats.csv` (dan metrics)
- `tests/results/s5_broker_nginx_stats.csv` (dan metrics)

### Cara Menjalankan S5 (Otomatis)

```powershell
cd tests
# Jalankan salah satu dari parameter berikut sesuai kebutuhan:
.\run_s5_loadbalancer.ps1 -ScenarioName Kafka
.\run_s5_loadbalancer.ps1 -ScenarioName NGINX
```

*(Untuk eksekusi manual per skenario, silakan merujuk ke Bagian 17 - Sub S5).*

---

## 10a. Menjalankan Semua Skenario Sekaligus

Jika Anda ingin menjalankan S1 hingga S5 secara berurutan tanpa intervensi manual, gunakan master runner:

```powershell
cd tests
.\run_all_tests.ps1
```

> **Perhatian:** Proses ini membutuhkan estimasi **1,5 hingga 3 jam** tergantung spesifikasi mesin. Pastikan komputer tidak masuk mode tidur (_sleep_) selama eksekusi.

Untuk mencegah komputer tidur saat tes berjalan panjang:

```powershell
# Jalankan ini di terminal terpisah selama pengujian berlangsung
while ($true) { [System.Console]::Write("."); Start-Sleep -Seconds 60 }
```

---

## 11. Checklist Output yang Harus Dikumpulkan

Tandai setiap item setelah berhasil dikumpulkan.

### Screenshot (satu kali, dari sistem yang sudah tervalidasi)

- [ ] `docker compose ps` — semua container Up
- [ ] `http://localhost:3333` — data trace muncul
- [ ] `http://localhost:3334` — koneksi WebSocket aktif
- [ ] `http://localhost:8107/metrics` — teks metrik Prometheus muncul
- [ ] `http://localhost:9090/targets` — semua target UP (hijau)
- [ ] Prometheus Graph — query `up`
- [ ] Prometheus Graph — query CPU
- [ ] Grafana dashboard — panel berisi grafik terisi data
- [ ] InfluxDB Data Explorer — bucket `eews` berisi data
- [ ] Mongo Express — koleksi berisi dokumen

### File CSV per Skenario

**S1 — Strategi Konkurensi Data Provider (1–4):**

- [ ] `tests/results/s1_sequential_stats.csv`
- [ ] `tests/results/s1_multithread_stats.csv`
- [ ] `tests/results/s1_multiprocess_stats.csv`
- [ ] `tests/results/s1_mp_mt_stats.csv`

**S2 — Overhead Instrumentasi:**

- [ ] `tests/results/s2_overhead_no_metrics_stats.csv`
- [ ] `tests/results/s2_overhead_with_metrics_stats.csv`

**S3 — Skalabilitas Data Archiver (1–5 container):**

- [ ] `tests/results/s3_archiver_1_container_stats.csv`
- [ ] `tests/results/s3_archiver_2_container_stats.csv`
- [ ] `tests/results/s3_archiver_3_container_stats.csv`
- [ ] `tests/results/s3_archiver_4_container_stats.csv`
- [ ] `tests/results/s3_archiver_5_container_stats.csv`

**S3 — Skalabilitas P-Wave Detector Kafka (2–5 container):**

- [ ] `tests/results/s3_pwave_kafka_2c_stats.csv`
- [ ] `tests/results/s3_pwave_kafka_3c_stats.csv`
- [ ] `tests/results/s3_pwave_kafka_4c_stats.csv`
- [ ] `tests/results/s3_pwave_kafka_5c_stats.csv`

**S3 — Skalabilitas P-Wave Detector Kafka-NGINX (2–5 container):**

- [ ] `tests/results/s3_pwave_kafka_nginx_2c_stats.csv`
- [ ] `tests/results/s3_pwave_kafka_nginx_3c_stats.csv`
- [ ] `tests/results/s3_pwave_kafka_nginx_4c_stats.csv`
- [ ] `tests/results/s3_pwave_kafka_nginx_5c_stats.csv`

**S4 — WebSocket Express vs FastAPI:**

- [ ] `tests/results/s4_websocket_express_1c_stats.csv`
- [ ] `tests/results/s4_websocket_express_5c_stats.csv`
- [ ] `tests/results/s4_websocket_fastapi_1c_stats.csv`
- [ ] `tests/results/s4_websocket_fastapi_5c_stats.csv`

**S5 — Load Balancer (Kafka vs NGINX):**

- [ ] `tests/results/s5_broker_kafka_stats.csv`
- [ ] `tests/results/s5_broker_kafka_metrics.csv`
- [ ] `tests/results/s5_broker_nginx_stats.csv`
- [ ] `tests/results/s5_broker_nginx_metrics.csv`

### Verifikasi Cepat Semua CSV

```powershell
Get-ChildItem "tests/results/*.csv" | ForEach-Object {
    $lines = (Get-Content $_.FullName).Count
    Write-Host "$($_.Name): $lines baris"
}
```

Setiap CSV harus memiliki **lebih dari 5 baris** (header + data). Jika kurang, pengujian mungkin terlalu singkat atau container belum stabil saat pengumpulan dimulai.

---

## 12. Troubleshooting

### Pengecekan Log Error per Modul

Untuk mendeteksi error pada seluruh modul atau modul tertentu secara menyeluruh:

**Filter Semua Error Terkini Sekaligus (5 Menit Terakhir):**
- PowerShell (Windows):
  ```powershell
  docker compose logs --since 5m | Select-String "ERROR", "Exception", "Traceback"
  ```
- Bash (Ubuntu / Linux):
  ```bash
  docker compose logs --since 5m | grep -iE "ERROR|Exception|Traceback"
  ```

**Pengecekan Error Terkini per Modul Spesifik:**
Jika ingin lebih detail, Anda bisa menjalankan perintah berikut untuk mengecek sisa bug terbaru pada setiap modul:

```powershell
# Data Provider
docker compose logs data_provider --since 5m | Select-String "ERROR", "Exception", "Traceback"

# AI Detectors
docker compose logs p_wave_detector --since 5m | Select-String "ERROR", "Exception", "Traceback"
docker compose logs loc_mag_detector --since 5m | Select-String "ERROR", "Exception", "Traceback"

# Backend & APIs
docker compose logs data_archiver --since 5m | Select-String "ERROR", "Exception", "Traceback"
docker compose logs api_server --since 5m | Select-String "ERROR", "Exception", "Traceback"
docker compose logs fast_api --since 5m | Select-String "ERROR", "Exception", "Traceback"

# Infrastruktur Inti (Kafka, Zookeeper, dll)
docker compose logs kafka1 --since 5m | Select-String "ERROR", "Exception", "Traceback"
docker compose logs zookeeper --since 5m | Select-String "ERROR", "Exception", "Traceback"
```

*(Tips: Jika Anda menggunakan Mac/Linux, cukup ganti `Select-String "..."` dengan `grep -iE "ERROR|Exception|Traceback"`).*

### Penanganan Resource Berlebihan (CPU > 100% / Memory Full / Laptop Lambat)

Jika Docker Desktop menggunakan resource berlebihan (misalnya CPU 1000%+ atau RAM penuh) saat pengujian lokal:

1. **Turunkan Beban Data Provider di `.env`:**
   Secara default konfigurasi produksi menggunakan 30 proses dan 6000 stasiun. Untuk pengujian skala lokal/laptop, sesuaikan nilai berikut di file `.env`:
   ```env
   DATA_PROVIDER_NUM_PROCESSES=2
   DATA_PROVIDER_NUM_STATIONS=50
   ```
2. **Restrukturisasi/Rebuild Container:**
   ```powershell
   docker compose down -v
   docker compose up -d --build
   ```
3. **Batasi Resource pada Docker Desktop (Windows):**
   Masuk ke Settings > Resources di Docker Desktop, batasi penggunaan CPU (misal max 4 core) dan RAM (misal max 8 GB).

### Container langsung Exiting atau Restarting

```powershell
docker compose logs --tail=50 data_provider
docker compose logs --tail=50 p_wave_detector
docker compose logs --tail=50 kafka1
```

Cari pesan `Error`, `Exception`, atau `ECONNREFUSED`. Untuk Kafka, tunggu minimal 60 detik karena Kafka membutuhkan waktu startup yang relatif lama.

### Error `model_p_wave.h5` atau `model_loc_mag.h5` tidak ditemukan

File model H5 harus tersedia di dalam folder masing-masing modul sebelum build:

- `p_wave_detector/model_p_wave.h5`
- `loc_mag_detector/model_p_wave.h5`

### Python: `ModuleNotFoundError: No module named 'requests'`

```powershell
pip install requests websockets
```

### CSV kosong atau hanya berisi header

Pastikan:

1. Container sudah berjalan selama minimal 60 detik sebelum kolektor dijalankan
2. Argumen `--target-substring` sesuai nama container (cek `docker compose ps`)

---

## 13. Verifikasi Penyimpanan Data ke Database

Selain metrik pada Grafana, Anda juga perlu memastikan bahwa seluruh data tersimpan dengan baik di database yang digunakan oleh sistem (InfluxDB, MongoDB, dan Prometheus). 

Berikut adalah cara memverifikasi data di masing-masing database:

### A. Verifikasi InfluxDB (Penyimpanan Data Gelombang & Metrik)
InfluxDB v2 menggunakan konsep **bucket** dan bahasa query **Flux**. Anda dapat memverifikasi data yang tersimpan secara langsung via terminal PowerShell menggunakan CLI InfluxDB v2 dengan token dan nama organisasi.

1. **Cek daftar bucket yang tersedia:**
   ```powershell
   docker compose exec influxdb influx bucket list --token "eFWu0UGcCzvGAX1w-z43heHjfDk8swujfryImhIsTrAkNJOgfMRSYsgYVki-QTiWHDwKLJtxsSnCmHhxisCN1w==" --org "owner"
   ```

2. **Cek data gelombang seismik terbaru (bucket `eews`):**
   Jalankan query Flux untuk menampilkan 10 sampel data dalam rentang 1 jam terakhir:
   ```powershell
   docker compose exec influxdb influx query 'from(bucket: \"eews\") |> range(start: -1h) |> limit(n: 10)' --token "eFWu0UGcCzvGAX1w-z43heHjfDk8swujfryImhIsTrAkNJOgfMRSYsgYVki-QTiWHDwKLJtxsSnCmHhxisCN1w==" --org "owner"
   ```

3. **Cek data Real-Time (Data mutakhir yang baru saja masuk):**
   - **Melihat data 1 menit terakhir (10 sampel paling akhir):**
     ```powershell
     docker compose exec influxdb influx query 'from(bucket: \"eews\") |> range(start: -1m) |> tail(n: 10)' --token "eFWu0UGcCzvGAX1w-z43heHjfDk8swujfryImhIsTrAkNJOgfMRSYsgYVki-QTiWHDwKLJtxsSnCmHhxisCN1w==" --org "owner"
     ```
   - **Melihat titik sampel paling mutakhir (`last()`) untuk tiap sensor/stasiun:**
     ```powershell
     docker compose exec influxdb influx query 'from(bucket: \"eews\") |> range(start: -5m) |> last()' --token "eFWu0UGcCzvGAX1w-z43heHjfDk8swujfryImhIsTrAkNJOgfMRSYsgYVki-QTiWHDwKLJtxsSnCmHhxisCN1w==" --org "owner"
     ```
   - **Melihat 10 data terbaru diurutkan dari timestamp paling baru (descending):**
     ```powershell
     docker compose exec influxdb influx query 'from(bucket: \"eews\") |> range(start: -5m) |> sort(columns: [\"_time\"], desc: true) |> limit(n: 10)' --token "eFWu0UGcCzvGAX1w-z43heHjfDk8swujfryImhIsTrAkNJOgfMRSYsgYVki-QTiWHDwKLJtxsSnCmHhxisCN1w==" --org "owner"
     ```

   > **Catatan PowerShell:** Pastikan menggunakan tanda petik tunggal (`'...'`) di luar query dan meng-escape nama bucket/kolom dengan backslash (`\"eews\"`, `\"_time\"`) agar tidak terpotong oleh parser PowerShell.

### B. Verifikasi MongoDB (Penyimpanan Hasil Deteksi AI)
MongoDB digunakan oleh modul `data_archiver` untuk menyimpan data timeseries dan hasil analisis dari modul AI.

1. **Masuk ke dalam container MongoDB (menggunakan `mongosh`):**
   *(Catatan: Nama service container di docker-compose adalah `mongo`)*
   ```powershell
   docker compose exec mongo mongosh
   ```
2. **Cek database yang tersedia dan pilih database `timeseries_db`:**
   ```javascript
   test> show dbs
   test> use timeseries_db
   ```
3. **Cek koleksi data yang tersedia:**
   ```javascript
   timeseries_db> show collections
   ```
4. **Cek jumlah dokumen / data yang sudah tersimpan:**
   ```javascript
   timeseries_db> db.timeseries_collection.countDocuments()
   ```
5. **Tampilkan data mutakhir/terbaru yang masuk:**
   ```javascript
   timeseries_db> db.timeseries_collection.find().sort({_id: -1}).limit(1)
   ```
*(Ketik `exit` untuk keluar dari shell MongoDB).*

### C. Verifikasi Prometheus (Penyimpanan Metrik Observabilitas)
Prometheus menarik (scrape) metrik dari seluruh layanan, termasuk Data Provider, Node Exporter, cAdvisor, dan Kafka.

1. Buka browser dan akses **Prometheus Web UI**:
   - `http://localhost:9090`
2. Di kolom pencarian (Expression), ketikkan query berikut dan klik **Execute** (pilih tab **Table** atau **Graph**):
   - Cek metrik dari Data Provider: `data_provider_traces_sent_total`
   - Cek penggunaan CPU container Kafka: `rate(container_cpu_usage_seconds_total{container_label_com_docker_compose_service=~"kafka.*"}[1m])`
   - Cek metrik API Server HTTP reqs: `http_requests_total`
3. Jika query mengembalikan tabel nilai (bukan "Empty query result"), artinya Prometheus berhasil menyimpan metrik.
3. Tidak ada error di terminal saat kolektor berjalan

### Permission Denied saat menulis CSV

Pastikan file CSV tidak sedang dibuka di Excel atau editor lain. Tutup semua aplikasi yang membuka file tersebut.

### Rebuild paksa setelah perubahan kode

```powershell
docker builder prune -af
docker compose -f docker-compose-s2-with_metrics.yml build --no-cache --progress=plain
```

### Hapus semua data volume (reset total)

```powershell
docker compose down -v
docker volume prune -f
```

> **Perhatian:** Perintah di atas menghapus seluruh data MongoDB, InfluxDB, dan Grafana. Gunakan hanya jika memang ingin reset penuh.

---

## Referensi Mapping Skenario ke Compose File

| Kode Skenario (BAB III)     | Compose File              | Script Otomatis                |
| --------------------------- | ------------------------- | ------------------------------ |
| S1 — Strategi Konkurensi    | `1-1.yml` - `1-4.yml`     | `run_s1_dataprovider.ps1`      |
| S2 — Tanpa Prometheus       | `docker-compose-s2-no_metrics.yml`  | `run_s2_overhead.ps1`          |
| S2 — Dengan Prometheus      | `docker-compose-s2-with_metrics.yml`  | `run_s2_overhead.ps1`          |
| S3 — Archiver (1-5 C)       | `docker-compose-s3-archiver-1c.yml`  | `run_s3_scalability_archiver.ps1`|
| S3 — P-Wave Kafka (2-5 C)   | `docker-compose-s3-pwave-kafka-2c.yml`  | `run_s3_scalability_pwave.ps1` |
| S3 — P-Wave Kafka-NGINX (2-5 C) | `docker-compose-s3-pwave-kafka-nginx-2c.yml` | `run_s3_scalability_pwave.ps1` |
| S4 — Express (1, 5 Client)  | `docker-compose-s4-express.yml`  | `run_s4_websocket.ps1`         |
| S4 — FastAPI (1, 5 Client)  | `docker-compose-s4-fastapi.yml`  | `run_s4_websocket.ps1`         |
| S5 — Kafka 3 Broker         | `docker-compose-s5-kafka.yml`  | `run_s5_loadbalancer.ps1`      |
| S5 — Kafka 3 Broker + NGINX | `docker-compose-s5-nginx.yml`  | `run_s5_loadbalancer.ps1`      |

---

## 16. Panduan Eksekusi Otomatis per Skenario Spesifik

Sistem kini dilengkapi dengan skrip otomatis (`.ps1`) yang mengabstraksi seluruh proses _build_ Docker, _startup_, _warm-up delay_ (60 detik), hingga pengumpulan metrik (120 detik) dan pembongkaran (_teardown_) secara otomatis.

Jika Anda ingin menjalankan **hanya satu tipe skenario tertentu** tanpa harus menjalankan keseluruhan skrip, Anda bisa menggunakan argumen `-ScenarioName` diikuti dengan _keyword_ (nama pendek) skenario tersebut.

**Contoh Kasus:**
Anda hanya ingin menjalankan skenario pengujian S1 dengan metode Multiprocessing.
```powershell
.\run_s1_dataprovider.ps1 -ScenarioName Multiprocess
```

---

## 17. Daftar Lengkap Perintah Eksekusi per Skenario

Berikut adalah kumpulan perintah lengkap (*copy-paste*) untuk menghidupkan dan mengekstrak data dari **setiap variasi skenario** secara otomatis, spesifik, dan terisolasi.

> **Catatan Penting:** Seluruh perintah di bawah ini harus dijalankan di dalam direktori `tests`.
> ```powershell
> cd tests
> ```

### S1. Strategi Konkurensi Data Provider (`run_s1_dataprovider.ps1`)

* Skenario 1.1: **Sequence** (Sekuensial)
  ```powershell
  .\run_s1_dataprovider.ps1 -ScenarioName Sequential
  ```
* Skenario 1.2: **Multi-thread**
  ```powershell
  .\run_s1_dataprovider.ps1 -ScenarioName Multithread
  ```
* Skenario 1.3: **Multi-process**
  ```powershell
  .\run_s1_dataprovider.ps1 -ScenarioName Multiprocess
  ```
* Skenario 1.4: **Multi-process & Multi-thread**
  ```powershell
  .\run_s1_dataprovider.ps1 -ScenarioName MP_MT
  ```

### S2. Overhead Instrumentasi (`run_s2_overhead.ps1`)

* Skenario 5.1: **Tanpa Metrik Prometheus**
  ```powershell
  .\run_s2_overhead.ps1 -ScenarioName NoMetrics
  ```
* Skenario 5.2: **Dengan Metrik Prometheus**
  ```powershell
  .\run_s2_overhead.ps1 -ScenarioName WithMetrics
  ```

### S3. Skalabilitas Data Archiver (`run_s3_scalability_archiver.ps1`)

* **1 Container**
  ```powershell
  .\run_s3_scalability_archiver.ps1 -ScenarioName 1c
  ```
* **2 Container**
  ```powershell
  .\run_s3_scalability_archiver.ps1 -ScenarioName 2c
  ```
* **3 Container**
  ```powershell
  .\run_s3_scalability_archiver.ps1 -ScenarioName 3c
  ```
* **4 Container**
  ```powershell
  .\run_s3_scalability_archiver.ps1 -ScenarioName 4c
  ```
* **5 Container**
  ```powershell
  .\run_s3_scalability_archiver.ps1 -ScenarioName 5c
  ```

### S3. Skalabilitas P-Wave Detector (`run_s3_scalability_pwave.ps1`)

* **Kafka Native (2 hingga 5 Container)**
  ```powershell
  .\run_s3_scalability_pwave.ps1 -ScenarioName Kafka2c
  .\run_s3_scalability_pwave.ps1 -ScenarioName Kafka3c
  .\run_s3_scalability_pwave.ps1 -ScenarioName Kafka4c
  .\run_s3_scalability_pwave.ps1 -ScenarioName Kafka5c
  ```
* **Kafka-NGINX Load Balanced (2 hingga 5 Container)**
  ```powershell
  .\run_s3_scalability_pwave.ps1 -ScenarioName KafkaNginx2c
  .\run_s3_scalability_pwave.ps1 -ScenarioName KafkaNginx3c
  .\run_s3_scalability_pwave.ps1 -ScenarioName KafkaNginx4c
  .\run_s3_scalability_pwave.ps1 -ScenarioName KafkaNginx5c
  ```

### S4. WebSocket Server (`run_s4_websocket.ps1`)

* **Express.js / Socket.IO (1 Klien)**
  ```powershell
  .\run_s4_websocket.ps1 -ScenarioName Express1c
  ```
* **Express.js / Socket.IO (5 Klien)**
  ```powershell
  .\run_s4_websocket.ps1 -ScenarioName Express5c
  ```
* **FastAPI WebSocket (1 Klien)**
  ```powershell
  .\run_s4_websocket.ps1 -ScenarioName KafkaNginx1c
  ```
* **FastAPI WebSocket (5 Klien)**
  ```powershell
  .\run_s4_websocket.ps1 -ScenarioName KafkaNginx5c
  ```

### S5. Load Balancer Message Broker (`run_s5_loadbalancer.ps1`)

* **Kafka (3 Broker tanpa NGINX)**
  ```powershell
  .\run_s5_loadbalancer.ps1 -ScenarioName Kafka
  ```
* **Kafka + NGINX (3 Broker di belakang NGINX)**
  ```powershell
  .\run_s5_loadbalancer.ps1 -ScenarioName NGINX
  ```

---

## 13. Analisis Hasil Pengujian (Otomatis)

Setelah Anda selesai menjalankan semua skenario dan file `.csv` terkumpul di dalam folder `tests/results/`, Anda dapat mengolah seluruh data tersebut secara instan menggunakan Skrip Analis Terpusat.

### Perintah Penggunaan

Buka terminal di root folder `MDLBEEWS` dan jalankan:

```powershell
# Untuk menganalisis Skenario 1 (Konkurensi)
python tests/analyze.py --scenario 1

# Untuk menganalisis Skenario 2 (Overhead)
python tests/analyze.py --scenario 2

# Untuk menganalisis Skenario 3 (Load Balancer)
python tests/analyze.py --scenario 3

# Untuk menganalisis Skenario 4 (WebSocket)
python tests/analyze.py --scenario 4

# Untuk memproses dan menampilkan SEMUA skenario sekaligus
python tests/analyze.py --scenario all
```

**Output**:
Skrip akan mencetak tabel format Markdown yang berisi rangkuman Rata-rata (*Mean*), Nilai Maksimal (*Max*), dan P95 untuk Konsumsi CPU, RAM, dan Latensi (*Delay*). Tabel ini sudah diformat sedemikian rupa sehingga **langsung siap disalin (copy-paste)** ke dalam Dokumen Skripsi Bab 4 Anda.

---

## 14. Menjalankan Aplikasi Dasbor Desktop Seismik (`seismic_app`)

`seismic_app` adalah aplikasi GUI Desktop berbasis PyQt5 & PyQtGraph dengan tema futuristik (*qdarktheme*) yang bertugas memvisualisasikan sinyal gelombang gempa (*waveform*) secara *real-time* serta menampilkan spanduk **🚨 PERINGATAN GEMPA** saat AI memprediksi gempa.

### Prasyarat
1. Stack infrastruktur EEWS (Kafka, Data Provider, AI Detector, dan WebSocket Server/`api_server` pada port `3333`) harus sudah menyala menggunakan Docker Compose.
2. Dependensi GUI terpasang di lingkungan Python lokal.

### Langkah Menjalankan

#### Langkah 1: Jalankan Infrastruktur Backend (Docker Compose)
Buka terminal PowerShell dan jalankan stack backend (contoh untuk Skenario WebSocket Express):
```powershell
docker compose -f docker-compose-s4-express.yml up -d
```
*(Atau jalankan file `docker-compose.yml` utama / skrip pengujian skenario yang Anda inginkan).*

#### Langkah 2: Jalankan Aplikasi Dasbor Desktop (`seismic_app`)
Buka terminal PowerShell **baru** dan jalankan:
```powershell
# 1. Masuk ke folder seismic_app
cd seismic_app

# 2. Pasang dependensi GUI (cukup sekali saja)
pip install -r requirements.txt

# 3. Jalankan aplikasi Dasbor Desktop
python main.py
```

### Fitur Utama Dasbor
- **Visualisasi Waveform 20Hz**: Plotting grafik sinyal gempa *real-time* berkecepatan tinggi dengan skema warna *cyan/dark mode*.
- **Sistem Peringatan Bencana (EEWS Alert)**: Spanduk status atas akan berubah dari `🟢 STATUS: AMAN` menjadi `🚨 PERINGATAN GEMPA` berwarna merah terang secara otomatis jika Magnitudo > 3.0 terdeteksi.

---

## 15. Verifikasi dan Pengecekan Environment Variables Container

Seluruh *microservice* pada sistem EEWS menerapkan prinsip **12-Factor App**, di mana konfigurasi sistem diinjeksikan secara terpusat melalui file `.env` menggunakan deklarasi `env_file: - .env` pada seluruh berkas `docker-compose-s*.yml`.

Untuk memverifikasi bahwa container benar-benar membaca nilai dari `.env` dan tidak menggunakan *fallback default*, gunakan perintah-perintah verifikasi berikut di PowerShell:

### A. Verifikasi Pembacaan `.env` pada Data Provider
```powershell
# 1. Cek konfigurasi gabungan Docker Compose sebelum container dinyalakan
docker compose config | Select-String "DATA_PROVIDER"

# 2. Cek variabel lingkungan aktif di dalam container hidup
docker exec data_provider env | Select-String "DATA_PROVIDER"

# 3. Cek log startup aplikasi (memastikan "loaded from ENV" tercetak)
docker compose logs data_provider | Select-String "DATA_PROVIDER_NUM"
```

*Ekspektasi Output Log*:
```text
data_provider  | INFO | DataProvider | DATA_PROVIDER_NUM_PROCESSES loaded from ENV: 32
data_provider  | INFO | DataProvider | DATA_PROVIDER_NUM_STATIONS loaded from ENV: 6000
```

### B. Verifikasi Environment Variable pada Service Lainnya

```powershell
# Cek variabel Kafka & Observabilitas pada P-Wave Detector
docker exec p_wave_detector env | Select-String -Pattern "KAFKA","METRICS"

# Cek variabel database InfluxDB & Mongo pada Data Archiver
docker exec eews-data_archiver-1 env | Select-String -Pattern "INFLUX","MONGO"

# Cek port observabilitas pada FastAPI WebSocket Server
docker exec fast_api env | Select-String -Pattern "FASTAPI","METRICS"

# Cek status aktifnya instrumentasi metrik di seluruh container
docker compose exec data_provider env | Select-String "ENABLE_METRICS"
```

