"""
Data Archiver — Kafka Consumer → InfluxDB / MongoDB / MiniSEED
Consumes seismic trace data from trace_topic and archives to multiple storage backends.

Instrumented with Prometheus metrics: Counter, Histogram.
"""

import sys
import os
import json
import time
import threading
from datetime import datetime, timedelta
import io
from typing import Dict, Any

import numpy as np
from obspy import Trace, Stream, read
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS
from pymongo import MongoClient
from filelock import FileLock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from config.settings import (
    ENABLE_METRICS,
    METRICS_PORT_DATA_ARCHIVER,
    KAFKA_BROKERS,
    KAFKA_TOPIC_TRACE,
    INFLUXDB_URL,
    INFLUXDB_TOKEN,
    INFLUXDB_ORG,
    INFLUXDB_BUCKET_TRACE
)
from utils.kafka_helper import check_kafka_connection, topic_exists, get_consumer
from utils.logger import get_logger

logger = get_logger("DataArchiver")

# =============================================================================
# Prometheus Metrics
# =============================================================================
if ENABLE_METRICS:
    from prometheus_client import start_http_server, Counter, Histogram

    ARCHIVER_RECORDS_SAVED = Counter(
        'archiver_records_saved_total',
        'Total number of records saved successfully',
        ['storage']
    )
    ARCHIVER_SAVE_ERRORS = Counter(
        'archiver_save_errors_total',
        'Total number of save errors',
        ['storage']
    )
    ARCHIVER_WRITE_LATENCY = Histogram(
        'archiver_write_latency_seconds',
        'Latency of writing data to storage',
        ['storage'],
        buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0]
    )
else:
    ARCHIVER_RECORDS_SAVED = None
    ARCHIVER_SAVE_ERRORS = None
    ARCHIVER_WRITE_LATENCY = None

# =============================================================================
# Configuration from environment variables
# =============================================================================
mongo_url = os.getenv("MONGO_URL", "mongodb://mongo:27017/")

# Initialize MongoDB connection with retry
mongo_collection = None

def init_mongodb(max_retries=5, retry_delay=5):
    """Initialize MongoDB connection with retry logic."""
    global mongo_collection
    for attempt in range(1, max_retries + 1):
        try:
            mongo_client = MongoClient(mongo_url, serverSelectionTimeoutMS=5000)
            mongo_db = mongo_client['timeseries_db']
            # Force connection check
            mongo_client.server_info()
            if 'timeseries_collection' not in mongo_db.list_collection_names():
                mongo_db.create_collection(
                    'timeseries_collection',
                    timeseries={
                        'timeField': 'timestamp',
                        'metaField': 'metadata',
                        'granularity': 'seconds'
                    }
                )
            mongo_collection = mongo_db['timeseries_collection']
            logger.info(f"MongoDB initialized successfully on attempt {attempt}")
            return
        except Exception as e:
            logger.warning(f"MongoDB init attempt {attempt}/{max_retries} failed: {e}")
            if attempt < max_retries:
                time.sleep(retry_delay)
    logger.error("Failed to initialize MongoDB after all retries")

init_mongodb()

# Initialize InfluxDB client
influxdb_client = InfluxDBClient(url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG)
influxdb_write_api = influxdb_client.write_api(write_options=SYNCHRONOUS)


def save_data_to_influxdb(data: Dict[str, Any]) -> None:
    """Write trace data to InfluxDB with Prometheus latency tracking."""
    try:
        start_run_time = time.time()
        start_time = int(data['start_time'] * 1e9)
        increment = int(1 / data['sampling_rate'] * 1e9)
        points = []

        for i, value in enumerate(data['data']):
            point = (
                Point("wave")
                .tag("stat", data['station'])
                .field(data['channel'], value)
                .time(start_time + i * increment, WritePrecision.NS)
            )
            points.append(point)

        influxdb_write_api.write(bucket=INFLUXDB_BUCKET_TRACE, org=INFLUXDB_ORG, record=points)
        end_run_time = time.time()
        duration = end_run_time - start_run_time

        if ENABLE_METRICS and ARCHIVER_RECORDS_SAVED:
            ARCHIVER_RECORDS_SAVED.labels(storage='influxdb').inc()
        if ENABLE_METRICS and ARCHIVER_WRITE_LATENCY:
            ARCHIVER_WRITE_LATENCY.labels(storage='influxdb').observe(duration)

    except Exception as e:
        logger.error(f"Error saving data to InfluxDB: {e}")
        if ENABLE_METRICS and ARCHIVER_SAVE_ERRORS:
            ARCHIVER_SAVE_ERRORS.labels(storage='influxdb').inc()


def save_data_to_mongodb(data: Dict[str, Any]) -> None:
    """Write trace data to MongoDB with Prometheus latency tracking."""
    if mongo_collection is None:
        logger.warning("MongoDB collection not initialized, skipping save")
        return
    try:
        start_run_time = time.time()
        start_time_dt = datetime.utcfromtimestamp(data['start_time'])
        increment = timedelta(seconds=1 / data['sampling_rate'])
        documents = []

        for i, value in enumerate(data['data']):
            timestamp = start_time_dt + i * increment
            document = {
                "timestamp": timestamp,
                "metadata": {
                    "station": data['station'],
                    "channel": data['channel']
                },
                "value": value
            }
            documents.append(document)

        mongo_collection.insert_many(documents)
        end_run_time = time.time()
        duration = end_run_time - start_run_time

        if ENABLE_METRICS and ARCHIVER_RECORDS_SAVED:
            ARCHIVER_RECORDS_SAVED.labels(storage='mongodb').inc()
        if ENABLE_METRICS and ARCHIVER_WRITE_LATENCY:
            ARCHIVER_WRITE_LATENCY.labels(storage='mongodb').observe(duration)

        logger.debug(f"MongoDB Time: {duration} seconds")
    except Exception as e:
        logger.error(f"Error saving data to MongoDB: {e}")
        if ENABLE_METRICS and ARCHIVER_SAVE_ERRORS:
            ARCHIVER_SAVE_ERRORS.labels(storage='mongodb').inc()


def read_existing_mseed(filepath: str) -> Stream:
    reclen = 512
    with open(filepath, 'rb') as fh:
        data_blocks = []
        block = fh.read(reclen)
        while block:
            data_blocks.append(block)
            block = fh.read(reclen)
    data_io = io.BytesIO(b''.join(data_blocks))
    data_io.seek(0)
    return read(data_io, format='MSEED')


def merge_and_write_mseed(existing_traces: Stream, new_trace: Trace, filepath: str) -> None:
    """Gabungkan trace baru ke stream dan tulis ke berkas MiniSEED."""
    if existing_traces:
        for tr in list(existing_traces):
            existing_traces.remove(tr)
        existing_traces.append(new_trace)
    else:
        existing_traces.append(new_trace)
    existing_traces.sort(keys=['starttime'])
    existing_traces.write(filepath, format='MSEED')


def save_data_to_mseed(data: Dict[str, Any]) -> None:
    """Write trace data to MiniSEED files with Prometheus latency tracking."""
    start_run_time = time.time()
    today = datetime.utcnow().date()

    try:
        required_keys = ["network", "station", "channel", "data", "location", "start_time", "sampling_rate"]
        if not all(key in data for key in required_keys):
            logger.error("Missing one or more required keys in data")
            return

        path_save = f"/mnt/data/{today}/{data['network']}/{data['station']}/{data['channel']}"
        path_save_day = f"{path_save}/day_mseed"
        os.makedirs(path_save, exist_ok=True)
        os.makedirs(path_save_day, exist_ok=True)

        utc_year = str(today.year)
        utc_julian_day = today.strftime('%j')

        trace = Trace(data=np.array(data["data"], dtype=float))
        trace.stats.station = data["station"]
        trace.stats.network = data["network"]
        trace.stats.location = data["location"]
        trace.stats.channel = data["channel"]
        trace.stats.starttime = datetime.utcfromtimestamp(data["start_time"])
        trace.stats.sampling_rate = float(data["sampling_rate"])

        day_mseed_filename = f"{data['network']}.{data['station']}.{data['location']}.{data['channel']}.{utc_year}.{utc_julian_day}.mseed"
        day_mseed_filepath = os.path.join(path_save_day, day_mseed_filename)

        # --- Tulis berkas harian MiniSEED dengan penguncian berkas ---
        lock_day = FileLock(day_mseed_filepath + ".lock")
        with lock_day:
            if not os.path.isfile(day_mseed_filepath):
                Stream([trace]).write(day_mseed_filepath, format="MSEED")
            else:
                try:
                    st1 = read_existing_mseed(day_mseed_filepath)
                    merge_and_write_mseed(st1, trace, day_mseed_filepath)
                except (UserWarning, Exception) as e:
                    logger.error(f"Error while reading/writing daily MiniSEED file: {e}")

        date_str = trace.stats.starttime.strftime("%Y.%j")
        fmtstr = '/'.join(
            date_str.split('.')[:1] + [trace.id.split('.')[i] for i in [0, 1, 3]]) + ".D"
        directory = f"/mnt/data/{fmtstr}"
        os.makedirs(directory, exist_ok=True)

        filename1 = f"{directory}/{trace.id}.D.{date_str}.mseed"

        # --- Tulis berkas arsip MiniSEED dengan penguncian berkas ---
        lock_arch = FileLock(filename1 + ".lock")
        with lock_arch:
            if os.path.exists(filename1):
                try:
                    st2 = read_existing_mseed(filename1)
                    merge_and_write_mseed(st2, trace, filename1)
                except (UserWarning, Exception) as e:
                    logger.error(f"Error while reading/writing archival MiniSEED file: {e}")
            else:
                trace.write(filename1, format='MSEED')

        end_run_time = time.time()
        duration = end_run_time - start_run_time

        if ENABLE_METRICS and ARCHIVER_RECORDS_SAVED:
            ARCHIVER_RECORDS_SAVED.labels(storage='mseed').inc()
        if ENABLE_METRICS and ARCHIVER_WRITE_LATENCY:
            ARCHIVER_WRITE_LATENCY.labels(storage='mseed').observe(duration)

        logger.debug(f"MiniSEED Time: {duration} seconds")

    except Exception as e:
        logger.error(f"Unexpected error while processing data to MiniSEED: {e}")
        if ENABLE_METRICS and ARCHIVER_SAVE_ERRORS:
            ARCHIVER_SAVE_ERRORS.labels(storage='mseed').inc()


def initialize_system() -> None:
    while True:
        if check_kafka_connection(KAFKA_BROKERS) and topic_exists(KAFKA_TOPIC_TRACE, KAFKA_BROKERS):
            logger.info("System initialization successful.")
            break
        time.sleep(3)


def consume_and_save_data() -> None:
    """Main consumer loop: save incoming trace data to InfluxDB (with threading)."""
    consumer = get_consumer(KAFKA_TOPIC_TRACE, 'data_archiver_group', KAFKA_BROKERS)

    try:
        logger.info(f"Consuming from topic: {KAFKA_TOPIC_TRACE}")
        for msg in consumer:
            data = msg.value

            start_time = time.time()
            threading.Thread(target=save_data_to_influxdb, args=(data,)).start()
            
            # Jika opsi pengarsipan MongoDB diaktifkan (default: True)
            if os.getenv("ENABLE_MONGO_ARCHIVE", "true").lower() in ("true", "1", "yes"):
                threading.Thread(target=save_data_to_mongodb, args=(data,)).start()

            logger.debug(
                f"Delay: {time.time() - data['data_provider_time']:.4f}s | "
                f"Processing Time: {time.time() - start_time:.4f}s"
            )

    except KeyboardInterrupt:
        logger.info("Shutting down gracefully...")
    finally:
        logger.info("Waiting for all threads to complete...")
        consumer.close()


if __name__ == "__main__":
    if ENABLE_METRICS:
        try:
            start_http_server(METRICS_PORT_DATA_ARCHIVER)
            logger.info(f"Prometheus metrics server started on port {METRICS_PORT_DATA_ARCHIVER}")
        except Exception as e:
            logger.error(f"Failed to start metrics server: {e}")

    initialize_system()
    consume_and_save_data()
