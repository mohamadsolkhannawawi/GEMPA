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
from utils.kafka_helper import get_consumer, get_producer
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


# Batasi jumlah thread inferensi paralel untuk mencegah ledakan alokasi memori TensorFlow.
# Setiap inference call dapat mengalokasikan >1 GB; 4 thread paralel aman di mesin 32 GB WSL.
_MAX_INFLIGHT_INFERENCES = int(os.getenv("PWAVE_MAX_INFLIGHT", "4"))
_inference_semaphore = threading.Semaphore(_MAX_INFLIGHT_INFERENCES)


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
        # Guard: hanya interpolasi jika sampling_rate valid dan data tidak semua nol.
        # Trace dengan sampling_rate == 0 atau data flat-nol menyebabkan divide-by-zero
        # di obspy interpolation dan menghasilkan NaN/Inf yang meledakkan alokasi TF.
        if data['sampling_rate'] > 0 and not np.all(trace.data == 0):
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
            # --- Guard: buang trace yang mengandung NaN atau Inf ---
            # Trace demikian dihasilkan dari data seismik degenerasi (semua nol,
            # sampling_rate tidak valid, dsb.) dan akan menyebabkan sliding_window_view
            # menghasilkan tensor berisi NaN yang membebani alokasi TensorFlow.
            if not np.isfinite(trace.data).all():
                logger.debug(
                    f"Trace {trace.stats.station}-{trace.stats.channel} "
                    f"mengandung NaN/Inf, dilewati."
                )
                return

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
            # Tangani dua kemungkinan shape output model:
            # - (N, 2): softmax 2-kelas → ambil kolom 1 (probabilitas P-wave)
            # - (N, 1): sigmoid 1-output → squeeze langsung
            # - (N,)  : sudah flat
            if predictions_p_wave.ndim > 1 and predictions_p_wave.shape[1] >= 2:
                preds_flat = predictions_p_wave[:, 1]
            else:
                preds_flat = predictions_p_wave.flatten()
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
            # Tidak memanggil flush() per pesan — biarkan Kafka producer
            # melakukan batching alami sesuai linger_ms dan acks (A5).

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

    def connectConsumer(self) -> None:
        """Loop utama consumer: terima pesan, spawn thread pemrosesan."""
        import time as _time
        logger.info(f"Memulai consumer loop pada topik {KAFKA_TOPIC_PWAVE}...")
        while True:
            try:
                for msg in self.consumer:
                    arrive_time = time()
                    data = msg.value
                    data_delay = arrive_time - data['data_provider_time']

                    # --- Kafka delay ---
                    if ENABLE_METRICS and PWAVE_KAFKA_DELAY:
                        PWAVE_KAFKA_DELAY.observe(data_delay)

                    if ENABLE_METRICS and PWAVE_REQUESTS:
                        PWAVE_REQUESTS.inc()

                    # --- [A2] Bangun salinan mandiri masukan di dalam lock SEBELUM spawn thread ---
                    # Urutan di dalam lock:
                    #   1. Ambil salinan cache lama
                    #   2. Gabungkan dengan paket baru
                    #   3. Simpan kembali ke cache (potong bila perlu)
                    #   4. Buat salinan mandiri untuk dikirim ke worker
                    # Ini mencegah aliasing: thread tidak berbagi objek list yang sama
                    # dengan cache, sehingga operasi extend/assign berikutnya tidak
                    # memodifikasi data yang sudah dikirim ke worker.
                    key = f"{data['station']}-{data['channel']}"
                    with self.cache_lock:
                        cached_data = self.last_waveform.get(key)
                        if cached_data:
                            combined = list(cached_data) + list(data['data'])
                        else:
                            combined = list(data['data'])

                        # Perbarui cache dengan paket terbaru saja (bukan combined)
                        new_cache = list(data['data'])
                        cut_length = int(4 * data['sampling_rate'])
                        if len(new_cache) > cut_length:
                            new_cache = new_cache[-cut_length:]
                        self.last_waveform[key] = new_cache

                        # Buat salinan data yang akan dikirim ke worker (mandiri dari cache)
                        worker_data = dict(data)
                        worker_data['data'] = combined
                        if cached_data:
                            worker_data['start_time'] = data['start_time'] - 4
                        worker_data['npts'] = len(combined)
                        worker_data['sample_cnt'] = len(combined)
                        worker_data['num_samples'] = len(combined)

                        cache_size = len(self.last_waveform)

                    threading.Thread(
                        target=self._run_predict_from_combined,
                        args=(worker_data, data_delay, arrive_time),
                        daemon=True,
                    ).start()

                    if ENABLE_METRICS and PWAVE_CACHE_SIZE:
                        PWAVE_CACHE_SIZE.set(cache_size)

                # for loop selesai berarti consumer disconnect / rebalance timeout
                logger.warning(
                    "Consumer loop berakhir (disconnect/rebalance). Reconnect dalam 5s..."
                )

            except Exception as e:
                logger.error(f"Exception di consumer loop: {e}. Reconnect dalam 5s...")

            _time.sleep(5)
            try:
                self.consumer = get_consumer(
                    KAFKA_TOPIC_PWAVE, 'trace_group', KAFKA_BROKERS_PWAVE
                )
                logger.info("Reconnect ke Kafka berhasil. Melanjutkan consumer loop...")
            except Exception as re:
                logger.error(f"Reconnect gagal: {re}. Coba lagi dalam 5s...")

    def _run_predict_from_combined(
        self,
        worker_data: Dict[str, Any],
        data_delay: float,
        arrive_time: float,
    ) -> None:
        """
        Worker thread: periksa panjang data dan jalankan prediksi.

        Menerima salinan data yang sudah mandiri (tidak berbagi referensi list
        dengan cache), sehingga aman dijalankan paralel.
        Semaphore _inference_semaphore membatasi jumlah inferensi aktif sekaligus
        untuk mencegah lonjakan alokasi memori TensorFlow.
        """
        if ENABLE_METRICS and PWAVE_INFLIGHT:
            PWAVE_INFLIGHT.inc()
        try:
            sampling_rate = worker_data['sampling_rate']
            ratio = sampling_rate / 20
            new_length = int(len(worker_data['data']) / ratio)

            if new_length >= 160:
                _inference_semaphore.acquire()
                try:
                    trace = self.setTrace(worker_data)
                    self.predict(trace, worker_data['data_provider_time'], arrive_time)
                finally:
                    _inference_semaphore.release()

            logger.debug(
                f"Delay Kafka: {data_delay:.4f}s"
            )
        finally:
            if ENABLE_METRICS and PWAVE_INFLIGHT:
                PWAVE_INFLIGHT.dec()


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

    # Topik Kafka dibuat secara deterministik oleh kafka-init (A9).
    # Tidak ada pemanggilan create_topic_if_not_exists di sini.

    traceConsumer.consumer = get_consumer(
        KAFKA_TOPIC_PWAVE, 'trace_group', KAFKA_BROKERS_PWAVE
    )
    traceConsumer.producer = get_producer(KAFKA_BROKERS)

    traceConsumer.connectConsumer()
