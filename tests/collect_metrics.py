"""
collect_metrics.py — Pengumpul metrik Prometheus ke CSV.

Perbaikan K1: Kueri histogram_quantile menggunakan sum by (le) agar hasilnya
              mencakup seluruh replika, bukan hanya satu replika acak.
Perbaikan K2: Pisahkan throughput per topik, tambahkan laju deteksi, cakupan
              CPU/RAM Data Provider & WebSocket Server, kolom status, opsi
              --dump-buckets.
"""

import requests
import csv
import time
import argparse
import os
import math
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ==============================================================================
# Definisi semua kueri PromQL
# ==============================================================================

# Bucket histogram yang dikumpulkan untuk --dump-buckets
BUCKET_METRICS = [
    'pwave_inference_latency_seconds',
    'pwave_lb_inference_latency_seconds',
    'pwave_end_to_end_latency_seconds',
    'pwave_kafka_delay_seconds',
    'pwave_lb_kafka_delay_seconds',
    'pwave_queue_wait_seconds',
    'pwave_lb_queue_wait_seconds',
    'lb_forward_latency_seconds',
    'archiver_write_latency_seconds',
    'fastapi_ws_broadcast_latency_seconds',
    'ws_broadcast_latency_seconds',
]

ALL_QUERIES = {
    # --- Latensi (sum by (le) agar agregasi seluruh replika) ---
    "pwave_inference_latency_p95": (
        'histogram_quantile(0.95, sum by (le) '
        '(rate(pwave_inference_latency_seconds_bucket[1m])))'
    ),
    "pwave_lb_inference_latency_p95": (
        'histogram_quantile(0.95, sum by (le) '
        '(rate(pwave_lb_inference_latency_seconds_bucket[1m])))'
    ),
    "lb_forward_latency_p95": (
        'histogram_quantile(0.95, sum by (le) '
        '(rate(lb_forward_latency_seconds_bucket[1m])))'
    ),
    "pwave_kafka_delay_p95": (
        'histogram_quantile(0.95, sum by (le) '
        '(rate(pwave_kafka_delay_seconds_bucket[1m])))'
    ),
    "pwave_lb_kafka_delay_p95": (
        'histogram_quantile(0.95, sum by (le) '
        '(rate(pwave_lb_kafka_delay_seconds_bucket[1m])))'
    ),
    "pwave_queue_wait_p95": (
        'histogram_quantile(0.95, sum by (le) '
        '(rate(pwave_queue_wait_seconds_bucket[1m])))'
    ),
    "pwave_lb_queue_wait_p95": (
        'histogram_quantile(0.95, sum by (le) '
        '(rate(pwave_lb_queue_wait_seconds_bucket[1m])))'
    ),
    "locmag_inference_latency_p95": (
        'histogram_quantile(0.95, sum by (le) '
        '(rate(locmag_inference_latency_seconds_bucket[1m])))'
    ),
    "e2e_delay_pwave_p95": (
        'histogram_quantile(0.95, sum by (le) '
        '(rate(pwave_end_to_end_latency_seconds_bucket[1m])))'
    ),
    "e2e_delay_locmag_p95": (
        'histogram_quantile(0.95, sum by (le) '
        '(rate(locmag_end_to_end_latency_seconds_bucket[1m])))'
    ),
    "ws_broadcast_latency_p95": (
        'histogram_quantile(0.95, sum by (le) '
        '(rate(ws_broadcast_latency_seconds_bucket[1m])))'
    ),
    "fastapi_ws_broadcast_latency_p95": (
        'histogram_quantile(0.95, sum by (le) '
        '(rate(fastapi_ws_broadcast_latency_seconds_bucket[1m])))'
    ),
    "archiver_write_latency_influxdb_p95": (
        'histogram_quantile(0.95, sum by (le) '
        '(rate(archiver_write_latency_seconds_bucket{storage="influxdb"}[1m])))'
    ),
    "archiver_write_latency_mongodb_p95": (
        'histogram_quantile(0.95, sum by (le) '
        '(rate(archiver_write_latency_seconds_bucket{storage="mongodb"}[1m])))'
    ),

    # --- WebSocket aktif ---
    "active_ws_clients_express": 'ws_active_clients',
    "active_ws_clients_fastapi": 'fastapi_ws_active_clients',

    # --- Throughput per topik (dipisah sesuai K2) ---
    "dp_throughput_trace_topic": (
        'sum(rate(data_provider_traces_sent_total{topic="trace_topic"}[1m]))'
    ),
    "dp_throughput_pwave_topic": (
        'sum(rate(data_provider_traces_sent_total{topic="p_wave_topic"}[1m]))'
    ),
    # Kolom lama (jumlah dua topik) dipertahankan untuk kompatibilitas mundur
    "dp_throughput_traces_per_sec": (
        'sum(rate(data_provider_traces_sent_total[1m]))'
    ),

    # --- Counter received & dropped SeedLink ---
    "dp_traces_received_per_sec": (
        'sum(rate(data_provider_traces_received_total[1m]))'
    ),
    "dp_traces_dropped_stale_per_sec": (
        'sum(rate(data_provider_traces_dropped_stale_total[1m]))'
    ),

    # --- Laju deteksi P-Wave (lebih valid sebagai C(N) untuk USL) ---
    "pwave_detection_rate": (
        'sum(rate(pwave_inference_latency_seconds_count[1m]))'
    ),
    "pwave_lb_detection_rate": (
        'sum(rate(pwave_lb_inference_latency_seconds_count[1m]))'
    ),
    "pwave_requests_rate": 'sum(rate(pwave_requests_total[1m]))',
    "pwave_lb_requests_rate": 'sum(rate(pwave_lb_requests_total[1m]))',

    # --- CPU/RAM P-Wave Detector ---
    "pwave_aggregate_cpu_percent": (
        'sum(docker_container_cpu_usage_percent'
        '{container_name=~".*p_wave_detector.*"})'
    ),
    "pwave_aggregate_mem_mb": (
        'sum(docker_container_mem_usage'
        '{container_name=~".*p_wave_detector.*"}) / 1048576'
    ),

    # --- CPU/RAM Data Provider (K2: ditambahkan) ---
    "dp_aggregate_cpu_percent": (
        'sum(docker_container_cpu_usage_percent'
        '{container_name=~".*data_provider.*"})'
    ),
    "dp_aggregate_mem_mb": (
        'sum(docker_container_mem_usage'
        '{container_name=~".*data_provider.*"}) / 1048576'
    ),

    # --- CPU/RAM WebSocket Server (K2: FastAPI dan Express) ---
    "ws_aggregate_cpu_percent": (
        'sum(docker_container_cpu_usage_percent'
        '{container_name=~".*(fast_api|api_server).*"})'
    ),
    "ws_aggregate_mem_mb": (
        'sum(docker_container_mem_usage'
        '{container_name=~".*(fast_api|api_server).*"}) / 1048576'
    ),

    # --- CPU/RAM Archiver ---
    "archiver_aggregate_cpu_percent": (
        'sum(docker_container_cpu_usage_percent'
        '{container_name=~".*data_archiver.*"})'
    ),
    "archiver_aggregate_mem_mb": (
        'sum(docker_container_mem_usage'
        '{container_name=~".*data_archiver.*"}) / 1048576'
    ),

    # --- Kapasitas Archiver ---
    "archiver_records_saved_rate": (
        'sum(rate(archiver_records_saved_total[1m]))'
    ),

    # --- Kafka consumer lag (bila kafka-exporter aktif) ---
    "kafka_consumer_lag_total": (
        'sum(kafka_consumergroup_lag)'
    ),

    # --- Inflight ---
    "pwave_inflight": 'sum(pwave_inflight)',
    "pwave_lb_inflight": 'sum(pwave_lb_inflight)',
}

SCENARIO_MAPPING = {
    "s1": [
        "dp_throughput_trace_topic",
        "dp_throughput_pwave_topic",
        "dp_throughput_traces_per_sec",
        "dp_traces_received_per_sec",
        "dp_traces_dropped_stale_per_sec",
        "dp_aggregate_cpu_percent",
        "dp_aggregate_mem_mb",
        "pwave_aggregate_cpu_percent",
        "pwave_aggregate_mem_mb",
    ],
    "s2": [
        "dp_throughput_traces_per_sec",
        "dp_aggregate_cpu_percent",
        "dp_aggregate_mem_mb",
        "pwave_inference_latency_p95",
        "locmag_inference_latency_p95",
        "e2e_delay_pwave_p95",
        "e2e_delay_locmag_p95",
        "pwave_aggregate_cpu_percent",
        "pwave_aggregate_mem_mb",
    ],
    "s3": [
        "dp_throughput_pwave_topic",
        "pwave_inference_latency_p95",
        "pwave_lb_inference_latency_p95",
        "lb_forward_latency_p95",
        "pwave_kafka_delay_p95",
        "pwave_lb_kafka_delay_p95",
        "pwave_queue_wait_p95",
        "pwave_lb_queue_wait_p95",
        "e2e_delay_pwave_p95",
        "pwave_detection_rate",
        "pwave_lb_detection_rate",
        "pwave_inflight",
        "pwave_lb_inflight",
        "pwave_aggregate_cpu_percent",
        "pwave_aggregate_mem_mb",
        "kafka_consumer_lag_total",
    ],
    "s4_archiver": [
        "dp_throughput_trace_topic",
        "archiver_aggregate_cpu_percent",
        "archiver_aggregate_mem_mb",
        "archiver_records_saved_rate",
        "archiver_write_latency_influxdb_p95",
        "archiver_write_latency_mongodb_p95",
    ],
    "s4_pwave": [
        "dp_throughput_pwave_topic",
        "pwave_inference_latency_p95",
        "pwave_lb_inference_latency_p95",
        "e2e_delay_pwave_p95",
        "pwave_detection_rate",
        "pwave_lb_detection_rate",
        "pwave_requests_rate",
        "pwave_lb_requests_rate",
        "pwave_aggregate_cpu_percent",
        "pwave_aggregate_mem_mb",
        "kafka_consumer_lag_total",
    ],
    "s5": [
        "dp_throughput_trace_topic",
        "ws_broadcast_latency_p95",
        "fastapi_ws_broadcast_latency_p95",
        "active_ws_clients_express",
        "active_ws_clients_fastapi",
        "ws_aggregate_cpu_percent",
        "ws_aggregate_mem_mb",
    ],
    "all": list(ALL_QUERIES.keys()),
}


# ==============================================================================
# Sesi HTTP dengan retry
# ==============================================================================

def create_session() -> requests.Session:
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    session = requests.Session()
    session.mount("http://", HTTPAdapter(max_retries=retry))
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def wait_for_prometheus(
    session: requests.Session,
    prometheus_url: str,
    timeout_sec: int = 60,
) -> None:
    ready_url = prometheus_url.rsplit('/api/v1/query', 1)[0] + '/-/ready'
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            response = session.get(ready_url, timeout=10)
            if response.status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(2)
    raise RuntimeError(f"Prometheus tidak siap di {ready_url}")


# ==============================================================================
# Fungsi pengambilan metrik tunggal
# ==============================================================================

def fetch_metric(
    session: requests.Session,
    prometheus_url: str,
    query: str,
) -> tuple[float | None, str]:
    """
    Ambil nilai skalar dari PromQL.

    Kembalian
    ---------
    (value, status)
        value  — float atau None bila tidak ada data
        status — "ok" | "no_data" | "timeout" | "error"
    """
    try:
        response = session.get(
            prometheus_url,
            params={'query': query},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()

        if payload.get('status') != 'success':
            return None, "error"

        results = payload['data']['result']
        if not results:
            return None, "no_data"

        if len(results) != 1:
            print(
                f"[PERINGATAN] Kueri mengembalikan {len(results)} deret, "
                f"diharapkan 1. Periksa apakah kueri mengandung sum by (le) "
                f"yang benar.\nKueri: {query}"
            )

        raw = float(results[0]['value'][1])
        if not math.isfinite(raw):
            return None, "no_data"

        # Simpan 6 desimal agar latensi sub-milidetik tidak terpotong
        return round(raw, 6), "ok"

    except requests.Timeout:
        return None, "timeout"
    except requests.RequestException as e:
        print(f"[PERINGATAN] Kesalahan jaringan saat kueri: {e}")
        return None, "error"
    except Exception as e:
        print(f"[PERINGATAN] Kesalahan tak terduga saat kueri: {e}")
        return None, "error"


# ==============================================================================
# Dump bucket (opsional, untuk --dump-buckets)
# ==============================================================================

def fetch_bucket_snapshot(
    session: requests.Session,
    prometheus_url: str,
    metric_name: str,
) -> list[dict]:
    """
    Ambil semua nilai bucket kumulatif dari histogram (dijumlahkan antar replika).

    Kembalian: daftar dict {"le": str, "value": float}
    """
    query = f'sum by (le) ({metric_name}_bucket)'
    try:
        response = session.get(
            prometheus_url,
            params={'query': query},
            timeout=30,
        )
        response.raise_for_status()
        results = response.json().get('data', {}).get('result', [])
        buckets = []
        for r in results:
            le = r.get('metric', {}).get('le', '?')
            val = float(r['value'][1]) if math.isfinite(float(r['value'][1])) else 0.0
            buckets.append({'le': le, 'value': val})
        return buckets
    except Exception:
        return []


def dump_buckets(
    session: requests.Session,
    prometheus_url: str,
    output_file: str,
    timestamp: str,
) -> None:
    """
    Simpan snapshot semua bucket histogram ke CSV panjang.
    Format: timestamp, metric, le, value
    """
    rows = []
    for metric in BUCKET_METRICS:
        buckets = fetch_bucket_snapshot(session, prometheus_url, metric)
        for b in buckets:
            rows.append({
                'timestamp': timestamp,
                'metric': metric,
                'le': b['le'],
                'value': b['value'],
            })

    if not rows:
        return

    file_exists = os.path.isfile(output_file)
    with open(output_file, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(
            f, fieldnames=['timestamp', 'metric', 'le', 'value']
        )
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)


# ==============================================================================
# Loop utama pengumpulan metrik
# ==============================================================================

def collect_metrics(
    duration_sec: int,
    interval_sec: int,
    output_file: str,
    prometheus_url: str,
    scenario: str = "all",
    enable_dump_buckets: bool = False,
) -> None:
    print(
        f"Mulai pengumpulan metrik selama {duration_sec} detik "
        f"(interval: {interval_sec}s).\n"
        f"Skenario: {scenario} | Output: {output_file}"
    )

    output_dir = os.path.dirname(output_file)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    bucket_file = output_file.replace('.csv', '_buckets.csv') if enable_dump_buckets else None

    scenario_keys = SCENARIO_MAPPING.get(scenario, SCENARIO_MAPPING["all"])
    queries_to_run = {k: ALL_QUERIES[k] for k in scenario_keys if k in ALL_QUERIES}

    # Kolom: timestamp + satu kolom nilai + satu kolom status per metrik
    value_cols = list(queries_to_run.keys())
    status_cols = [f"{k}_status" for k in value_cols]
    headers = ["timestamp"] + [
        col for pair in zip(value_cols, status_cols) for col in pair
    ]

    session = create_session()
    wait_for_prometheus(session, prometheus_url)

    try:
        output_file_handle = open(output_file, mode='w', newline='', encoding='utf-8')
    except PermissionError as error:
        raise PermissionError(
            f"Tidak dapat menulis '{output_file}'. Tutup program lain yang "
            f"membuka berkas ini, lalu coba lagi."
        ) from error

    with output_file_handle as file:
        writer = csv.writer(file)
        writer.writerow(headers)

        start_time = time.time()
        try:
            while time.time() - start_time < duration_sec:
                current_time = time.strftime("%Y-%m-%d %H:%M:%S")
                row = [current_time]

                for name, query in queries_to_run.items():
                    value, status = fetch_metric(session, prometheus_url, query)
                    row.append(value if value is not None else '')
                    row.append(status)

                writer.writerow(row)
                file.flush()

                if enable_dump_buckets and bucket_file:
                    dump_buckets(session, prometheus_url, bucket_file, current_time)

                print(f"Dikumpulkan pada {current_time}: {row}")
                time.sleep(interval_sec)

        except MemoryError:
            print(
                "\n[KRITIS] Kesalahan Out-of-Memory (OOM)! "
                "RAM sistem habis. Pengumpulan metrik dibatalkan."
            )
        except Exception as e:
            print(
                f"\n[KRITIS] Pengumpulan metrik berhenti tak terduga "
                f"(kemungkinan kekurangan CPU/RAM): {e}"
            )

    print(f"Pengumpulan metrik selesai. Data disimpan ke {output_file}")
    if bucket_file and os.path.isfile(bucket_file):
        print(f"Data bucket disimpan ke {bucket_file}")


# ==============================================================================
# CLI entry point
# ==============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Kumpulkan metrik Prometheus ke CSV"
    )
    parser.add_argument(
        "--duration", type=int, default=60,
        help="Durasi pengumpulan dalam detik"
    )
    parser.add_argument(
        "--interval", type=int, default=5,
        help="Interval antar scrape dalam detik"
    )
    parser.add_argument(
        "--output", type=str, default="results/metrics_output.csv",
        help="Jalur berkas CSV keluaran"
    )
    parser.add_argument(
        "--prometheus-url",
        default="http://localhost:9090/api/v1/query",
        help="URL API kueri Prometheus"
    )
    parser.add_argument(
        "--scenario", type=str, default="all",
        choices=list(SCENARIO_MAPPING.keys()),
        help="Metrik skenario yang dikumpulkan"
    )
    parser.add_argument(
        "--dump-buckets", action="store_true",
        help=(
            "Simpan nilai bucket histogram kumulatif ke CSV terpisah. "
            "Penting: jalankan sebelum `docker-compose down -v` agar data "
            "tidak hilang."
        ),
    )
    args = parser.parse_args()

    collect_metrics(
        args.duration,
        args.interval,
        args.output,
        args.prometheus_url,
        args.scenario,
        args.dump_buckets,
    )
