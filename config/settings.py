import os
from distutils.util import strtobool

# ==============================================================================
# Feature Flags
# ==============================================================================
ENABLE_METRICS = bool(strtobool(os.getenv("ENABLE_METRICS", "true")))

# ==============================================================================
# Kafka Configuration
# ==============================================================================
KAFKA_BROKERS = os.getenv("KAFKA_BROKERS", "kafka1:9092,kafka2:9093").split(",")
KAFKA_BROKERS_PWAVE = os.getenv("KAFKA_BROKERS_PWAVE", "kafka3:9094").split(",")

KAFKA_TOPIC_TRACE = os.getenv("KAFKA_TOPIC_TRACE", "trace_topic")
KAFKA_TOPIC_PWAVE = os.getenv("KAFKA_TOPIC_PWAVE", "p_wave_topic")
KAFKA_TOPIC_LOCMAG = os.getenv("KAFKA_TOPIC_LOCMAG", "loc_mag_topic")
KAFKA_TOPIC_RESULT = os.getenv("KAFKA_TOPIC_RESULT", "result_loc_mag_topic")

# ==============================================================================
# Metrics Ports
# ==============================================================================
METRICS_PORT_DATA_PROVIDER = int(os.getenv("METRICS_PORT_DATA_PROVIDER", "8101"))
METRICS_PORT_PWAVE_DETECTOR = int(os.getenv("METRICS_PORT_PWAVE_DETECTOR", "8102"))
METRICS_PORT_LOAD_BALANCER = int(os.getenv("METRICS_PORT_LOAD_BALANCER", "8103"))
METRICS_PORT_PWAVE_LB = int(os.getenv("METRICS_PORT_PWAVE_LB", "8104"))
METRICS_PORT_LOCMAG = int(os.getenv("METRICS_PORT_LOCMAG", "8105"))
METRICS_PORT_DATA_ARCHIVER = int(os.getenv("METRICS_PORT_DATA_ARCHIVER", "8106"))
METRICS_PORT_FASTAPI = int(os.getenv("METRICS_PORT_FASTAPI", "8108"))

# ==============================================================================
# InfluxDB Configuration
# ==============================================================================
INFLUXDB_URL = os.getenv("INFLUXDB_URL", "http://influxdb:8086")
INFLUXDB_TOKEN = os.getenv("INFLUXDB_TOKEN")
INFLUXDB_ORG = os.getenv("INFLUXDB_ORG", "owner")
INFLUXDB_BUCKET_TRACE = os.getenv("INFLUXDB_BUCKET_TRACE", os.getenv("INFLUXDB_BUCKET", "gempa"))
INFLUXDB_BUCKET_RESULT = os.getenv("INFLUXDB_BUCKET_RESULT", os.getenv("INFLUXDB_BUCKET", "gempa"))
