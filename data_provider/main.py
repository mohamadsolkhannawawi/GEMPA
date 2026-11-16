"""
main.py — Entry point Data Provider.

Inisialisasi Prometheus multiprocess, buat topik Kafka, lalu dispatch ke mode
yang dipilih lewat DATA_PROVIDER_MODE.
"""

import sys
import os
import shutil
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from config.settings import (
    ENABLE_METRICS,
    METRICS_PORT_DATA_PROVIDER,
    KAFKA_BROKERS,
    KAFKA_BROKERS_PWAVE,
    KAFKA_TOPIC_TRACE,
    KAFKA_TOPIC_PWAVE,
    SEEDLINK_SERVER,
    STALE_SECONDS,
)
from utils.kafka_helper import check_kafka_connection, topic_exists
from utils.logger import get_logger

logger = get_logger("DataProvider")

# ==============================================================================
# Prometheus Multiprocess Setup
# ==============================================================================
# Bersihkan dan siapkan direktori multiprocess agar proses anak dapat menulis
# metrik ke berkas bersama yang diagregasi oleh server HTTP induk.
MULTIPROC_DIR = os.environ.get("PROMETHEUS_MULTIPROC_DIR", "/tmp/prometheus_multiproc")

if ENABLE_METRICS:
    if os.path.isdir(MULTIPROC_DIR):
        shutil.rmtree(MULTIPROC_DIR)
    os.makedirs(MULTIPROC_DIR, exist_ok=True)

    from prometheus_client import (
        Counter, Gauge,
        CollectorRegistry, multiprocess, generate_latest, CONTENT_TYPE_LATEST
    )
    from http.server import HTTPServer, BaseHTTPRequestHandler

    # Metrik dibagikan ke semua proses anak via PROMETHEUS_MULTIPROC_DIR.
    TRACES_SENT = Counter(
        'data_provider_traces_sent',
        'Total rekaman yang dikirim ke Kafka',
        ['topic']
    )
    TRACES_RECEIVED = Counter(
        'data_provider_traces_received',
        'Total rekaman yang diterima dari SeedLink (sebelum filter basi)',
        ['type'],
    )
    TRACES_DROPPED_STALE = Counter(
        'data_provider_traces_dropped_stale',
        'Total rekaman yang dibuang karena dianggap basi',
    )
    PUBLISH_ERRORS = Counter(
        'data_provider_publish_errors',
        'Total kesalahan publikasi ke Kafka'
    )
    ACTIVE_STREAMS = Gauge(
        'data_provider_active_streams',
        'Jumlah stream SeedLink yang sedang aktif',
        multiprocess_mode='livesum'
    )

    class MetricsHandler(BaseHTTPRequestHandler):
        """HTTP handler yang mengagregasi metrik dari semua proses anak."""

        def do_GET(self):
            registry = CollectorRegistry()
            multiprocess.MultiProcessCollector(registry)
            output = generate_latest(registry)
            self.send_response(200)
            self.send_header('Content-Type', CONTENT_TYPE_LATEST)
            self.end_headers()
            self.wfile.write(output)

        def log_message(self, format, *args):
            pass  # Tekan log akses bawaan

else:
    TRACES_SENT = None
    TRACES_RECEIVED = None
    TRACES_DROPPED_STALE = None
    PUBLISH_ERRORS = None
    ACTIVE_STREAMS = None


if __name__ == '__main__':
    logger.info("Memulai Data Provider...")

    # --- Server metrik Prometheus (multiprocess aggregation) ---
    if ENABLE_METRICS:
        try:
            import threading
            server = HTTPServer(('0.0.0.0', METRICS_PORT_DATA_PROVIDER), MetricsHandler)
            metrics_thread = threading.Thread(target=server.serve_forever, daemon=True)
            metrics_thread.start()
            logger.info(
                f"Server metrik Prometheus (multiprocess) dimulai di port "
                f"{METRICS_PORT_DATA_PROVIDER}"
            )
        except Exception as e:
            logger.error(f"Gagal memulai server metrik: {e}")

    # --- Topik Kafka dibuat secara deterministik oleh kafka-init (A9) ---
    # Tidak ada pemanggilan create_topic_if_not_exists di sini.
    # Tunggu topik tersedia sebelum memulai streaming.
    logger.info("Menunggu topik Kafka tersedia dari kafka-init...")
    for topic in [KAFKA_TOPIC_TRACE, KAFKA_TOPIC_PWAVE]:
        while True:
            if check_kafka_connection(KAFKA_BROKERS) and topic_exists(topic, KAFKA_BROKERS):
                logger.info(f"Topik '{topic}' tersedia.")
                break
            logger.debug(f"Menunggu topik '{topic}'...")
            time.sleep(3)

    # --- Baca parameter dari env ---
    raw_num_proc = os.getenv("DATA_PROVIDER_NUM_PROCESSES")
    if raw_num_proc is not None:
        num_processes = int(raw_num_proc)
        logger.info(f"DATA_PROVIDER_NUM_PROCESSES dari ENV: {num_processes}")
    else:
        num_processes = 32
        logger.info(
            f"DATA_PROVIDER_NUM_PROCESSES tidak diatur, pakai default: {num_processes}"
        )

    raw_num_stat = os.getenv("DATA_PROVIDER_NUM_STATIONS")
    if raw_num_stat is not None:
        num_stations = int(raw_num_stat)
        logger.info(f"DATA_PROVIDER_NUM_STATIONS dari ENV: {num_stations}")
    else:
        # 5984 = 187 × 32 — kelipatan 32 terbesar di bawah 6000, tanpa sisa kanal
        num_stations = 5984
        logger.info(
            f"DATA_PROVIDER_NUM_STATIONS tidak diatur, pakai default: {num_stations}"
        )

    # --- Validasi: peringatkan bila num_stations tidak habis dibagi num_processes ---
    remainder = num_stations % num_processes
    if remainder != 0:
        logger.warning(
            f"DATA_PROVIDER_NUM_STATIONS={num_stations} tidak habis dibagi "
            f"DATA_PROVIDER_NUM_PROCESSES={num_processes}. "
            f"Sisa {remainder} kanal akan terpotong pada mode multiprocess/multithread. "
            f"Disarankan menggunakan nilai yang habis dibagi (mis. 5984 untuk 32 proses)."
        )

    mode = os.getenv("DATA_PROVIDER_MODE", "multithread")
    logger.info(
        f"Mode: {mode} | Proses/Thread: {num_processes} | "
        f"Stasiun: {num_stations} | SeedLink: {SEEDLINK_SERVER} | "
        f"Stale threshold: {STALE_SECONDS}s"
    )

    # Gunakan SEEDLINK_SERVER dari settings.py (dibaca dari env SEEDLINK_SERVER)
    station_path = './data/stations.json'

    if mode == "multiprocess":
        from multi_process import main
        main(
            server=SEEDLINK_SERVER,
            station_path=station_path,
            num_processes=num_processes,
            num_station_configs=num_stations,
        )
    elif mode == "multithread":
        from multi_thread import main
        main(
            server=SEEDLINK_SERVER,
            station_path=station_path,
            num_processes=num_processes,
            num_station_configs=num_stations,
        )
    elif mode == "sequence":
        from sequence import main
        main(
            server=SEEDLINK_SERVER,
            station_path=station_path,
            num_processes=num_processes,
            num_station_configs=num_stations,
        )
    elif mode == "hibrida":
        from multi_process_thread import main
        main(
            server=SEEDLINK_SERVER,
            station_path=station_path,
            num_processes=num_processes,
            num_station_configs=num_stations,
        )
    else:
        logger.error(f"DATA_PROVIDER_MODE tidak dikenal: {mode}")
