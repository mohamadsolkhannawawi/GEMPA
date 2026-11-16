"""
WebSocket Server (FastAPI) — Kafka Consumer → WebSocket + Socket.IO

Mendukung dua protokol siaran:
  1. Native WebSocket di /ws  (klien browser atau ws_load_generator.py)
  2. Socket.IO di /socket.io  (kompatibel dengan seismic_app yang menggunakan
     pustaka socket.io-client, identik dengan format yang dikirim Express.js)

Instrumen Prometheus: Counter, Gauge, Histogram.
Perbaikan K8:
  - Integrasi python-socketio (AsyncServer mode='asgi') ke FastAPI via ASGI mount.
  - Waktu penyelesaian siaran diukur dengan time.perf_counter() (resolusi tinggi).
  - Siaran ke Socket.IO dan WebSocket native dilakukan dari satu fungsi bersama.
"""

import sys
import os
import json
import asyncio
import time
from threading import Thread

import socketio
from fastapi import FastAPI, WebSocket, Response
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from config.settings import (
    ENABLE_METRICS,
    METRICS_PORT_FASTAPI,
    KAFKA_BROKERS,
    KAFKA_TOPIC_TRACE,
    KAFKA_TOPIC_RESULT,
)
from utils.kafka_helper import get_consumer, check_kafka_connection
from utils.logger import get_logger

logger = get_logger("FastAPI")

# ==============================================================================
# Prometheus Metrics
# ==============================================================================
if ENABLE_METRICS:
    from prometheus_client import (
        Counter, Gauge, Histogram,
        generate_latest, CONTENT_TYPE_LATEST,
    )

    FASTAPI_WS_BROADCAST = Counter(
        'fastapi_ws_messages_broadcast_total',
        'Total pesan yang disiarkan ke klien WebSocket',
        ['topic'],
    )
    FASTAPI_WS_CONNECTIONS = Counter(
        'fastapi_ws_client_connections_total',
        'Total koneksi klien WebSocket',
    )
    FASTAPI_WS_DISCONNECTIONS = Counter(
        'fastapi_ws_client_disconnections_total',
        'Total pemutusan koneksi klien WebSocket',
    )
    FASTAPI_WS_ACTIVE = Gauge(
        'fastapi_ws_active_clients',
        'Jumlah klien WebSocket yang sedang terhubung',
    )
    FASTAPI_WS_BROADCAST_LATENCY = Histogram(
        'fastapi_ws_broadcast_latency_seconds',
        'Waktu penyelesaian siaran ke seluruh klien (diukur dengan perf_counter)',
        buckets=[
            0.0001, 0.0005, 0.001, 0.005, 0.01, 0.05,
            0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0,
        ],
    )
else:
    FASTAPI_WS_BROADCAST = None
    FASTAPI_WS_CONNECTIONS = None
    FASTAPI_WS_DISCONNECTIONS = None
    FASTAPI_WS_ACTIVE = None
    FASTAPI_WS_BROADCAST_LATENCY = None


# ==============================================================================
# Socket.IO server (kompatibel dengan seismic_app yang pakai socket.io-client)
# ==============================================================================
sio = socketio.AsyncServer(
    async_mode='asgi',
    cors_allowed_origins='*',
)

# ==============================================================================
# FastAPI app + CORS
# ==============================================================================
_fastapi_app = FastAPI()
_fastapi_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Socket.IO ASGI ke FastAPI via sub-aplikasi
app = socketio.ASGIApp(sio, other_asgi_app=_fastapi_app)

# Set alias untuk kemudahan registrasi route
_app = _fastapi_app

# ==============================================================================
# State klien
# ==============================================================================
connected_ws_clients: set = set()   # klien native WebSocket
main_loop = None


# ==============================================================================
# Lifecycle
# ==============================================================================

@_app.on_event("startup")
async def startup_event():
    global main_loop
    main_loop = asyncio.get_running_loop()


# ==============================================================================
# Socket.IO event handlers
# ==============================================================================

@sio.event
async def connect(sid, environ):
    logger.info(f"Socket.IO klien terhubung: {sid}")
    if ENABLE_METRICS and FASTAPI_WS_CONNECTIONS:
        FASTAPI_WS_CONNECTIONS.inc()
    if ENABLE_METRICS and FASTAPI_WS_ACTIVE:
        FASTAPI_WS_ACTIVE.set(
            await sio.get_participant_count('/') + len(connected_ws_clients)
        )


@sio.event
async def disconnect(sid):
    logger.info(f"Socket.IO klien terputus: {sid}")
    if ENABLE_METRICS and FASTAPI_WS_DISCONNECTIONS:
        FASTAPI_WS_DISCONNECTIONS.inc()


# ==============================================================================
# Native WebSocket endpoint (untuk ws_load_generator.py dan klien non-Socket.IO)
# ==============================================================================

@_app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Handler koneksi WebSocket native."""
    await websocket.accept()
    connected_ws_clients.add(websocket)

    if ENABLE_METRICS:
        if FASTAPI_WS_CONNECTIONS:
            FASTAPI_WS_CONNECTIONS.inc()
        if FASTAPI_WS_ACTIVE:
            FASTAPI_WS_ACTIVE.set(len(connected_ws_clients))

    try:
        while True:
            await websocket.receive_text()
    except Exception as e:
        logger.info(f"Klien WebSocket terputus: {e}")
    finally:
        connected_ws_clients.discard(websocket)
        if ENABLE_METRICS:
            if FASTAPI_WS_DISCONNECTIONS:
                FASTAPI_WS_DISCONNECTIONS.inc()
            if FASTAPI_WS_ACTIVE:
                FASTAPI_WS_ACTIVE.set(len(connected_ws_clients))


# ==============================================================================
# Siaran pesan
# ==============================================================================

async def broadcast_message(message: dict, event_name: str = "message") -> None:
    """
    Siarkan pesan ke semua klien Socket.IO DAN klien WebSocket native.

    Waktu penyelesaian diukur dengan time.perf_counter() (resolusi sub-milidetik).
    """
    broadcast_start = time.perf_counter()

    # --- Socket.IO (seismic_app / browser) ---
    await sio.emit(event_name, message)

    # --- Native WebSocket ---
    msg_str = json.dumps(message)
    to_remove = []
    for client in list(connected_ws_clients):
        try:
            await client.send_text(msg_str)
        except Exception as e:
            logger.warning(f"Kesalahan saat mengirim ke klien WS: {e}")
            to_remove.append(client)

    for client in to_remove:
        connected_ws_clients.discard(client)

    broadcast_duration = time.perf_counter() - broadcast_start

    if ENABLE_METRICS and FASTAPI_WS_BROADCAST_LATENCY:
        FASTAPI_WS_BROADCAST_LATENCY.observe(broadcast_duration)


# ==============================================================================
# Kafka consumer threads
# ==============================================================================

def consume_trace() -> None:
    """Thread Kafka consumer untuk trace_topic."""
    consumer = get_consumer(KAFKA_TOPIC_TRACE, 'fast-api-group', KAFKA_BROKERS)
    logger.info(f"Mulai mengonsumsi {KAFKA_TOPIC_TRACE}")

    for message in consumer:
        data = message.value
        data['api_time'] = int(time.time() * 1000)
        message_data = {'waves-data': data}

        try:
            future = asyncio.run_coroutine_threadsafe(
                broadcast_message(message_data, event_name='waves-data'),
                main_loop,
            )
            future.result(timeout=5)
        except Exception as e:
            logger.error(f"Kesalahan saat menyiarkan trace: {e}")

        if ENABLE_METRICS and FASTAPI_WS_BROADCAST:
            FASTAPI_WS_BROADCAST.labels(topic=KAFKA_TOPIC_TRACE).inc()


def consume_loc_mag() -> None:
    """Thread Kafka consumer untuk result_loc_mag_topic."""
    consumer = get_consumer(KAFKA_TOPIC_RESULT, 'fast-api-group2', KAFKA_BROKERS)
    logger.info(f"Mulai mengonsumsi {KAFKA_TOPIC_RESULT}")

    for message in consumer:
        data = message.value
        data['api_time'] = int(time.time() * 1000)
        message_data = {'loc-mag-data': data}

        logger.debug(
            f"Menyiarkan Loc-Mag: {data.get('predictions_loc_mag', 'N/A')}"
        )

        try:
            future = asyncio.run_coroutine_threadsafe(
                broadcast_message(message_data, event_name='loc-mag-data'),
                main_loop,
            )
            future.result(timeout=5)
        except Exception as e:
            logger.error(f"Kesalahan saat menyiarkan loc-mag: {e}")

        if ENABLE_METRICS and FASTAPI_WS_BROADCAST:
            FASTAPI_WS_BROADCAST.labels(topic=KAFKA_TOPIC_RESULT).inc()


# ==============================================================================
# HTTP endpoints
# ==============================================================================

@_app.get("/")
async def get():
    return FileResponse("public/index.html")


@_app.get("/metrics")
async def metrics():
    """Endpoint metrik Prometheus."""
    if ENABLE_METRICS:
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
    return Response(content="Metrics disabled", status_code=404)


@_app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


# ==============================================================================
# Utilitas
# ==============================================================================

def wait_for_kafka(brokers: list, max_retries: int = 30, retry_interval: int = 3) -> bool:
    """Tunggu hingga broker Kafka dapat dijangkau."""
    for attempt in range(1, max_retries + 1):
        if check_kafka_connection(brokers):
            logger.info("Broker Kafka tersedia.")
            return True
        logger.warning(
            f"Kafka belum siap (percobaan {attempt}/{max_retries}), "
            f"coba lagi dalam {retry_interval}s..."
        )
        time.sleep(retry_interval)
    logger.error("Broker Kafka tidak tersedia. Tetap melanjutkan...")
    return False


# ==============================================================================
# Entry point
# ==============================================================================

if __name__ == "__main__":
    logger.info("Memulai FastAPI WebSocket Server (dengan Socket.IO)")

    wait_for_kafka(KAFKA_BROKERS)

    consumer_thread = Thread(target=consume_trace, daemon=True)
    consumer_thread2 = Thread(target=consume_loc_mag, daemon=True)
    consumer_thread.start()
    consumer_thread2.start()

    # Jalankan via uvicorn dengan app ASGI yang sudah di-mount Socket.IO
    uvicorn.run(app, host="0.0.0.0", port=3333)
