"""
analyze.py — Analisis terpadu hasil pengujian prototipe EEWS per skenario (S1–S5).

Perbaikan terpadu:
- Pemotongan jendela analisis berbasis waktu absolut (buang WARMUP_SEC=50s awal;
  ambil WINDOW_SEC=150s berikutnya) dengan binding argumen dinamis agar flag CLI
  --warmup-sec dan --window-sec berfungsi penuh.
- Interval sampling aktual (_actual_interval) diterapkan seragam di S1–S5.
- Persentil P95 menggunakan numpy.percentile dengan label tegas "p95_of_window_p95".
- Menyertakan simpangan baku (Std) pada metrik utama di seluruh ringkasan S1–S5.
- Mengintegrasikan uji validitas statistik Skenario 2 (per-run & grand mean vs
  pooled-std pada jendela 50–200s yang sama) sehingga tidak memerlukan skrip
  s2_analysis.py terpisah.
"""

import argparse
import csv
import glob
import math
import os
from collections import defaultdict
from datetime import datetime
from typing import Optional

import numpy as np

RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")

# Jendela analisis (detik) — sesuai protokol pengujian
WARMUP_SEC = 50.0
WINDOW_SEC = 150.0

# Interval pengambilan sampel default (detik)
DEFAULT_INTERVAL_SEC = 5.0

# Run yang dianalisis (None = gabungkan semua run yang ada)
CURRENT_RUN: Optional[int] = None


def _run_suffix() -> str:
    """Kembalikan suffix nama file output, mis. '_run2' atau '' untuk gabungan."""
    return f"_run{CURRENT_RUN}" if CURRENT_RUN is not None else ""


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


def _actual_interval(path: str) -> float:
    """Hitung rata-rata interval antar sampel dari file CSV."""
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        if len(rows) < 2:
            return DEFAULT_INTERVAL_SEC
        times = [t for r in rows if (t := parse_timestamp(r.get("timestamp", ""))) is not None]
        if len(times) < 2:
            return DEFAULT_INTERVAL_SEC
        total = (times[-1] - times[0]).total_seconds()
        return total / (len(times) - 1)
    except Exception:
        return DEFAULT_INTERVAL_SEC


# ==============================================================================
# Pembaca CSV dengan pemotongan berbasis waktu
# ==============================================================================

def read_csv(
    path: str,
    warmup_sec: Optional[float] = None,
    window_sec: Optional[float] = None,
    interval_sec: float = DEFAULT_INTERVAL_SEC,
) -> Optional[dict]:
    """
    Baca CSV metrik, potong jendela analisis berbasis waktu, lalu kembalikan
    dict kolom beserta metadata validasi.
    """
    if not os.path.exists(path):
        return None

    w_warmup = WARMUP_SEC if warmup_sec is None else warmup_sec
    w_window = WINDOW_SEC if window_sec is None else window_sec

    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        return None

    t0 = parse_timestamp(rows[0].get("timestamp", ""))
    if t0 is None:
        rows = rows[10:40]
    else:
        window_rows = []
        for row in rows:
            t = parse_timestamp(row.get("timestamp", ""))
            if t is None:
                continue
            elapsed = (t - t0).total_seconds()
            if elapsed < w_warmup:
                continue
            if elapsed > w_warmup + w_window:
                break
            window_rows.append(row)
        rows = window_rows

    n_rows_window = len(rows)
    expected_rows = w_window / max(interval_sec, 0.1)
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

    columns: dict[str, list] = defaultdict(list)
    for row in rows:
        for name, value in row.items():
            if name in ("timestamp",) or name.endswith("_status"):
                continue
            columns[name].append(parse_value(value))

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
    """Hitung mean, p95_of_window_p95, max, dan std dari daftar nilai."""
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
    """Hitung statistik yang sama lalu konversi detik ke milidetik."""
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


def _warn_invalid(label: str, result: Optional[dict]) -> None:
    if result is not None and not result["valid"]:
        print(
            f"  [INVALID – {label}] {result['invalid_reason']} "
            f"(baris jendela: {result['n_rows_window']})"
        )


def _read_runs(prefix: str, alt_prefix: Optional[str] = None, run: Optional[int] = None) -> list:
    """Kumpulkan file _run{N}.csv untuk suatu prefix."""
    if run is not None:
        pattern = os.path.join(RESULTS_DIR, f"{prefix}_metrics_run{run}.csv")
        paths = [pattern] if os.path.exists(pattern) else []
        if not paths and alt_prefix:
            pattern = os.path.join(RESULTS_DIR, f"{alt_prefix}_metrics_run{run}.csv")
            paths = [pattern] if os.path.exists(pattern) else []
        return paths

    pattern = os.path.join(RESULTS_DIR, f"{prefix}_metrics_run*.csv")
    paths = sorted(p for p in glob.glob(pattern) if not p.endswith("_buckets.csv"))
    if not paths and alt_prefix:
        pattern = os.path.join(RESULTS_DIR, f"{alt_prefix}_metrics_run*.csv")
        paths = sorted(p for p in glob.glob(pattern) if not p.endswith("_buckets.csv"))
    return paths


def _merge_run_results(paths: list, label: str) -> tuple[dict, str, int, int]:
    """Baca semua file run dengan interval aktual dan gabungkan run yang valid."""
    merged: dict[str, list] = defaultdict(list)
    n_valid = 0
    for path in paths:
        interval = _actual_interval(path)
        result = read_csv(path, interval_sec=interval)
        run_name = os.path.basename(path)
        _warn_invalid(f"{label}/{run_name}", result)
        if result and result["valid"]:
            n_valid += 1
            for col, vals in result["columns"].items():
                merged[col].extend(vals)
    status = "VALID" if n_valid > 0 else "INVALID"
    return merged, status, n_valid, len(paths)


# ==============================================================================
# Analisis per skenario
# ==============================================================================

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
        "Throughput trace_topic Std",
        "Throughput pwave_topic (Trace/s)",
        "Received (Trace/s)",
        "Dropped Stale (Trace/s)",
        "DP CPU Mean (%)", "DP CPU Std (%)",
        "DP RAM Mean (MB)", "DP RAM Std (MB)",
        "PW CPU Mean (%)", "PW RAM Mean (MB)",
        "Run Valid", "Status",
    ]
    table_data = []

    for mode_name, prefix, alt_prefix in scenarios:
        paths = _read_runs(prefix, alt_prefix, run=CURRENT_RUN)

        if not paths:
            path = os.path.join(RESULTS_DIR, f"{prefix}_metrics.csv")
            if alt_prefix and not os.path.exists(path):
                path = os.path.join(RESULTS_DIR, f"{alt_prefix}_metrics.csv")
            result = read_csv(path, interval_sec=_actual_interval(path))
            _warn_invalid(mode_name, result)
            merged = result["columns"] if (result and result["valid"]) else {}
            status = "VALID" if (result and result["valid"]) else "INVALID"
            run_summary = "1/1" if status == "VALID" else "0/1"
        else:
            merged, status, n_valid, n_total = _merge_run_results(paths, mode_name)
            run_summary = f"{n_valid}/{n_total}"

        def _cols(key: str) -> list:
            return [v for v in merged.get(key, []) if v is not None]

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
            tp_trace["mean"], tp_trace["std"],
            tp_pwave["mean"],
            received["mean"], dropped["mean"],
            dp_cpu["mean"], dp_cpu["std"],
            dp_mem["mean"], dp_mem["std"],
            pw_cpu["mean"], pw_mem["mean"],
            run_summary, status,
        ])

    save_and_print_table(
        "ANALISIS SKENARIO 1 (Optimasi Hulu / Concurrency Data Provider)",
        headers, table_data, f"summary_s1_concurrency{_run_suffix()}.csv",
    )


def analyze_s2() -> None:
    """
    S2: Overhead Instrumentasi Prometheus (Docker SDK) + Uji Signifikansi Pooled-Std.
    """
    scenarios = [
        ("Tanpa Metrics (Baseline)",    "s2_overhead_no_metrics_api", False),
        ("Dengan Metrics (Prometheus)", "s2_overhead_with_metrics",   True),
    ]
    headers = [
        "Kondisi",
        "PW CPU Mean (%)", "PW CPU Std (%)", "PW CPU P95 (%)",
        "PW RAM Mean (MB)", "PW RAM Std (MB)", "PW RAM Max (MB)",
        "Overhead CPU vs Baseline",
        "Run Valid", "Status",
    ]
    table_data = []
    baseline_cpu_mean = None
    per_run_stats: dict[str, list[tuple[float, float, float]]] = {"base": [], "prom": []}

    for label, prefix, has_prometheus in scenarios:
        if has_prometheus:
            if CURRENT_RUN is not None:
                p = os.path.join(RESULTS_DIR, f"{prefix}_metrics_run{CURRENT_RUN}_docker_api.csv")
                docker_api_paths = [p] if os.path.exists(p) else []
            else:
                docker_api_paths = sorted(glob.glob(
                    os.path.join(RESULTS_DIR, f"{prefix}_metrics_run*_docker_api.csv")
                ))
            paths = docker_api_paths if docker_api_paths else _read_runs(prefix, run=CURRENT_RUN)
        else:
            paths = _read_runs(prefix, run=CURRENT_RUN)

        merged_cols: dict[str, list] = defaultdict(list)
        n_valid = 0

        for p in paths:
            r = read_csv(p, interval_sec=_actual_interval(p))
            run_name = os.path.basename(p)
            if r is not None:
                pw_vals = [v for v in r["columns"].get("pwave_aggregate_cpu_percent", []) if v is not None]
                r["valid"] = len(pw_vals) >= 10
                if not r["valid"]:
                    r["invalid_reason"] = f"Kurang dari 10 sampel PW CPU valid ({len(pw_vals)} sampel)"
            _warn_invalid(f"{label}/{run_name}", r)
            if r and r["valid"]:
                n_valid += 1
                for col, vals in r["columns"].items():
                    merged_cols[col].extend(vals)
                run_cpu = calc_stats([v for v in r["columns"].get("pwave_aggregate_cpu_percent", []) if v is not None])
                run_mem = calc_stats([v for v in r["columns"].get("pwave_aggregate_mem_mb", []) if v is not None])
                key = "prom" if has_prometheus else "base"
                if run_cpu["mean"] != "N/A":
                    per_run_stats[key].append((float(run_cpu["mean"]), float(run_cpu["std"]), float(run_mem["mean"])))

        status = "VALID" if n_valid > 0 else "INVALID"
        run_summary = f"{n_valid}/{len(paths)}"

        cpu_s = calc_stats([v for v in merged_cols.get("pwave_aggregate_cpu_percent", []) if v is not None])
        mem_s = calc_stats([v for v in merged_cols.get("pwave_aggregate_mem_mb", []) if v is not None])

        if not has_prometheus:
            baseline_cpu_mean = cpu_s["mean"]
            overhead = "— (baseline)"
        else:
            if baseline_cpu_mean and baseline_cpu_mean != "N/A" and cpu_s["mean"] != "N/A":
                delta = round(float(cpu_s["mean"]) - float(baseline_cpu_mean), 2)
                pct = round((delta / float(baseline_cpu_mean)) * 100, 1)
                overhead = f"{delta:+.2f}% ({pct:+.1f}%)"
            else:
                overhead = "N/A"

        table_data.append([
            label,
            cpu_s["mean"], cpu_s["std"], cpu_s["p95_of_window_p95"],
            mem_s["mean"], mem_s["std"], mem_s["max"],
            overhead,
            run_summary, status,
        ])

    save_and_print_table(
        "ANALISIS SKENARIO 2 (Overhead Instrumentasi Prometheus — Docker SDK)",
        headers, table_data, f"summary_s2_overhead{_run_suffix()}.csv",
    )

    # Uji signifikansi statistik per-run & grand mean (menggantikan s2_analysis.py)
    if per_run_stats["base"] and len(per_run_stats["base"]) == len(per_run_stats["prom"]):
        print("\n--- Uji Signifikansi Pooled-Std Skenario 2 (Jendela Steady-State) ---")
        for idx, ((nm, ns, nrm), (wm, ws, wrm)) in enumerate(zip(per_run_stats["base"], per_run_stats["prom"]), 1):
            diff = wm - nm
            pooled_std = (ns + ws) / 2.0
            sig = "SIGNIFIKAN" if abs(diff) >= pooled_std else "NOISE NORMAL"
            print(
                f"  Run {idx}: NoMetrics={nm:.2f}%±{ns:.2f}% (RAM {nrm:.1f} MB) | "
                f"WithMetrics={wm:.2f}%±{ws:.2f}% (RAM {wrm:.1f} MB) | "
                f"Selisih={diff:+.2f}% | PooledStd={pooled_std:.2f}% -> {sig}"
            )
        g_no = sum(x[0] for x in per_run_stats["base"]) / len(per_run_stats["base"])
        g_wi = sum(x[0] for x in per_run_stats["prom"]) / len(per_run_stats["prom"])
        g_ns = sum(x[1] for x in per_run_stats["base"]) / len(per_run_stats["base"])
        g_ws = sum(x[1] for x in per_run_stats["prom"]) / len(per_run_stats["prom"])
        g_pooled = (g_ns + g_ws) / 2.0
        ratio = abs(g_wi - g_no) / g_pooled if g_pooled > 0 else 0.0
        kesimpulan = "NOISE (bukan overhead nyata)" if ratio < 0.5 else "Perlu investigasi"
        print(
            f"  Grand Mean: NoMetrics={g_no:.2f}%±{g_ns:.2f}% vs WithMetrics={g_wi:.2f}%±{g_ws:.2f}% | "
            f"Selisih={g_wi - g_no:+.2f}% ({ratio:.2f}x pooled-std -> {kesimpulan})"
        )


def analyze_s3() -> None:
    scenarios = [
        ("Kafka Native",  "s3_broker_kafka", False),
        ("Kafka + NGINX", "s3_broker_nginx", True),
    ]
    headers = [
        "Arsitektur Broker",
        "Throughput pwave_topic (tr/s)",
        "E2E P-Wave Mean (ms)", "E2E P-Wave P95 (ms)", "E2E P-Wave Std (ms)",
        "Kafka Delay P95 (ms)", "Queue Wait P95 (ms)",
        "Inferensi P95 (ms)",
        "Laju Deteksi (det/s)", "Laju Deteksi Std",
        "Inflight Mean",
        "CPU Mean (%)", "CPU Std (%)",
        "RAM Mean (MB)", "RAM Std (MB)",
        "Consumer Lag Mean",
        "Run Valid", "Status",
    ]
    table_data = []

    for mode_label, prefix, is_lb in scenarios:
        paths = _read_runs(prefix, run=CURRENT_RUN)
        merged_cols: dict[str, list] = defaultdict(list)
        n_valid = 0
        for p in paths:
            r = read_csv(p, interval_sec=_actual_interval(p))
            run_name = os.path.basename(p)
            if r is not None:
                cpu_vals = [v for v in r["columns"].get("pwave_aggregate_cpu_percent", []) if v is not None]
                tp_vals  = [v for v in r["columns"].get("dp_throughput_pwave_topic", []) if v is not None]
                if len(cpu_vals) >= 10 or len(tp_vals) >= 10:
                    r["valid"] = True
            _warn_invalid(f"{mode_label}/{run_name}", r)
            if r and r["valid"]:
                n_valid += 1
                for col, vals in r["columns"].items():
                    merged_cols[col].extend(vals)

        status = "VALID" if n_valid > 0 else "INVALID"
        run_summary = f"{n_valid}/{len(paths)}" if paths else "0/0"

        def _cols(key: str) -> list:
            return [v for v in merged_cols.get(key, []) if v is not None]

        if is_lb:
            lat_col, kd_col, qw_col, det_col, inf_col = (
                "pwave_lb_inference_latency_p95", "pwave_lb_kafka_delay_p95",
                "pwave_lb_queue_wait_p95", "pwave_lb_detection_rate", "pwave_lb_inflight"
            )
        else:
            lat_col, kd_col, qw_col, det_col, inf_col = (
                "pwave_inference_latency_p95", "pwave_kafka_delay_p95",
                "pwave_queue_wait_p95", "pwave_detection_rate", "pwave_inflight"
            )

        tp  = calc_stats(_cols("dp_throughput_pwave_topic"))
        e2e = calc_latency_stats(_cols("e2e_delay_pwave_p95"))
        kd  = calc_latency_stats(_cols(kd_col))
        qw  = calc_latency_stats(_cols(qw_col))
        lat = calc_latency_stats(_cols(lat_col))
        det = calc_stats(_cols(det_col))
        inf = calc_stats(_cols(inf_col))
        cpu = calc_stats(_cols("pwave_aggregate_cpu_percent"))
        mem = calc_stats(_cols("pwave_aggregate_mem_mb"))
        lag = calc_stats(_cols("kafka_consumer_lag_total"))

        table_data.append([
            mode_label,
            tp["mean"],
            e2e["mean"], e2e["p95_of_window_p95"], e2e["std"],
            kd["p95_of_window_p95"], qw["p95_of_window_p95"],
            lat["p95_of_window_p95"],
            det["mean"], det["std"],
            inf["mean"],
            cpu["mean"], cpu["std"],
            mem["mean"], mem["std"],
            lag["mean"],
            run_summary, status,
        ])

    save_and_print_table(
        "ANALISIS SKENARIO 3 (Pemilihan Arsitektur Inti / Load Balancing)",
        headers, table_data, f"summary_s3_broker{_run_suffix()}.csv",
    )


def analyze_s4() -> None:
    analyze_s4a()
    analyze_s4b()


def analyze_s4a() -> None:
    headers_a = [
        "Replika Archiver",
        "CPU Mean (%)", "CPU Std (%)", "CPU Max (%)",
        "RAM Mean (MB)", "RAM Std (MB)",
        "Records Saved (rec/s)", "Records Saved Std",
        "Write Latency InfluxDB P95 (ms)",
        "Write Latency MongoDB P95 (ms)",
        "Run Valid", "Status",
    ]
    table_data_a = []

    for i in range(1, 6):
        paths = _read_runs(f"s4_archiver_{i}_container", run=CURRENT_RUN)
        merged_cols: dict[str, list] = defaultdict(list)
        n_valid = 0
        for p in paths:
            r = read_csv(p, interval_sec=_actual_interval(p))
            run_name = os.path.basename(p)
            if r is not None:
                cpu_vals = [v for v in r["columns"].get("archiver_aggregate_cpu_percent", []) if v is not None]
                if len(cpu_vals) >= 10:
                    r["valid"] = True
            _warn_invalid(f"Archiver {i}c/{run_name}", r)
            if r and r["valid"]:
                n_valid += 1
                for col, vals in r["columns"].items():
                    merged_cols[col].extend(vals)

        status = "VALID" if n_valid > 0 else "INVALID"
        run_summary = f"{n_valid}/{len(paths)}" if paths else "0/0"

        def _cols_a(key: str) -> list:
            return [v for v in merged_cols.get(key, []) if v is not None]

        cpu    = calc_stats(_cols_a("archiver_aggregate_cpu_percent"))
        mem    = calc_stats(_cols_a("archiver_aggregate_mem_mb"))
        saved  = calc_stats(_cols_a("archiver_records_saved_rate"))
        lat_if = calc_latency_stats(_cols_a("archiver_write_latency_influxdb_p95"))
        lat_mg = calc_latency_stats(_cols_a("archiver_write_latency_mongodb_p95"))

        table_data_a.append([
            f"{i} Container",
            cpu["mean"], cpu["std"], cpu["max"],
            mem["mean"], mem["std"],
            saved["mean"], saved["std"],
            lat_if["p95_of_window_p95"],
            lat_mg["p95_of_window_p95"],
            run_summary, status,
        ])

    save_and_print_table(
        "ANALISIS SKENARIO 4A (Skalabilitas Data Archiver / I/O Bound)",
        headers_a, table_data_a, f"summary_s4a_archiver{_run_suffix()}.csv",
    )


def analyze_s4b() -> None:
    scenarios_b = [
        ("Native Kafka",  "s4_pwave_kafka",      False, range(2, 6)),
        ("Load Balancer", "s4_pwave_kafka_nginx", True,  range(2, 6)),
    ]
    headers_b = [
        "Arsitektur", "Replika ML",
        "Throughput pwave_topic (Trace/s)",
        "Laju Deteksi (det/s)", "Laju Deteksi Std",
        "Latensi Inferensi P95 (ms)",
        "E2E P95 (ms)",
        "CPU Mean (%)", "CPU Std (%)",
        "RAM Mean (MB)", "RAM Std (MB)",
        "Run Valid", "Status",
    ]
    table_data_b = []

    for mode_label, prefix, is_lb, replika_range in scenarios_b:
        for i in replika_range:
            paths = _read_runs(f"{prefix}_{i}c", run=CURRENT_RUN)
            merged_cols2: dict[str, list] = defaultdict(list)
            n_valid = 0
            for p in paths:
                r = read_csv(p, interval_sec=_actual_interval(p))
                run_name = os.path.basename(p)
                if r is not None:
                    cpu_vals = [v for v in r["columns"].get("pwave_aggregate_cpu_percent", []) if v is not None]
                    tp_vals  = [v for v in r["columns"].get("dp_throughput_pwave_topic", []) if v is not None]
                    if len(cpu_vals) >= 10 or len(tp_vals) >= 10:
                        r["valid"] = True
                _warn_invalid(f"{mode_label} {i}c/{run_name}", r)
                if r and r["valid"]:
                    n_valid += 1
                    for col, vals in r["columns"].items():
                        merged_cols2[col].extend(vals)

            status = "VALID" if n_valid > 0 else "INVALID"
            run_summary = f"{n_valid}/{len(paths)}" if paths else "0/0"

            def _cols_b(key: str) -> list:
                return [v for v in merged_cols2.get(key, []) if v is not None]

            det_col = "pwave_lb_detection_rate" if is_lb else "pwave_detection_rate"
            lat_col = "pwave_lb_inference_latency_p95" if is_lb else "pwave_inference_latency_p95"

            tp  = calc_stats(_cols_b("dp_throughput_pwave_topic"))
            det = calc_stats(_cols_b(det_col))
            lat = calc_latency_stats(_cols_b(lat_col))
            e2e = calc_latency_stats(_cols_b("e2e_delay_pwave_p95"))
            cpu = calc_stats(_cols_b("pwave_aggregate_cpu_percent"))
            mem = calc_stats(_cols_b("pwave_aggregate_mem_mb"))

            table_data_b.append([
                mode_label, f"{i} Container",
                tp["mean"],
                det["mean"], det["std"],
                lat["p95_of_window_p95"],
                e2e["p95_of_window_p95"],
                cpu["mean"], cpu["std"],
                mem["mean"], mem["std"],
                run_summary, status,
            ])

    save_and_print_table(
        "ANALISIS SKENARIO 4B (Skalabilitas P-Wave Detector / CPU Bound)",
        headers_b, table_data_b, f"summary_s4b_pwave{_run_suffix()}.csv",
    )


def analyze_s5() -> None:
    headers = [
        "WebSocket Server", "Klien Aktif",
        "Broadcast P95 (ms)", "Broadcast Std (ms)",
        "CPU Mean (%)", "CPU Std (%)",
        "RAM Mean (MB)", "RAM Std (MB)",
        "Run Valid", "Status",
    ]
    table_data = []

    for mode_label, prefix in [("FastAPI", "s5_websocket_fastapi"), ("Express.js", "s5_websocket_express")]:
        for c in [1, 5]:
            paths = _read_runs(f"{prefix}_{c}c", run=CURRENT_RUN)
            merged_cols: dict[str, list] = defaultdict(list)
            n_valid = 0
            for p in paths:
                r = read_csv(p, interval_sec=_actual_interval(p))
                run_name = os.path.basename(p)
                if r is not None:
                    cpu_vals = [v for v in r["columns"].get("ws_aggregate_cpu_percent", []) if v is not None]
                    if len(cpu_vals) >= 10:
                        r["valid"] = True
                _warn_invalid(f"{mode_label} {c}c/{run_name}", r)
                if r and r["valid"]:
                    n_valid += 1
                    for col, vals in r["columns"].items():
                        merged_cols[col].extend(vals)

            status = "VALID" if n_valid > 0 else "INVALID"
            run_summary = f"{n_valid}/{len(paths)}" if paths else "0/0"

            def _cols(key: str) -> list:
                return [v for v in merged_cols.get(key, []) if v is not None]

            lat_key = "fastapi_ws_broadcast_latency_p95" if "fastapi" in prefix else "ws_broadcast_latency_p95"
            lat = calc_latency_stats(_cols(lat_key))
            cpu = calc_stats(_cols("ws_aggregate_cpu_percent"))
            mem = calc_stats(_cols("ws_aggregate_mem_mb"))

            table_data.append([
                mode_label, f"{c} Klien",
                lat["p95_of_window_p95"], lat["std"],
                cpu["mean"], cpu["std"],
                mem["mean"], mem["std"],
                run_summary, status,
            ])

    save_and_print_table(
        "ANALISIS SKENARIO 5 (Optimasi Hilir / Diseminasi WebSocket)",
        headers, table_data, f"summary_s5_websocket{_run_suffix()}.csv",
    )


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
        help="Skenario yang dianalisis (default: all)",
    )
    parser.add_argument("--run", type=int, default=None, help="Analisis run tunggal tertentu (mis. --run 1)")
    parser.add_argument("--warmup-sec", type=float, default=WARMUP_SEC, help=f"Detik warmup (default {WARMUP_SEC}s)")
    parser.add_argument("--window-sec", type=float, default=WINDOW_SEC, help=f"Lebar jendela stabil (default {WINDOW_SEC}s)")
    parser.add_argument("--results-dir", type=str, default=RESULTS_DIR, help="Direktori folder results")
    args = parser.parse_args()

    WARMUP_SEC = args.warmup_sec
    WINDOW_SEC = args.window_sec
    CURRENT_RUN = args.run
    RESULTS_DIR = args.results_dir

    if CURRENT_RUN is not None:
        print(f"[Mode: Run {CURRENT_RUN} saja — output diberi suffix _run{CURRENT_RUN}]")
    else:
        print("[Mode: Gabungkan semua run yang valid]")

    if args.scenario in ("1", "s1"):
        analyze_s1()
    elif args.scenario in ("2", "s2"):
        analyze_s2()
    elif args.scenario in ("3", "s3"):
        analyze_s3()
    elif args.scenario in ("4", "s4_archiver"):
        analyze_s4a()
    elif args.scenario in ("s4_pwave",):
        analyze_s4b()
    elif args.scenario in ("5", "s5"):
        analyze_s5()
    elif args.scenario in ("all", "final"):
        analyze_all()