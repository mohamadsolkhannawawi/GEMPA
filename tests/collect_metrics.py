import requests
import csv
import time
import argparse
import os
import math
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Define all PromQL queries
ALL_QUERIES = {
    "pwave_inference_latency_p95": 'histogram_quantile(0.95, rate(pwave_inference_latency_seconds_bucket[1m]))',
    "pwave_lb_inference_latency_p95": 'histogram_quantile(0.95, rate(pwave_lb_inference_latency_seconds_bucket[1m]))',
    "lb_forward_latency_p95": 'histogram_quantile(0.95, rate(lb_forward_latency_seconds_bucket[1m]))',
    "locmag_inference_latency_p95": 'histogram_quantile(0.95, rate(locmag_inference_latency_seconds_bucket[1m]))',
    "e2e_delay_pwave_p95": 'histogram_quantile(0.95, rate(pwave_end_to_end_latency_seconds_bucket[1m]))',
    "e2e_delay_locmag_p95": 'histogram_quantile(0.95, rate(locmag_end_to_end_latency_seconds_bucket[1m]))',
    "ws_broadcast_latency_p95": 'histogram_quantile(0.95, rate(ws_broadcast_latency_seconds_bucket[1m]))',
    "fastapi_ws_broadcast_latency_p95": 'histogram_quantile(0.95, rate(fastapi_ws_broadcast_latency_seconds_bucket[1m]))',
    "active_ws_clients_express": 'ws_active_clients',
    "active_ws_clients_fastapi": 'fastapi_ws_active_clients',
    "dp_throughput_traces_per_sec": 'sum(rate(data_provider_traces_sent_total[1m]))',
    "pwave_aggregate_cpu_percent": 'sum(docker_container_cpu_usage_percent{container_name=~".*p_wave_detector.*"})',
    "pwave_aggregate_mem_mb": 'sum(docker_container_mem_usage{container_name=~".*p_wave_detector.*"}) / 1048576'
}

SCENARIO_MAPPING = {
    "s1": ["dp_throughput_traces_per_sec", "pwave_aggregate_cpu_percent", "pwave_aggregate_mem_mb"],
    "s2": ["dp_throughput_traces_per_sec", "pwave_inference_latency_p95", "locmag_inference_latency_p95", "e2e_delay_pwave_p95", "e2e_delay_locmag_p95", "pwave_aggregate_cpu_percent", "pwave_aggregate_mem_mb"],
    "s3a": ["dp_throughput_traces_per_sec", "pwave_aggregate_cpu_percent", "pwave_aggregate_mem_mb"],
    "s3b": ["dp_throughput_traces_per_sec", "pwave_inference_latency_p95", "pwave_lb_inference_latency_p95", "pwave_aggregate_cpu_percent", "pwave_aggregate_mem_mb"],
    "s4": ["dp_throughput_traces_per_sec", "ws_broadcast_latency_p95", "fastapi_ws_broadcast_latency_p95", "active_ws_clients_express", "active_ws_clients_fastapi", "pwave_aggregate_cpu_percent", "pwave_aggregate_mem_mb"],
    "s5": ["dp_throughput_traces_per_sec", "pwave_inference_latency_p95", "pwave_lb_inference_latency_p95", "lb_forward_latency_p95", "e2e_delay_pwave_p95", "pwave_aggregate_cpu_percent", "pwave_aggregate_mem_mb"],
    "all": list(ALL_QUERIES.keys())
}

def create_session():
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"]
    )
    session = requests.Session()
    session.mount("http://", HTTPAdapter(max_retries=retry))
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session
  

def wait_for_prometheus(session, prometheus_url, timeout_sec=60):
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
    raise RuntimeError(f"Prometheus is not ready at {ready_url}")


def fetch_metric(session, prometheus_url, query):
    response = session.get(
        prometheus_url,
        params={'query': query},
        timeout=30
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get('status') != 'success':
        raise RuntimeError(payload.get('error', 'Prometheus query failed'))
    results = payload['data']['result']
    if results:
        value = float(results[0]['value'][1])
        return round(value, 4) if math.isfinite(value) else ''
    else:
        # Pemicu warning jika Prometheus tidak punya data (misal container mati/OOM)
        raise RuntimeError("No data returned by Prometheus (Container might be dead or unresponsive)")
    return ''

def collect_metrics(duration_sec, interval_sec, output_file, prometheus_url, scenario="all"):
    print(f"Starting metrics collection for {duration_sec} seconds (interval: {interval_sec}s).")
    print(f"Scenario: {scenario}, Output: {output_file}")
    
    output_dir = os.path.dirname(output_file)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    
    scenario_keys = SCENARIO_MAPPING.get(scenario, SCENARIO_MAPPING["all"])
    queries_to_run = {k: ALL_QUERIES[k] for k in scenario_keys if k in ALL_QUERIES}
    
    headers = ["timestamp"] + list(queries_to_run.keys())
    
    session = create_session()
    wait_for_prometheus(session, prometheus_url)

    try:
        output_file_handle = open(output_file, mode='w', newline='')
    except PermissionError as error:
        raise PermissionError(
            f"Cannot write '{output_file}'. Close Excel or another program using the file, then retry."
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
                    try:
                        val = fetch_metric(session, prometheus_url, query)
                    except requests.RequestException as error:
                        print(f"[WARNING] Prometheus Timeout (Possible CPU Starvation) while querying {name}: {error}")
                        val = ''
                    except (KeyError, TypeError, ValueError, RuntimeError) as error:
                        print(f"Metric unavailable for '{name}': {error}")
                        val = ''
                    row.append(val)
                    
                writer.writerow(row)
                file.flush() # Force write to disk immediately to prevent data loss if OOM killed
                print(f"Collected at {current_time}: {row}")
                time.sleep(interval_sec)
                
        except MemoryError:
            print("\n[CRITICAL WARNING] Out of Memory (OOM) error detected! System RAM is exhausted. Metrics collection aborted.")
        except Exception as e:
            print(f"\n[CRITICAL WARNING] Metrics collection crashed unexpectedly (Possible CPU/RAM exhaustion): {e}")
            
    print(f"Metrics collection completed. Data saved to {output_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Collect Prometheus metrics to CSV")
    parser.add_argument("--duration", type=int, default=60, help="Duration to collect metrics in seconds")
    parser.add_argument("--interval", type=int, default=5, help="Interval between scrapes in seconds")
    parser.add_argument("--output", type=str, default="results/metrics_output.csv", help="Output CSV file path")
    parser.add_argument("--prometheus-url", default="http://localhost:9090/api/v1/query", help="Prometheus query API URL")
    parser.add_argument("--scenario", type=str, default="all", choices=list(SCENARIO_MAPPING.keys()), help="Which scenario metrics to collect")
    args = parser.parse_args()

    collect_metrics(args.duration, args.interval, args.output, args.prometheus_url, args.scenario)
