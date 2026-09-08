import time
import json
import random
import sys

def simulate_earthquake_kafka(station, network, magnitude, lat, lon, depth):
    try:
        from kafka import KafkaProducer
    except ImportError:
        print("Error: Library 'kafka-python' belum terpasang.")
        print("Silakan jalankan perintah berikut untuk memasangnya:")
        print("    pip install kafka-python")
        print("\nMencoba fallback via WebSocket...")
        return False

    try:
        producer = KafkaProducer(
            bootstrap_servers=['localhost:9092', 'localhost:9093', 'localhost:9094'],
            value_serializer=lambda v: json.dumps(v).encode('utf-8')
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
        
        print(f"Simulating Large Earthquake Trigger via Kafka on Station {station}-{network}...")
        print(f"  -> Magnitude: M {magnitude}")
        print(f"  -> Location : Lat {lat}, Lon {lon}, Depth {depth} km")
        
        producer.send('result_loc_mag_topic', locmag_payload)
        producer.send('trace_topic', trace_payload)
        producer.flush()
        producer.close()
        
        print("Simulated Earthquake Event Broadcasted Successfully to Dashboard!")
        return True
    except Exception as e:
        print(f"Failed to produce to Kafka: {e}")
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
