"""
multi_process_thread.py — Mode multiprocess+thread Data Provider.

Membagi station_configs ke num_processes proses, lalu setiap proses membagi
konfigurasinya ke 2 thread secara merata.
Jika num_stations adalah kelipatan num_processes (mis. 5984 untuk 32 proses),
setiap proses mendapat jumlah kanal yang identik tanpa sisa.
"""

from SeedlinkClient import run_client
from utils.util import get_station_configs
import multiprocessing
import threading
from time import sleep


def process_worker(server: str, configs: list, process_id: int) -> None:
    """Jalankan beberapa thread SeedLink dalam satu proses."""
    num_threads = 2
    if len(configs) < num_threads:
        num_threads = len(configs)

    if num_threads == 0:
        return

    chunk_size = len(configs) // num_threads
    threads = []

    for i in range(num_threads):
        start_idx = i * chunk_size
        # Proses terakhir mengambil sisa (0 bila habis dibagi)
        end_idx = (i + 1) * chunk_size if i < num_threads - 1 else len(configs)
        chunk = configs[start_idx:end_idx]

        if chunk:
            t = threading.Thread(
                target=run_client, args=(server, chunk, f"{process_id}-{i}")
            )
            t.daemon = False
            threads.append(t)

    for t in threads:
        t.start()
        sleep(0.2)

    for t in threads:
        t.join()


def main(
    server: str = 'geofon.gfz-potsdam.de:18000',
    station_path: str = 'data_provider/data/stations.json',
    num_processes: int = 32,
    num_station_configs: int = 5984,
) -> None:
    station_configs = get_station_configs(station_path, num_station_configs)
    n_configs = len(station_configs)
    n_procs = num_processes

    print(f'Jumlah konfigurasi stasiun: {n_configs}')
    print(f'Jumlah proses: {n_procs}')

    chunk_size = n_configs // n_procs
    if chunk_size == 0:
        chunk_size = 1
        n_procs = n_configs
        print(
            f'[PERINGATAN] Lebih banyak proses ({num_processes}) dari konfigurasi '
            f'({n_configs}). Kurangi ke {n_procs} proses.'
        )

    processes = []
    for i in range(n_procs):
        start_idx = i * chunk_size
        # Proses terakhir mengambil sisa (0 bila habis dibagi)
        end_idx = (i + 1) * chunk_size if i < n_procs - 1 else n_configs
        chunk = station_configs[start_idx:end_idx]

        if chunk:
            p = multiprocessing.Process(
                target=process_worker, args=(server, chunk, i)
            )
            processes.append(p)

    for p in processes:
        p.start()
        sleep(0.2)

    print('Semua proses dimulai')

    for p in processes:
        p.join()