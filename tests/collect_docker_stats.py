import docker
import time
import csv
import argparse
import os

def get_docker_stats_api(client):
    total_cpu = 0.0
    total_mem_mb = 0.0

    try:
        # Mengambil daftar container yang sedang hidup
        containers = client.containers.list()
        for container in containers:
            # Hanya filter container p_wave_detector (sesuai filter Prometheus)
            if "p_wave_detector" in container.name:
                # Ambil snapshot stats langsung dari API Docker Daemon (stream=False agar tidak blocking)
                stats = container.stats(stream=False)
                
                # Kalkulasi Memori (MB)
                mem_usage = stats['memory_stats'].get('usage', 0)
                mem_mb = mem_usage / (1024 * 1024)
                total_mem_mb += mem_mb

                # Kalkulasi CPU Persentase (Mirip formula internal docker stats CLI)
                cpu_stats = stats.get('cpu_stats', {})
                precpu_stats = stats.get('precpu_stats', {})
                
                cpu_usage = cpu_stats.get('cpu_usage', {}).get('total_usage', 0)
                precpu_usage = precpu_stats.get('cpu_usage', {}).get('total_usage', 0)
                system_cpu_usage = cpu_stats.get('system_cpu_usage', 0)
                system_precpu_usage = precpu_stats.get('system_cpu_usage', 0)
                online_cpus = cpu_stats.get('online_cpus', 1)

                cpu_delta = cpu_usage - precpu_usage
                system_delta = system_cpu_usage - system_precpu_usage

                if system_delta > 0.0 and cpu_delta > 0.0:
                    cpu_percent = (cpu_delta / system_delta) * online_cpus * 100.0
                    total_cpu += cpu_percent

    except Exception as e:
        print(f"Error communicating with Docker API: {e}")

    return total_cpu, total_mem_mb

def main():
    parser = argparse.ArgumentParser(description="Collect Docker Stats Lightly via SDK")
    parser.add_argument("--duration", type=int, default=60, help="Duration to collect in seconds")
    parser.add_argument("--output", type=str, required=True, help="Output CSV path")
    args = parser.parse_args()

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    headers = ["timestamp", "pwave_aggregate_cpu_percent", "pwave_aggregate_mem_mb"]
    
    # Inisialisasi koneksi langsung ke Docker Daemon (Socket)
    try:
        client = docker.from_env()
    except Exception as e:
        print(f"Gagal terhubung ke Docker Daemon. Pastikan Docker Desktop menyala. Error: {e}")
        return

    start_time = time.time()
    
    try:
        with open(args.output, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            
            while time.time() - start_time < args.duration:
                ts = time.strftime("%Y-%m-%d %H:%M:%S")
                
                # Mengambil data langsung tanpa membuka subprocess CLI baru
                cpu, mem = get_docker_stats_api(client)
                
                row = [ts, round(cpu, 4), round(mem, 4)]
                writer.writerow(row)
                f.flush()
                print(f"Collected at {ts}: {row}")
                
                time.sleep(5)
                
    except PermissionError:
        print(f"Permission denied writing to {args.output}")

if __name__ == "__main__":
    main()
