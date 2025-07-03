import socket
import argparse
import threading
import queue
import time

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

def sensor_listener(port, q, stop_event):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('127.0.0.1', port))
    sock.settimeout(0.2)
    while not stop_event.is_set():
        try:
            data, _ = sock.recvfrom(1024)
            msg = parse_sensor_msg(data)
            if msg:
                q.put((port, msg))
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
    parser = argparse.ArgumentParser(description="Sensor Fusion App: Fuses positions from multiple sensors.")
    parser.add_argument('--sensor_ports', type=int, nargs='+', required=True, help='UDP ports to listen to sensors')
    parser.add_argument('--interval', type=float, default=0.1, help='Fusion interval (default: 0.1s)')
    args = parser.parse_args()

    q = queue.Queue()
    stop_event = threading.Event()
    threads = []
    for port in args.sensor_ports:
        t = threading.Thread(target=sensor_listener, args=(port, q, stop_event), daemon=True)
        t.start()
        threads.append(t)

    print(f"Listening to sensors on ports: {args.sensor_ports}")
    last_data = {}  # port -> latest msg
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
