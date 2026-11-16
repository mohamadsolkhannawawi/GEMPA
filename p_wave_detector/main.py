"""
P-Wave Detector — Kafka Consumer Mode (Native)
Consumes seismic traces from p_wave_topic, detects P-wave onset using deep learning,
and publishes detection results to loc_mag_topic.

Instrumen Prometheus: Counter, Gauge, Histogram.
Normalisasi dan logika deteksi diambil dari utils/pwave_common.py agar identik
dengan mode Load-Balance (p_wave_detector_load_balance/main.py).
"""

import sys
import os
import threading
from time import sleep, time
from typing import Dict, Any

import obspy
import numpy as np
import tensorflow as tf

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from config.settings import (
    ENABLE_METRICS,
    METRICS_PORT_PWAVE_DETECTOR,
    KAFKA_BROKERS,
    KAFKA_BROKERS_PWAVE,
    KAFKA_TOPIC_PWAVE,
    KAFKA_TOPIC_LOCMAG,
)
from utils.kafka_helper import create_topic_if_not_exists, get_consumer, get_producer
from utils.logger import get_logger
from utils.pwave_common import normalize_batch, detect, PWAVE_THRESHOLD, PWAVE_CONSEC

logger = get_logger("PWaveDetector")

# ==============================================================================
# Prometheus Metrics
# ==============================================================================
if ENABLE_METRICS:
    from prometheus_client import start_http_server, Counter, Gauge, Histogram

    PWAVE_REQUESTS = Counter(
        'pwave_requests_total',
        'Total number of trace messages received for P-wave detection'
    )
    PWAVE_DETECTIONS = Counter(
        'pwave_detections_total',
        'Total number of positive P-wave detections'
    )
    PWAVE_ERRORS = Counter(
        'pwave_inference_errors_total',
        'Total number of inference errors'
    )
    PWAVE_CACHE_SIZE = Gauge(
        'pwave_waveform_cache_size',
        'Number of station-channel entries in waveform cache'
    )
    PWAVE_INFLIGHT = Gauge(
        'pwave_inflight',
        'Number of processing threads currently running'
    )
    FINE_BUCKETS = [
        0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 15.0, 20.0,
        30.0, 45.0, 60.0, 90.0, 120.0, 180.0, 300.0, 600.0,
    ]
    PWAVE_INFERENCE_LATENCY = Histogram(
        'pwave_inference_latency_seconds',
        'Latency of P-wave model inference',
        buckets=FINE_BUCKETS,
    )
    PWAVE_KAFKA_DELAY = Histogram(
        'pwave_kafka_delay_seconds',
        'Delay antara data_provider_time dan saat pesan tiba di consumer',
        buckets=FINE_BUCKETS,
    )
    PWAVE_QUEUE_WAIT = Histogram(
        'pwave_queue_wait_seconds',
        'Waktu dari pesan tiba di consumer hingga inferensi mulai',
        buckets=FINE_BUCKETS,
    )
    PWAVE_E2E_LATENCY = Histogram(
        'pwave_end_to_end_latency_seconds',
        'Latensi E2E: dari data_provider_time hingga sesudah inferensi selesai',
        buckets=FINE_BUCKETS,
    )
else:
    PWAVE_REQUESTS = None
    PWAVE_DETECTIONS = None
    PWAVE_ERRORS = None
    PWAVE_CACHE_SIZE = None
    PWAVE_INFLIGHT = None
    PWAVE_INFERENCE_LATENCY = None
    PWAVE_KAFKA_DELAY = None
    PWAVE_QUEUE_WAIT = None
    PWAVE_E2E_LATENCY = None


class TraceConsumer:
    """Kafka consumer yang mendeteksi P-wave pada setiap trace seismik masuk."""

    def __init__(self):
        self.consumer = None
        self.producer = None
        self.model = tf.keras.models.load_model('./model_p_wave.h5', compile=False)
        self.last_waveform: Dict[str, list] = {}
        self.cache_lock = threading.Lock()

    def setTrace(self, data: Dict[str, Any]) -> obspy.Trace:
        """Rekonstruksi obspy.Trace dari pesan Kafka yang di-deserialize."""
        trace = obspy.Trace(np.array(data['data']))
        trace.stats.network = data['network']
        trace.stats.station = data['station']
        trace.stats.location = data['location']
        trace.stats.channel = data['channel']
        trace.stats.starttime = obspy.UTCDateTime(data['start_time'])
        trace.stats.sampling_rate = data['sampling_rate']
        trace.stats.delta = data['delta']
        trace.stats.npts = data['npts']
        trace.stats.calib = data['calib']
        trace.stats.dataquality = data['data_quality']
        trace.stats.numsamples = data['num_samples']
        trace.stats.samplecnt = data['sample_cnt']
        trace.stats.sampletype = data['sample_type']
        trace.interpolate(sampling_rate=20)
        return trace

    def predict(
        self,
        trace: obspy.Trace,
        data_provider_time: float,
        arrive_time: float,
    ) -> None:
        """
        Jalankan model deteksi P-wave pada trace dan terbitkan hasilnya.

        Parameter
        ---------
        trace            : obspy.Trace setelah di-resample ke 20 Hz
        data_provider_time : timestamp saat data dibuat oleh Data Provider
        arrive_time      : timestamp saat pesan tiba di consumer loop
                           (digunakan untuk mengukur pwave_queue_wait_seconds)
        """
        try:
            # --- Siapkan input model (vektorisasi, tanpa apply_along_axis) ---
            converter_np = np.stack([trace.data, trace.data, trace.data], axis=-1)
            sliding_array = np.lib.stride_tricks.sliding_window_view(
                converter_np, (160, 3)
            ).reshape(-1, 160, 3)

            # Normalisasi batch secara vektorisasi (utils/pwave_common.normalize_batch)
            preprocessed_array = normalize_batch(sliding_array)

            # --- Ukur latensi antrean (pesan tiba → inferensi mulai) ---
            inference_start = time()
            if ENABLE_METRICS and PWAVE_QUEUE_WAIT:
                PWAVE_QUEUE_WAIT.observe(inference_start - arrive_time)

            # --- Inferensi ---
            predictions_p_wave = self.model(preprocessed_array, training=False).numpy()
            inference_duration = time() - inference_start

            # --- Latensi inferensi ---
            if ENABLE_METRICS and PWAVE_INFERENCE_LATENCY:
                PWAVE_INFERENCE_LATENCY.observe(inference_duration)

            # --- Latensi E2E (dicatat SESUDAH inferensi selesai) ---
            if ENABLE_METRICS and PWAVE_E2E_LATENCY:
                PWAVE_E2E_LATENCY.observe(time() - data_provider_time)

            # --- Deteksi menggunakan logika bersama dari pwave_common ---
            preds_flat = predictions_p_wave[:, 1] if predictions_p_wave.ndim > 1 else predictions_p_wave.flatten()
            idx, max_value = detect(preds_flat, PWAVE_THRESHOLD, PWAVE_CONSEC)

            if max_value == 0.0:
                return

            # --- P-Wave terdeteksi! ---
            if ENABLE_METRICS and PWAVE_DETECTIONS:
                PWAVE_DETECTIONS.inc()

            p_wave_time = trace.stats.starttime.timestamp + idx * trace.stats.delta
            p_wave_waveform = trace.data.tolist()[idx + 40: idx + 120]

            result = {
                'network': trace.stats.network,
                'station': trace.stats.station,
                'location': trace.stats.location,
                'channel': trace.stats.channel,
                'sampling_rate': trace.stats.sampling_rate,
                'p_wave_time': p_wave_time,
                'data_provider_time': data_provider_time,
                'p_wave_detector_time': time(),
                'data': p_wave_waveform,
            }

            self.producer.send(
                KAFKA_TOPIC_LOCMAG, result,
                key=f"{result['station']}-{result['channel']}"
            )
            self.producer.flush()

            logger.info(
                f"P-Wave terdeteksi untuk "
                f"{trace.stats.station}-{trace.stats.channel}"
            )

        except Exception as e:
            logger.error(
                f"Kesalahan prediksi "
                f"{trace.stats.station} {trace.stats.channel}: {e}"
            )
            if ENABLE_METRICS and PWAVE_ERRORS:
                PWAVE_ERRORS.inc()

    def process(self, data: Dict[str, Any], data_delay: float, arrive_time: float) -> None:
        """
        Proses trace masuk: gabungkan cache, periksa panjang, lalu prediksi.

        Parameter
        ---------
        arrive_time : timestamp saat pesan tiba di consumer loop (untuk PWAVE_QUEUE_WAIT)
        """
        if ENABLE_METRICS and PWAVE_INFLIGHT:
            PWAVE_INFLIGHT.inc()
        try:
            start_time = time()
            key = f"{data['station']}-{data['channel']}"

            with self.cache_lock:
                cached_data = self.last_waveform.get(key)

            if cached_data:
                data['data'] = cached_data + data['data']
                data['start_time'] = data['start_time'] - 4
                data['npts'] = len(data['data'])
                data['sample_cnt'] = len(data['data'])
                data['num_samples'] = len(data['data'])

            sampling_rate = data['sampling_rate']
            ratio = sampling_rate / 20
            new_length = int(len(data['data']) / ratio)

            if new_length >= 160:
                trace = self.setTrace(data)
                self.predict(trace, data['data_provider_time'], arrive_time)

                with self.cache_lock:
                    self.last_waveform[key] = []

            process_time = time() - start_time
            logger.debug(
                f"Delay Kafka: {data_delay:.4f}s | Waktu Proses: {process_time:.4f}s"
            )
        finally:
            if ENABLE_METRICS and PWAVE_INFLIGHT:
                PWAVE_INFLIGHT.dec()

    def connectConsumer(self) -> None:
        """Loop utama consumer: terima pesan, spawn thread pemrosesan."""
        logger.info(f"Memulai consumer loop pada topik {KAFKA_TOPIC_PWAVE}...")
        for msg in self.consumer:
            arrive_time = time()
            data = msg.value
            data_delay = arrive_time - data['data_provider_time']

            # --- Kafka delay ---
            if ENABLE_METRICS and PWAVE_KAFKA_DELAY:
                PWAVE_KAFKA_DELAY.observe(data_delay)

            if ENABLE_METRICS and PWAVE_REQUESTS:
                PWAVE_REQUESTS.inc()

            threading.Thread(
                target=self.process,
                args=(data, data_delay, arrive_time),
                daemon=True,
            ).start()

            # --- Perbarui cache waveform ---
            key = f"{data['station']}-{data['channel']}"
            with self.cache_lock:
                if key in self.last_waveform:
                    self.last_waveform[key].extend(data['data'])
                else:
                    self.last_waveform[key] = data['data']

                cut_length = int(4 * data['sampling_rate'])
                if len(self.last_waveform[key]) > cut_length:
                    self.last_waveform[key] = self.last_waveform[key][-cut_length:]

                cache_size = len(self.last_waveform)

            if ENABLE_METRICS and PWAVE_CACHE_SIZE:
                PWAVE_CACHE_SIZE.set(cache_size)


if __name__ == '__main__':
    if ENABLE_METRICS:
        try:
            start_http_server(METRICS_PORT_PWAVE_DETECTOR)
            logger.info(
                f"Server metrik Prometheus dimulai di port {METRICS_PORT_PWAVE_DETECTOR}"
            )
        except Exception as e:
            logger.error(f"Gagal memulai server metrik: {e}")

    traceConsumer = TraceConsumer()

    create_topic_if_not_exists(
        topic_name=KAFKA_TOPIC_LOCMAG,
        num_partitions=3,
        replication_factor=1,
        bootstrap_servers=KAFKA_BROKERS,
    )

    traceConsumer.consumer = get_consumer(
        KAFKA_TOPIC_PWAVE, 'trace_group', KAFKA_BROKERS_PWAVE
    )
    traceConsumer.producer = get_producer(KAFKA_BROKERS)

    traceConsumer.connectConsumer()
