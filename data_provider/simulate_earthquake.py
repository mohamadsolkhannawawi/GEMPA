import time
import json
import random
import sys
import os
from kafka import KafkaProducer

def simulate_earthquake_kafka(station, network, magnitude, lat, lon, depth):
    brokers = ['kafka1:9092', 'kafka2:9093', 'kafka3:9094']
    try:
        producer = KafkaProducer(
            bootstrap_servers=brokers,
            value_serializer=lambda v: json.dumps(v).encode('utf-8'),
            request_timeout_ms=5000
        )
        
        now = time.time()
        
        trace_payload = {
            "station": station,
            "network": network,
            "timestamp": now,
            "api_time": int(now * 1000),
            "data": [random.uniform(-1000, 1000) for _ in range(80)]
        }
        
        locmag_payload = {
            "station": station,
            "channel": "HHZ",
            "predictions_loc_mag": [[lat, lon, depth, magnitude]],
            "data_provider_time": now - 0.05,
            "p_wave_detector_time": now - 0.02,
            "loc_mag_detector_time": now
        }
        
        print(f"=== SIMULASI GEMPA M {magnitude} ===")
        print(f"Stasiun  : {station}-{network}")
        print(f"Lokasi   : Lat {lat}, Lon {lon}, Kedalaman {depth} km")
        
        producer.send('result_loc_mag_topic', locmag_payload)
        producer.send('trace_topic', trace_payload)
        producer.flush()
        producer.close()
        
        print(">>> SUKSES: Data gempa berhasil di-broadcast ke Dashboard WebSocket! <<<")
        return True
    except Exception as e:
        print(f"Gagal mengirim ke Kafka: {e}")
        return False

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description="Simulate Large Earthquake Event for Demo")
    parser.add_argument("--station", type=str, default="BKNI", help="Station code")
    parser.add_argument("--network", type=str, default="IA", help="Network code")
    parser.add_argument("--magnitude", type=float, default=6.8, help="Earthquake magnitude")
    parser.add_argument("--lat", type=float, default=-6.20, help="Latitude")
    parser.add_argument("--lon", type=float, default=106.81, help="Longitude")
    parser.add_argument("--depth", type=float, default=12.5, help="Depth in km")
    args = parser.parse_args()

    simulate_earthquake_kafka(
        station=args.station,
        network=args.network,
        magnitude=args.magnitude,
        lat=args.lat,
        lon=args.lon,
        depth=args.depth
    )
