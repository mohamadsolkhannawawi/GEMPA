"""
collect_kafka_offsets.py — Mengukur throughput Kafka dari selisih end-offset.

Digunakan pada Skenario S2 kondisi "tanpa metrik Prometheus" (NoMetricsCLI dan
NoMetricsAPI) sebagai alat ukur throughput yang seragam di semua kondisi.

Prinsip kerja: ambil end-offset tiap partisi topik pada awal dan akhir interval,
lalu hitung (offset_akhir - offset_awal) / interval_detik = pesan/detik.

Tidak memerlukan Prometheus — hanya membutuhkan akses TCP ke broker Kafka.
"""

from __future__ import annotations

import argparse
import csv
import os
import time
from typing import Dict, List

from kafka import KafkaConsumer
from kafka.structs import TopicPartition

DEFAULT_BROKERS = os.getenv("KAFKA_BROKERS_ALL", "localhost:9092,localhost:9093,localhost:9094")
DEFAULT_TOPICS = ["trace_topic", "p_wave_topic"]
POLL_INTERVAL = 5  # detik antar pengambilan sampel


def _get_end_offsets(consumer: KafkaConsumer, topic: str) -> Dict[int, int]:
    """Ambil end-offset semua partisi topik menggunakan consumer yang sudah ada."""
    partitions = consumer.partitions_for_topic(topic)
    if not partitions:
        return {}
    tps = [TopicPartition(topic, p) for p in partitions]
    offsets = consumer.end_offsets(tps)
    return {tp.partition: v for tp, v in offsets.items()}


def _sum_offsets(offsets: Dict[int, int]) -> int:
    return sum(offsets.values())


def collect_kafka_offsets(
    duration_sec: int,
    output_file: str,
    brokers: List[str],
    topics: List[str],
) -> None:
    print(
        f"Mulai pengukuran throughput Kafka selama {duration_sec}s "
        f"(interval: {POLL_INTERVAL}s)\n"
        f"Topik: {topics} | Broker: {brokers}\n"
        f"Output: {output_file}"
    )

    output_dir = os.path.dirname(output_file)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    # Header: timestamp + rate per topik
    headers = ["timestamp"] + [f"{t}_messages_per_sec" for t in topics]

    # Buat satu consumer untuk seluruh durasi pengukuran
    consumer = KafkaConsumer(bootstrap_servers=brokers)
    try:
        # Ambil snapshot pertama
        prev_offsets = {t: _sum_offsets(_get_end_offsets(consumer, t)) for t in topics}
        prev_time = time.time()

        start_time = time.time()

        with open(output_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(headers)

            while time.time() - start_time < duration_sec:
                time.sleep(POLL_INTERVAL)

                now = time.time()
                elapsed = now - prev_time
                current_offsets = {
                    t: _sum_offsets(_get_end_offsets(consumer, t)) for t in topics
                }

                ts = time.strftime("%Y-%m-%d %H:%M:%S")
                row = [ts]
                for t in topics:
                    delta = current_offsets[t] - prev_offsets[t]
                    rate = round(delta / elapsed, 4) if elapsed > 0 else 0.0
                    row.append(rate)

                writer.writerow(row)
                f.flush()
                print(f"[{ts}] {dict(zip(topics, row[1:]))}")

                prev_offsets = current_offsets
                prev_time = now
    finally:
        consumer.close()

    print(f"Selesai. Data disimpan ke {output_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Ukur throughput Kafka dari selisih end-offset (tanpa Prometheus)"
    )
    parser.add_argument(
        "--duration", type=int, default=300,
        help="Durasi pengukuran dalam detik (default 300)"
    )
    parser.add_argument(
        "--output", type=str, default="results/kafka_offsets.csv",
        help="Jalur berkas CSV keluaran"
    )
    parser.add_argument(
        "--brokers", type=str, default=DEFAULT_BROKERS,
        help="Daftar broker Kafka dipisah koma"
    )
    parser.add_argument(
        "--topics", type=str, default=",".join(DEFAULT_TOPICS),
        help="Daftar topik dipisah koma"
    )
    args = parser.parse_args()

    collect_kafka_offsets(
        duration_sec=args.duration,
        output_file=args.output,
        brokers=args.brokers.split(","),
        topics=args.topics.split(","),
    )
