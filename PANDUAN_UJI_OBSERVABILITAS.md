# Panduan Pengujian Observabilitas Sistem GEMPA: Skenario S1 hingga S5 dan Konfigurasi Akhir

Dokumen ini merupakan panduan operasional resmi untuk melaksanakan seluruh rangkaian pengujian kinerja dan observabilitas pada sistem GEMPA (*Earthquake Early Warning System* berbasis arsitektur mikrolayanan). Panduan ini merinci prosedur pelaksanaan uji, instrumen metrik, skrip otomasi pengujian, hingga pengolahan data statistik untuk kebutuhan evaluasi kinerja sistem pada Bab IV.

---

## Daftar Isi

1. [Prasyarat dan Spesifikasi Lingkungan Pengujian](#1-prasyarat-dan-spesifikasi-lingkungan-pengujian)
2. [Karakteristik Beban Kerja dan Sumber Data SeedLink](#2-karakteristik-beban-kerja-dan-sumber-data-seedlink)
3. [Tahap Verifikasi Awal: Uji Gerbang Validasi (Fase 0)](#3-tahap-verifikasi-awal-uji-gerbang-validasi-fase-0)
4. [Spesifikasi Metrik dan Formula Kueri PromQL](#4-spesifikasi-metrik-dan-formula-kueri-promql)
5. [Prosedur Pengujian Skenario S1 hingga S5](#5-prosedur-pengujian-skenario-s1-hingga-s5)
   - [S1: Strategi Konkurensi Data Provider](#s1-strategi-konkurensi-data-provider)
   - [S2: Beban Overhead Observabilitas Penuh](#s2-beban-overhead-observabilitas-penuh)
   - [S3: Topologi Load Balancing Message Broker](#s3-topologi-load-balancing-message-broker)
   - [S4: Skalabilitas Beban Data Archiver dan P-Wave Detector](#s4-skalabilitas-beban-data-archiver-dan-p-wave-detector)
   - [S5: Diseminasi WebSocket Klien Konkuren](#s5-diseminasi-websocket-klien-konkuren)
6. [Prosedur Pengujian Konfigurasi Akhir Sistem GEMPA](#6-prosedur-pengujian-konfigurasi-akhir-sistem-gempa)
7. [Pengujian Keandalan dan Isolasi Kegagalan (KNF-02)](#7-pengujian-keandalan-dan-isolasi-kegagalan-knf-02)
8. [Analisis Data Statistik dan Pemodelan Skalabilitas (USL)](#8-analisis-data-statistik-dan-pemodelan-skalabilitas-usl)
9. [Daftar Luaran Pengujian (Deliverables)](#9-daftar-luaran-pengujian-deliverables)
10. [Verifikasi Penyimpanan Data dan Penanganan Kendala](#10-verifikasi-penyimpanan-data-dan-penanganan-kendala)

---

## 1. Prasyarat dan Spesifikasi Lingkungan Pengujian

### A. Spesifikasi Mesin Pengujian
Seluruh inferensi model pembelajaran mesin (CNN-LSTM P-Wave) berjalan murni pada unit pemroses utama (CPU) komputer host, dan akselerator grafis (GPU) tidak digunakan:
- CPU: Intel Core i9-14900 (24 inti fisik, 32 untaian komputasi, dengan alokasi 16 inti logika untuk subsistem WSL 2).
- RAM: 64 GB DDR5 (dengan alokasi 32 GB memori fisik untuk WSL 2 dan 4 GB ruang *swap*).
- Sistem Operasi: Windows 11 Pro 64-bit dan WSL 2 berbasis Ubuntu 22.04 LTS.
- Docker Engine: Docker Desktop v4.34 atau lebih baru (Docker Compose v2.29 atau lebih baru).

### B. Perangkat Lunak Pendukung
| Perangkat Lunak | Versi Minimum | Perintah Verifikasi |
| :--- | :--- | :--- |
| Docker Desktop | 4.x | `docker --version` |
| Docker Compose | 2.20+ | `docker compose version` |
| Python Runtime | 3.10 s.d. 3.12 | `python --version` |
| Git Client | 2.x | `git --version` |
| PowerShell | 5.1+ / 7.x | `$PSVersionTable.PSVersion` |

### C. Persiapan Repositori dan Berkas Lingkungan
1. Masuk ke direktori utama repositori GEMPA dan pastikan cabang kerja berada pada versi terbaru:
   ```powershell
   git pull origin main
   git log -1 --oneline
   ```
2. Pastikan berkas konfigurasi `.env` pada direktori utama telah terisi parameter operasional standar:
   - `PWAVE_THRESHOLD=0.9`
   - `PWAVE_CONSEC=20`
   - `DATA_PROVIDER_NUM_STATIONS=5984`
   - `DATA_PROVIDER_MODE=multiprocess`
   - `STALE_SECONDS=60`
   - `LB_TARGET_URL=http://nginx_load_balancer:80/trace`
   - `INFLUXDB_TOKEN=bhIGAk5dlA2gJm1WUG3GmUu_UNtY4G4TVoU2T0vIQBg5o3stlAXsxYoOrKA7ttUhSq8rS3QA1Y-K1wKCTiAGuQ==`
   - `INFLUXDB_ORG=owner`
   - `INFLUXDB_BUCKET=gempa`
3. Pasang seluruh pustaka Python yang dibutuhkan untuk modul pengujian:
   ```powershell
   pip install -r tests/requirements.txt
   ```

---

## 2. Karakteristik Beban Kerja dan Sumber Data SeedLink

Pengujian sistem GEMPA menggunakan pasokan data aliran langsung (*real-time streaming*) dari server SeedLink GEOFON Potsdam Jerman (`geofon.gfz-potsdam.de:18000`). Pengujian ini tidak menggunakan simulator data sintetis atau pemutaran ulang berkas historis.

1. Rasionalisasi Sumber Data:
   - Pada Skenario 1, penantian transmisi jaringan SeedLink menjadi beban I/O aktual yang dievaluasi efisiensi konkurensinya.
   - Pada Skenario 2 hingga Skenario 5, variabilitas internet diredam oleh partisi Kafka sebagai penyangga (*buffer*), sehingga beban kerja yang dialirkan ke komponen hilir tetap stabil.
2. Penyaring Paket Tertunda (*Stale Filter*):
   Paket rekaman dengan keterlambatan jaringan melebihi 60 detik langsung disaring dan dicatat pada metrik `data_provider_traces_dropped_stale_total`. Langkah ini menjamin bahwa seluruh data yang diproses oleh P-Wave Detector mencerminkan kondisi gempa bumi langsung.
3. Kuota Kanal Standar:
   Beban kerja dibatasi tepat 5.984 kanal stasiun seismik, yang terbagi rata ke dalam 32 pekerja komputasi (187 kanal per unit pekerja). Pembagian seragam ini meniadakan sisa kanal yang dapat memicu ketimpangan alokasi beban (*load imbalance*).

---

## 3. Tahap Verifikasi Awal: Uji Gerbang Validasi (Fase 0)

Sebelum menjalankan skenario eksperimen, jalankan seluruh uji gerbang berikut untuk memastikan kesiapan dan integritas lingkungan pengujian.

### T0.1: Uji Unit Normalisasi dan Logika Deteksi P-Wave
Pastikan fungsi normalisasi batch dan algoritma deteksi menghasilkan luaran deterministik:
```powershell
cd tests
python -c "import sys; sys.path.insert(0, '..'); import numpy as np; from utils.pwave_common import normalize_batch, detect; d=np.random.randn(5,160,3); assert normalize_batch(d).shape==(5,160,3); p=np.zeros(50); p[10:30]=0.95; idx,m=detect(p,0.9,20); assert idx==10; print('T0.1 PASS')"
```

### T0.2: Verifikasi Partisi Topik Kafka
Pastikan layanan `kafka-init` mengonfigurasi partisi dan faktor replikasi topik secara tepat:
```powershell
cd ..
docker compose -f docker-compose-s3-kafka.yml up -d zookeeper kafka1 kafka2 kafka3 kafka-init
docker exec kafka1 kafka-topics --bootstrap-server kafka1:9092 --describe
```
Parameter yang wajib terverifikasi:
- `trace_topic`: 5 partisi dengan faktor replikasi 2.
- `p_wave_topic`: 5 partisi dengan faktor replikasi 1.
- `loc_mag_topic`: 3 partisi dengan faktor replikasi 1.
- `result_loc_mag_topic`: 3 partisi dengan faktor replikasi 1.

Hentikan kontainer uji setelah verifikasi selesai:
```powershell
docker compose -f docker-compose-s3-kafka.yml down -v
```

### T0.3: Uji Pembagian Beban Load Balancer
Jalankan konfigurasi NGINX Load Balancer dengan 3 replika pekerja P-Wave, alirkan data uji, dan periksa perataan distribusi:
```powershell
docker compose -f docker-compose-s3-nginx.yml up -d
# Amati metrik: sum by (replica) (rate(lb_forwarded_by_replica_total[1m]))
# Selisih proporsi distribusi antarreplika harus berada di bawah 10 persen.
docker compose -f docker-compose-s3-nginx.yml down -v
```

### T0.4: Verifikasi Agregasi Histogram PromQL
Pastikan formula persentil 95 pada Prometheus menggunakan sintaks agregasi lintas replika sehingga hasilnya merepresentasikan keseluruhan replika, bukan hanya satu replika acak.

Jalankan stack NGINX yang memuat Prometheus dan replika P-Wave:
```powershell
docker compose -f docker-compose-s3-nginx.yml up -d
```

Tunggu sekitar 2 menit hingga data metrik terkumpul, lalu buka Prometheus di `http://localhost:9090` dan eksekusi kueri berikut pada tab **Graph**.

Gunakan kueri sesuai stack yang sedang berjalan:

- **Stack NGINX** (`docker-compose-s3-nginx.yml`) — metric dari `p_wave_detector_load_balance`:
  ```
  histogram_quantile(0.95, sum by (le) (rate(pwave_lb_inference_latency_seconds_bucket[1m])))
  ```

- **Stack Kafka Native** (`docker-compose-s3-kafka.yml`) — metric dari `p_wave_detector`:
  ```
  histogram_quantile(0.95, sum by (le) (rate(pwave_inference_latency_seconds_bucket[1m])))
  ```

**Kriteria kelulusan:** hasil mengembalikan **satu deret nilai tunggal** (bukan deret terpisah per replika). Jika muncul banyak baris dengan label `instance=...`, berarti `sum by (le)` tidak bekerja.

Hentikan kontainer setelah verifikasi selesai:
```powershell
docker compose -f docker-compose-s3-nginx.yml down -v
```

### T0.5: Uji Ketahanan Alokasi Memori Kontainer
Jalankan replika pekerja P-Wave Native selama 10 menit untuk memastikan tidak terjadi *out-of-memory kill* pada beban penuh. Jumlah replika disesuaikan dengan kapasitas RAM mesin — gunakan 3 replika pada mesin dengan RAM ≤ 8 GB, dan 5 replika pada mesin dengan RAM ≥ 16 GB.

```powershell
# Jalankan stack (gunakan 3c untuk mesin RAM ≤ 8GB, 5c untuk RAM ≥ 16GB)
docker compose -f docker-compose-s4-pwave-kafka-3c.yml up -d

# Tunggu 10 menit
Start-Sleep 600

# Periksa status OOM dan restart count seluruh replika (sintaks PowerShell)
docker ps --filter "name=p_wave_detector" --format "{{.Names}}" | ForEach-Object {
    docker inspect --format='{{.Name}}: OOMKilled={{.State.OOMKilled}} Restarts={{.RestartCount}}' $_
}
```

**Kriteria kelulusan:** seluruh baris menunjukkan `OOMKilled=false` dan `Restarts=0`.

Hentikan kontainer setelah verifikasi selesai:
```powershell
docker compose -f docker-compose-s4-pwave-kafka-3c.yml down -v
```

### T0.6: Verifikasi Rebalancing Partisi Kafka Consumer Group
Naikkan replika dari 2 menjadi 3 secara live dan amati proses *rebalance* partisi untuk memastikan tidak terjadi kebuntuan (*deadlock*) pada aliran konsumsi.

```powershell
# Step 1: Jalankan dengan 2 replika
docker compose -f docker-compose-s4-pwave-kafka-2c.yml up -d

# Tunggu sistem stabil
Start-Sleep 60

# Step 2: Amati distribusi partisi sebelum scale up
docker exec kafka1 kafka-consumer-groups --bootstrap-server kafka1:9092 --describe --group p_wave_detector_group

# Step 3: Naikkan ke 3 replika
docker compose -f docker-compose-s4-pwave-kafka-3c.yml up -d --no-recreate --scale p_wave_detector=3

# Tunggu proses rebalance selesai
Start-Sleep 30

# Step 4: Amati ulang — semua partisi harus memiliki consumer aktif
docker exec kafka1 kafka-consumer-groups --bootstrap-server kafka1:9092 --describe --group p_wave_detector_group
```

**Kriteria kelulusan:** seluruh partisi `p_wave_topic` memiliki kolom `CONSUMER-ID` terisi (tidak ada partisi dengan `CONSUMER-ID` bernilai `-`), dan nilai `LAG` tidak terus membesar seiring waktu.

Hentikan kontainer setelah verifikasi selesai:
```powershell
docker compose -f docker-compose-s4-pwave-kafka-3c.yml down -v
```

---

## 4. Spesifikasi Metrik dan Formula Kueri PromQL

Seluruh pengukuran latensi wajib menggunakan operator `sum by (le)` agar persentil yang dihitung merepresentasikan akumulasi seluruh replika secara proporsional.

| No | Parameter Metrik | Formula Kueri PromQL | Definisi dan Tujuan |
| :--- | :--- | :--- | :--- |
| 1 | Throughput Trace Hulu | `sum(rate(data_provider_traces_sent_total{topic="trace_topic"}[1m]))` | Laju paket sinyal seismik masuk ke broker. |
| 2 | Throughput Topik P-Wave | `sum(rate(data_provider_traces_sent_total{topic="p_wave_topic"}[1m]))` | Laju paket yang dialirkan ke antrean inferensi. |
| 3 | Laju Paket Basi Tersaring | `sum(rate(data_provider_traces_dropped_stale_total[1m]))` | Laju data tertunda yang dieliminasi oleh filter 60 detik. |
| 4 | Kapasitas Deteksi Native | `sum(rate(pwave_inference_latency_seconds_count[1m]))` | Laju inferensi aktual model AI pada mode Kafka Native. |
| 5 | Kapasitas Deteksi NGINX | `sum(rate(pwave_lb_inference_latency_seconds_count[1m]))` | Laju inferensi aktual model AI pada mode NGINX HTTP. |
| 6 | Latensi Inferensi Native (P95) | `histogram_quantile(0.95, sum by (le) (rate(pwave_inference_latency_seconds_bucket[1m])))` | Durasi eksekusi model CNN-LSTM pada mode Native. |
| 7 | Latensi Inferensi NGINX (P95) | `histogram_quantile(0.95, sum by (le) (rate(pwave_lb_inference_latency_seconds_bucket[1m])))` | Durasi eksekusi model CNN-LSTM pada mode NGINX. |
| 8 | Penundaan Broker Kafka (P95) | `histogram_quantile(0.95, sum by (le) (rate(pwave_kafka_delay_seconds_bucket[1m])))` | Waktu transit pesan di dalam partisi broker Kafka. |
| 9 | Waktu Antrean Internal (P95) | `histogram_quantile(0.95, sum by (le) (rate(pwave_queue_wait_seconds_bucket[1m])))` | Waktu antre pesan sebelum dieksekusi proses inferensi. |
| 10 | Latensi Penerusan LB (P95) | `histogram_quantile(0.95, sum by (le) (rate(lb_forward_latency_seconds_bucket[1m])))` | Waktu penerusan permintaan HTTP dari LB ke pekerja. |
| 11 | Latensi Ujung ke Ujung (P95) | `histogram_quantile(0.95, sum by (le) (rate(pwave_end_to_end_latency_seconds_bucket[1m])))` | Waktu total dari stempel hulu hingga selesai inferensi. |
| 12 | Kapasitas Simpan Archiver | `sum(rate(archiver_records_saved_total{storage="influxdb"}[1m]))` | Laju penyimpanan rekaman bersih ke basis data InfluxDB. |
| 13 | Latensi Siar WS Express (P95)| `histogram_quantile(0.95, sum by (le) (rate(ws_broadcast_latency_seconds_bucket[1m])))` | Durasi penyebaran data WebSocket Express Socket.IO. |
| 14 | Latensi Siar WS FastAPI (P95)| `histogram_quantile(0.95, sum by (le) (rate(fastapi_ws_broadcast_latency_seconds_bucket[1m])))`| Durasi penyebaran data WebSocket ASGI FastAPI. |
| 15 | Konsumsi CPU Pekerja AI (%) | `sum(docker_container_cpu_usage_percent{container_name=~".*p_wave_detector.*"})` | Akumulasi beban CPU seluruh pekerja P-Wave Detector. |
| 16 | Alokasi RAM Pekerja AI (MB) | `sum(docker_container_mem_usage{container_name=~".*p_wave_detector.*"}) / 1048576` | Total penggunaan memori fisik pekerja P-Wave. |
| 17 | Beban CPU Observabilitas (%) | `sum(docker_container_cpu_usage_percent{container_name=~".*(prometheus|grafana|telegraf|node-exporter).*"})` | Total beban CPU tumpukan sistem pemantau. |
| 18 | Alokasi RAM Observabilitas (MB)| `sum(docker_container_mem_usage{container_name=~".*(prometheus|grafana|telegraf|node-exporter).*"}) / 1048576`| Total alokasi RAM tumpukan sistem pemantau. |
| 19 | Akumulasi Lag Antrean Kafka | `sum(kafka_consumergroup_lag)` | Total antrean pesan yang belum diproses oleh konsumen. |

---

## 5. Prosedur Pengujian Skenario S1 hingga S5

Setiap skenario dieksekusi melalui skrip PowerShell terotomasi di dalam direktori `tests`. Protokol pengujian mewajibkan:
- Pengulangan 3 kali (`-Repeat 3`) per konfigurasi untuk menjamin signifikansi statistik.
- Pengacakan urutan pengujian (`-Shuffle`) untuk mengeliminasi bias pemanasan CPU dan *cache*.
- Gerbang kesiapan sistem otomatis (`Wait-SystemReady`) yang memverifikasi kesiapan Prometheus dan broker Kafka sebelum pencatatan dimulai.
- Pemotongan jendela fase stabil (*steady-state*) pada detik ke-50 hingga ke-200.
- Ekstraksi seluruh nilai ember metrik secara kumulatif (`--dump-buckets`) guna menghitung nilai P95 jendela sejati.
- Jeda pendinginan sistem (*cooldown*) selama 120 detik antar-run untuk melepaskan alokasi memori fisik.

Masuk ke folder pengujian sebelum menjalankan perintah:
```powershell
cd tests
```

---

### S1: Strategi Konkurensi Data Provider
Mengevaluasi kinerja empat mekanisme konkurensi (Sekuensial, Multi-Threading, Multi-Processing, dan Hibrida) dalam menyerap data SeedLink tanpa mengalami kelaparan data (*data starvation*).

```powershell
# Eksekusi seluruh variasi S1 dengan 3 pengulangan acak
.\run_s1_dataprovider.ps1 -Repeat 3 -Shuffle

# Opsi eksekusi konfigurasi individual
.\run_s1_dataprovider.ps1 -ScenarioName Sequential -Repeat 3
.\run_s1_dataprovider.ps1 -ScenarioName Multithread -Repeat 3
.\run_s1_dataprovider.ps1 -ScenarioName Multiprocess -Repeat 3
.\run_s1_dataprovider.ps1 -ScenarioName Hibrida -Repeat 3
```

---

### S2: Beban Overhead Observabilitas Penuh
Mengukur beban penalti sumber daya komputasi dan memori yang timbul akibat instrumentasi Prometheus pada aplikasi serta pengoperasian tumpukan observabilitas penuh (*monitoring stack*).

```powershell
# Eksekusi perbandingan tanpa metrik versus dengan metrik
.\run_s2_overhead.ps1 -Repeat 3 -Shuffle

# Opsi eksekusi kondisi individual
.\run_s2_overhead.ps1 -ScenarioName NoMetrics -Repeat 3
.\run_s2_overhead.ps1 -ScenarioName WithMetrics -Repeat 3
```

---

### S3: Topologi Load Balancing Message Broker
Membandingkan keandalan topologi partisi Kafka Native versus perataan beban HTTP terdistribusi menggunakan NGINX Load Balancer pada 3 replika pekerja inferensi.

```powershell
# Eksekusi perbandingan kedua topologi
.\run_s3_broker.ps1 -Repeat 3 -Shuffle

# Opsi eksekusi topologi individual
.\run_s3_broker.ps1 -ScenarioName Kafka -Repeat 3
.\run_s3_broker.ps1 -ScenarioName NGINX -Repeat 3
```

---

### S4: Skalabilitas Beban Data Archiver dan P-Wave Detector
Mengevaluasi efisiensi penskalaan horizontal dan membuktikan batas kejenuhan komputasi model inferensi.

#### A. Skalabilitas Data Archiver (1 hingga 5 Kontainer)
```powershell
.\run_s4_scalability_archiver.ps1 -Repeat 3
```

#### B. Skalabilitas P-Wave Detector (2 hingga 5 Replika Native dan 2 hingga 6 Replika NGINX)
Pada mode NGINX, pengujian menyertakan variasi 6 replika kontainer untuk membuktikan titik optimal Universal Scalability Law ($N^* = 6{,}40$) secara empiris:
```powershell
.\run_s4_scalability_pwave.ps1 -Repeat 3

# Opsi eksekusi variasi individual
.\run_s4_scalability_pwave.ps1 -ScenarioName Kafka2c -Repeat 3
.\run_s4_scalability_pwave.ps1 -ScenarioName KafkaNginx6c -Repeat 3
```

---

### S5: Diseminasi WebSocket Klien Konkuren
Mengukur latensi siar data peringatan dini gempa bumi ke antarmuka pengguna pada beban 1 klien dan 5 klien konkuren.

```powershell
# Eksekusi perbandingan Express.js vs FastAPI
.\run_s5_websocket.ps1 -Repeat 3 -Shuffle

# Opsi eksekusi variasi individual
.\run_s5_websocket.ps1 -ScenarioName Express1c -Repeat 3
.\run_s5_websocket.ps1 -ScenarioName Express5c -Repeat 3
.\run_s5_websocket.ps1 -ScenarioName FastAPI1c -Repeat 3
.\run_s5_websocket.ps1 -ScenarioName FastAPI5c -Repeat 3
```

---

## 6. Prosedur Pengujian Konfigurasi Akhir Sistem GEMPA

Pengujian ini memvalidasi arsitektur produksi sistem GEMPA yang direkomendasikan pada Subbab 4.8. Konfigurasi ini mengintegrasikan seluruh komponen terbaik:
- Data Provider: Mode Multiprocess (5.984 kanal).
- Arsitektur Deteksi: NGINX Load Balancer dengan 5 Replika Pekerja AI P-Wave.
- Arsitektur Penyimpanan: 3 Replika Data Archiver (InfluxDB dan MongoDB).
- Komponen Diseminasi: Layanan WebSocket FastAPI.
- Ketahanan Sistem: Kontainer `restarter` berkala aktif merestart pekerja secara bergilir setiap 600 detik tanpa memutus layanan.

Jalankan pengujian konfigurasi akhir utuh sebanyak 3 kali pengulangan (durasi 300 detik per run):
```powershell
cd ..

# Pengulangan Pertama
docker compose -f docker-compose-final.yml up -d --build
python tests/collect_metrics.py --duration 300 --interval 5 --output tests/results/final_production_run1.csv --dump-buckets
docker compose -f docker-compose-final.yml down -v
Start-Sleep -Seconds 120

# Pengulangan Kedua
docker compose -f docker-compose-final.yml up -d
python tests/collect_metrics.py --duration 300 --interval 5 --output tests/results/final_production_run2.csv --dump-buckets
docker compose -f docker-compose-final.yml down -v
Start-Sleep -Seconds 120

# Pengulangan Ketiga
docker compose -f docker-compose-final.yml up -d
python tests/collect_metrics.py --duration 300 --interval 5 --output tests/results/final_production_run3.csv --dump-buckets
docker compose -f docker-compose-final.yml down -v
```

---

## 7. Pengujian Keandalan dan Isolasi Kegagalan (KNF-02)

Pengujian ini membuktikan pemenuhan kebutuhan non-fungsional KNF-02, yaitu kegagalan salah satu simpul komputasi tidak menimbulkan kegagalan berantai (*zero cascading failure*):

1. Aktifkan arsitektur NGINX dengan 3 replika pekerja:
   ```powershell
   docker compose -f docker-compose-s3-nginx.yml up -d
   ```
2. Saat aliran data sedang berlangsung (setelah detik ke-60), hentikan secara paksa satu kontainer pekerja P-Wave:
   ```powershell
   docker stop gempa-p_wave_detector_load_balance-1
   ```
3. Pantau log operasional Load Balancer dan Data Archiver:
   ```powershell
   docker logs --tail 20 gempa-load_balancer-1
   docker logs --tail 20 gempa-data_archiver-1
   ```
4. Indikator Keberhasilan:
   - Load Balancer secara otomatis mengarahkan beban HTTP ke dua replika yang tetap aktif.
   - Modul Data Archiver dan WebSocket tetap mengonsumsi dan menyiarkan data tanpa interupsi.
   - Sistem tidak mengalami terminasi paksa massal.
5. Bersihkan lingkungan pengujian:
   ```powershell
   docker compose -f docker-compose-s3-nginx.yml down -v
   ```

---

## 8. Analisis Data Statistik dan Pemodelan Skalabilitas (USL)

Setelah seluruh berkas hasil CSV tersimpan pada direktori `tests/results/`, jalankan pengolahan statistik otomatis:

```powershell
cd tests
python analyze.py --scenario all
```

### Prosedur Komputasi Modul `analyze.py`:
1. Pemotongan Jendela Waktu Stabil:
   Mengeliminasi 50 detik pertama untuk membuang fase pemanasan awal (*warmup transient*), dan mengevaluasi 150 detik fase stabil berikutnya.
2. Perhitungan Persentil 95 Sejati:
   Nilai persentil 95 dihitung langsung dari selisih nilai kumulatif ember histogram pada akhir jendela terhadap awal jendela.
3. Kriteria Pembatalan Uji (*Invalid Run*):
   Data pengujian dinyatakan tidak valid dan dikeluarkan dari ringkasan statistik apabila:
   - Jumlah baris data sampel kurang dari 90 persen dari target waktu.
   - Terdapat kolom metrik utama yang bernilai kosong melebihi 10 persen baris.
   - Ditemukan kontainer yang mengalami kondisi *Out-of-Memory* (`OOMKilled`) atau restart tidak terjadwal.
4. Estimasi Parameter Skalabilitas (Universal Scalability Law):
   Menurunkan koefisien perebutan sumber daya (*contention* $\sigma$), koefisien sinkronisasi (*coherency* $\kappa$), dan titik puncak kapasitas ($N^*$). Model regresi dihitung berdasarkan laju inferensi aktual $C(N)$, bukan laju paket masuk.

---

## 9. Daftar Luaran Pengujian (Deliverables)

Seluruh berkas luaran berikut wajib disimpan dan didokumentasikan untuk kebutuhan penulisan Bab IV:

- Log teks mentah eksekusi Uji Gerbang Validasi Fase 0 (T0.1 hingga T0.6).
- Berkas CSV mentah hasil pencatatan metrik berkala (`tests/results/*_metrics.csv`).
- Berkas CSV ekstraksi nilai kumulatif ember histogram (`tests/results/*_dump_buckets.csv`).
- Berkas metadata JSON tiap sesi run yang mencatat commit hash, status OOMKilled, dan jumlah restart.
- Tabel rekapitulasi statistik (nilai rerata, simpangan baku, nilai minimum, nilai maksimum, dan P95 sejati).
- Parameter koefisien USL ($\sigma$, $\kappa$, $N^*$) beserta kurva kecocokan model regresi.
- Log pemantauan host dari Telegraf untuk evaluasi Skenario 2.

---

## 10. Verifikasi Penyimpanan Data dan Penanganan Kendala

### A. Verifikasi Basis Data InfluxDB
Gunakan perintah berikut untuk memvalidasi penyimpanan sinyal gelombang pada bucket `gempa`:
```powershell
docker compose exec influxdb influx query 'from(bucket: "gempa") |> range(start: -5m) |> tail(n: 5)' --token "bhIGAk5dlA2gJm1WUG3GmUu_UNtY4G4TVoU2T0vIQBg5o3stlAXsxYoOrKA7ttUhSq8rS3QA1Y-K1wKCTiAGuQ==" --org "owner"
```

### B. Verifikasi Basis Data MongoDB
Gunakan perintah berikut untuk memeriksa penyimpanan data deteksi parameter gempa:
```powershell
docker compose exec mongo mongosh -u admin -p UNDIPJAYA --eval "use timeseries_db; db.timeseries_collection.find().sort({_id: -1}).limit(3)"
```

### C. Penanganan Kendala Operasional
1. Partisi Topik Kafka Tidak Ditemukan:
   Pastikan kontainer `kafka-init` telah selesai berjalan dengan kode keluar 0 sebelum aplikasi konsumen dinyalakan.
2. Penolakan Kueri Prometheus Akibat Waktu Tidak Sinkron:
   Sinkronkan jam sistem antara Windows dan WSL 2 melalui perintah:
   ```powershell
   wsl -d docker-desktop hwclock -s
   ```
3. Pembersihan Menyeluruh Lingkungan Docker:
   Untuk mengembalikan Docker ke kondisi awal yang bersih tanpa membawa residu volume atau jaringan lama:
   ```powershell
   docker stop $(docker ps -aq)
   docker rm $(docker ps -aq)
   docker volume prune -f
   ```
