"""
P-Wave Detector — Load-Balanced Mode (HTTP/FastAPI)
Menerima HTTP POST /trace dari Load Balancer, menjalankan inferensi async,
dan menerbitkan hasil ke Kafka.

Instrumen Prometheus: Counter, Gauge, Histogram.
Normalisasi dan logika deteksi diambil dari utils/pwave_common.py agar identik
dengan mode Native Kafka (p_wave_detector/main.py).
"""

import sys
import os
import asyncio
from time import time
from typing import Dict, Any

from fastapi import FastAPI, Response
import uvicorn
import obspy
import numpy as np
import tensorflow as tf
from cachetools import LRUCache

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from config.settings import (
    ENABLE_METRICS,
    KAFKA_BROKERS,
    KAFKA_TOPIC_LOCMAG,
)
from utils.kafka_helper import get_producer
from utils.logger import get_logger
from utils.pwave_common import normalize_batch, detect, PWAVE_THRESHOLD, PWAVE_CONSEC

logger = get_logger("PWaveDetectorLB")

# ==============================================================================
# Prometheus Metrics
# ==============================================================================
if ENABLE_METRICS:
    from prometheus_client import (
        Counter, Gauge, Histogram,
        generate_latest, CONTENT_TYPE_LATEST,
    )

    PWAVE_LB_REQUESTS = Counter(
        'pwave_lb_requests_total',
        'Total HTTP trace requests received'
    )
    PWAVE_LB_DETECTIONS = Counter(
        'pwave_lb_detections_total',
        'Total positive P-wave detections (load-balanced)'
    )
    PWAVE_LB_ERRORS = Counter(
        'pwave_lb_inference_errors_total',
        'Total inference errors (load-balanced)'
    )
    PWAVE_LB_CACHE_SIZE = Gauge(
        'pwave_lb_waveform_cache_size',
        'Station-channel entries in waveform cache (load-balanced)'
    )
    PWAVE_LB_INFLIGHT = Gauge(
        'pwave_lb_inflight',
        'Number of async process tasks currently running'
    )
    FINE_BUCKETS = [
        0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 15.0, 20.0,
        30.0, 45.0, 60.0, 90.0, 120.0, 180.0, 300.0, 600.0,
    ]
    PWAVE_LB_INFERENCE_LATENCY = Histogram(
        'pwave_lb_inference_latency_seconds',
        'Latency of P-wave model inference (load-balanced)',
        buckets=FINE_BUCKETS,
    )
    PWAVE_LB_KAFKA_DELAY = Histogram(
        'pwave_lb_kafka_delay_seconds',
        'Delay antara data_provider_time dan saat permintaan HTTP diterima',
        buckets=FINE_BUCKETS,
    )
    PWAVE_LB_QUEUE_WAIT = Histogram(
        'pwave_lb_queue_wait_seconds',
        'Waktu dari permintaan HTTP diterima hingga inferensi mulai',
        buckets=FINE_BUCKETS,
    )
    PWAVE_E2E_LATENCY = Histogram(
        'pwave_end_to_end_latency_seconds',
        'Latensi E2E: dari data_provider_time hingga sesudah inferensi selesai',
        buckets=FINE_BUCKETS,
    )
else:
    PWAVE_LB_REQUESTS = None
    PWAVE_LB_DETECTIONS = None
    PWAVE_LB_ERRORS = None
    PWAVE_LB_CACHE_SIZE = None
    PWAVE_LB_INFLIGHT = None
    PWAVE_LB_INFERENCE_LATENCY = None
    PWAVE_LB_KAFKA_DELAY = None
    PWAVE_LB_QUEUE_WAIT = None
    PWAVE_E2E_LATENCY = None


# ==============================================================================
# Inisialisasi aplikasi & sumber daya
# ==============================================================================

app = FastAPI()
last_waveform: LRUCache = LRUCache(maxsize=6000)
model = tf.keras.models.load_model('./model_p_wave.h5', compile=False)

# Perlindungan garbage collector: referensi task asyncio disimpan di sini (A8).
background_tasks: set = set()

# Topik Kafka dibuat secara deterministik oleh kafka-init (A9).
# Tidak ada pemanggilan create_topic_if_not_exists di sini.
producer = get_producer(KAFKA_BROKERS)

# Hostname replika — dikembalikan dalam respons /trace untuk pelacakan distribusi.
REPLICA_HOSTNAME: str = os.getenv("HOSTNAME", "unknown")


# ==============================================================================
# Fungsi bantu
# ==============================================================================

def set_trace(data: Dict[str, Any]) -> obspy.Trace:
    """Rekonstruksi obspy.Trace dari dict pesan."""
    trace = obspy.Trace(np.array(data['data']))
    trace.stats.update({
        'network': data['network'],
        'station': data['station'],
        'location': data['location'],
        'channel': data['channel'],
        'starttime': obspy.UTCDateTime(data['start_time']),
        'sampling_rate': data['sampling_rate'],
        'delta': data['delta'],
        'npts': data['npts'],
        'calib': data['calib'],
        'dataquality': data['data_quality'],
        'numsamples': data['num_samples'],
        'samplecnt': data['sample_cnt'],
        'sampletype': data['sample_type'],
    })
    trace.interpolate(sampling_rate=20)
    return trace


async def predict(
    trace: obspy.Trace,
    data_provider_time: float,
    arrive_time: float,
) -> None:
    """
    Jalankan model deteksi P-wave secara async.

    Parameter
    ---------
    arrive_time : timestamp saat permintaan HTTP diterima endpoint /trace
    """
    try:
        # --- Siapkan input model ---
        converter_np = np.stack([trace.data, trace.data, trace.data], axis=-1)
        sliding_array = np.lib.stride_tricks.sliding_window_view(
            converter_np, (160, 3)
        ).reshape(-1, 160, 3)
        preprocessed_array = normalize_batch(sliding_array)

        # --- Latensi antrean (HTTP diterima → inferensi mulai) ---
        inference_start = time()
        if ENABLE_METRICS and PWAVE_LB_QUEUE_WAIT:
            PWAVE_LB_QUEUE_WAIT.observe(inference_start - arrive_time)

        # --- Inferensi (di executor agar tidak memblokir event loop) ---
        loop = asyncio.get_event_loop()
        predictions_p_wave = await loop.run_in_executor(
            None, lambda: model(preprocessed_array, training=False).numpy()
        )
        inference_duration = time() - inference_start

        if ENABLE_METRICS and PWAVE_LB_INFERENCE_LATENCY:
            PWAVE_LB_INFERENCE_LATENCY.observe(inference_duration)

        # --- E2E latency (dicatat SESUDAH inferensi selesai) ---
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
        if ENABLE_METRICS and PWAVE_LB_DETECTIONS:
            PWAVE_LB_DETECTIONS.inc()

        p_wave_time = trace.stats.starttime.timestamp + idx * trace.stats.delta
        p_wave_waveform = trace.data[idx + 40: idx + 120].tolist()

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

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: producer.send(
                KAFKA_TOPIC_LOCMAG, result,
                key=f"{result['station']}-{result['channel']}"
            )
        )
        # Tidak memanggil flush() per pesan — batching alami Kafka (A5).

        logger.info(
            f"P-Wave terdeteksi untuk "
            f"{trace.stats.station}-{trace.stats.channel}"
        )

    except Exception as e:
        logger.error(
            f"Kesalahan prediksi "
            f"{trace.stats.station} {trace.stats.channel}: {e}"
        )
        if ENABLE_METRICS and PWAVE_LB_ERRORS:
            PWAVE_LB_ERRORS.inc()


async def process(
    data: Dict[str, Any],
    data_delay: float,
    arrive_time: float,
) -> None:
    """Periksa panjang data yang sudah digabungkan cache, lalu jalankan prediksi."""
    if ENABLE_METRICS and PWAVE_LB_INFLIGHT:
        PWAVE_LB_INFLIGHT.inc()
    try:
        sampling_rate = data['sampling_rate']
        ratio = sampling_rate / 20
        new_length = int(len(data['data']) / ratio)

        if new_length >= 160:
            trace = set_trace(data)
            await predict(trace, data['data_provider_time'], arrive_time)

        logger.debug(
            f"Delay Kafka: {data_delay:.4f}s"
        )
    finally:
        if ENABLE_METRICS and PWAVE_LB_INFLIGHT:
            PWAVE_LB_INFLIGHT.dec()


# ==============================================================================
# Endpoint HTTP
# ==============================================================================

@app.post("/trace")
async def trace_endpoint(data: dict):
    """Endpoint HTTP untuk menerima trace dari Load Balancer."""
    arrive_time = time()

    if ENABLE_METRICS and PWAVE_LB_REQUESTS:
        PWAVE_LB_REQUESTS.inc()

    data_delay = arrive_time - data['data_provider_time']

    if ENABLE_METRICS and PWAVE_LB_KAFKA_DELAY:
        PWAVE_LB_KAFKA_DELAY.observe(data_delay)

    # --- [A2] Bangun salinan mandiri masukan sebelum spawn task ---
    # 1. Ambil cache lama
    # 2. Gabungkan dengan paket baru → salinan baru (list(...))
    # 3. Perbarui cache dengan paket baru saja
    # 4. Kirim salinan ke asyncio task (tidak berbagi referensi dengan cache)
    key = f"{data['station']}-{data['channel']}"
    cached_data = last_waveform.get(key)
    if cached_data:
        combined = list(cached_data) + list(data['data'])
    else:
        combined = list(data['data'])

    # Perbarui cache dengan paket terbaru saja
    new_cache = list(data['data'])
    cut_length = int(4 * data['sampling_rate'])
    if len(new_cache) > cut_length:
        new_cache = new_cache[-cut_length:]
    last_waveform[key] = new_cache

    # Buat salinan worker_data yang mandiri
    worker_data = dict(data)
    worker_data['data'] = combined
    if cached_data:
        worker_data['start_time'] = data['start_time'] - 4
    worker_data['npts'] = len(combined)
    worker_data['sample_cnt'] = len(combined)
    worker_data['num_samples'] = len(combined)

    if ENABLE_METRICS and PWAVE_LB_CACHE_SIZE:
        PWAVE_LB_CACHE_SIZE.set(len(last_waveform))

    # --- [A8] Simpan referensi task agar tidak dihapus garbage collector ---
    task = asyncio.create_task(process(worker_data, data_delay, arrive_time))
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)

    # Kembalikan nama replika agar Load Balancer dapat menghitung distribusi
    return {"replica": REPLICA_HOSTNAME}


@app.get("/metrics")
async def metrics():
    """Endpoint metrik Prometheus."""
    if ENABLE_METRICS:
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
    return Response(content="Metrics disabled", status_code=404)


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


if __name__ == '__main__':
    logger.info("Memulai P-Wave Detector (Load Balanced Mode)")
    uvicorn.run(app, host="0.0.0.0", port=8004)
