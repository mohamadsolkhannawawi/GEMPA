"""
multi_process.py — Mode multiprocessing Data Provider.

Membagi station_configs ke num_processes proses secara merata.
Jika num_stations adalah kelipatan num_processes (mis. 5984 untuk 32 proses),
setiap proses mendapat jumlah kanal yang identik tanpa sisa.
"""

import multiprocessing
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
    n_procs = num_processes

    print(f'Jumlah konfigurasi stasiun: {n_configs}')
    print(f'Jumlah proses: {n_procs}')

    # Hitung ukuran chunk; bila ada sisa, peringatkan (tidak terjadi bila
    # DATA_PROVIDER_NUM_STATIONS adalah kelipatan DATA_PROVIDER_NUM_PROCESSES).
    chunk_size = n_configs // n_procs
    if chunk_size == 0:
        # Lebih banyak proses dari konfigurasi — kurangi proses
        chunk_size = 1
        n_procs = n_configs
        print(
            f'[PERINGATAN] Lebih banyak proses ({num_processes}) dari konfigurasi '
            f'({n_configs}). Kurangi ke {n_procs} proses.'
        )

    processes = []
    for i in range(n_procs):
        start = i * chunk_size
        # Proses terakhir mengambil sisa (0 bila habis dibagi)
        end = (i + 1) * chunk_size if i < n_procs - 1 else n_configs
        chunk = station_configs[start:end]
        if not chunk:
            continue
        p = multiprocessing.Process(
            target=run_client, args=(server, chunk, i)
        )
        processes.append(p)

    for p in processes:
        p.start()
        sleep(0.2)

    print('Semua proses dimulai')

    for p in processes:
        p.join()
