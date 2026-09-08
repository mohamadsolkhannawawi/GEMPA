import time
import json
import random
from kafka import KafkaProducer

def simulate_earthquake(station="PB02", network="CX", magnitude=6.5, lat=-6.200, lon=106.816, depth=15.0):
    producer = KafkaProducer(
        bootstrap_servers=['localhost:9092', 'localhost:9093', 'localhost:9094'],
        value_serializer=lambda v: json.dumps(v).encode('utf-8')
    )
    
    now = time.time()
    
    # 1. Produce P-Wave Trace Event
    trace_payload = {
        "station": station,
        "network": network,
        "timestamp": now,
        "api_time": int(now * 1000),
        "data": [random.uniform(-1000, 1000) for _ in range(80)]
    }
    
    # 2. Produce Loc-Mag Prediction Event (Large Earthquake Event)
    locmag_payload = {
        "station": station,
        "channel": "HHZ",
        "predictions_loc_mag": [[lat, lon, depth, magnitude]],
        "data_provider_time": now - 0.05,
        "p_wave_detector_time": now - 0.02,
        "loc_mag_detector_time": now
    }
    
    print(f"Simulating Large Earthquake Trigger on Station {station}-{network}...")
    print(f"  -> Magnitude: M {magnitude}")
    print(f"  -> Location : Lat {lat}, Lon {lon}, Depth {depth} km")
    
    # Send to Kafka result topics
    producer.send('result_loc_mag_topic', locmag_payload)
    producer.send('trace_topic', trace_payload)
    producer.flush()
    producer.close()
    
    print("Simulated Earthquake Event Broadcasted Successfully to Dashboard!")

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description="Simulate Large Earthquake Event for Demo")
    parser.add_argument("--station", type=str, default="BKNI", help="Station code")
    parser.add_argument("--magnitude", type=float, default=6.5, help="Earthquake magnitude")
    parser.add_argument("--lat", type=float, default=-6.20, help="Latitude")
    parser.add_argument("--lon", type=float, default=106.81, help="Longitude")
    parser.add_argument("--depth", type=float, default=10.0, help="Depth in km")
    args = parser.parse_args()

    simulate_earthquake(
        station=args.station,
        magnitude=args.magnitude,
        lat=args.lat,
        lon=args.lon,
        depth=args.depth
    )
