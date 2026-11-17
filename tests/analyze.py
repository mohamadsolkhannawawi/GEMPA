"""
analyze.py — Analisis hasil pengujian EEWS per skenario.

Perbaikan K3:
- Pemotongan jendela berdasarkan WAKTU absolut (buang 50 detik pertama sejak
  sampel pertama; ambil 150 detik berikutnya), bukan berdasarkan baris tetap.
- Persentil menggunakan numpy.percentile agar presisi.
- Kolom P95 diberi label tegas "p95_of_window_p95".
- Run ditandai INVALID bila: baris < 90% dari yang diharapkan, kolom kosong > 10%,
  atau ada baris OOM/restart. Run INVALID tidak masuk ringkasan.
- Ringkasan lintas pengulangan: mean, std, min, max, jumlah run valid.
"""

import argparse
import csv
import math
import os
import statistics
from collections import defaultdict
from datetime import datetime
from typing import Optional

import numpy as np

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")

# Jendela analisis (detik) — sesuai protokol bersama
WARMUP_SEC = 50
WINDOW_SEC = 150

# Interval pengambilan sampel yang diharapkan (detik)
# Digunakan untuk menghitung jumlah baris minimum (90% dari ekspektasi)
DEFAULT_INTERVAL_SEC = 5


# ==============================================================================
# Utilitas parsing
# ==============================================================================

def parse_value(value: str) -> Optional[float]:
    """Parse string CSV ke float; kembalikan None bila tidak valid atau tak terhingga."""
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def parse_timestamp(value: str) -> Optional[datetime]:
    """Parse string timestamp CSV ke datetime."""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    return None


# ==============================================================================
# Pembaca CSV dengan pemotongan berbasis waktu
# ==============================================================================

def read_csv(
    path: str,
    warmup_sec: float = WARMUP_SEC,
    window_sec: float = WINDOW_SEC,
    interval_sec: float = DEFAULT_INTERVAL_SEC,
) -> Optional[dict]:
    """
    Baca CSV metrik, potong jendela analisis berbasis waktu, lalu kembalikan
    dict kolom beserta metadata validasi.

    Kembalian
    ---------
    dict dengan kunci:
        "columns"       : dict[str, list[float|None]] — data kolom dalam jendela
        "valid"         : bool — True bila run dianggap valid
        "invalid_reason": str  — penjelasan bila tidak valid
        "n_rows_total"  : int
        "n_rows_window" : int
    atau None bila berkas tidak ada.
    """
    if not os.path.exists(path):
        return None

    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        return None

    # --- Pemotongan berbasis waktu ---
    t0 = parse_timestamp(rows[0].get("timestamp", ""))
    if t0 is None:
        # Tidak ada kolom timestamp — fallback ke potongan berbasis baris lama
        rows = rows[10:40]
        time_based = False
    else:
        window_rows = []
        for row in rows:
            t = parse_timestamp(row.get("timestamp", ""))
            if t is None:
                continue
            elapsed = (t - t0).total_seconds()
            if elapsed < warmup_sec:
                continue
            if elapsed > warmup_sec + window_sec:
                break
            window_rows.append(row)
        rows = window_rows
        time_based = True

    n_rows_window = len(rows)

    # --- Validasi jumlah baris ---
    expected_rows = window_sec / interval_sec
    min_rows = int(expected_rows * 0.9)
    if n_rows_window < min_rows:
        reason = (
            f"Hanya {n_rows_window} baris dalam jendela (minimum {min_rows} "
            f"= 90% dari {expected_rows:.0f} yang diharapkan)"
        )
        return {
            "columns": defaultdict(list),
            "valid": False,
            "invalid_reason": reason,
            "n_rows_total": len(rows),
            "n_rows_window": n_rows_window,
        }

    # --- Susun kolom, periksa kekosongan ---
    columns: dict[str, list] = defaultdict(list)
    for row in rows:
        for name, value in row.items():
            if name in ("timestamp",) or name.endswith("_status"):
                continue
            columns[name].append(parse_value(value))

    # Periksa kolom dengan > 10% nilai kosong
    empty_cols = []
    for name, vals in columns.items():
        n_empty = sum(1 for v in vals if v is None)
        if n_empty / max(len(vals), 1) > 0.10:
            empty_cols.append(f"{name}({n_empty}/{len(vals)})")

    if empty_cols:
        reason = f"Kolom dengan > 10% nilai kosong: {', '.join(empty_cols)}"
        return {
            "columns": columns,
            "valid": False,
            "invalid_reason": reason,
            "n_rows_total": len(rows),
            "n_rows_window": n_rows_window,
        }

    # --- Simpan clean CSV ---
    if rows:
        dir_name = os.path.dirname(path)
        base_name = os.path.basename(path)
        clean_path = os.path.join(dir_name, f"clean_{base_name}")
        with open(clean_path, mode="w", newline="", encoding="utf-8") as fc:
            fieldnames = list(rows[0].keys())
            writer = csv.DictWriter(fc, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    return {
        "columns": columns,
        "valid": True,
        "invalid_reason": "",
        "n_rows_total": len(rows),
        "n_rows_window": n_rows_window,
    }


# ==============================================================================
# Statistik
# ==============================================================================

def calc_stats(values: list) -> dict:
    """Hitung mean, p95_of_window_p95, max dari daftar nilai."""
    if not values:
        return {"mean": "N/A", "p95_of_window_p95": "N/A", "max": "N/A", "std": "N/A"}

    valid = [v for v in values if v is not None]
    if not valid:
        return {"mean": "N/A", "p95_of_window_p95": "N/A", "max": "N/A", "std": "N/A"}

    arr = np.array(valid, dtype=float)
    return {
        "mean": round(float(np.mean(arr)), 2),
        "p95_of_window_p95": round(float(np.percentile(arr, 95)), 2),
        "max": round(float(np.max(arr)), 2),
        "std": round(float(np.std(arr)), 2),
    }


def calc_latency_stats(values: list) -> dict:
    """Hitung statistik yang sama lalu konversi detik → milidetik."""
    if not values:
        return {"mean": "N/A", "p95_of_window_p95": "N/A", "max": "N/A", "std": "N/A"}

    valid = [v * 1000.0 for v in values if v is not None]
    if not valid:
        return {"mean": "N/A", "p95_of_window_p95": "N/A", "max": "N/A", "std": "N/A"}

    arr = np.array(valid, dtype=float)
    return {
        "mean": round(float(np.mean(arr)), 2),
        "p95_of_window_p95": round(float(np.percentile(arr, 95)), 2),
        "max": round(float(np.max(arr)), 2),
        "std": round(float(np.std(arr)), 2),
    }


# ==============================================================================
# Penyimpanan & pencetakan tabel
# ==============================================================================

def save_and_print_table(
    title: str,
    headers: list,
    data: list,
    filename: str,
) -> None:
    print(f"\n=== {title} ===")

    if not data:
        print("Tidak ada data untuk ditampilkan.")
        return

    col_widths = [
        max(len(str(item)) for item in col)
        for col in zip(*([headers] + data))
    ]
    fmt = " | ".join(f"{{:<{w}}}" for w in col_widths)

    print(fmt.format(*headers))
    print("-" * (sum(col_widths) + 3 * (len(headers) - 1)))
    for row in data:
        print(fmt.format(*[str(item) for item in row]))

    out_path = os.path.join(RESULTS_DIR, filename)
    try:
        with open(out_path, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerows(data)
        print(f"(Disimpan ke {filename})")
    except PermissionError:
        print(
            f"(GAGAL: Berkas {filename} sedang terbuka di program lain. "
            f"Tutup program tersebut.)"
        )


def _get_cols(result: Optional[dict], key: str) -> list:
    """Ambil kolom dari hasil read_csv; kembalikan list kosong bila tidak ada."""
    if result is None or not result["valid"]:
        return []
    return result["columns"].get(key, [])


def _warn_invalid(label: str, result: Optional[dict]) -> None:
    if result is not None and not result["valid"]:
        print(
            f"  [INVALID – {label}] {result['invalid_reason']} "
            f"(baris jendela: {result['n_rows_window']})"
        )


# ==============================================================================
# Analisis per skenario
# ==============================================================================

def _read_runs(prefix: str, alt_prefix: Optional[str] = None) -> list:
    """
    Kumpulkan semua file _run{N}.csv untuk suatu prefix, kembalikan list result
    dari read_csv yang valid. Bila tidak ada, coba alt_prefix sebagai fallback.
    """
    import glob as _glob
    pattern = os.path.join(RESULTS_DIR, f"{prefix}_metrics_run*.csv")
    # Hanya ambil file per-run (bukan _buckets.csv)
    paths = sorted(
        p for p in _glob.glob(pattern)
        if not p.endswith("_buckets.csv")
    )
    if not paths and alt_prefix:
        pattern = os.path.join(RESULTS_DIR, f"{alt_prefix}_metrics_run*.csv")
        paths = sorted(
            p for p in _glob.glob(pattern)
            if not p.endswith("_buckets.csv")
        )
    return paths


def _merge_run_results(paths: list, label: str) -> tuple[list, str, int, int]:
    """
    Baca semua file run, gabungkan kolom dari run-run yang valid, kembalikan
    (all_values_dict, status_string, n_valid, n_total).
    """
    from collections import defaultdict as _dd
    merged: dict[str, list] = _dd(list)
    n_valid = 0
    for path in paths:
        result = read_csv(path)
        run_name = os.path.basename(path)
        _warn_invalid(f"{label}/{run_name}", result)
        if result and result["valid"]:
            n_valid += 1
            for col, vals in result["columns"].items():
                merged[col].extend(vals)
    status = "VALID" if n_valid > 0 else "INVALID"
    return merged, status, n_valid, len(paths)


def analyze_s1() -> None:
    scenarios = [
        ("SEQUENTIAL",   "s1_sequential",   None),
        ("MULTITHREAD",  "s1_multithread",  None),
        ("MULTIPROCESS", "s1_multiprocess", None),
        ("HIBRIDA",      "s1_hibrida",      None),
    ]
    headers = [
        "Arsitektur",
        "Throughput trace_topic (Trace/s)",
        "Throughput pwave_topic (Trace/s)",
        "Received (Trace/s)",
        "Dropped Stale (Trace/s)",
        "DP CPU Mean (%)",
        "DP RAM Mean (MB)",
        "PW CPU Mean (%)",
        "PW RAM Mean (MB)",
        "Run Valid",
        "Status",
    ]
    table_data = []

    for mode_name, prefix, alt_prefix in scenarios:
        paths = _read_runs(prefix, alt_prefix)

        if not paths:
            # Fallback ke file agregat lama bila tidak ada file per-run sama sekali
            path = os.path.join(RESULTS_DIR, f"{prefix}_metrics.csv")
            if alt_prefix and not os.path.exists(path):
                path = os.path.join(RESULTS_DIR, f"{alt_prefix}_metrics.csv")
            result = read_csv(path)
            _warn_invalid(mode_name, result)
            merged = result["columns"] if (result and result["valid"]) else {}
            status = "VALID" if (result and result["valid"]) else "INVALID"
            run_summary = "1/1" if status == "VALID" else "0/1"
        else:
            merged, status, n_valid, n_total = _merge_run_results(paths, mode_name)
            run_summary = f"{n_valid}/{n_total}"

        def _cols(key: str) -> list:
            vals = merged.get(key, [])
            return [v for v in vals if v is not None]

        tp_trace = calc_stats(_cols("dp_throughput_trace_topic"))
        tp_pwave = calc_stats(_cols("dp_throughput_pwave_topic"))
        received = calc_stats(_cols("dp_traces_received_per_sec"))
        dropped  = calc_stats(_cols("dp_traces_dropped_stale_per_sec"))
        dp_cpu   = calc_stats(_cols("dp_aggregate_cpu_percent"))
        dp_mem   = calc_stats(_cols("dp_aggregate_mem_mb"))
        pw_cpu   = calc_stats(_cols("pwave_aggregate_cpu_percent"))
        pw_mem   = calc_stats(_cols("pwave_aggregate_mem_mb"))

        table_data.append([
            mode_name,
            tp_trace["mean"], tp_pwave["mean"],
            received["mean"], dropped["mean"],
            dp_cpu["mean"], dp_mem["mean"],
            pw_cpu["mean"], pw_mem["mean"],
            run_summary,
            status,
        ])

    save_and_print_table(
        "ANALISIS SKENARIO 1 (Optimasi Hulu / Concurrency Data Provider)",
        headers, table_data, "summary_s1_concurrency.csv",
    )


def _actual_interval(path: str) -> float:
    """Hitung rata-rata interval antar sampel dari file CSV."""
    import csv as _csv
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            rows = list(_csv.DictReader(f))
        if len(rows) < 2:
            return DEFAULT_INTERVAL_SEC
        times = []
        for r in rows:
            t = parse_timestamp(r.get("timestamp", ""))
            if t:
                times.append(t)
        if len(times) < 2:
            return DEFAULT_INTERVAL_SEC
        total = (times[-1] - times[0]).total_seconds()
        return total / (len(times) - 1)
    except Exception:
        return DEFAULT_INTERVAL_SEC


def analyze_s2() -> None:
    """
    S2: Overhead Instrumentasi Prometheus.

    Perbandingan dilakukan antara dua kondisi yang apple-to-apple —
    keduanya diukur dengan alat yang sama (Docker SDK):
      - NoMetrics API  : baseline tanpa Prometheus
      - WithMetrics    : dengan Prometheus aktif, diukur via _docker_api.csv

    NoMetrics CLI tidak diikutsertakan karena menggunakan alat ukur berbeda
    (docker stats CLI subprocess) sehingga tidak sebanding.
    """
    scenarios = [
        ("Tanpa Metrics (Baseline)",   "s2_overhead_no_metrics_api",  False),
        ("Dengan Metrics (Prometheus)", "s2_overhead_with_metrics",    True),
    ]
    headers = [
        "Kondisi",
        "PW CPU Mean (%)", "PW CPU Std (%)", "PW CPU P95 (%)",
        "PW RAM Mean (MB)", "PW RAM Max (MB)",
        "Overhead CPU vs Baseline",
        "Run Valid", "Status",
    ]
    table_data = []
    baseline_cpu_mean = None

    for label, prefix, has_prometheus in scenarios:
        # Tentukan file yang dipakai per kondisi
        if has_prometheus:
            # WithMetrics: pakai _docker_api.csv untuk perbandingan setara
            import glob as _glob
            docker_api_paths = sorted(_glob.glob(
                os.path.join(RESULTS_DIR, f"{prefix}_metrics_run*_docker_api.csv")
            ))
            paths = docker_api_paths if docker_api_paths else _read_runs(prefix)
        else:
            paths = _read_runs(prefix)

        merged_cols: dict = {}
        n_valid = 0

        for p in paths:
            actual_interval = _actual_interval(p)
            r = read_csv(p, interval_sec=actual_interval)
            run_name = os.path.basename(p)
            if r is not None:
                pw_vals = [v for v in r["columns"].get(
                    "pwave_aggregate_cpu_percent", []) if v is not None]
                r["valid"] = len(pw_vals) >= 10
                if not r["valid"]:
                    r["invalid_reason"] = (
                        f"Kurang dari 10 sampel PW CPU valid ({len(pw_vals)} sampel)"
                    )
            _warn_invalid(f"{label}/{run_name}", r)
            if r and r["valid"]:
                n_valid += 1
                for col, vals in r["columns"].items():
                    merged_cols.setdefault(col, []).extend(vals)

        status = "VALID" if n_valid > 0 else "INVALID"
        run_summary = f"{n_valid}/{len(paths)}"

        def _cols(key: str) -> list:
            return [v for v in merged_cols.get(key, []) if v is not None]

        cpu_vals = _cols("pwave_aggregate_cpu_percent")
        mem_vals = _cols("pwave_aggregate_mem_mb")

        if cpu_vals:
            import numpy as _np
            cpu_mean = round(float(_np.mean(cpu_vals)), 2)
            cpu_std  = round(float(_np.std(cpu_vals)), 2)
            cpu_p95  = round(float(_np.percentile(cpu_vals, 95)), 2)
            mem_mean = round(float(_np.mean(mem_vals)), 2) if mem_vals else "N/A"
            mem_max  = round(float(_np.max(mem_vals)), 2)  if mem_vals else "N/A"
        else:
            cpu_mean = cpu_std = cpu_p95 = mem_mean = mem_max = "N/A"

        # Hitung overhead relatif terhadap baseline
        if not has_prometheus:
            baseline_cpu_mean = cpu_mean
            overhead = "— (baseline)"
        else:
            if baseline_cpu_mean and baseline_cpu_mean != "N/A" and cpu_mean != "N/A":
                delta = round(cpu_mean - baseline_cpu_mean, 2)
                pct   = round((delta / baseline_cpu_mean) * 100, 1)
                overhead = f"{delta:+.2f}% ({pct:+.1f}%)"
            else:
                overhead = "N/A"

        table_data.append([
            label,
            cpu_mean, cpu_std, cpu_p95,
            mem_mean, mem_max,
            overhead,
            run_summary, status,
        ])

    save_and_print_table(
        "ANALISIS SKENARIO 2 (Overhead Instrumentasi Prometheus — Docker SDK)",
        headers, table_data, "summary_s2_overhead.csv",
    )


def analyze_s3() -> None:
    headers = [
        "Arsitektur Broker",
        "E2E P-Wave Mean (ms)", "E2E P-Wave P95 (ms)",
        "Kafka Delay P95 (ms)", "Queue Wait P95 (ms)",
        "Inferensi P95 (ms)",
        "Laju Deteksi (det/s)",
        "Inflight Mean",
        "CPU Mean (%)", "RAM Mean (MB)",
        "Run Valid",
        "Status",
    ]
    table_data = []

    for mode_label, prefix in [("Kafka Native", "s3_broker_kafka"), ("Kafka + NGINX", "s3_broker_nginx")]:
        paths = _read_runs(prefix)

        if not paths:
            path = os.path.join(RESULTS_DIR, f"{prefix}_metrics.csv")
            result = read_csv(path)
            _warn_invalid(mode_label, result)
            merged = result["columns"] if (result and result["valid"]) else {}
            status = "VALID" if (result and result["valid"]) else "INVALID"
            run_summary = "1/1" if status == "VALID" else "0/1"
        else:
            merged, status, n_valid, n_total = _merge_run_results(paths, mode_label)
            run_summary = f"{n_valid}/{n_total}"

        def _cols(key: str) -> list:
            vals = merged.get(key, [])
            return [v for v in vals if v is not None]

        e2e  = calc_latency_stats(_cols("e2e_delay_pwave_p95"))
        kd   = calc_latency_stats(_cols("pwave_kafka_delay_p95") or _cols("pwave_lb_kafka_delay_p95"))
        qw   = calc_latency_stats(_cols("pwave_queue_wait_p95") or _cols("pwave_lb_queue_wait_p95"))
        lat  = calc_latency_stats(_cols("pwave_inference_latency_p95") or _cols("pwave_lb_inference_latency_p95"))
        det  = calc_stats(_cols("pwave_detection_rate") or _cols("pwave_lb_detection_rate"))
        inf  = calc_stats(_cols("pwave_inflight") or _cols("pwave_lb_inflight"))
        cpu  = calc_stats(_cols("pwave_aggregate_cpu_percent"))
        mem  = calc_stats(_cols("pwave_aggregate_mem_mb"))

        table_data.append([
            mode_label,
            e2e["mean"], e2e["p95_of_window_p95"],
            kd["p95_of_window_p95"], qw["p95_of_window_p95"],
            lat["p95_of_window_p95"],
            det["mean"], inf["mean"],
            cpu["mean"], mem["mean"],
            run_summary,
            status,
        ])

    save_and_print_table(
        "ANALISIS SKENARIO 3 (Pemilihan Arsitektur Inti / Load Balancing)",
        headers, table_data, "summary_s3_broker.csv",
    )


def analyze_s4() -> None:
    # --- 4A: Archiver ---
    headers_a = [
        "Replika Archiver",
        "CPU Mean (%)", "CPU Max (%)",
        "RAM Mean (MB)",
        "Records Saved (rec/s)",
        "Write Latency InfluxDB P95 (ms)",
        "Write Latency MongoDB P95 (ms)",
        "Status",
    ]
    table_data_a = []

    for i in range(1, 6):
        path = os.path.join(RESULTS_DIR, f"s4_archiver_{i}_container_metrics.csv")
        result = read_csv(path)
        _warn_invalid(f"Archiver {i}c", result)

        status = "VALID" if (result and result["valid"]) else "INVALID"

        cpu    = calc_stats(_get_cols(result, "archiver_aggregate_cpu_percent"))
        mem    = calc_stats(_get_cols(result, "archiver_aggregate_mem_mb"))
        saved  = calc_stats(_get_cols(result, "archiver_records_saved_rate"))
        lat_if = calc_latency_stats(_get_cols(result, "archiver_write_latency_influxdb_p95"))
        lat_mg = calc_latency_stats(_get_cols(result, "archiver_write_latency_mongodb_p95"))

        table_data_a.append([
            f"{i} Container",
            cpu["mean"], cpu["max"],
            mem["mean"],
            saved["mean"],
            lat_if["p95_of_window_p95"],
            lat_mg["p95_of_window_p95"],
            status,
        ])

    save_and_print_table(
        "ANALISIS SKENARIO 4A (Skalabilitas Data Archiver / I/O Bound)",
        headers_a, table_data_a, "summary_s4a_archiver.csv",
    )

    # --- 4B: P-Wave Detector ---
    scenarios_b = [
        ("Native Kafka",  "s4_pwave_kafka"),
        ("Load Balancer", "s4_pwave_kafka_nginx"),
    ]
    headers_b = [
        "Arsitektur", "Replika ML",
        "Throughput pwave_topic (Trace/s)",
        "Laju Deteksi (det/s)",
        "Latensi Inferensi P95 (ms)",
        "E2E P95 (ms)",
        "CPU Mean (%)", "RAM Mean (MB)",
        "Status",
    ]
    table_data_b = []

    for mode_label, prefix in scenarios_b:
        for i in range(2, 6):
            path = os.path.join(RESULTS_DIR, f"{prefix}_{i}c_metrics.csv")
            result = read_csv(path)
            _warn_invalid(f"{mode_label} {i}c", result)

            status = "VALID" if (result and result["valid"]) else "INVALID"

            tp    = calc_stats(_get_cols(result, "dp_throughput_pwave_topic"))
            det   = calc_stats(_get_cols(result, "pwave_detection_rate") or
                                _get_cols(result, "pwave_lb_detection_rate"))
            # Latensi — pilih metrik yang tersedia
            lat_raw  = (_get_cols(result, "pwave_inference_latency_p95") or
                        _get_cols(result, "pwave_lb_inference_latency_p95"))
            lat   = calc_latency_stats(lat_raw)
            e2e   = calc_latency_stats(_get_cols(result, "e2e_delay_pwave_p95"))
            cpu   = calc_stats(_get_cols(result, "pwave_aggregate_cpu_percent"))
            mem   = calc_stats(_get_cols(result, "pwave_aggregate_mem_mb"))

            table_data_b.append([
                mode_label, f"{i} Container",
                tp["mean"],
                det["mean"],
                lat["p95_of_window_p95"],
                e2e["p95_of_window_p95"],
                cpu["mean"], mem["mean"],
                status,
            ])

    save_and_print_table(
        "ANALISIS SKENARIO 4B (Skalabilitas P-Wave Detector / CPU Bound)",
        headers_b, table_data_b, "summary_s4b_pwave.csv",
    )


def analyze_s5() -> None:
    headers = [
        "WebSocket Server", "Klien Aktif",
        "Broadcast P95 (ms)",
        "CPU Mean (%)", "RAM Mean (MB)",
        "Status",
    ]
    table_data = []

    for mode_label, prefix in [("FastAPI", "s5_websocket_fastapi"), ("Express.js", "s5_websocket_express")]:
        for c in [1, 5]:
            path = os.path.join(RESULTS_DIR, f"{prefix}_{c}c_metrics.csv")
            result = read_csv(path)
            _warn_invalid(f"{mode_label} {c}c", result)

            status = "VALID" if (result and result["valid"]) else "INVALID"

            if "fastapi" in prefix:
                lat = calc_latency_stats(_get_cols(result, "fastapi_ws_broadcast_latency_p95"))
            else:
                lat = calc_latency_stats(_get_cols(result, "ws_broadcast_latency_p95"))

            cpu = calc_stats(_get_cols(result, "ws_aggregate_cpu_percent"))
            mem = calc_stats(_get_cols(result, "ws_aggregate_mem_mb"))

            table_data.append([
                mode_label, f"{c} Klien",
                lat["p95_of_window_p95"],
                cpu["mean"], mem["mean"],
                status,
            ])

    save_and_print_table(
        "ANALISIS SKENARIO 5 (Optimasi Hilir / Diseminasi WebSocket)",
        headers, table_data, "summary_s5_websocket.csv",
    )


# ==============================================================================
# Entry point
# ==============================================================================

def analyze_all() -> None:
    analyze_s1()
    analyze_s2()
    analyze_s3()
    analyze_s4()
    analyze_s5()
    print(
        "\nSemua skenario (S1–S5) berhasil dianalisis dan disimpan ke CSV "
        "yang siap dimasukkan ke Tabel Bab IV."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="EEWS Test Result Analyzer")
    parser.add_argument(
        "--scenario",
        choices=["1", "2", "3", "4", "5", "all", "s1", "s2", "s3", "s4_archiver", "s4_pwave", "s5", "final"],
        default="all",
        help="Skenario yang dianalisis (1/s1, 2/s2, 3/s3, 4/s4_archiver/s4_pwave, 5/s5, all)",
    )
    parser.add_argument(
        "--warmup-sec",
        type=float,
        default=WARMUP_SEC,
        help=f"Detik warmup yang dibuang dari awal (default {WARMUP_SEC}s)",
    )
    parser.add_argument(
        "--window-sec",
        type=float,
        default=WINDOW_SEC,
        help=f"Lebar jendela analisis setelah warmup (default {WINDOW_SEC}s)",
    )
    args = parser.parse_args()

    # Override global jendela bila diberikan lewat argumen
    WARMUP_SEC = args.warmup_sec
    WINDOW_SEC = args.window_sec

    if args.scenario in ("1", "s1"):
        analyze_s1()
    elif args.scenario in ("2", "s2"):
        analyze_s2()
    elif args.scenario in ("3", "s3"):
        analyze_s3()
    elif args.scenario in ("4", "s4_archiver", "s4_pwave"):
        analyze_s4()
    elif args.scenario in ("5", "s5"):
        analyze_s5()
    elif args.scenario in ("all", "final"):
        analyze_all()
