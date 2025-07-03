import socket
import struct
import argparse
import threading
import queue
import time
from multicast_config import SENSOR_MCAST_GRP, SENSOR_MCAST_PORT

def parse_sensor_msg(msg):
    # Format: name,x,y,t,noise_std
    parts = msg.decode().strip().split(',')
    if len(parts) != 5:
        return None
    return {
        'name': parts[0],
        'x': float(parts[1]),
        'y': float(parts[2]),
        't': float(parts[3]),
        'noise_std': float(parts[4]),
    }

def sensor_multicast_listener(q, stop_event):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('', SENSOR_MCAST_PORT))
    mreq = struct.pack('4sl', socket.inet_aton(SENSOR_MCAST_GRP), socket.INADDR_ANY)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    sock.settimeout(0.2)
    while not stop_event.is_set():
        try:
            data, _ = sock.recvfrom(1024)
            try:
                text = data.decode()
                parts = text.strip().split(',')
                if len(parts) < 6 or parts[0] != 'sensor':
                    continue
                # Parse sensor message: sensor,name,x,y,t,noise_std
                msg = {
                    'name': parts[1],
                    'x': float(parts[2]),
                    'y': float(parts[3]),
                    't': float(parts[4]),
                    'noise_std': float(parts[5])
                }
                q.put((parts[1], msg))
            except Exception:
                continue
        except socket.timeout:
            continue
    sock.close()

def fuse_positions(sensor_data):
    # Weighted average by 1/(noise_std^2)
    weighted_sum_x = 0.0
    weighted_sum_y = 0.0
    weight_total = 0.0
    for d in sensor_data:
        w = 1.0 / (d['noise_std'] ** 2) if d['noise_std'] > 0 else 1.0
        weighted_sum_x += d['x'] * w
        weighted_sum_y += d['y'] * w
        weight_total += w
    if weight_total == 0:
        return None
    return (weighted_sum_x / weight_total, weighted_sum_y / weight_total)

def main():
    parser = argparse.ArgumentParser(description="Sensor Fusion App: Fuses positions from multiple sensors (UDP multicast).")
    parser.add_argument('--interval', type=float, default=0.1, help='Fusion interval (default: 0.1s)')
    args = parser.parse_args()

    q = queue.Queue()
    stop_event = threading.Event()
    t = threading.Thread(target=sensor_multicast_listener, args=(q, stop_event), daemon=True)
    t.start()
    threads = [t]

    print(f"Listening for sensor messages on multicast group {SENSOR_MCAST_GRP}:{SENSOR_MCAST_PORT}")
    last_data = {}  # sensor name -> latest msg
    try:
        while True:
            start = time.time()
            # Gather all new data
            while not q.empty():
                port, msg = q.get()
                last_data[port] = msg
            if last_data:
                fused = fuse_positions(list(last_data.values()))
                if fused:
                    print(f"FUSED POSITION: x={fused[0]:.3f}, y={fused[1]:.3f} from {len(last_data)} sensors")
            elapsed = time.time() - start
            time.sleep(max(0, args.interval - elapsed))
    except KeyboardInterrupt:
        print("Fusion app stopped.")
    finally:
        stop_event.set()
        for t in threads:
            t.join()

if __name__ == "__main__":
    main()
