import subprocess
import time
import csv
import argparse
import os

def get_docker_stats():
    # Calling the docker stats command directly via subprocess
    try:
        # --no-stream so it exits after one run, --format for easier parsing
        cmd = ['docker', 'stats', '--no-stream', '--format', '{{.Name}},{{.CPUPerc}},{{.MemUsage}}']
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        
        total_cpu = 0.0
        total_mem_mb = 0.0
        
        for line in result.stdout.strip().split('\n'):
            if not line:
                continue
            name, cpu_str, mem_str = line.split(',')
            
            # Filter for p_wave_detector containers
            if "p_wave_detector" in name:
                # cpu_str is like '0.15%'
                cpu = float(cpu_str.replace('%', ''))
                
                # mem_str is like '150MiB / 2GiB' or '150MB / 2GB'
                mem_usage = mem_str.split('/')[0].strip()
                if 'GiB' in mem_usage:
                    mem = float(mem_usage.replace('GiB', '')) * 1024
                elif 'MiB' in mem_usage:
                    mem = float(mem_usage.replace('MiB', ''))
                elif 'KiB' in mem_usage:
                    mem = float(mem_usage.replace('KiB', '')) / 1024
                elif 'GB' in mem_usage:
                    mem = float(mem_usage.replace('GB', '')) * 1024
                elif 'MB' in mem_usage:
                    mem = float(mem_usage.replace('MB', ''))
                elif 'kB' in mem_usage:
                    mem = float(mem_usage.replace('kB', '')) / 1024
                elif 'B' in mem_usage:
                    mem = float(mem_usage.replace('B', '')) / (1024 * 1024)
                else:
                    mem = 0.0
                
                total_cpu += cpu
                total_mem_mb += mem

        return total_cpu, total_mem_mb
        
    except Exception as e:
        print(f"Error executing docker stats: {e}")
        return 0.0, 0.0

def main():
    parser = argparse.ArgumentParser(description="Collect Docker Stats via CLI subprocess")
    parser.add_argument("--duration", type=int, default=60, help="Duration to collect in seconds")
    parser.add_argument("--output", type=str, required=True, help="Output CSV path")
    args = parser.parse_args()

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    headers = ["timestamp", "pwave_aggregate_cpu_percent", "pwave_aggregate_mem_mb"]
    
    start_time = time.time()
    
    try:
        with open(args.output, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            
            while time.time() - start_time < args.duration:
                ts = time.strftime("%Y-%m-%d %H:%M:%S")
                
                # Mengambil data menggunakan subprocess CLI
                cpu, mem = get_docker_stats()
                
                row = [ts, round(cpu, 4), round(mem, 4)]
                writer.writerow(row)
                f.flush()
                print(f"Collected at {ts}: {row}")
                
                time.sleep(5)
                
    except PermissionError:
        print(f"Permission denied writing to {args.output}")

if __name__ == "__main__":
    main()
