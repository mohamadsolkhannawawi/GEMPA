"""
SeedlinkClient.py — Klien SeedLink yang mempublikasikan trace ke Kafka.

Digunakan oleh semua mode Data Provider (sequential, multithread, multiprocess,
multiprocess+thread). Metrik Prometheus dibagikan ke proses induk via mode
multiprocess prometheus_client.
"""

import os
import time
import concurrent.futures
import threading

from obspy.clients.seedlink.easyseedlink import EasySeedLinkClient
from kafka import KafkaProducer
import json

# ==============================================================================
# Parameter dari env
# ==============================================================================
ENABLE_METRICS = os.getenv("ENABLE_METRICS", "true").lower() in ("1", "true", "yes", "on")

# Rekaman dianggap basi dan dibuang bila delay melebihi nilai ini (detik).
STALE_SECONDS: float = float(os.getenv("STALE_SECONDS", "60"))

# ==============================================================================
# Prometheus Metrics (dibagikan lewat multiprocess mode)
# ==============================================================================
if ENABLE_METRICS:
    from prometheus_client import Counter, Gauge, REGISTRY

    def _get_or_create(metric_class, name, desc, labelnames=(), **kwargs):
        """
        Ambil metrik yang sudah ada dari REGISTRY atau buat baru.
        Menghindari duplikasi saat modul di-import di proses yang berbeda-beda.
        """
        for candidate in [name, f"{name}_total", f"{name}_created"]:
            if candidate in REGISTRY._names_to_collectors:
                return REGISTRY._names_to_collectors[candidate]
        if labelnames:
            return metric_class(name, desc, labelnames, **kwargs)
        return metric_class(name, desc, **kwargs)

    TRACES_RECEIVED = _get_or_create(
        Counter,
        'data_provider_traces_received',
        'Total rekaman yang diterima dari SeedLink (sebelum filter basi)',
        ['type'],
    )
    TRACES_DROPPED_STALE = _get_or_create(
        Counter,
        'data_provider_traces_dropped_stale',
        'Total rekaman yang dibuang karena dianggap basi (delay > STALE_SECONDS)',
    )
    TRACES_SENT = _get_or_create(
        Counter,
        'data_provider_traces_sent',
        'Total rekaman yang berhasil dikirim ke Kafka',
        ['topic'],
    )
    PUBLISH_ERRORS = _get_or_create(
        Counter,
        'data_provider_publish_errors',
        'Total kesalahan publikasi ke Kafka',
    )
    ACTIVE_STREAMS = _get_or_create(
        Gauge,
        'data_provider_active_streams',
        'Jumlah stream SeedLink yang sedang aktif',
        multiprocess_mode='livesum',
    )
else:
    TRACES_RECEIVED = None
    TRACES_DROPPED_STALE = None
    TRACES_SENT = None
    PUBLISH_ERRORS = None
    ACTIVE_STREAMS = None


class SeedlinkClient(EasySeedLinkClient):
    """
    Klien SeedLink kustom yang mengonsumsi data seismik dan mempublikasikan ke Kafka.
    Dilengkapi Counter dan Gauge Prometheus.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        bootstrap_servers = os.getenv(
            "KAFKA_BROKERS", "kafka1:9092,kafka2:9093"
        ).split(",")
        bootstrap_servers_pwave = os.getenv(
            "KAFKA_BROKERS_PWAVE", "kafka3:9094"
        ).split(",")

        self.producer = KafkaProducer(
            bootstrap_servers=bootstrap_servers,
            value_serializer=lambda v: json.dumps(v).encode('utf-8'),
            key_serializer=lambda v: json.dumps(v).encode('utf-8'),
        )
        self.producer2 = KafkaProducer(
            bootstrap_servers=bootstrap_servers_pwave,
            value_serializer=lambda v: json.dumps(v).encode('utf-8'),
            key_serializer=lambda v: json.dumps(v).encode('utf-8'),
        )
        self.data_station_channel = {}
        self._logger = _get_logger()

    def down_sampling(self, trace):
        """Turunkan sampling rate ke 20 Hz jika lebih tinggi."""
        if trace.stats.sampling_rate > 20:
            before = trace.stats.sampling_rate
            trace.interpolate(sampling_rate=20)
            self._logger.debug(
                f"Down-sampling {trace.stats.station}\t{trace.stats.channel}: "
                f"{before} → {trace.stats.sampling_rate}"
            )
        return trace

    def on_send_success(self, record_metadata):
        pass

    def on_send_error(self, excp):
        self._logger.error(f"Kesalahan kirim Kafka: {excp}")
        if ENABLE_METRICS and PUBLISH_ERRORS:
            PUBLISH_ERRORS.inc()

    def calculate_gap_time(self, trace):
        """Hitung dan log gap antar trace pada kanal yang sama."""
        key = f"{trace.stats.station}-{trace.stats.channel}"
        if key in self.data_station_channel:
            gap = trace.stats.starttime - self.data_station_channel[key].stats.endtime
            if gap > trace.stats.delta * 2:
                self._logger.debug(
                    f"[{key}] Delta: {trace.stats.delta:.4f}s | "
                    f"Gap: {gap:.4f}s | "
                    f"Delay: {time.time() - trace.stats.endtime.timestamp:.4f}s"
                )
        self.data_station_channel[key] = trace

    def send_to_kafka(self, trace):
        """Serialisasi trace dan publikasikan ke topik Kafka."""
        channel_type = trace.stats.channel[-1] if trace.stats.channel else "?"

        # --- Hitung counter received SEBELUM filter basi ---
        if ENABLE_METRICS and TRACES_RECEIVED:
            TRACES_RECEIVED.labels(type=channel_type).inc()

        # --- Filter basi ---
        delay = time.time() - trace.stats.endtime.timestamp
        if delay > STALE_SECONDS:
            self._logger.debug(
                f"Rekaman basi dibuang: {trace.stats.station}-{trace.stats.channel} "
                f"delay={delay:.1f}s > {STALE_SECONDS}s"
            )
            if ENABLE_METRICS and TRACES_DROPPED_STALE:
                TRACES_DROPPED_STALE.inc()
            return

        data = {
            'network': trace.stats.network,
            'station': trace.stats.station,
            'location': trace.stats.location,
            'channel': trace.stats.channel,
            'start_time': trace.stats.starttime.timestamp,
            'end_time': trace.stats.endtime.timestamp,
            'sampling_rate': trace.stats.sampling_rate,
            'delta': trace.stats.delta,
            'npts': trace.stats.npts,
            'calib': trace.stats.calib,
            'data_quality': trace.stats.dataquality,
            'num_samples': trace.stats.numsamples,
            'sample_cnt': trace.stats.samplecnt,
            'sample_type': trace.stats.sampletype,
            'data_provider_time': time.time(),
            'data': trace.data.tolist(),
        }

        topic_trace = os.getenv("KAFKA_TOPIC_TRACE", "trace_topic")
        topic_pwave = os.getenv("KAFKA_TOPIC_PWAVE", "p_wave_topic")

        try:
            self.producer.send(
                topic_trace, data, key=f"{data['station']}-{data['channel']}"
            ).add_callback(self.on_send_success).add_errback(self.on_send_error)
            self.producer.flush()

            if ENABLE_METRICS and TRACES_SENT:
                TRACES_SENT.labels(topic=topic_trace).inc()

            # Hanya kanal Z yang dikirim ke p_wave_topic
            if trace.stats.channel.endswith('Z'):
                self.producer2.send(
                    topic_pwave, data, key=f"{data['station']}-{data['channel']}"
                ).add_callback(self.on_send_success).add_errback(self.on_send_error)
                self.producer2.flush()

                if ENABLE_METRICS and TRACES_SENT:
                    TRACES_SENT.labels(topic=topic_pwave).inc()

        except Exception as e:
            self._logger.error(f"Kesalahan kirim ke Kafka: {e}")
            if ENABLE_METRICS and PUBLISH_ERRORS:
                PUBLISH_ERRORS.inc()
            return

        self._logger.debug(
            f"Delay {data['station']}\t{data['channel']}: "
            f"{time.time() - trace.stats.endtime.timestamp:.4f}s"
        )

    def on_data(self, trace):
        self.send_to_kafka(trace)

    def on_seedlink_error(self):
        self._logger.error('Kesalahan SeedLink')

    def on_terminate(self):
        self._logger.info('Koneksi SeedLink diakhiri')


def _get_logger():
    """Ambil logger dengan nama SeedlinkClient."""
    import logging
    logger = logging.getLogger("SeedlinkClient")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter('%(asctime)s | %(levelname)-8s | %(name)s | %(message)s')
        )
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


def run_client(server, station_configs, process_id):
    """Jalankan satu instance SeedlinkClient untuk subset konfigurasi stasiun."""
    logger = _get_logger()
    client = SeedlinkClient(server)

    if ENABLE_METRICS and ACTIVE_STREAMS:
        ACTIVE_STREAMS.inc(len(station_configs))

    for config in station_configs:
        client.select_stream(
            config['network'], config['station'], config['seedname']
        )

    logger.info(
        f"Klien {process_id} dimulai dengan {len(station_configs)} konfigurasi stasiun"
    )
    client.run()
