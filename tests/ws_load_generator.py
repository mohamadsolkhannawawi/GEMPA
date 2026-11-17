import asyncio
import websockets
import argparse
import time

async def connect_client(uri, client_id, duration):
    try:
        async with websockets.connect(uri) as websocket:
            print(f"Client {client_id} connected to {uri}")
            
            # Handle Socket.IO 4.x protocol handshake if connecting to Express.js Socket.IO server
            if "socket.io" in uri:
                # 1. Server sends Engine.IO Open Packet '0{"sid":...}'
                init_msg = await websocket.recv()
                if init_msg.startswith("0"):
                    # 2. Client sends Socket.IO Connect Packet '40'
                    await websocket.send("40")
                    # 3. Server responds with Socket.IO Connect Ack '40{"sid":...}'
                    await websocket.recv()
            
            start_time = time.time()
            while time.time() - start_time < duration:
                try:
                    msg = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                    # Engine.IO Heartbeat: Respond to Ping '2' with Pong '3'
                    if "socket.io" in uri and msg == "2":
                        await websocket.send("3")
                except asyncio.TimeoutError:
                    pass
            print(f"Client {client_id} disconnecting.")
    except Exception as e:
        print(f"Client {client_id} error: {e}")

async def main(uri: str, clients: int, duration: int) -> None:
    print(f"Starting {clients} websocket clients to {uri} for {duration}s")
    
    tasks = []
    for i in range(clients):
        tasks.append(asyncio.create_task(connect_client(uri, i+1, duration)))
        # Stagger connections slightly
        await asyncio.sleep(0.1) 
        
    await asyncio.gather(*tasks)
    print("All clients finished.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--uri', type=str, required=True, help="WebSocket URI, e.g., ws://localhost:3334/ws")
    parser.add_argument('--clients', type=int, required=True, help="Number of concurrent clients")
    parser.add_argument('--duration', type=int, default=120, help="Duration in seconds to hold connections")
    args = parser.parse_args()

    asyncio.run(main(args.uri, args.clients, args.duration))
