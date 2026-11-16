# Panduan Pengujian Observabilitas Sistem GEMPA — Skenario S1 hingga S5 dan Konfigurasi Akhir

Dokumen ini adalah panduan kerja operasional komprehensif untuk melaksanakan seluruh rangkaian pengujian performa sistem GEMPA (*Earthquake Early Warning System* berbasis *microservices*). Panduan ini telah diperbarui secara menyeluruh mengikuti standar perbaikan kode **K1 s.d. K17**, perbaikan logika **A1 s.d. A13**, serta protokol validasi **B1 s.d. B10**.

---

## Daftar Isi

1. [Prasyarat, Spesifikasi Mesin, dan Persiapan Awal](#1-prasyarat-spesifikasi-mesin-dan-persiapan-awal)
2. [Landasan Sumber Data Streaming SeedLink & Kuota Kanal](#2-landasan-sumber-data-streaming-seedlink--kuota-kanal)
3. [Uji Gerbang Validasi — Fase 0 (T0.1 s.d. T0.6)](#3-uji-gerbang-validasi--fase-0-t01-sd-t06)
4. [Daftar Formula Kueri PromQL Standar (Histogram Agregat & Metrik Baru)](#4-daftar-formula-kueri-promql-standar-histogram-agregat--metrik-baru)
5. [Protokol Eksekusi Pengujian Skenario S1 hingga S5](#5-protokol-eksekusi-pengujian-skenario-s1-hingga-s5)
   - [S1 — Strategi Konkurensi Data Provider](#s1--strategi-konkurensi-data-provider)
   - [S2 — Biaya Overhead Observabilitas Penuh](#s2--biaya-overhead-observabilitas-penuh)
   - [S3 — Topologi Load Balancing P-Wave (Kafka vs NGINX)](#s3--topologi-load-balancing-p-wave-kafka-vs-nginx)
   - [S4 — Uji Skalabilitas Beban (Data Archiver & P-Wave 2–6 Replika)](#s4--uji-skalabilitas-beban-data-archiver--p-wave-26-replika)
   - [S5 — Diseminasi WebSocket (Express.js vs FastAPI)](#s5--diseminasi-websocket-expressjs-vs-fastapi)
6. [Pengujian Validasi Konfigurasi Akhir Utuh (Subbab 4.8)](#6-pengujian-validasi-konfigurasi-akhir-utuh-subbab-48)
7. [Uji Ketahanan dan Isolasi Kegagalan (KNF-02 Failover)](#7-uji-ketahanan-dan-isolasi-kegagalan-knf-02-failover)
8. [Analisis Data Otomatis & Pemodelan USL (analyze.py)](#8-analisis-data-otomatis--pemodelan-usl-analyzepy)
9. [Daftar Luaran Deliverables yang Wajib Dikumpulkan](#9-daftar-luaran-deliverables-yang-wajib-dikumpulkan)
10. [Verifikasi Penyimpanan Database & Troubleshooting](#10-verifikasi-penyimpanan-database--troubleshooting)

---

## 1. Prasyarat, Spesifikasi Mesin, dan Persiapan Awal

### A. Spesifikasi Mesin Pengujian (*Host Metadata*)
Seluruh inferensi model pembelajaran mesin (CNN-LSTM P-Wave) berjalan murni pada CPU host (GPU NVIDIA tidak digunakan):
- **CPU:** Intel Core i9-14900 (24 Core / 32 Thread; dialokasikan 16 core untuk runtime WSL 2).
- **RAM:** 64 GB DDR5 (dialokasikan 32 GB untuk WSL 2 + 4 GB swap).
- **OS:** Windows 11 Pro 64-bit / WSL 2 (Ubuntu 22.04 LTS kernel 5.15+).
- **Docker:** Docker Desktop v4.34+ (Docker Engine 27.x, Docker Compose v2.29+).

### B. Software & Environment
| Software | Versi Minimum | Cara Verifikasi |
| :--- | :--- | :--- |
| Docker Desktop | 4.x | `docker --version` |
| Docker Compose | 2.20+ | `docker compose version` |
| Python | 3.10 s.d. 3.12 | `python --version` |
| Git | 2.x | `git --version` |
| PowerShell | 5.1+ / 7.x | `$PSVersionTable.PSVersion` |

### C. Persiapan Direktori & File Konfigurasi
1. Pastikan Anda berada pada repositori proyek terkini:
   ```powershell
   git pull origin main
   git log -1 --oneline
   # Pastikan commit hash berada pada 0ca46d7 atau lebih baru
   ```
2. Pastikan file `.env` di *root folder* telah terisi token dan parameter standar:
   - `PWAVE_THRESHOLD=0.9`
   - `PWAVE_CONSEC=20`
   - `DATA_PROVIDER_NUM_STATIONS=5984`
   - `DATA_PROVIDER_MODE=multiprocess`
   - `STALE_SECONDS=60`
   - `LB_TARGET_URL=http://nginx_load_balancer:80/trace`
   - `INFLUXDB_TOKEN=bhIGAk5dlA2gJm1WUG3GmUu_UNtY4G4TVoU2T0vIQBg5o3stlAXsxYoOrKA7ttUhSq8rS3QA1Y-K1wKCTiAGuQ==`
   - `INFLUXDB_ORG=owner`
   - `INFLUXDB_BUCKET=gempa`
3. Pasang pustaka dependensi Python untuk modul pengujian:
   ```powershell
   pip install -r tests/requirements.txt
   ```

---

## 2. Landasan Sumber Data Streaming SeedLink & Kuota Kanal

Pengujian sistem GEMPA menggunakan sumber data aliran langsung (*real-time streaming*) dari server SeedLink GEOFON Potsdam Jerman (`geofon.gfz-potsdam.de:18000`). Tidak ada simulator sintetis atau pemutaran ulang berkas historis (.mseed).

1. **Validitas SeedLink:** 
   - **S1:** Menguji kemampuan konkurensi Data Provider dalam menangani I/O penantian jaringan riil.
   - **S2 s.d. S5:** Variabilitas internet diserap oleh partisi Kafka sebagai *buffer*, sehingga modul hilir menerima beban aliran kerja stabil.
2. **Penyaring Paket Basi (*Stale Filter*):**
   - Paket data dengan keterlambatan jaringan $> 60$ detik (`time.time() - endtime > 60`) otomatis disaring dan dicatat pada metrik `data_provider_traces_dropped_stale_total`.
3. **Standarisasi Kuota Beban (Tepat 5.984 Kanal):**
   - Kuota kanal dibatasi tepat **5.984 kanal** ($187\text{ kanal/pekerja} \times 32\text{ unit konkurensi}$). Pembagian ini seragam di seluruh mode konkurensi sehingga tidak ada unit pekerja yang menanggung beban sisa (*zero load imbalance*).

---

## 3. Uji Gerbang Validasi — Fase 0 (T0.1 s.d. T0.6)

Sebelum mengeksekusi skenario S1 s.d. S5, jalankan seluruh uji gerbang berikut untuk membuktikan lingkungan pengujian siap dan valid.

### T0.1 — Uji Unit Normalisasi & Ambang Deteksi P-Wave
Buktikan bahwa `normalize_batch` dan `detect` pada `utils/pwave_common.py` menghasilkan keluaran identik dan deterministik:
```powershell
cd tests
python -c "import sys; sys.path.insert(0, '..'); import numpy as np; from utils.pwave_common import normalize_batch, detect; d=np.random.randn(5,160,3); assert normalize_batch(d).shape==(5,160,3); p=np.zeros(50); p[10:30]=0.95; idx,m=detect(p,0.9,20); assert idx==10; print('T0.1 PASS')"
```

### T0.2 — Verifikasi Partisi Topik Kafka Deterministik
Buktikan bahwa layanan `kafka-init` membuat topik dengan jumlah partisi dan *replication factor* (RF) sesuai desain:
```powershell
cd ..
docker compose -f docker-compose-s3-kafka.yml up -d zookeeper kafka1 kafka2 kafka3 kafka-init
docker exec kafka1 kafka-topics --bootstrap-server kafka1:9092 --describe
```
*Kriteria Lolos:*
- `trace_topic`: 5 partisi, PartitionCount: 5, ReplicationFactor: 2.
- `p_wave_topic`: 5 partisi, PartitionCount: 5, ReplicationFactor: 1.
- `loc_mag_topic`: 3 partisi, PartitionCount: 3, ReplicationFactor: 1.
- `result_loc_mag_topic`: 3 partisi, PartitionCount: 3, ReplicationFactor: 1.

Bersihkan kontainer uji:
```powershell
docker compose -f docker-compose-s3-kafka.yml down -v
```

### T0.3 — Uji Perataan Beban Load Balancer (< 10% Skew)
Jalankan NGINX Load Balancer dengan 3 replika P-Wave, kirim 1.000 permintaan uji sintesis, dan verifikasi distribusi:
```powershell
# Jalankan S3 NGINX
docker compose -f docker-compose-s3-nginx.yml up -d
# Periksa metrik perataan beban di Prometheus:
# Query: sum by (replica) (rate(lb_forwarded_by_replica_total[1m]))
# Selisih distribusi antarreplika wajib < 10%.
docker compose -f docker-compose-s3-nginx.yml down -v
```

### T0.4 — Verifikasi Agregasi Histogram PromQL `sum by (le)`
Pastikan kueri persentil 95 pada Prometheus menggunakan sintaks agregasi lintas replika:
`histogram_quantile(0.95, sum by (le) (rate(pwave_inference_latency_seconds_bucket[1m])))`
Hasil kueri wajib menghasilkan deret tunggal teragregasi.

### T0.5 — Uji Ketahanan 5 Replika Kontainer Native (Bebas OOM)
Nyalakan 5 replika kontainer Native P-Wave selama 10 menit. Periksa metadata status kontainer:
```powershell
docker inspect --format='{{.Name}}: OOMKilled={{.State.OOMKilled}} Restarts={{.RestartCount}}' $(docker ps -aq --filter "name=p_wave_detector")
```
*Kriteria Lolos:* `OOMKilled=false` dan `Restarts=0` pada seluruh 5 replika.

### T0.6 — Verifikasi Rebalance Kafka Consumer Group
Catat proses rebalance partisi saat replika ditambahkan dari 2 ke 3, pastikan tidak terjadi *deadlock* konsumsi.

---

## 4. Daftar Formula Kueri PromQL Standar (Histogram Agregat & Metrik Baru)

Semua kueri latensi wajib menggunakan `sum by (le)` agar mewakili seluruh replika secara proporsional.

| No | Metrik Evaluasi | Rumus PromQL Standar | Deskripsi & Tujuan |
| :--- | :--- | :--- | :--- |
| 1 | **Throughput Trace (Hulu)** | `sum(rate(data_provider_traces_sent_total{topic="trace_topic"}[1m]))` | Laju paket sinyal seismik masuk ke broker. |
| 2 | **Throughput P-Wave Topic** | `sum(rate(data_provider_traces_sent_total{topic="p_wave_topic"}[1m]))` | Laju paket yang dialirkan ke topik inferensi P-Wave. |
| 3 | **Paket Basi Tersaring** | `sum(rate(data_provider_traces_dropped_stale_total[1m]))` | Paket yang dibuang karena delay jaringan $> 60$s. |
| 4 | **Laju Deteksi $C(N)$** | `sum(rate(pwave_inference_latency_seconds_count[1m]))` | Kapasitas inferensi aktual P-Wave (Native). |
| 5 | **Laju Deteksi LB $C(N)$** | `sum(rate(pwave_lb_inference_latency_seconds_count[1m]))` | Kapasitas inferensi aktual P-Wave (NGINX Mode). |
| 6 | **Latensi Inferensi P95** | `histogram_quantile(0.95, sum by (le) (rate(pwave_inference_latency_seconds_bucket[1m])))` | Durasi murni eksekusi model CNN-LSTM (Native). |
| 7 | **Latensi Inferensi LB P95** | `histogram_quantile(0.95, sum by (le) (rate(pwave_lb_inference_latency_seconds_bucket[1m])))` | Durasi inferensi model CNN-LSTM (NGINX Mode). |
| 8 | **Penundaan Kafka P95** | `histogram_quantile(0.95, sum by (le) (rate(pwave_kafka_delay_seconds_bucket[1m])))` | Waktu transit pesan di broker sebelum diambil worker. |
| 9 | **Antrean Worker P95** | `histogram_quantile(0.95, sum by (le) (rate(pwave_queue_wait_seconds_bucket[1m])))` | Waktu tunggu paket dalam antrean internal worker. |
| 10 | **Latensi Forward LB P95** | `histogram_quantile(0.95, sum by (le) (rate(lb_forward_latency_seconds_bucket[1m])))` | Waktu penerusan HTTP dari LB ke NGINX replika. |
| 11 | **Latensi End-to-End P95** | `histogram_quantile(0.95, sum by (le) (rate(pwave_end_to_end_latency_seconds_bucket[1m])))` | Waktu total dari stempel waktu hulu hingga inferensi selesai. |
| 12 | **Kapasitas Archiver** | `sum(rate(archiver_records_saved_total{storage="influxdb"}[1m]))` | Laju penulisan rekaman bersih ke InfluxDB. |
| 13 | **Latensi Broadcast WS P95**| `histogram_quantile(0.95, sum by (le) (rate(ws_broadcast_latency_seconds_bucket[1m])))` | Durasi broadcast Socket.IO Express (nanodetik/ms). |
| 14 | **Latensi Broadcast FastAPI**| `histogram_quantile(0.95, sum by (le) (rate(fastapi_ws_broadcast_latency_seconds_bucket[1m])))`| Durasi broadcast WebSocket FastAPI (`perf_counter`). |
| 15 | **CPU Worker P-Wave (%)** | `sum(docker_container_cpu_usage_percent{container_name=~".*p_wave_detector.*"})` | Beban CPU seluruh pekerja P-Wave Detector. |
| 16 | **RAM Worker P-Wave (MB)** | `sum(docker_container_mem_usage{container_name=~".*p_wave_detector.*"}) / 1048576` | Penggunaan memori fisik pekerja P-Wave. |
| 17 | **Biaya CPU Stack Observabilitas** | `sum(docker_container_cpu_usage_percent{container_name=~".*(prometheus|grafana|telegraf|node-exporter).*"})` | Total beban observabilitas penuh (S2). |
| 18 | **Biaya RAM Stack Observabilitas** | `sum(docker_container_mem_usage{container_name=~".*(prometheus|grafana|telegraf|node-exporter).*"}) / 1048576` | Total memori observabilitas penuh (S2). |
| 19 | **Lag Antrean Kafka** | `sum(kafka_consumergroup_lag)` | Akumulasi lag antrean partisi dari `kafka-exporter`. |

---

## 5. Protokol Eksekusi Pengujian Skenario S1 hingga S5

Seluruh skrip pengujian berada di dalam direktori `tests`. Jalankan perintah pengujian dengan protokol baku:
- **`-Repeat 3`**: Pengujian wajib diulang sebanyak 3 kali per konfigurasi.
- **`-Shuffle`**: Urutan skenario diacak otomatis guna meminimalkan efek *caching* dan bias termal CPU.
- **`Wait-SystemReady`**: Gerbang kesiapan aktif secara otomatis memvalidasi kesiapan Kafka dan Prometheus sebelum pencatatan metrik dimulai.
- **Fairness Window (Detik 50–200)**: Analisis metrik membuang 50 detik pertama (transien *warmup*) dan mengambil 150 detik fase stabil (*steady-state*).
- **`--dump-buckets`**: Nilai kumulatif seluruh bucket histogram tersimpan ke CSV mentah untuk verifikasi P95 sejati.
- **Jeda Pendinginan (*Cooldown*)**: Skrip otomatis memberi jeda 120 detik antar-run untuk pembersihan memori.

```powershell
cd tests
```

---

### S1 — Strategi Konkurensi Data Provider
Mengevaluasi 4 mekanisme *ingestion*: Sekuensial, Multi-Threading, Multi-Processing, dan Gabungan (MP+MT) pada kuota 5.984 kanal.

```powershell
# Eksekusi 3x pengulangan acak
.\run_s1_dataprovider.ps1 -Repeat 3 -Shuffle

# ATAU eksekusi variasi individual:
.\run_s1_dataprovider.ps1 -ScenarioName Sequential -Repeat 3
.\run_s1_dataprovider.ps1 -ScenarioName Multithread -Repeat 3
.\run_s1_dataprovider.ps1 -ScenarioName Multiprocess -Repeat 3
.\run_s1_dataprovider.ps1 -ScenarioName MP_MT -Repeat 3
```
*Luaran:* `tests/results/s1_*_metrics.csv` dan `*_dump_buckets.csv`.

---

### S2 — Biaya Overhead Observabilitas Penuh
Mengukur beban instrumentasi aplikasi dan beban *full stack* observabilitas (`prometheus`, `grafana`, `telegraf`, `node-exporter`):

```powershell
# Eksekusi 3x pengulangan acak
.\run_s2_overhead.ps1 -Repeat 3 -Shuffle

# ATAU eksekusi kondisi spesifik:
.\run_s2_overhead.ps1 -ScenarioName NoMetrics -Repeat 3
.\run_s2_overhead.ps1 -ScenarioName WithMetrics -Repeat 3
```
*Luaran:* `tests/results/s2_overhead_*_metrics.csv` dan log Telegraf host.

---

### S3 — Topologi Load Balancing P-Wave (Kafka vs NGINX)
Membandingkan pembagian beban berbasis *Consumer Group* (Kafka Native) versus *HTTP Round-Robin* (NGINX Load Balancer) pada 3 replika pekerja P-Wave:

```powershell
# Eksekusi 3x pengulangan acak
.\run_s3_broker.ps1 -Repeat 3 -Shuffle

# ATAU eksekusi per topologi:
.\run_s3_broker.ps1 -ScenarioName Kafka -Repeat 3
.\run_s3_broker.ps1 -ScenarioName NGINX -Repeat 3
```
*Luaran:* `tests/results/s3_broker_*_metrics.csv`.

---

### S4 — Uji Skalabilitas Beban (Data Archiver & P-Wave 2–6 Replika)
Mengevaluasi skalabilitas horizontal dan membuktikan titik jenuh komputasi Universal Scalability Law (USL):

#### A. Skalabilitas Data Archiver (1 s.d. 5 Kontainer)
```powershell
.\run_s4_scalability_archiver.ps1 -Repeat 3
```

#### B. Skalabilitas P-Wave Detector (2 s.d. 5 Replika Native & 2 s.d. 6 Replika NGINX)
Khusus NGINX, pengujian menyertakan **6 replika** (`docker-compose-s4-pwave-kafka-nginx-6c.yml`) untuk memvalidasi titik puncak optimal $N^* = 6{,}40$:
```powershell
.\run_s4_scalability_pwave.ps1 -Repeat 3

# ATAU eksekusi konfigurasi tertentu:
.\run_s4_scalability_pwave.ps1 -ScenarioName Kafka2c -Repeat 3
.\run_s4_scalability_pwave.ps1 -ScenarioName KafkaNginx6c -Repeat 3
```
*Luaran:* `tests/results/s4_archiver_*_metrics.csv` dan `tests/results/s4_pwave_*_metrics.csv`.

---

### S5 — Diseminasi WebSocket (Express.js vs FastAPI)
Membandingkan performa *broadcast* data gempa ke 1 klien dan 5 klien konkuren:

```powershell
# Eksekusi 3x pengulangan acak
.\run_s5_websocket.ps1 -Repeat 3 -Shuffle

# ATAU eksekusi variasi individual:
.\run_s5_websocket.ps1 -ScenarioName Express1c -Repeat 3
.\run_s5_websocket.ps1 -ScenarioName Express5c -Repeat 3
.\run_s5_websocket.ps1 -ScenarioName FastAPI1c -Repeat 3
.\run_s5_websocket.ps1 -ScenarioName FastAPI5c -Repeat 3
```
*Luaran:* `tests/results/s5_websocket_*_metrics.csv` dan ringkasan latensi sisi klien.

---

## 6. Pengujian Validasi Konfigurasi Akhir Utuh (Subbab 4.8)

Untuk membuktikan performa arsitektur produksi final sistem GEMPA yang direkomendasikan pada Subbab 4.8:
- **Data Provider:** Mode Multiprocess (5.984 kanal).
- **Arsitektur P-Wave:** NGINX Load Balancer dengan 5 Replika ML Worker.
- **Penyimpanan:** 3 Replika Data Archiver (InfluxDB & MongoDB).
- **Diseminasi:** FastAPI WebSocket.
- **Keandalan:** Kontainer `restarter` berkala aktif merestart worker secara bergilir setiap 600 detik tanpa memutus aliran sistem.

Eksekusi 3 kali pengulangan (masing-masing 300 detik):
```powershell
cd ..
# Run 1
docker compose -f docker-compose-final.yml up -d --build
python tests/collect_metrics.py --duration 300 --interval 5 --output tests/results/final_production_run1.csv --dump-buckets
docker compose -f docker-compose-final.yml down -v
Start-Sleep -Seconds 120

# Run 2
docker compose -f docker-compose-final.yml up -d
python tests/collect_metrics.py --duration 300 --interval 5 --output tests/results/final_production_run2.csv --dump-buckets
docker compose -f docker-compose-final.yml down -v
Start-Sleep -Seconds 120

# Run 3
docker compose -f docker-compose-final.yml up -d
python tests/collect_metrics.py --duration 300 --interval 5 --output tests/results/final_production_run3.csv --dump-buckets
docker compose -f docker-compose-final.yml down -v
```

---

## 7. Uji Ketahanan dan Isolasi Kegagalan (KNF-02 Failover)

Uji ini membuktikan persyaratan non-fungsional KNF-02 bahwa kegagalan satu replika pekerja tidak menimbulkan kegagalan berantai (*zero cascading failure*):

1. Jalankan arsitektur NGINX dengan 3 replika:
   ```powershell
   docker compose -f docker-compose-s3-nginx.yml up -d
   ```
2. Saat aliran data sedang berlangsung (setelah detik ke-60), matikan paksa satu kontainer pekerja P-Wave secara sengaja:
   ```powershell
   docker stop gempa-p_wave_detector_load_balance-1
   ```
3. Pantau log Load Balancer, Data Archiver, dan WebSocket:
   ```powershell
   docker logs --tail 20 gempa-load_balancer-1
   docker logs --tail 20 gempa-data_archiver-1
   ```
4. **Verifikasi Keberhasilan:** 
   - Load Balancer otomatis mengalihkan *traffic* HTTP ke replika 2 dan 3 yang masih hidup.
   - Metrik `lb_forward_errors_total` mencatat lonjakan transien singkat lalu kembali normal.
   - Modul `data_archiver` dan WebSocket tetap memproses dan menyiarkan data tanpa terhenti (*no cascading crash*).
5. Bersihkan kontainer:
   ```powershell
   docker compose -f docker-compose-s3-nginx.yml down -v
   ```

---

## 8. Analisis Data Otomatis & Pemodelan USL (analyze.py)

Setelah seluruh berkas CSV terkumpul di folder `tests/results/`, jalankan analisis otomatis:

```powershell
cd tests
# Analisis seluruh skenario sekaligus
python analyze.py --scenario all
```

### Mekanisme Pengolahan Data di `analyze.py`:
1. **Time-Based Windowing:** Mengabaikan 50 detik pertama sejak data mulai tercatat dan menganalisis 150 detik fase stabil berikutnya.
2. **True P95 Calculation:** Menghitung persentil 95 sebenarnya dari selisih nilai kumulatif bucket histogram (`--dump-buckets`) antara akhir jendela dan awal jendela.
3. **Penyaringan Run INVALID:** Run otomatis ditandai `INVALID` dan dikeluarkan dari tabel ringkasan jika:
   - Jumlah baris sampel kurang dari 90% target waktu.
   - Kolom metrik bernilai NaN/kosong lebih dari 10%.
   - Ditemukan kontainer berstatus `OOMKilled` atau restart tak terduga.
4. **Regresi USL (Universal Scalability Law):**
   - Menghitung koefisien *contention* ($\sigma$), koefisien *coherency* ($\kappa$), dan kapasitas puncak optimal ($N^*$).
   - Regresi dihitung menggunakan kapasitas laju deteksi $C(N)$ murni (`sum(rate(pwave_inference_latency_seconds_count[1m]))`), bukan laju paket masuk.

---

## 9. Daftar Luaran Deliverables yang Wajib Dikumpulkan

Setelah pengujian tuntas, pastikan berkas-berkas berikut tersedia di repositori untuk penyusunan BAB IV:

- [ ] **Keluaran Mentah Fase 0:** Catatan teks eksekusi T0.1 s.d. T0.6.
- [ ] **CSV Mentah Seluruh Run:** Berkas `tests/results/*_metrics.csv` untuk S1–S5 dan Final (minimal 3 run per skenario).
- [ ] **CSV Dump Buckets:** Berkas `tests/results/*_dump_buckets.csv` untuk verifikasi persentil sejati.
- [ ] **Metadata Run JSON:** Berkas metadata yang mencatat status `OOMKilled`, `RestartCount`, dan *commit hash* per run.
- [ ] **Tabel Statistik Ringkasan:** Hasil keluaran `analyze.py` (mean, std dev, min, max, P95 sejati).
- [ ] **Tabel Parameter USL:** Nilai $\sigma$, $\kappa$, dan $N^*$ untuk Native vs NGINX.
- [ ] **Keluaran Telegraf & Offset Kafka:** Log metrik host untuk S2 dan lag antrean partisi.

---

## 10. Verifikasi Penyimpanan Database & Troubleshooting

### A. Verifikasi InfluxDB (Penyimpanan Rekaman Seismik)
```powershell
# Jalankan kueri data mentah dari bucket gempa
docker compose exec influxdb influx query 'from(bucket: "gempa") |> range(start: -5m) |> tail(n: 5)' --token "bhIGAk5dlA2gJm1WUG3GmUu_UNtY4G4TVoU2T0vIQBg5o3stlAXsxYoOrKA7ttUhSq8rS3QA1Y-K1wKCTiAGuQ==" --org "owner"
```

### B. Verifikasi MongoDB (Hasil Deteksi AI)
```powershell
docker compose exec mongo mongosh -u admin -p UNDIPJAYA --eval "use timeseries_db; db.timeseries_collection.find().sort({_id: -1}).limit(3)"
```

### C. Troubleshooting Kendala Umum
1. **Topik Kafka Belum Siap (*Topic Not Found*):**
   - Pastikan kontainer `kafka-init` telah selesai berjalan (`Exited (0)`). Layanan ini otomatis membuat partisi deterministik.
2. **Prometheus Menolak Kueri (*Out of Order*):**
   - Pastikan jam pada host Windows dan WSL 2 tersinkronisasi: `wsl -d docker-desktop hwclock -s`.
3. **Pembersihan Bersih Total (*Clean Slate*):**
   - Jika ingin mengulang pengujian dari awal tanpa residu volume:
     ```powershell
     docker stop $(docker ps -aq)
     docker rm $(docker ps -aq)
     docker volume prune -f
     ```
