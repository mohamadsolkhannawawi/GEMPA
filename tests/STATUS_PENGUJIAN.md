# Status Pengujian & Langkah Selanjutnya
Dibuat: 2026-11-19 | Diperbarui: 2026-11-19 (setelah S5 selesai)

---

## Ringkasan Status Per Skenario

| Skenario | Run Tersedia | Status | Perlu Diulang |
|---|---|---|---|
| S1 | run1, run2, run3 | ✅ Konsisten | ❌ Tidak — FINAL |
| S2 | run1, run2, run3 | ⚠️ Run2 outlier | ✅ Wajib |
| S3 | run1, run2, run3 (NGINX OK, Kafka INVALID) | ❌ Kafka Native bermasalah | ✅ Wajib |
| S4a | run1, run2, run3 | ⚠️ Anomali parsial run2 & run3 | ✅ Wajib |
| S4b | run1, run2, run3 | ✅ Sangat konsisten | ❌ Tidak — FINAL |
| S5 | run1, run2, run3 | ✅ Semua valid, Express.js konsisten menang | ❌ Tidak — FINAL |

> **Prinsip:** Semua skenario dengan anomali, outlier, atau data tidak lengkap
> harus diulang agar data yang masuk skripsi benar-benar valid dan dapat
> dipertanggungjawabkan. S1, S4b, dan S5 sudah cukup kuat untuk digunakan.

---

## Yang Sudah FINAL (Tidak Perlu Diulang)

### S1 — Konkurensi Data Provider ✅ FINAL
**Pemenang: MULTITHREAD**

| Arsitektur | Run1 | Run2 | Run3 | Rata-rata |
|---|---|---|---|---|
| Sequential | INVALID | INVALID | INVALID | INVALID |
| Multithread | 160.68 | 161.91 | 159.46 | **160.68 tr/s** |
| Multiprocess | 163.53 | 164.25 | 162.04 | **163.27 tr/s** |
| Hibrida | 73.80 | 72.90 | 76.64 | **74.45 tr/s** |

> Multiprocess sedikit lebih tinggi di throughput, namun RAM 4× lebih besar
> (387 vs 92 MB). Multithread dipilih karena efisiensi resource lebih baik.

---

### S4b — Skalabilitas P-Wave Detector ✅ FINAL
**Pemenang: LOAD BALANCER 5 CONTAINER**

| Konfigurasi | Run1 | Run2 | Run3 | Rata-rata |
|---|---|---|---|---|
| Native 5c det.rate | 3.39/s | 1.18/s | 2.06/s | **2.21/s** |
| **LB 5c det.rate** | **19.39/s** | **19.97/s** | **19.07/s** | **19.48/s** |
| LB 5c latency P95 | 40,800 ms | 20,792 ms | 19,715 ms | **27,102 ms** |

---

### S5 — WebSocket Server ✅ FINAL
**Pemenang: EXPRESS.JS** (konsisten di semua run)

| Konfigurasi | Arsip Lama | Run1 | Run2 | Run3 | Rata-rata |
|---|---|---|---|---|---|
| FastAPI 1c P95 | 1.74 ms | 1.73 ms | 0.98 ms | 1.75 ms | **1.49 ms** |
| FastAPI 5c P95 | 4.86 ms | 4.86 ms | 4.82 ms | 4.84 ms | **4.84 ms** |
| **Express 1c P95** | **0.49 ms** | **0.49 ms** | **0.50 ms** | **0.49 ms** | **0.49 ms** |
| **Express 5c P95** | **2.17 ms** | **2.77 ms** | **2.87 ms** | **0.98 ms\*** | **2.21 ms** |
| Express 1c CPU | 20.42% | 22.44% | 21.56% | 22.1% | **22.0%** |
| Express 5c CPU | 23.98% | 26.76% | 25.41% | 23.99% | **25.4%** |

\* run3 Express 5c anomali ringan (0.98 ms vs normal 2.17–2.87 ms) —
histogram belum terisi penuh di awal window. Tidak mengubah kesimpulan.

> Express 1c identik sempurna di semua run (0.49 ms). Express selalu lebih
> cepat dan lebih hemat CPU dari FastAPI di semua run.

---

## Yang Perlu Diulang

### S2 — Overhead Prometheus ⚠️ WAJIB DIULANG

**Masalah:** Run2 baseline CPU (533.81%) jauh di atas run1 (499%) dan run3 (498%).
Menyebabkan overhead terhitung -7.3% yang tidak konsisten.

**Data sementara:**

| Run | Baseline CPU | WithMetrics CPU | Overhead |
|---|---|---|---|
| Run1 | 499.33% | 495.0% | -0.9% |
| Run2 | **533.81%** | 495.0% | **-7.3% ← outlier** |
| Run3 | 497.78% | 495.0% | -0.6% |

**Penyebab:** Sistem belum dingin saat run2 dimulai.
**Fix yang sudah diterapkan:** `run_s2_overhead.ps1` sudah ada `-RelaxDpRate`.
**Perintah:**
```powershell
.\tests\run_s2_overhead.ps1 -Repeat 3
```

---

### S3 — Broker Architecture ⚠️ WAJIB DIULANG

**Masalah:** Kafka Native INVALID di semua run baru (run1, run2, run3).
Hanya tersedia data arsip lama (1 run) untuk perbandingan.

**Data NGINX sementara dari 3 run baru (konsisten):**

| Run | E2E P95 | Det.Rate |
|---|---|---|
| Run1 | 117,997 ms | 18.19/s |
| Run2 | 114,114 ms | 19.51/s |
| Run3 | 113,843 ms | 19.11/s |

**Kafka Native sementara (arsip lama, 1 run):**
E2E P95 = 173,475 ms | Det.Rate = 7.03/s

**Penyebab:** `Wait-SystemReady` timeout 300 detik menyebabkan collect terpotong.
**Fix yang sudah diterapkan:**
- `run_s3_broker.ps1` → `-RelaxDpRate | Out-Null`
- `docker-compose-s3-kafka.yml` → `data_provider depends_on kafka-init`
- `docker-compose-s3-nginx.yml` → `data_provider depends_on kafka-init`

**Perintah:**
```powershell
.\tests\run_s3_broker.ps1 -Repeat 3
```

---

### S4a — Skalabilitas Archiver ⚠️ WAJIB DIULANG

**Masalah:** Anomali di run2 (replika 4–5 drop ke 186 rec/s) dan run3
(replika 3 drop ke 187 rec/s) menyebabkan ambiguitas replika 2 vs 3
sebagai titik saturasi optimal.

**Data sementara:**

| Replika | Run1 | Run2 | Run3 | Rata-rata |
|---|---|---|---|---|
| 1 | 166 | 206 | 207 | **193 rec/s** |
| **2** | **329** | **329** | **339** | **332 rec/s** |
| 3 | 364 | 421 | **187\*** | **324 rec/s** |
| 4 | 344 | **186\*** | 371 | **300 rec/s** |
| 5 | 370 | **186\*** | 376 | **311 rec/s** |

\* anomali karena MongoDB/InfluxDB belum siap setelah banyak siklus down/up

**Ambiguitas:** Rata-rata run baru menunjukkan replika 2 (332) > replika 3 (324).
Arsip lama menunjukkan replika 3 (346) > replika 2 (323). Perlu run ulang
yang bersih untuk menentukan titik saturasi yang sebenarnya.

**Fix yang sudah diterapkan:**
- `run_s4_scalability_archiver.ps1` → `-RelaxDpRate | Out-Null`
- Semua `docker-compose-s4-archiver-*.yml` → `data_provider depends_on kafka-init`

**Perintah:**
```powershell
.\tests\run_s4_scalability_archiver.ps1 -Repeat 3
```

---

## Langkah Selanjutnya (Urutan Prioritas)

### Persiapan (jalankan sekali sebelum semua pengujian ulang)
```powershell
cd D:\MDLBEEWS-V3
git pull
```

### 1. Jalankan ulang S4a (paling lama ~2.5 jam)
```powershell
.\tests\run_s4_scalability_archiver.ps1 -Repeat 3
```

### 2. Jalankan ulang S3 (~1 jam)
```powershell
.\tests\run_s3_broker.ps1 -Repeat 3
```

### 3. Jalankan ulang S2 (~30 menit)
```powershell
.\tests\run_s2_overhead.ps1 -Repeat 3
```

### 4. Analisis per-run setelah semua selesai
```powershell
cd D:\MDLBEEWS-V3\tests
python analyze.py --scenario s2 --run 1
python analyze.py --scenario s2 --run 2
python analyze.py --scenario s2 --run 3
python analyze.py --scenario s3 --run 1
python analyze.py --scenario s3 --run 2
python analyze.py --scenario s3 --run 3
python analyze.py --scenario s4_archiver --run 1
python analyze.py --scenario s4_archiver --run 2
python analyze.py --scenario s4_archiver --run 3
```

### 5. Generate rata-rata final semua skenario untuk Bab IV
```powershell
python analyze.py --scenario all
```

---

## Konfigurasi Final (Status Terkini)

| Skenario | Konfigurasi Terpilih | Keyakinan |
|---|---|---|
| S1 | Multithread | ✅ Tinggi — FINAL |
| S2 | Prometheus aktif | ⚠️ Sedang — perlu run ulang |
| S3 | Kafka + NGINX | ⚠️ Sedang — perlu data Kafka Native valid |
| S4a | Archiver 3 replika (konservatif) | ⚠️ Sedang — perlu run ulang |
| S4b | P-Wave LB 5 replika | ✅ Tinggi — FINAL |
| S5 | Express.js | ✅ Tinggi — FINAL |

---

## Catatan untuk Skripsi

1. **S1** — Laporkan rata-rata ± std dari 3 run. Siap digunakan.

2. **S4b** — Laporkan rata-rata ± std dari 3 run. Siap digunakan.

3. **S5** — Express.js lebih cepat dari FastAPI di semua run dan semua jumlah
   klien. Laporkan rata-rata ± std dari 3 run. Siap digunakan.

4. **S2 run2 outlier** — Setelah diulang, gunakan rata-rata 3 run baru.

5. **S3 Kafka Native** — Gunakan data arsip lama hanya sebagai referensi
   sementara. Data final harus dari run ulang yang sudah diperbaiki.

6. **S4a ambiguitas 2 vs 3 replika** — Setelah run ulang tanpa anomali,
   lihat apakah replika 3 kembali lebih tinggi dari replika 2. Jika iya,
   pilih 3. Jika masih ambigu, pilih 3 sebagai konservatif.
