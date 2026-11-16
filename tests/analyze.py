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

def analyze_s1() -> None:
    scenarios = [
        ("SEQUENTIAL",  "s1_sequential"),
        ("MULTITHREAD",  "s1_multithread"),
        ("MULTIPROCESS", "s1_multiprocess"),
        ("MP_MT",        "s1_mp_mt"),
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
        "Status",
    ]
    table_data = []

    for mode_name, prefix in scenarios:
        path = os.path.join(RESULTS_DIR, f"{prefix}_metrics.csv")
        result = read_csv(path)
        _warn_invalid(mode_name, result)

        status = "VALID" if (result and result["valid"]) else "INVALID"

        tp_trace = calc_stats(_get_cols(result, "dp_throughput_trace_topic"))
        tp_pwave = calc_stats(_get_cols(result, "dp_throughput_pwave_topic"))
        received = calc_stats(_get_cols(result, "dp_traces_received_per_sec"))
        dropped  = calc_stats(_get_cols(result, "dp_traces_dropped_stale_per_sec"))
        dp_cpu   = calc_stats(_get_cols(result, "dp_aggregate_cpu_percent"))
        dp_mem   = calc_stats(_get_cols(result, "dp_aggregate_mem_mb"))
        pw_cpu   = calc_stats(_get_cols(result, "pwave_aggregate_cpu_percent"))
        pw_mem   = calc_stats(_get_cols(result, "pwave_aggregate_mem_mb"))

        table_data.append([
            mode_name,
            tp_trace["mean"], tp_pwave["mean"],
            received["mean"], dropped["mean"],
            dp_cpu["mean"], dp_mem["mean"],
            pw_cpu["mean"], pw_mem["mean"],
            status,
        ])

    save_and_print_table(
        "ANALISIS SKENARIO 1 (Optimasi Hulu / Concurrency Data Provider)",
        headers, table_data, "summary_s1_concurrency.csv",
    )


def analyze_s2() -> None:
    scenarios = [
        ("Tanpa Metrics (CLI)", "s2_overhead_no_metrics_cli"),
        ("Tanpa Metrics (API)", "s2_overhead_no_metrics_api"),
        ("Dengan Metrics (Prometheus)", "s2_overhead_with_metrics"),
    ]
    headers = [
        "Kondisi",
        "DP CPU Mean (%)", "DP CPU P95 (%)",
        "DP RAM Mean (MB)", "DP RAM Max (MB)",
        "PW CPU Mean (%)", "PW CPU P95 (%)",
        "PW RAM Mean (MB)", "PW RAM Max (MB)",
        "Status",
    ]
    table_data = []

    for label, prefix in scenarios:
        path = os.path.join(RESULTS_DIR, f"{prefix}_metrics.csv")
        result = read_csv(path)
        _warn_invalid(label, result)

        status = "VALID" if (result and result["valid"]) else "INVALID"

        dp_cpu = calc_stats(_get_cols(result, "dp_aggregate_cpu_percent"))
        dp_mem = calc_stats(_get_cols(result, "dp_aggregate_mem_mb"))
        pw_cpu = calc_stats(_get_cols(result, "pwave_aggregate_cpu_percent"))
        pw_mem = calc_stats(_get_cols(result, "pwave_aggregate_mem_mb"))

        table_data.append([
            label,
            dp_cpu["mean"], dp_cpu["p95_of_window_p95"],
            dp_mem["mean"], dp_mem["max"],
            pw_cpu["mean"], pw_cpu["p95_of_window_p95"],
            pw_mem["mean"], pw_mem["max"],
            status,
        ])

    save_and_print_table(
        "ANALISIS SKENARIO 2 (Overhead Instrumentasi)",
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
        "Status",
    ]
    table_data = []

    for mode_label, prefix in [("Kafka Native", "s3_broker_kafka"), ("Kafka + NGINX", "s3_broker_nginx")]:
        path = os.path.join(RESULTS_DIR, f"{prefix}_metrics.csv")
        result = read_csv(path)
        _warn_invalid(mode_label, result)

        status = "VALID" if (result and result["valid"]) else "INVALID"

        e2e  = calc_latency_stats(_get_cols(result, "e2e_delay_pwave_p95"))
        kd   = calc_latency_stats(_get_cols(result, "pwave_kafka_delay_p95") or
                                   _get_cols(result, "pwave_lb_kafka_delay_p95"))
        qw   = calc_latency_stats(_get_cols(result, "pwave_queue_wait_p95") or
                                   _get_cols(result, "pwave_lb_queue_wait_p95"))
        lat  = calc_latency_stats(_get_cols(result, "pwave_inference_latency_p95") or
                                   _get_cols(result, "pwave_lb_inference_latency_p95"))
        det  = calc_stats(_get_cols(result, "pwave_detection_rate") or
                           _get_cols(result, "pwave_lb_detection_rate"))
        inf  = calc_stats(_get_cols(result, "pwave_inflight") or
                           _get_cols(result, "pwave_lb_inflight"))
        cpu  = calc_stats(_get_cols(result, "pwave_aggregate_cpu_percent"))
        mem  = calc_stats(_get_cols(result, "pwave_aggregate_mem_mb"))

        table_data.append([
            mode_label,
            e2e["mean"], e2e["p95_of_window_p95"],
            kd["p95_of_window_p95"], qw["p95_of_window_p95"],
            lat["p95_of_window_p95"],
            det["mean"], inf["mean"],
            cpu["mean"], mem["mean"],
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
        choices=["1", "2", "3", "4", "5", "all"],
        default="all",
        help="Skenario yang dianalisis",
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

    if args.scenario == "1":
        analyze_s1()
    elif args.scenario == "2":
        analyze_s2()
    elif args.scenario == "3":
        analyze_s3()
    elif args.scenario == "4":
        analyze_s4()
    elif args.scenario == "5":
        analyze_s5()
    else:
        analyze_all()
