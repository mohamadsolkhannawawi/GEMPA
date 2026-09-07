# Panduan Pengujian Observabilitas EEWS — Skenario S1 hingga S5

Dokumen ini adalah panduan langkah-demi-langkah untuk melaksanakan seluruh pengujian BAB IV, mulai dari persiapan awal hingga semua file CSV output berhasil dikumpulkan. Skenario S1–S5 telah diurutkan berdasarkan aliran data (Data Flow) dari hulu (Ingestion) hingga ke hilir (Diseminasi).

---

## Daftar Isi

1. [Prasyarat dan Persiapan Awal](#1-prasyarat-dan-persiapan-awal)
2. [Mengambil Source Code](#2-mengambil-source-code)
3. [Pemasangan Dependensi Python](#3-pemasangan-dependensi-python)
4. [Validasi Sistem Sebelum Pengujian](#4-validasi-sistem-sebelum-pengujian)
5. [Panduan Pengambilan Screenshot](#5-panduan-pengambilan-screenshot)
6. [S1 — Optimasi Hulu (Strategi Konkurensi)](#6-s1--optimasi-hulu-strategi-konkurensi)
7. [S2 — Validasi Alat Ukur (Overhead Instrumentasi)](#7-s2--validasi-alat-ukur-overhead-instrumentasi)
8. [S3 — Pemilihan Arsitektur Inti (Load Balancing)](#8-s3--pemilihan-arsitektur-inti-load-balancing)
9. [S4 — Uji Skalabilitas (Stress Testing)](#9-s4--uji-skalabilitas-stress-testing)
10. [S5 — Optimasi Hilir (Perbandingan WebSocket)](#10-s5--optimasi-hilir-perbandingan-websocket)
11. [Menjalankan Semua Skenario Sekaligus](#11-menjalankan-semua-skenario-sekaligus)
12. [Checklist Output yang Harus Dikumpulkan](#12-checklist-output-yang-harus-dikumpulkan)
13. [Troubleshooting](#13-troubleshooting)
14. [Verifikasi Penyimpanan Data ke Database](#14-verifikasi-penyimpanan-data-ke-database)
15. [Referensi Mapping Skenario ke Compose File](#15-referensi-mapping-skenario-ke-compose-file)
16. [Panduan Eksekusi Otomatis per Skenario Spesifik](#16-panduan-eksekusi-otomatis-per-skenario-spesifik)
17. [Daftar Lengkap Perintah Eksekusi per Skenario](#17-daftar-lengkap-perintah-eksekusi-per-skenario)
18. [Analisis Hasil Pengujian (Otomatis)](#18-analisis-hasil-pengujian-otomatis)
19. [Menjalankan Aplikasi Dasbor Desktop Seismik (seismic_app)](#19-menjalankan-aplikasi-dasbor-desktop-seismik-seismic_app)
20. [Verifikasi dan Pengecekan Environment Variables Container](#20-verifikasi-dan-pengecekan-environment-variables-container)

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

Semua skrip pengumpul metrik membutuhkan library berikut. Pasang sekali saja menggunakan file requirements:

```powershell
pip install -r tests/requirements.txt
```

### Verifikasi

```powershell
python -c "import requests, websockets, docker; print('OK')"
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

## 6. S1 — Optimasi Hulu (Strategi Konkurensi)

**Tujuan:** Mengevaluasi mekanisme konkurensi (sekuensial, multi-thread, multi-process, atau gabungan) pada tahap ingesti data untuk mencegah data starvation di Kafka.

**Compose file yang digunakan:** `docker-compose-s1-sequential.yml` hingga `docker-compose-s1-mp_mt.yml`

**Output yang dihasilkan:**
- `tests/results/s1_sequential_stats.csv` & `metrics.csv`
- `tests/results/s1_multithread_stats.csv` & `metrics.csv`
- `tests/results/s1_multiprocess_stats.csv` & `metrics.csv`
- `tests/results/s1_mp_mt_stats.csv` & `metrics.csv`

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

---

## 7. S2 — Validasi Alat Ukur (Overhead Instrumentasi)

**Tujuan:** Mengukur selisih CPU (%), memori (MB), dan latensi (ms) antara sistem _tanpa_ instrumentasi Prometheus dan sistem _dengan_ instrumentasi Prometheus sebagai Margin of Error.

**Compose file yang digunakan:** `docker-compose-s2-no_metrics.yml` dan `docker-compose-s2-with_metrics.yml`

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

---

## 8. S3 — Pemilihan Arsitektur Inti (Load Balancing)

**Tujuan:** Membandingkan arsitektur message broker Kafka native (3 broker) secara head-to-head versus Kafka+NGINX sebagai HTTP load balancer eksternal untuk P-Wave Detector.

**Compose file yang digunakan:**
- Kafka Native: `docker-compose-s3-kafka.yml`
- Kafka + NGINX: `docker-compose-s3-nginx.yml`

**Output yang dihasilkan:**
- `tests/results/s3_broker_kafka_stats.csv` & `metrics.csv`
- `tests/results/s3_broker_nginx_stats.csv` & `metrics.csv`

### Cara Menjalankan S3 (Otomatis)

```powershell
cd tests
# Jalankan salah satu dari parameter berikut sesuai kebutuhan:
.\run_s3_broker.ps1 -ScenarioName Kafka
.\run_s3_broker.ps1 -ScenarioName NGINX
```

---

## 9. S4 — Uji Skalabilitas (Stress Testing)

**Tujuan:** Mencari titik jenuh komputasi (CPU Bound) pada P-Wave Detector dan hambatan I/O (I/O Bound) pada Data Archiver dengan menaikkan jumlah kontainer secara bertahap (1 hingga 5).

**Compose file yang digunakan:**
- Data Archiver (1–5 container): `docker-compose-s4-archiver-1c.yml` hingga `5c.yml`
- P-Wave Detector Kafka (2–5 container): `docker-compose-s4-pwave-kafka-2c.yml` hingga `5c.yml`
- P-Wave Detector Kafka-NGINX (2–5 container): `docker-compose-s4-pwave-kafka-nginx-2c.yml` hingga `5c.yml`

**Output yang dihasilkan:**
- Data Archiver: `tests/results/s4_archiver_1_container_stats.csv` dsb.
- P-Wave Kafka: `tests/results/s4_pwave_kafka_2c_stats.csv` dsb.
- P-Wave Kafka-NGINX: `tests/results/s4_pwave_kafka_nginx_2c_stats.csv` dsb.

### Cara Menjalankan S4 (Otomatis)

```powershell
cd tests

# Menjalankan seluruh variasi Archiver sekaligus:
.\run_s4_scalability_archiver.ps1

# Menjalankan seluruh variasi P-Wave sekaligus:
.\run_s4_scalability_pwave.ps1

# ATAU jalankan variasi spesifik:
.\run_s4_scalability_archiver.ps1 -ScenarioName 1c
.\run_s4_scalability_pwave.ps1 -ScenarioName Kafka2c
.\run_s4_scalability_pwave.ps1 -ScenarioName KafkaNginx2c
```

---

## 10. S5 — Optimasi Hilir (Perbandingan WebSocket)

**Tujuan:** Membandingkan performa Express.js/Socket.IO versus FastAPI dalam menangani diseminasi koneksi WebSocket pada 1 client dan 5 client konkuren.

**Compose file yang digunakan:**
- Express.js: `docker-compose-s5-express.yml`
- FastAPI: `docker-compose-s5-fastapi.yml`

**Output yang dihasilkan:**
- `tests/results/s5_websocket_express_1c_stats.csv` & `metrics.csv`
- `tests/results/s5_websocket_express_5c_stats.csv` & `metrics.csv`
- `tests/results/s5_websocket_fastapi_1c_stats.csv` & `metrics.csv`
- `tests/results/s5_websocket_fastapi_5c_stats.csv` & `metrics.csv`

### Cara Menjalankan S5 (Otomatis)

```powershell
cd tests
# Jalankan salah satu dari parameter berikut sesuai kebutuhan:
.\run_s5_websocket.ps1 -ScenarioName Express1c
.\run_s5_websocket.ps1 -ScenarioName Express5c
.\run_s5_websocket.ps1 -ScenarioName FastAPI1c
.\run_s5_websocket.ps1 -ScenarioName FastAPI5c
```

---

## 11. Menjalankan Semua Skenario Sekaligus

Jika Anda ingin menjalankan S1 hingga S5 secara berurutan tanpa intervensi manual, gunakan master runner:

```powershell
cd tests
.\run_all_tests.ps1
```

> **Perhatian:** Proses ini membutuhkan estimasi **1,5 hingga 3 jam** tergantung spesifikasi mesin. Pastikan komputer tidak masuk mode tidur (_sleep_) selama eksekusi.

Untuk mencegah komputer tidur saat tes berjalan panjang:

```powershell
while ($true) { [System.Console]::Write("."); Start-Sleep -Seconds 60 }
```

---

## 12. Checklist Output yang Harus Dikumpulkan

Tandai setiap item setelah berhasil dikumpulkan.

### File CSV per Skenario

**S1 — Optimasi Hulu (Strategi Konkurensi):**
- [ ] `s1_sequential_metrics.csv`
- [ ] `s1_multithread_metrics.csv`
- [ ] `s1_multiprocess_metrics.csv`
- [ ] `s1_mp_mt_metrics.csv`

**S2 — Validasi Alat Ukur (Overhead):**
- [ ] `s2_overhead_no_metrics_metrics.csv`
- [ ] `s2_overhead_with_metrics_metrics.csv`

**S3 — Pemilihan Arsitektur Inti (Load Balancer):**
- [ ] `s3_broker_kafka_metrics.csv`
- [ ] `s3_broker_nginx_metrics.csv`

**S4 — Uji Skalabilitas (Data Archiver 1-5c):**
- [ ] `s4_archiver_1_container_metrics.csv` (hingga `5_container`)

**S4 — Uji Skalabilitas (P-Wave Kafka 2-5c):**
- [ ] `s4_pwave_kafka_2c_metrics.csv` (hingga `5c`)

**S4 — Uji Skalabilitas (P-Wave Kafka-NGINX 2-5c):**
- [ ] `s4_pwave_kafka_nginx_2c_metrics.csv` (hingga `5c`)

**S5 — Optimasi Hilir (WebSocket Express vs FastAPI):**
- [ ] `s5_websocket_express_1c_metrics.csv`
- [ ] `s5_websocket_express_5c_metrics.csv`
- [ ] `s5_websocket_fastapi_1c_metrics.csv`
- [ ] `s5_websocket_fastapi_5c_metrics.csv`

---

## 13. Troubleshooting

### Pengecekan Log Error per Modul

Filter Semua Error Terkini Sekaligus (5 Menit Terakhir):
```powershell
docker compose logs --since 5m | Select-String "ERROR", "Exception", "Traceback"
```

Pengecekan Error Terkini per Modul Spesifik:
```powershell
# Data Provider
docker compose logs data_provider --since 5m | Select-String "ERROR"

# AI Detectors
docker compose logs p_wave_detector --since 5m | Select-String "ERROR"
docker compose logs loc_mag_detector --since 5m | Select-String "ERROR"

# Backend & APIs
docker compose logs data_archiver --since 5m | Select-String "ERROR"
docker compose logs api_server --since 5m | Select-String "ERROR"
docker compose logs fast_api --since 5m | Select-String "ERROR"

# Infrastruktur Inti
docker compose logs kafka1 --since 5m | Select-String "ERROR"
```

---

## 14. Verifikasi Penyimpanan Data ke Database

### A. Verifikasi InfluxDB (Penyimpanan Data Gelombang & Metrik)
```powershell
# Cek data gelombang seismik terbaru (bucket `eews`)
docker compose exec influxdb influx query 'from(bucket: \"eews\") |> range(start: -1m) |> tail(n: 10)' --token "eFWu0UGcCzvGAX1w-z43heHjfDk8swujfryImhIsTrAkNJOgfMRSYsgYVki-QTiWHDwKLJtxsSnCmHhxisCN1w==" --org "owner"
```

### B. Verifikasi MongoDB (Penyimpanan Hasil Deteksi AI)
```powershell
docker compose exec mongo mongosh
test> use timeseries_db
timeseries_db> db.timeseries_collection.find().sort({_id: -1}).limit(1)
```

### C. Verifikasi Prometheus (Penyimpanan Metrik Observabilitas)
Buka `http://localhost:9090` dan uji query: `data_provider_traces_sent_total`.

---

## 15. Referensi Mapping Skenario ke Compose File

| Kode Skenario (BAB III)     | Compose File              | Script Otomatis                |
| --------------------------- | ------------------------- | ------------------------------ |
| S1 — Strategi Konkurensi    | `docker-compose-s1-*.yml` | `run_s1_dataprovider.ps1`      |
| S2 — Overhead Instrumentasi | `docker-compose-s2-*.yml` | `run_s2_overhead.ps1`          |
| S3 — Arsitektur (Load Bal)  | `docker-compose-s3-*.yml` | `run_s3_broker.ps1`            |
| S4 — Skala Archiver (1-5 C) | `docker-compose-s4-archiver-*.yml` | `run_s4_scalability_archiver.ps1` |
| S4 — Skala P-Wave (2-5 C)   | `docker-compose-s4-pwave-*.yml`    | `run_s4_scalability_pwave.ps1`    |
| S5 — Diseminasi WebSocket   | `docker-compose-s5-*.yml` | `run_s5_websocket.ps1`         |

---

## 16. Panduan Eksekusi Otomatis per Skenario Spesifik

Jika Anda ingin menjalankan **hanya satu tipe skenario tertentu**, gunakan argumen `-ScenarioName` diikuti nama pendek skenario tersebut.

Contoh:
```powershell
.\run_s1_dataprovider.ps1 -ScenarioName Multiprocess
```

---

## 17. Daftar Lengkap Perintah Eksekusi per Skenario

Seluruh perintah di bawah ini harus dijalankan di dalam direktori `tests`.

```powershell
cd tests
```

### S1. Strategi Konkurensi Data Provider
```powershell
.\run_s1_dataprovider.ps1 -ScenarioName Sequential
.\run_s1_dataprovider.ps1 -ScenarioName Multithread
.\run_s1_dataprovider.ps1 -ScenarioName Multiprocess
.\run_s1_dataprovider.ps1 -ScenarioName MP_MT
```

### S2. Overhead Instrumentasi
```powershell
.\run_s2_overhead.ps1 -ScenarioName NoMetrics
.\run_s2_overhead.ps1 -ScenarioName WithMetrics
```

### S3. Load Balancer Message Broker
```powershell
.\run_s3_broker.ps1 -ScenarioName Kafka
.\run_s3_broker.ps1 -ScenarioName NGINX
```

### S4. Skalabilitas Data Archiver
```powershell
.\run_s4_scalability_archiver.ps1 -ScenarioName 1c
.\run_s4_scalability_archiver.ps1 -ScenarioName 5c
```

### S4. Skalabilitas P-Wave Detector
```powershell
.\run_s4_scalability_pwave.ps1 -ScenarioName Kafka2c
.\run_s4_scalability_pwave.ps1 -ScenarioName KafkaNginx2c
```

### S5. WebSocket Server Diseminasi
```powershell
.\run_s5_websocket.ps1 -ScenarioName Express1c
.\run_s5_websocket.ps1 -ScenarioName Express5c
.\run_s5_websocket.ps1 -ScenarioName FastAPI1c
.\run_s5_websocket.ps1 -ScenarioName FastAPI5c
```

---

## 18. Analisis Hasil Pengujian (Otomatis)

Buka terminal di root folder `MDLBEEWS` dan jalankan:

```powershell
# Untuk menganalisis Skenario 1 (Konkurensi)
python tests/analyze.py --scenario 1

# Untuk memproses dan menampilkan SEMUA skenario sekaligus
python tests/analyze.py --scenario all
```

---

## 19. Menjalankan Aplikasi Dasbor Desktop Seismik (`seismic_app`)

```powershell
# 1. Jalankan Infrastruktur Backend (contoh S5 Express)
docker compose -f docker-compose-s5-express.yml up -d

# 2. Buka terminal baru, masuk ke folder aplikasi
cd seismic_app
pip install -r requirements.txt

# 3. Jalankan aplikasi Dasbor Desktop
python main.py
```

---

## 20. Verifikasi dan Pengecekan Environment Variables Container

Untuk memverifikasi bahwa container membaca konfigurasi dari `.env`:

```powershell
# Cek log startup aplikasi (memastikan "loaded from ENV" tercetak)
docker compose logs data_provider | Select-String "DATA_PROVIDER_NUM"

# Cek status aktifnya instrumentasi metrik di seluruh container
docker compose exec data_provider env | Select-String "ENABLE_METRICS"
```


