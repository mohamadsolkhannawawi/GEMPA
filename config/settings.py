"""
settings.py — Konfigurasi terpusat untuk seluruh modul EEWS.

Semua nilai dibaca dari variabel lingkungan (env). Docker Compose meneruskan
nilai dari .env ke tiap container. Modul lain mengimpor konstanta dari sini.
"""

import os


# ==============================================================================
# Fungsi bantu (menggantikan distutils.util.strtobool yang dihapus Python 3.12)
# ==============================================================================

def _strtobool(val: str) -> bool:
    """
    Konversi string ke bool.
    Nilai benar : '1', 'yes', 'true', 'on'
    Nilai salah : '0', 'no', 'false', 'off'
    Angkat ValueError bila tidak dikenali.
    """
    val = val.strip().lower()
    if val in ('1', 'yes', 'true', 'on'):
        return True
    if val in ('0', 'no', 'false', 'off'):
        return False
    raise ValueError(f"Nilai boolean tidak dikenali: {val!r}")


# ==============================================================================
# Feature Flags
# ==============================================================================
ENABLE_METRICS: bool = _strtobool(os.getenv("ENABLE_METRICS", "true"))

# ==============================================================================
# Kafka Configuration
# ==============================================================================
KAFKA_BROKERS: list[str] = os.getenv("KAFKA_BROKERS", "kafka1:9092,kafka2:9093").split(",")
KAFKA_BROKERS_PWAVE: list[str] = os.getenv("KAFKA_BROKERS_PWAVE", "kafka3:9094").split(",")

KAFKA_TOPIC_TRACE: str = os.getenv("KAFKA_TOPIC_TRACE", "trace_topic")
KAFKA_TOPIC_PWAVE: str = os.getenv("KAFKA_TOPIC_PWAVE", "p_wave_topic")
KAFKA_TOPIC_LOCMAG: str = os.getenv("KAFKA_TOPIC_LOCMAG", "loc_mag_topic")
KAFKA_TOPIC_RESULT: str = os.getenv("KAFKA_TOPIC_RESULT", "result_loc_mag_topic")

# ==============================================================================
# Metrics Ports
# ==============================================================================
METRICS_PORT_DATA_PROVIDER: int = int(os.getenv("METRICS_PORT_DATA_PROVIDER", "8101"))
METRICS_PORT_PWAVE_DETECTOR: int = int(os.getenv("METRICS_PORT_PWAVE_DETECTOR", "8102"))
METRICS_PORT_LOAD_BALANCER: int = int(os.getenv("METRICS_PORT_LOAD_BALANCER", "8103"))
# Sinkronisasi: .env menggunakan METRICS_PORT_PWAVE_DETECTOR_LB
METRICS_PORT_PWAVE_LB: int = int(os.getenv("METRICS_PORT_PWAVE_DETECTOR_LB", "8104"))
METRICS_PORT_LOCMAG: int = int(os.getenv("METRICS_PORT_LOCMAG_DETECTOR", "8105"))
METRICS_PORT_DATA_ARCHIVER: int = int(os.getenv("METRICS_PORT_DATA_ARCHIVER", "8106"))
METRICS_PORT_FASTAPI: int = int(os.getenv("METRICS_PORT_FAST_API", "8108"))

# ==============================================================================
# InfluxDB Configuration
# ==============================================================================
INFLUXDB_URL: str = os.getenv("INFLUXDB_URL", "http://influxdb:8086")

_raw_token = os.getenv("INFLUXDB_TOKEN")
if not _raw_token:
    raise EnvironmentError(
        "INFLUXDB_TOKEN tidak diatur di environment. "
        "Tambahkan INFLUXDB_TOKEN ke file .env sebelum menjalankan sistem."
    )
INFLUXDB_TOKEN: str = _raw_token

INFLUXDB_ORG: str = os.getenv("INFLUXDB_ORG", "owner")
INFLUXDB_BUCKET_TRACE: str = os.getenv(
    "INFLUXDB_BUCKET_TRACE", os.getenv("INFLUXDB_BUCKET", "gempa")
)
INFLUXDB_BUCKET_RESULT: str = os.getenv(
    "INFLUXDB_BUCKET_RESULT", os.getenv("INFLUXDB_BUCKET", "gempa")
)

# ==============================================================================
# SeedLink & Data Provider
# ==============================================================================
SEEDLINK_SERVER: str = os.getenv("SEEDLINK_SERVER", "geofon.gfz-potsdam.de:18000")
STALE_SECONDS: float = float(os.getenv("STALE_SECONDS", "60"))

# ==============================================================================
# P-Wave Detector — Parameter Deteksi
# ==============================================================================
# Nilai-nilai ini dibaca juga oleh utils/pwave_common.py lewat os.getenv langsung,
# tetapi didefinisikan di sini sebagai dokumentasi resmi variabel lingkungan.
PWAVE_THRESHOLD: float = float(os.getenv("PWAVE_THRESHOLD", "0.9"))
PWAVE_CONSEC: int = int(os.getenv("PWAVE_CONSEC", "20"))

# ==============================================================================
# Load Balancer
# ==============================================================================
# Tidak ada nilai bawaan — bila tidak diatur, load_balancer/main.py akan berhenti.
LB_TARGET_URL: str | None = os.getenv("LB_TARGET_URL")
