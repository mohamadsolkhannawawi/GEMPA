"""
multi_thread.py — Mode multithread Data Provider.

Membagi station_configs ke num_processes thread secara merata.
Thread dijalankan sebagai non-daemon dan di-join agar proses utama
tidak keluar sebelum semua thread selesai.
"""

import threading
from time import sleep

from SeedlinkClient import run_client
from utils.util import get_station_configs


def main(
    server: str = 'geofon.gfz-potsdam.de:18000',
    station_path: str = 'data_provider/data/stations.json',
    num_processes: int = 32,
    num_station_configs: int = 5984,
) -> None:
    station_configs = get_station_configs(station_path, num_station_configs)
    n_configs = len(station_configs)
    n_threads = num_processes

    print(f'Jumlah konfigurasi stasiun: {n_configs}')
    print(f'Jumlah thread: {n_threads}')

    chunk_size = n_configs // n_threads
    if chunk_size == 0:
        chunk_size = 1
        n_threads = n_configs
        print(
            f'[PERINGATAN] Lebih banyak thread ({num_processes}) dari konfigurasi '
            f'({n_configs}). Kurangi ke {n_threads} thread.'
        )

    threads = []
    for i in range(n_threads):
        start = i * chunk_size
        end = (i + 1) * chunk_size if i < n_threads - 1 else n_configs
        chunk = station_configs[start:end]
        if not chunk:
            continue
        t = threading.Thread(
            target=run_client, args=(server, chunk, i)
        )
        # Non-daemon agar proses utama tidak keluar sebelum thread selesai
        t.daemon = False
        threads.append(t)

    for t in threads:
        t.start()
        sleep(0.2)

    print('Semua thread dimulai')

    # Blokir sampai semua thread selesai (SeedLink berjalan terus-menerus)
    for t in threads:
        t.join()
