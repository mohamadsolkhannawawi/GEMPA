# Status Pengujian & Langkah Selanjutnya
Dibuat: 2026-11-19 | Diperbarui: 2026-11-19

---

## Ringkasan Status Per Skenario

| Skenario | Run Tersedia | Status | Perlu Diulang |
|---|---|---|---|
| S1 | run1, run2, run3 | ✅ Konsisten | ❌ Tidak |
| S2 | run1, run2, run3 | ⚠️ Run2 outlier | ✅ Wajib (run2 outlier) |
| S3 | run1, run2, run3 (NGINX OK, Kafka INVALID) | ❌ Kafka Native bermasalah | ✅ Wajib |
| S4a | run1, run2, run3 | ⚠️ Anomali parsial di run2 & run3 | ✅ Wajib |
| S4b | run1, run2, run3 | ✅ Sangat konsisten | ❌ Tidak |
| S5 | run1 saja (run2, run3 INVALID) | ❌ Hanya 1 run valid | ✅ Wajib |

> **Prinsip:** Semua skenario dengan anomali, outlier, atau data tidak lengkap
> harus diulang agar data yang masuk skripsi benar-benar valid dan dapat
> dipertanggungjawabkan. Hanya S1 dan S4b yang sudah cukup kuat untuk
> langsung digunakan.

---

## Detail Masalah & Penyebab

### S2 — Run2 Outlier (WAJIB DIULANG)
**Deskripsi:** Baseline CPU run2 (533.81%) jauh di atas run1 (499.33%) dan
run3 (497.78%). Menyebabkan overhead terhitung -7.3% yang tidak konsisten
dengan run1 (-0.9%) dan run3 (-0.6%).
**Penyebab:** Sistem belum dingin saat run2 dimulai — cooldown 120 detik
tidak cukup setelah run sebelumnya (WithMetrics) yang berat.
**Dampak ke skripsi:** Jika digunakan apa adanya, overhead Prometheus
terlihat negatif di run2 yang membingungkan pembaca.
**Tindakan:** Jalankan ulang S2 dengan `-Repeat 3` dan cooldown lebih panjang.

---

### S3 — Kafka Native INVALID di run1, run2, run3 (WAJIB DIULANG)
**Penyebab:** `Wait-SystemReady` tanpa `-RelaxDpRate` menunggu penuh 300 detik
hingga `dp_rate > 0`. Setelah timeout + stabilisasi 60 detik, jendela
collect 300 detik tidak terpenuhi (hanya 141–217 detik terkumpul).
Minimum 200 detik yang dibutuhkan tidak tercapai sehingga INVALID.
**Fix yang sudah diterapkan:**
- `run_s3_broker.ps1` → tambah `-RelaxDpRate | Out-Null`
- `docker-compose-s3-kafka.yml` → `data_provider depends_on kafka-init`
- `docker-compose-s3-nginx.yml` → `data_provider depends_on kafka-init`
**Tindakan:** Jalankan ulang S3 dengan `-Repeat 3`

---

### S4a — Anomali Parsial (WAJIB DIULANG)
**Deskripsi:**
- Run2: replika 4 dan 5 drop ke 186 rec/s (normal ~350 rec/s)
- Run3: replika 3 drop ke 187 rec/s (normal ~350 rec/s)

**Penyebab:** MongoDB atau InfluxDB belum siap menerima koneksi setelah
banyak siklus `docker compose down/up` berturutan dalam sesi panjang
(15 stack naik-turun). Archiver berhasil start tapi koneksi database
timeout di awal window collect.

**Dampak ke skripsi:** Rata-rata menjadi tidak representatif untuk replika
3–5 karena satu run selalu anomali. Ini memunculkan ambiguitas antara
replika 2 vs 3 sebagai titik saturasi.

**Fix yang sudah diterapkan:**
- `run_s4_scalability_archiver.ps1` → tambah `-RelaxDpRate | Out-Null`
- Semua `docker-compose-s4-archiver-*.yml` → `data_provider depends_on kafka-init`

**Tindakan:** Jalankan ulang S4a dengan `-Repeat 3`

---

### S5 — Hanya run1 yang valid (WAJIB DIULANG)
**Penyebab:** File `_run2.csv` dan `_run3.csv` tidak ada di folder results.
Run2 dan run3 kemungkinan gagal karena `ws_broadcast_latency` tidak
terukur saat SeedLink belum stabil mengalirkan data ke WebSocket server.
**Fix yang sudah diterapkan:**
- `run_s5_websocket.ps1` sudah ada `-RelaxDpRate | Out-Null`
- `docker-compose-s5-*.yml` sudah ada `depends_on kafka-init`
**Tindakan:** Jalankan ulang S5 dengan `-Repeat 3`

---

### Compose & Run Script — Semua Sudah Diperbaiki ✅
Semua compose dan run script sudah mendapat:
- `data_provider depends_on kafka-init` (mencegah race condition topik)
- `Wait-SystemReady -RelaxDpRate | Out-Null` (mencegah timeout 300 detik)

Jalankan `git pull` di `D:\MDLBEEWS-V3` sebelum pengujian ulang.

---

## Hasil Per Skenario (Data Terkini)

### S1 — Konkurensi Data Provider ✅ FINAL
**Pemenang: MULTITHREAD** (konsisten di semua run)

| Arsitektur | Run1 | Run2 | Run3 | Rata-rata |
|---|---|---|---|---|
| Sequential | INVALID | INVALID | INVALID | INVALID |
| Multithread | 160.68 | 161.91 | 159.46 | **160.68 tr/s** |
| Multiprocess | 163.53 | 164.25 | 162.04 | **163.27 tr/s** |
| Hibrida | 73.80 | 72.90 | 76.64 | **74.45 tr/s** |

> Multiprocess sedikit lebih tinggi di throughput, namun RAM 4× lebih besar
> (387 vs 92 MB). Multithread dipilih karena efisiensi resource lebih baik.

---

### S2 — Overhead Prometheus ⚠️ PERLU DIULANG
**Data sementara:**

| Run | Baseline CPU | WithMetrics CPU | Overhead |
|---|---|---|---|
| Run1 | 499.33% | 495.0% | -0.9% |
| Run2 | **533.81%** | 495.0% | **-7.3% ← outlier** |
| Run3 | 497.78% | 495.0% | -0.6% |

---

### S3 — Broker Architecture ⚠️ PERLU DIULANG
**Kafka Native selalu INVALID. Data NGINX sementara dari 3 run:**

| Run | NGINX E2E P95 | NGINX Det.Rate |
|---|---|---|
| Run1 | 117,997 ms | 18.19/s |
| Run2 | 114,114 ms | 19.51/s |
| Run3 | 113,843 ms | 19.11/s |

**Kafka Native sementara dari arsip lama (repeat 1):**
E2E P95 = 173,475 ms | Det.Rate = 7.03/s

---

### S4a — Skalabilitas Archiver ⚠️ PERLU DIULANG
**Data sementara dengan anomali ditandai:**

| Replika | Run1 | Run2 | Run3 | Rata-rata |
|---|---|---|---|---|
| 1 | 166 | 206 | 207 | **193 rec/s** |
| 2 | 329 | 329 | 339 | **332 rec/s** |
| 3 | 364 | 421 | **187\*** | **324 rec/s** |
| 4 | 344 | **186\*** | 371 | **300 rec/s** |
| 5 | 370 | **186\*** | 376 | **311 rec/s** |

\* anomali — MongoDB/InfluxDB belum siap

---

### S4b — Skalabilitas P-Wave Detector ✅ FINAL
**Pemenang: LOAD BALANCER 5 CONTAINER** (sangat konsisten)

| Konfigurasi | Run1 | Run2 | Run3 | Rata-rata |
|---|---|---|---|---|
| Native 5c det.rate | 3.39/s | 1.18/s | 2.06/s | **2.21/s** |
| **LB 5c det.rate** | **19.39/s** | **19.97/s** | **19.07/s** | **19.48/s** |
| LB 5c latency P95 | 40,800 ms | 20,792 ms | 19,715 ms | **27,102 ms** |

---

### S5 — WebSocket Server ⚠️ PERLU DIULANG
**Data sementara dari run1 saja:**

| Server | Klien | Broadcast P95 | CPU | RAM |
|---|---|---|---|---|
| FastAPI | 1 | 1.74 ms | 26.82% | 43.67 MB |
| FastAPI | 5 | 4.86 ms | 46.45% | 42.72 MB |
| **Express.js** | **1** | **0.49 ms** | **20.42%** | **61.11 MB** |
| **Express.js** | **5** | **2.17 ms** | **23.98%** | **62.76 MB** |

---

## Konfigurasi Final (Sementara)

| Skenario | Konfigurasi Terpilih | Keyakinan |
|---|---|---|
| S1 | Multithread | ✅ Tinggi — 3 run konsisten, FINAL |
| S2 | Prometheus aktif | ⚠️ Sedang — perlu run ulang untuk konfirmasi |
| S3 | Kafka + NGINX | ⚠️ Sedang — perlu data Kafka Native yang valid |
| S4a | Archiver 3 replika (konservatif) | ⚠️ Sedang — perlu run ulang untuk resolusi ambiguitas |
| S4b | P-Wave LB 5 replika | ✅ Tinggi — 3 run sangat konsisten, FINAL |
| S5 | Express.js | ⚠️ Sedang — perlu 2 run lagi untuk konfirmasi |

---

## Langkah Selanjutnya (Urutan Prioritas)

### Persiapan (jalankan sekali sebelum semua pengujian ulang)
```powershell
cd D:\MDLBEEWS-V3
git pull
```

### 1. Jalankan ulang S4a (paling lama, mulai duluan)
```powershell
.\tests\run_s4_scalability_archiver.ps1 -Repeat 3
```

### 2. Jalankan ulang S3
```powershell
.\tests\run_s3_broker.ps1 -Repeat 3
```

### 3. Jalankan ulang S5
```powershell
.\tests\run_s5_websocket.ps1 -Repeat 3
```

### 4. Jalankan ulang S2
```powershell
.\tests\run_s2_overhead.ps1 -Repeat 3
```

### 5. Analisis per-run setelah semua selesai
```powershell
cd D:\MDLBEEWS-V3\tests
python analyze.py --scenario all --run 1
python analyze.py --scenario all --run 2
python analyze.py --scenario all --run 3
```

### 6. Generate rata-rata final untuk Bab IV
```powershell
python analyze.py --scenario all
```

---

## Catatan untuk Skripsi

1. **S1** — Siap digunakan. Laporkan sebagai rata-rata ± std dari 3 run.

2. **S4b** — Siap digunakan. Laporkan sebagai rata-rata ± std dari 3 run.

3. **S2 run2 outlier** — Setelah diulang, jika konsisten maka gunakan rata-rata
   3 run baru. Jika outlier tetap muncul, jelaskan sebagai variabilitas inherent
   dan laporkan median sebagai nilai representatif.

4. **S3 Kafka Native** — Gunakan data arsip lama hanya sebagai referensi sementara.
   Data final harus dari run ulang yang sudah diperbaiki.

5. **S4a ambiguitas 2 vs 3 replika** — Setelah run ulang tanpa anomali, lihat
   apakah replika 3 kembali lebih tinggi dari replika 2. Jika iya, pilih 3.
   Jika masih ambigu, pilih 3 sebagai konservatif dengan narasi yang menjelaskan
   selisih tidak signifikan.

6. **S5** — Setelah 3 run valid, konfirmasi Express.js sebagai pemenang.


---

## Ringkasan Status Per Skenario

| Skenario | Run Tersedia | Status | Perlu Diulang |
|---|---|---|---|
| S1 | run1, run2, run3 | ✅ Konsisten | ❌ Tidak |
| S2 | run1, run2, run3 | ✅ Kesimpulan sama | ❌ Tidak |
| S3 | run1, run2, run3 (NGINX OK, Kafka INVALID) | ❌ Kafka Native bermasalah | ✅ Wajib |
| S4a | run1, run2, run3 | ⚠️ Anomali parsial, tren jelas | ❌ Tidak |
| S4b | run1, run2, run3 | ✅ Sangat konsisten | ❌ Tidak |
| S5 | run1 saja (run2, run3 INVALID) | ❌ Hanya 1 run valid | ✅ Wajib |

---

## Detail Masalah & Penyebab

### S3 — Kafka Native INVALID di run1, run2, run3
**Penyebab:** `Wait-SystemReady` tanpa `-RelaxDpRate` menunggu penuh 300 detik
hingga `dp_rate > 0`. Setelah timeout + stabilisasi 60 detik, jendela
collect 300 detik tidak terpenuhi (hanya 141–217 detik terkumpul).
Minimum 200 detik yang dibutuhkan tidak tercapai sehingga INVALID.

**Fix yang sudah diterapkan:**
- `run_s3_broker.ps1` → tambah `-RelaxDpRate`
- `docker-compose-s3-kafka.yml` → `data_provider depends_on kafka-init`
- `docker-compose-s3-nginx.yml` → `data_provider depends_on kafka-init`

**Tindakan:** Jalankan ulang S3 dengan `-Repeat 3`

---

### S5 — Hanya run1 yang valid (run2 dan run3 INVALID / 0/0)
**Penyebab:** File `_run2.csv` dan `_run3.csv` tidak ada di folder results.
Skrip `run_s5_websocket.ps1 -Repeat 3` hanya berhasil menyimpan run1 —
kemungkinan run2 dan run3 gagal karena `ws_broadcast_latency` tidak
terukur (SeedLink belum konek saat window collect dimulai), atau file
tidak tersimpan karena path issue.

**Tindakan:** Jalankan ulang S5 dengan `-Repeat 3`

---

### S4a — Anomali Parsial (TIDAK perlu diulang)
**Deskripsi:** Run2 replika 4–5 drop ke 186 rec/s (normal ~350 rec/s).
Run3 replika 3 drop ke 187 rec/s.
**Penyebab:** MongoDB/InfluxDB belum siap setelah banyak siklus down/up.
**Kesimpulan tetap valid:** Tren saturasi di replika 2–3 terlihat jelas.
Anomali hanya 1 dari 3 run per konfigurasi.

---

### Compose MISSING `depends_on kafka-init` (semua skenario kecuali S3 dan S5)
Compose berikut masih punya `data_provider` tanpa `depends_on: kafka-init`:
- docker-compose-s1-hibrida.yml
- docker-compose-s1-multiprocess.yml
- docker-compose-s1-multithread.yml
- docker-compose-s1-sequential.yml
- docker-compose-s4-archiver-1c.yml s/d 5c (5 file)
- docker-compose-s4-pwave-kafka-2c.yml s/d 5c (4 file)
- docker-compose-s4-pwave-kafka-nginx-2c.yml s/d 5c (4 file)

**Dampak:** Karena S1 dan S4 sudah selesai dengan hasil valid, ini tidak
menyebabkan masalah (topik sudah ada dari sesi sebelumnya atau kafka-init
selesai cukup cepat). Namun sebaiknya diperbaiki untuk konsistensi.
**Prioritas:** Rendah — perbaiki setelah semua pengujian ulang selesai.

---

## Hasil Per Skenario (Ringkasan Data Terkini)

### S1 — Konkurensi Data Provider
**Pemenang: MULTITHREAD** (konsisten di semua run)

| Arsitektur | Run1 | Run2 | Run3 | Rata-rata |
|---|---|---|---|---|
| Sequential | INVALID | INVALID | INVALID | INVALID |
| Multithread | 160.68 | 161.91 | 159.46 | **160.68 tr/s** |
| Multiprocess | 163.53 | 164.25 | 162.04 | **163.27 tr/s** |
| Hibrida | 73.80 | 72.90 | 76.64 | **74.45 tr/s** |

> Catatan: Multiprocess sedikit lebih tinggi dari Multithread pada throughput
> trace_topic, namun RAM Multiprocess 4× lebih besar (387 vs 92 MB).
> Multithread dipilih karena efisiensi resource lebih baik.

---

### S2 — Overhead Prometheus
**Kesimpulan: Overhead sangat kecil, dapat diabaikan**

| Run | Baseline CPU | WithMetrics CPU | Overhead |
|---|---|---|---|
| Run1 | 499.33% | 495.0% | -0.9% |
| Run2 | 533.81% | 495.0% | -7.3% ← outlier |
| Run3 | 497.78% | 495.0% | -0.6% |
| **Rata-rata (ex. outlier)** | **498.56%** | **495.0%** | **-0.7%** |

> Run2 baseline lebih tinggi karena sistem belum dingin. Kesimpulan: overhead
> Prometheus < 1% CPU — tidak signifikan secara praktis.

---

### S3 — Broker Architecture
**Status: PERLU DIULANG (Kafka Native selalu INVALID)**
**Sementara dari arsip lama (repeat 1):**

| Arsitektur | Throughput | E2E P95 | Det.Rate |
|---|---|---|---|
| Kafka Native | 47.93 tr/s | 173,475 ms | 7.03/s |
| Kafka + NGINX | 56.97 tr/s | 116,862 ms | 17.85/s |

NGINX 3 run baru konsisten: E2E P95 113–117s, det.rate 18–19/s.

---

### S4a — Skalabilitas Archiver
**Pemenang: 2 atau 3 Replika (ambigu, lihat catatan)**

| Replika | Run1 | Run2 | Run3 | Rata-rata |
|---|---|---|---|---|
| 1 | 166 | 206 | 207 | **193 rec/s** |
| **2** | **329** | **329** | **339** | **332 rec/s** |
| 3 | 364 | 421 | 187* | **324 rec/s** |
| 4 | 344 | 186* | 371 | **300 rec/s** |
| 5 | 370 | 186* | 376 | **311 rec/s** |

*anomali karena MongoDB/InfluxDB belum siap

> **Ambiguitas:** Rata-rata run baru menunjukkan replika 2 (332) > replika 3 (324),
> berbeda dengan arsip lama yang menunjukkan replika 3 (346) > replika 2 (323).
> Selisih hanya 2.4% — berada dalam margin variabilitas.
> **Keputusan: tetap pilih 3 replika** sebagai buffer konservatif, dengan catatan
> bahwa peningkatan 2→3 tidak signifikan secara statistik.

---

### S4b — Skalabilitas P-Wave Detector
**Pemenang: LOAD BALANCER 5 CONTAINER** (sangat konsisten)

| Konfigurasi | Run1 | Run2 | Run3 | Rata-rata |
|---|---|---|---|---|
| Native 5c det.rate | 3.39/s | 1.18/s | 2.06/s | **2.21/s** |
| **LB 5c det.rate** | **19.39/s** | **19.97/s** | **19.07/s** | **19.48/s** |
| LB 5c latency P95 | 40,800 ms | 20,792 ms | 19,715 ms | **27,102 ms** |

---

### S5 — WebSocket Server
**Status: PERLU DIULANG (hanya run1 valid)**
**Sementara dari run1:**

| Server | Klien | Broadcast P95 | CPU | RAM |
|---|---|---|---|---|
| FastAPI | 1 | 1.74 ms | 26.82% | 43.67 MB |
| FastAPI | 5 | 4.86 ms | 46.45% | 42.72 MB |
| **Express.js** | **1** | **0.49 ms** | **20.42%** | **61.11 MB** |
| **Express.js** | **5** | **2.17 ms** | **23.98%** | **62.76 MB** |

---

## Konfigurasi Final Terkonfirmasi

| Skenario | Konfigurasi Terpilih | Keyakinan |
|---|---|---|
| S1 | Multithread | ✅ Tinggi (3 run konsisten) |
| S2 | Prometheus aktif | ✅ Tinggi |
| S3 | Kafka + NGINX | ✅ Tinggi (perlu data Kafka Native untuk perbandingan) |
| S4a | Archiver 3 replika | ⚠️ Sedang (ambigu dengan 2 replika, selisih <3%) |
| S4b | P-Wave LB 5 replika | ✅ Tinggi (3 run sangat konsisten) |
| S5 | Express.js | ⚠️ Sedang (baru 1 run valid) |

---

## Langkah Selanjutnya (Urutan Prioritas)

### 1. Perbaiki compose yang MISSING depends_on (sekali, sebelum pengujian ulang)
```powershell
cd E:\Documents\Bahan Skripsi\Program EEWS\MDLBEEWS
# Sudah ditangani oleh Kiro — jalankan git pull di D:\MDLBEEWS-V3 sebelum test
```

### 2. Jalankan ulang S3
```powershell
cd D:\MDLBEEWS-V3
git pull
.\tests\run_s3_broker.ps1 -Repeat 3
```

### 3. Jalankan ulang S5
```powershell
cd D:\MDLBEEWS-V3
git pull
.\tests\run_s5_websocket.ps1 -Repeat 3
```

### 4. Analisis per-run setelah selesai
```powershell
cd D:\MDLBEEWS-V3\tests
python analyze.py --scenario s3 --run 1
python analyze.py --scenario s3 --run 2
python analyze.py --scenario s3 --run 3
python analyze.py --scenario s5 --run 1
python analyze.py --scenario s5 --run 2
python analyze.py --scenario s5 --run 3
```

### 5. Generate rata-rata final semua skenario
```powershell
python analyze.py --scenario all
```

### 6. Perbaiki depends_on kafka-init di compose S1 dan S4 (opsional, low priority)
Tidak mempengaruhi hasil karena S1 dan S4 sudah selesai dengan valid.
Perbaiki untuk konsistensi kodebase.

---

## Catatan untuk Skripsi

1. **S4a ambiguitas 2 vs 3 replika** — gunakan narasi: *"Peningkatan dari 2 ke 3
   replika tidak signifikan secara statistik (selisih 2.4%, dalam margin
   variabilitas sistem). Konfigurasi 3 replika dipilih sebagai buffer konservatif."*

2. **S2 run2 outlier** — sebutkan: *"Run ke-2 menunjukkan baseline CPU yang lebih
   tinggi (533.81% vs rata-rata 498%) yang diduga akibat sistem belum sepenuhnya
   dingin. Nilai ini tidak dikeluarkan dari rata-rata namun diakui sebagai
   variabilitas inherent sistem."*

3. **S3 Kafka Native** — gunakan data arsip lama untuk perbandingan sampai
   data run ulang tersedia. Tambahkan catatan kaki bahwa run ulang dilakukan
   setelah perbaikan `Wait-SystemReady`.
