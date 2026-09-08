import time
import json
import argparse
import random
from kafka import KafkaProducer

def simulate_earthquake_kafka(station="BKNI", magnitude=6.8, depth=12.5, lat=-6.20, lon=106.81, bootstrap_servers=['localhost:9092', 'localhost:9093', 'localhost:9094']):
    """
    Mengirimkan event simulasi gempa bumi magnitudo besar ke Kafka Topic (result_loc_mag_topic dan trace_topic)
    sehingga backend API (Express / FastAPI) akan menyiarkan event ini ke Web UI via WebSocket,
    dan memicu Modal Pop-Up Peringatan Gempa Darurat.
    """
    print(f"Mengirim simulasi trigger gempa untuk stasiun {station}...")
    print(f"  -> Magnitudo : M {magnitude}")
    print(f"  -> Lokasi    : Lat {lat}, Lon {lon}, Depth {depth} km")

    try:
        producer = KafkaProducer(
            bootstrap_servers=bootstrap_servers,
            value_serializer=lambda v: json.dumps(v).encode('utf-8')
        )
    except Exception as e:
        print(f"Gagal menghubungkan KafkaProducer ke {bootstrap_servers}: {e}")
        print("Mencoba fallback bootstrap servers ke container network ('kafka1:9092', 'kafka2:9093', 'kafka3:9094')...")
        try:
            producer = KafkaProducer(
                bootstrap_servers=['kafka1:9092', 'kafka2:9093', 'kafka3:9094'],
                value_serializer=lambda v: json.dumps(v).encode('utf-8')
            )
        except Exception as ex:
            print(f"Koneksi ke Kafka gagal total: {ex}")
            return

    t = time.time()
    
    # 1. Kirim Trace Data Stream ke trace_topic
    trace_payload = {
        'station': station,
        'network': 'IA',
        'timestamp': t,
        'api_time': int(t * 1000),
        'data': [random.uniform(-1500, 1500) for _ in range(80)]
    }
    producer.send('trace_topic', trace_payload)

    # 2. Kirim Prediksi Magnitudo & Lokasi Gempa ke result_loc_mag_topic
    loc_mag_payload = {
        'station': station,
        'channel': 'HHZ',
        'predictions_loc_mag': [[lat, lon, depth, magnitude]],
        'data_provider_time': t - 0.05,
        'p_wave_detector_time': t - 0.02,
        'loc_mag_detector_time': t
    }
    producer.send('result_loc_mag_topic', loc_mag_payload)
    
    producer.flush()
    producer.close()
    
    print(f"=== SIMULASI GEMPA M {magnitude} BERHASIL DI-BROADCAST KE KAFKA TOPIC ===")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Simulasi Pemicu Peringatan Gempa Bumi untuk EEWS / GEMPA")
    parser.add_argument('--station', type=str, default='BKNI', help='Kode stasiun (default: BKNI)')
    parser.add_argument('--magnitude', type=float, default=6.8, help='Magnitudo gempa (default: 6.8)')
    parser.add_argument('--depth', type=float, default=12.5, help='Kedalaman gempa dalam km (default: 12.5)')
    parser.add_argument('--lat', type=float, default=-6.20, help='Garis lintang episenter (default: -6.20)')
    parser.add_argument('--lon', type=float, default=106.81, help='Garis bujur episenter (default: 106.81)')
    
    args = parser.parse_args()
    
    simulate_earthquake_kafka(
        station=args.station,
        magnitude=args.magnitude,
        depth=args.depth,
        lat=args.lat,
        lon=args.lon
    )
