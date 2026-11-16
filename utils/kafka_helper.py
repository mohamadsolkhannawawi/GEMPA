"""
kafka_helper.py — Abstraksi Kafka yang dipakai semua modul EEWS.

Menyediakan fungsi pemeriksaan koneksi, pengelolaan topik, serta factory
producer/consumer dengan parameter yang dapat dikonfigurasi lewat .env.
"""

import json
import os
import socket
from time import sleep
from typing import Optional

from kafka import KafkaConsumer, KafkaProducer
from kafka.admin import KafkaAdminClient, NewTopic
from kafka.errors import KafkaError

from utils.logger import get_logger

logger = get_logger("KafkaHelper")


# ==============================================================================
# Koneksi & pemeriksaan topik
# ==============================================================================

def check_kafka_connection(bootstrap_servers: list[str]) -> bool:
    """
    Periksa apakah setidaknya satu Kafka broker dapat dijangkau via TCP.

    Mengembalikan True segera setelah satu broker berhasil dihubungi.
    """
    if not isinstance(bootstrap_servers, list):
        bootstrap_servers = [bootstrap_servers]

    logger.info(f"Memeriksa koneksi Kafka ke: {bootstrap_servers}")
    for server in bootstrap_servers:
        host, port = server.rsplit(":", 1)
        sock: Optional[socket.socket] = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex((host, int(port)))
            if result == 0:
                logger.info(f"Berhasil terhubung ke broker Kafka di {server}")
                return True
        except Exception as e:
            logger.debug(f"Gagal terhubung ke {server}: {e}")
        finally:
            if sock is not None:
                sock.close()

    logger.warning("Tidak ada broker Kafka yang dapat dijangkau.")
    return False


def topic_exists(topic_name: str, bootstrap_servers: list[str]) -> bool:
    """
    Periksa apakah sebuah topik Kafka sudah ada.

    Menggunakan satu KafkaAdminClient yang selalu ditutup di blok finally.
    """
    admin_client: Optional[KafkaAdminClient] = None
    try:
        admin_client = KafkaAdminClient(bootstrap_servers=bootstrap_servers)
        exists = topic_name in admin_client.list_topics()
        logger.debug(f"Topik '{topic_name}' ada: {exists}")
        return exists
    except Exception as e:
        logger.error(f"Kesalahan saat memeriksa topik '{topic_name}': {e}")
        return False
    finally:
        if admin_client is not None:
            try:
                admin_client.close()
            except Exception:
                pass


def create_topic_if_not_exists(
    topic_name: str,
    num_partitions: int,
    replication_factor: int,
    bootstrap_servers: list[str],
) -> None:
    """
    Buat topik Kafka jika belum ada. Memblokir hingga berhasil.

    Menggunakan satu KafkaAdminClient per upaya pembuatan dan menutupnya
    di blok finally untuk mencegah kebocoran koneksi.
    """
    while not check_kafka_connection(bootstrap_servers):
        sleep(3)

    while not topic_exists(topic_name, bootstrap_servers):
        admin_client: Optional[KafkaAdminClient] = None
        try:
            admin_client = KafkaAdminClient(bootstrap_servers=bootstrap_servers)
            new_topic = NewTopic(
                name=topic_name,
                num_partitions=num_partitions,
                replication_factor=replication_factor,
            )
            logger.info(f"Membuat topik '{topic_name}'...")
            admin_client.create_topics(new_topics=[new_topic])
            logger.info(f"Topik '{topic_name}' berhasil dibuat.")
            break
        except Exception as e:
            if "TopicAlreadyExistsError" in str(e) or "already exists" in str(e):
                logger.info(f"Topik '{topic_name}' sudah ada, lewati pembuatan.")
                break
            logger.error(f"Kesalahan saat membuat topik '{topic_name}': {e}")
            sleep(3)
        finally:
            if admin_client is not None:
                try:
                    admin_client.close()
                except Exception:
                    pass


# ==============================================================================
# Factory Producer
# ==============================================================================

def get_producer(bootstrap_servers: list[str]) -> KafkaProducer:
    """
    Kembalikan KafkaProducer yang dikonfigurasi.

    Parameter `acks` dan `linger_ms` dapat diatur lewat env.
    Nilai bawaan mempertahankan perilaku sebelumnya (acks=1, linger_ms=0).
    """
    acks = os.getenv("KAFKA_PRODUCER_ACKS", "1")
    # Konversi "all" tetap string; integer dikonversi
    if acks not in ("all",):
        try:
            acks = int(acks)  # type: ignore[assignment]
        except ValueError:
            acks = 1

    linger_ms: int = int(os.getenv("KAFKA_PRODUCER_LINGER_MS", "0"))

    return KafkaProducer(
        bootstrap_servers=bootstrap_servers,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        key_serializer=lambda v: json.dumps(v).encode("utf-8") if v else None,
        acks=acks,
        linger_ms=linger_ms,
    )


# ==============================================================================
# Factory Consumer
# ==============================================================================

def get_consumer(
    topic: str,
    group_id: str,
    bootstrap_servers: list[str],
) -> KafkaConsumer:
    """
    Kembalikan KafkaConsumer yang dikonfigurasi.

    Semua parameter penting dapat diatur lewat env; nilai bawaan mempertahankan
    perilaku sebelumnya.
    """
    auto_offset_reset: str = os.getenv("KAFKA_AUTO_OFFSET_RESET", "earliest")
    enable_auto_commit: bool = os.getenv(
        "KAFKA_ENABLE_AUTO_COMMIT", "true"
    ).lower() in ("1", "true", "yes", "on")
    max_poll_records: int = int(os.getenv("KAFKA_MAX_POLL_RECORDS", "500"))
    session_timeout_ms: int = int(os.getenv("KAFKA_SESSION_TIMEOUT_MS", "10000"))
    heartbeat_interval_ms: int = int(os.getenv("KAFKA_HEARTBEAT_INTERVAL_MS", "3000"))
    max_poll_interval_ms: int = int(os.getenv("KAFKA_MAX_POLL_INTERVAL_MS", "300000"))

    return KafkaConsumer(
        topic,
        group_id=group_id,
        bootstrap_servers=bootstrap_servers,
        value_deserializer=lambda x: json.loads(x.decode("utf-8")),
        key_deserializer=lambda x: json.loads(x.decode("utf-8")) if x else None,
        auto_offset_reset=auto_offset_reset,
        enable_auto_commit=enable_auto_commit,
        max_poll_records=max_poll_records,
        session_timeout_ms=session_timeout_ms,
        heartbeat_interval_ms=heartbeat_interval_ms,
        max_poll_interval_ms=max_poll_interval_ms,
    )
