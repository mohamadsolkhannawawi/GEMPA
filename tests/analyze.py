import argparse
import csv
import math
import os
import statistics
from collections import defaultdict

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")

def parse_value(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None

def read_csv(path):
    if not os.path.exists(path):
        return None
    with open(path, newline="", encoding="utf-8-sig") as file:
        rows = list(csv.DictReader(file))
        
    # FAIRNESS FIX: Buang 10 baris pertama (warmup 50s) dan batasi hingga maksimal baris ke-40 (200s).
    if len(rows) > 10:
        rows = rows[10:40]
        
        # Simpan data clean ke CSV baru
        dir_name = os.path.dirname(path)
        base_name = os.path.basename(path)
        clean_path = os.path.join(dir_name, f"clean_{base_name}")
        with open(clean_path, mode="w", newline="", encoding="utf-8") as f_clean:
            if rows:
                fieldnames = list(rows[0].keys())
                writer = csv.DictWriter(f_clean, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
        
    columns = defaultdict(list)
    for row in rows:
        for name, value in row.items():
            if name == "timestamp":
                continue
            columns[name].append(parse_value(value))
    return columns

def calc_stats(values):
    if not values:
        return {'mean': 'N/A', 'p95': 'N/A', 'max': 'N/A'}
    valid_values = [v for v in values if v is not None]
    if not valid_values:
        return {'mean': 'N/A', 'p95': 'N/A', 'max': 'N/A'}
    
    mean_val = statistics.mean(valid_values)
    max_val = max(valid_values)
    
    ordered = sorted(valid_values)
    idx = int(0.95 * len(ordered))
    p95_val = ordered[idx] if idx < len(ordered) else ordered[-1]
    
    return {
        'mean': round(mean_val, 2),
        'p95': round(p95_val, 2),
        'max': round(max_val, 2)
    }

def calc_latency_stats(values):
    """
    Sama dengan calc_stats, namun mengkonversi detik menjadi milidetik (ms)
    serta membulatkan ke 2 angka di belakang koma untuk presisi latensi.
    """
    if not values:
        return {'mean': 'N/A', 'p95': 'N/A', 'max': 'N/A'}
    valid_values = [v for v in values if v is not None]
    if not valid_values:
        return {'mean': 'N/A', 'p95': 'N/A', 'max': 'N/A'}
    
    # Konversi seconds ke milliseconds
    valid_values = [v * 1000 for v in valid_values]
    
    mean_val = statistics.mean(valid_values)
    max_val = max(valid_values)
    
    ordered = sorted(valid_values)
    idx = int(0.95 * len(ordered))
    p95_val = ordered[idx] if idx < len(ordered) else ordered[-1]
    
    return {
        'mean': round(mean_val, 2),
        'p95': round(p95_val, 2),
        'max': round(max_val, 2)
    }

def save_and_print_table(title, headers, data, filename):
    print(f"\n=== {title} ===")
    
    # Mencegah crash jika data kosong
    if not data:
        print("Tidak ada data untuk ditampilkan.")
        return

    col_widths = [max(len(str(item)) for item in col) for col in zip(*([headers] + data))]
    header_format = " | ".join(f"{{:<{w}}}" for w in col_widths)
    
    print(header_format.format(*headers))
    print("-" * (sum(col_widths) + 3 * (len(headers) - 1)))
    
    for row in data:
        print(header_format.format(*[str(item) for item in row]))
        
    out_path = os.path.join(RESULTS_DIR, filename)
    try:
        with open(out_path, mode='w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerows(data)
        print(f"(Disimpan ke {filename})")
    except PermissionError:
        print(f"(GAGAL: File {filename} sedang terbuka di program lain. Harap tutup program tersebut.)")

def analyze_s1():
    scenarios = ["s1_sequential", "s1_multithread", "s1_multiprocess", "s1_mp_mt"]
    headers = ["Arsitektur", "Throughput (Trace/s)", "CPU Mean (%)", "CPU Max (%)", "RAM Mean (MB)"]
    table_data = []
    
    for prefix in scenarios:
        metrics = read_csv(os.path.join(RESULTS_DIR, f"{prefix}_metrics.csv"))
        mode_name = prefix.replace("s1_", "").upper()
        
        if not metrics:
            table_data.append([mode_name, "N/A", "N/A", "N/A", "N/A"])
            continue
            
        cpu = calc_stats(metrics.get("pwave_aggregate_cpu_percent", []))
        mem = calc_stats(metrics.get("pwave_aggregate_mem_mb", []))
        tp = calc_stats(metrics.get("dp_throughput_traces_per_sec", []))
        
        table_data.append([mode_name, tp['mean'], cpu['mean'], cpu['max'], mem['mean']])
    
    save_and_print_table("ANALISIS SKENARIO 1 (Optimasi Hulu / Ingestion)", headers, table_data, "summary_s1_concurrency.csv")

def analyze_s2():
    scenarios = [
        ("Tanpa Metrics (CLI)", "s2_overhead_no_metrics_cli"),
        ("Tanpa Metrics (API)", "s2_overhead_no_metrics_api"),
        ("Dengan Metrics (Prometheus)", "s2_overhead_with_metrics")
    ]
    headers = ["Kondisi", "CPU Mean (%)", "CPU P95 (%)", "RAM Mean (MB)", "RAM Max (MB)"]
    table_data = []
    
    for label, prefix in scenarios:
        metrics = read_csv(os.path.join(RESULTS_DIR, f"{prefix}_metrics.csv"))
        if not metrics:
            table_data.append([label, "N/A", "N/A", "N/A", "N/A"])
            continue
        cpu = calc_stats(metrics.get("pwave_aggregate_cpu_percent", []))
        mem = calc_stats(metrics.get("pwave_aggregate_mem_mb", []))
        table_data.append([label, cpu['mean'], cpu['p95'], mem['mean'], mem['max']])
    
    save_and_print_table("ANALISIS SKENARIO 2 (Overhead Instrumentasi & Observer Effect)", headers, table_data, "summary_s2_overhead.csv")

def analyze_s3():
    # Menggunakan metode calc_latency_stats agar hasil dalam milidetik (ms)
    headers = ["Arsitektur Broker", "E2E P-Wave Mean (ms)", "E2E P-Wave P95 (ms)", "CPU Mean (%)", "RAM Mean (MB)"]
    table_data = []
    for mode in [("Kafka Native", "s3_broker_kafka"), ("Kafka + NGINX", "s3_broker_nginx")]:
        metrics = read_csv(os.path.join(RESULTS_DIR, f"{mode[1]}_metrics.csv"))
        if not metrics:
            table_data.append([mode[0], "N/A", "N/A", "N/A", "N/A"])
            continue
            
        lat = calc_latency_stats(metrics.get("e2e_delay_pwave_p95", []))
        cpu = calc_stats(metrics.get("pwave_aggregate_cpu_percent", []))
        mem = calc_stats(metrics.get("pwave_aggregate_mem_mb", []))
        table_data.append([mode[0], lat['mean'], lat['p95'], cpu['mean'], mem['mean']])
    save_and_print_table("ANALISIS SKENARIO 3 (Pemilihan Arsitektur Inti / Load Balancing)", headers, table_data, "summary_s3_broker.csv")

def analyze_s4():
    # Part A: Archiver Scalability
    headers_a = ["Replika Archiver", "CPU Mean (%)", "CPU Max (%)", "RAM Mean (MB)"]
    table_data_a = []
    for i in range(1, 6):
        metrics = read_csv(os.path.join(RESULTS_DIR, f"s4_archiver_{i}_container_metrics.csv"))
        if metrics:
            # PERBAIKAN KUNCI: Menarik metrik CPU/RAM khusus untuk Archiver, bukan P-Wave
            cpu = calc_stats(metrics.get("archiver_aggregate_cpu_percent", []))
            mem = calc_stats(metrics.get("archiver_aggregate_mem_mb", []))
            table_data_a.append([f"{i} Container", cpu['mean'], cpu['max'], mem['mean']])
        else:
            table_data_a.append([f"{i} Container", "N/A", "N/A", "N/A"])
    save_and_print_table("ANALISIS SKENARIO 4A (Skalabilitas Data Archiver / I/O Bound)", headers_a, table_data_a, "summary_s4a_archiver.csv")

    # Part B: P-Wave Detector Scalability
    scenarios_b = [("Native Kafka", "s4_pwave_kafka"), ("Load Balancer", "s4_pwave_kafka_nginx")]
    headers_b = ["Arsitektur", "Replika ML", "Throughput (Trace/s)", "Inference Latency P95 (ms)", "CPU Mean (%)", "RAM Mean (MB)"]
    table_data_b = []
    
    for mode in scenarios_b:
        for i in range(2, 6):
            metrics = read_csv(os.path.join(RESULTS_DIR, f"{mode[1]}_{i}c_metrics.csv"))
            if metrics:
                tp = calc_stats(metrics.get("dp_throughput_traces_per_sec", []))
                
                # Check mana metrik latensi yang aktif (Native vs NGINX) lalu konversi ke ms
                raw_lat = metrics.get("pwave_inference_latency_p95", [])
                lat = calc_latency_stats(raw_lat)
                if lat['p95'] == 'N/A':
                    raw_lat_lb = metrics.get("pwave_lb_inference_latency_p95", [])
                    lat = calc_latency_stats(raw_lat_lb)
                    
                cpu = calc_stats(metrics.get("pwave_aggregate_cpu_percent", []))
                mem = calc_stats(metrics.get("pwave_aggregate_mem_mb", []))
                table_data_b.append([mode[0], f"{i} Container", tp['mean'], lat['p95'], cpu['mean'], mem['mean']])
            else:
                table_data_b.append([mode[0], f"{i} Container", "N/A", "N/A", "N/A", "N/A"])
    save_and_print_table("ANALISIS SKENARIO 4B (Skalabilitas P-Wave Detector / CPU Bound)", headers_b, table_data_b, "summary_s4b_pwave.csv")

def analyze_s5():
    headers = ["WebSocket Server", "Klien Aktif", "Broadcast P95 (ms)", "CPU Mean (%)", "RAM Mean (MB)"]
    table_data = []
    for mode in [("FastAPI", "s5_websocket_fastapi"), ("Express.js", "s5_websocket_express")]:
        for c in [1, 5]:
            metrics = read_csv(os.path.join(RESULTS_DIR, f"{mode[1]}_{c}c_metrics.csv"))
            if not metrics:
                table_data.append([mode[0], f"{c} Klien", "N/A", "N/A", "N/A"])
                continue
            
            # Konversi latensi ke ms
            if "fastapi" in mode[1]:
                lat = calc_latency_stats(metrics.get("fastapi_ws_broadcast_latency_p95", []))
            else:
                lat = calc_latency_stats(metrics.get("ws_broadcast_latency_p95", []))
                
            cpu = calc_stats(metrics.get("pwave_aggregate_cpu_percent", []))
            mem = calc_stats(metrics.get("pwave_aggregate_mem_mb", []))
            
            table_data.append([mode[0], f"{c} Klien", lat['p95'], cpu['mean'], mem['mean']])
    save_and_print_table("ANALISIS SKENARIO 5 (Optimasi Hilir / Diseminasi WebSocket)", headers, table_data, "summary_s5_websocket.csv")

def analyze_all():
    analyze_s1()
    analyze_s2()
    analyze_s3()
    analyze_s4()
    analyze_s5()
    print("\nSemua skenario (S1 - S5) berhasil dianalisis dan disimpan ke format CSV yang siap dimasukkan ke Tabel Bab IV!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="EEWS Test Result Analyzer")
    parser.add_argument('--scenario', choices=['1', '2', '3', '4', '5', 'all'], default='all')
    args = parser.parse_args()
    
    if args.scenario == '1': analyze_s1()
    elif args.scenario == '2': analyze_s2()
    elif args.scenario == '3': analyze_s3()
    elif args.scenario == '4': analyze_s4()
    elif args.scenario == '5': analyze_s5()
    else: analyze_all()
