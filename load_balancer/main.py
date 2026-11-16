"""
Load Balancer — Kafka Consumer → HTTP Forwarder
Mengonsumsi dari p_wave_topic dan meneruskan via HTTP ke replika P-Wave Detector.

Instrumen Prometheus: Counter, Histogram.
"""

import sys
import os
import time
from time import sleep
import requests
from typing import Dict, Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from config.settings import (
    ENABLE_METRICS,
    METRICS_PORT_LOAD_BALANCER,
    KAFKA_BROKERS_PWAVE,
    KAFKA_TOPIC_PWAVE,
)
from utils.kafka_helper import check_kafka_connection, topic_exists, get_consumer
from utils.logger import get_logger

logger = get_logger("LoadBalancer")

# ==============================================================================
# Validasi LB_TARGET_URL — wajib diatur, tidak ada nilai bawaan
# ==============================================================================
_lb_target_url = os.getenv("LB_TARGET_URL")
if not _lb_target_url:
    raise EnvironmentError(
        "LB_TARGET_URL tidak diatur di environment. "
        "Tambahkan LB_TARGET_URL=http://nginx_load_balancer:80/trace (atau URL replika) "
        "ke file .env atau docker-compose sebelum menjalankan Load Balancer."
    )
LB_TARGET_URL: str = _lb_target_url

# ==============================================================================
# Prometheus Metrics
# ==============================================================================
if ENABLE_METRICS:
    from prometheus_client import start_http_server, Counter, Histogram

    LB_FORWARDED = Counter(
        'lb_messages_forwarded_total',
        'Total pesan yang diteruskan ke P-Wave Detector'
    )
    LB_FORWARD_ERRORS = Counter(
        'lb_forward_errors_total',
        'Total kegagalan penerusan'
    )
    FINE_BUCKETS = [
        0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 15.0, 20.0,
        30.0, 45.0, 60.0, 90.0, 120.0, 180.0, 300.0, 600.0,
    ]
    LB_FORWARD_LATENCY = Histogram(
        'lb_forward_latency_seconds',
        'Latensi HTTP POST ke P-Wave Detector',
        buckets=FINE_BUCKETS,
    )
    LB_KAFKA_DELAY = Histogram(
        'lb_kafka_delay_seconds',
        'Delay antara data_provider_time dan saat pesan tiba di Load Balancer',
        buckets=FINE_BUCKETS,
    )
    LB_FORWARDED_BY_REPLICA = Counter(
        'lb_forwarded_by_replica_total',
        'Pesan yang diteruskan per replika P-Wave Detector',
        ['replica'],
    )
else:
    LB_FORWARDED = None
    LB_FORWARD_ERRORS = None
    LB_FORWARD_LATENCY = None
    LB_KAFKA_DELAY = None
    LB_FORWARDED_BY_REPLICA = None


class TraceConsumer:
    """Kafka consumer yang meneruskan trace via HTTP ke replika P-Wave Detector."""

    def __init__(self):
        self.consumer = None
        # [A7] Gunakan Session untuk HTTP keep-alive — menghilangkan overhead
        # TCP handshake berulang pada ribuan paket trace.
        self._http_session = requests.Session()

    def connectConsumer(self) -> None:
        """Loop utama consumer: teruskan tiap pesan via HTTP."""
        logger.info(
            f"Mulai mengonsumsi dari {KAFKA_TOPIC_PWAVE} "
            f"dan meneruskan ke {LB_TARGET_URL}"
        )

        for msg in self.consumer:
            data = msg.value
            kafka_delay = time.time() - data['data_provider_time']

            if ENABLE_METRICS and LB_KAFKA_DELAY:
                LB_KAFKA_DELAY.observe(kafka_delay)

            logger.debug(
                f"Partisi: {msg.partition} | Offset: {msg.offset} | "
                f"Stasiun: {data['station']}-{data['channel']} | "
                f"Delay Kafka: {kafka_delay:.4f}s"
            )

            forward_start = time.time()
            try:
                response = self._http_session.post(LB_TARGET_URL, json=data, timeout=30)
                response.raise_for_status()
                forward_duration = time.time() - forward_start

                if ENABLE_METRICS:
                    if LB_FORWARDED:
                        LB_FORWARDED.inc()
                    if LB_FORWARD_LATENCY:
                        LB_FORWARD_LATENCY.observe(forward_duration)

                    # Catat distribusi per replika dari respons JSON
                    if LB_FORWARDED_BY_REPLICA:
                        try:
                            replica = response.json().get("replica", "unknown")
                        except Exception:
                            replica = "unknown"
                        LB_FORWARDED_BY_REPLICA.labels(replica=replica).inc()

            except Exception as e:
                logger.error(f"Kesalahan saat meneruskan ke {LB_TARGET_URL}: {e}")
                if ENABLE_METRICS and LB_FORWARD_ERRORS:
                    LB_FORWARD_ERRORS.inc()


def initialize_system() -> None:
    """Tunggu hingga Kafka siap dan topik tersedia."""
    while True:
        if (
            check_kafka_connection(KAFKA_BROKERS_PWAVE)
            and topic_exists(KAFKA_TOPIC_PWAVE, KAFKA_BROKERS_PWAVE)
        ):
            logger.info("Inisialisasi sistem berhasil.")
            break
        sleep(3)


if __name__ == '__main__':
    if ENABLE_METRICS:
        try:
            start_http_server(METRICS_PORT_LOAD_BALANCER)
            logger.info(
                f"Server metrik Prometheus dimulai di port {METRICS_PORT_LOAD_BALANCER}"
            )
        except Exception as e:
            logger.error(f"Gagal memulai server metrik: {e}")

    initialize_system()

    consumer = TraceConsumer()
    consumer.consumer = get_consumer(
        KAFKA_TOPIC_PWAVE, 'load_balancer_group', KAFKA_BROKERS_PWAVE
    )
    consumer.connectConsumer()
