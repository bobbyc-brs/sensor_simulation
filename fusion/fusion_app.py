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
                noise_raw = parts[5]
                try:
                    noise_std = float(noise_raw)
                except ValueError:
                    noise_std = {'ADAS': 200.0, 'TACAN': 150.0}.get(noise_raw, 100.0)
                vehicle = parts[6] if len(parts) >= 7 else ''
                msg = {
                    'name': parts[1],
                    'x': float(parts[2]),
                    'y': float(parts[3]),
                    't': float(parts[4]),
                    'noise_std': noise_std,
                    'vehicle': vehicle,
                }
                q.put((parts[1], msg))
            except Exception:
                continue
        except socket.timeout:
            continue
    sock.close()

def fuse_positions(sensor_data):
    """Weighted average by 1/(noise_std^2). x/y are lon/lat."""
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


def fuse_positions_by_vehicle(sensor_data):
    """
    Fuse readings per target aircraft. Returns {vehicle: (lon, lat)}.
    Skips messages without a vehicle id (legacy single-target format).
    """
    by_vehicle = {}
    for d in sensor_data:
        vehicle = d.get('vehicle') or ''
        if not vehicle:
            continue
        by_vehicle.setdefault(vehicle, []).append(d)
    fused = {}
    for vehicle, readings in by_vehicle.items():
        pos = fuse_positions(readings)
        if pos:
            fused[vehicle] = pos
    return fused

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
    # vehicle -> sensor_name -> latest msg
    sensor_latest = {}
    try:
        while True:
            start = time.time()
            while not q.empty():
                _port, msg = q.get()
                vehicle = msg.get('vehicle') or ''
                if vehicle:
                    sensor_latest.setdefault(vehicle, {})[msg['name']] = msg
            if sensor_latest:
                flat = [m for per_v in sensor_latest.values() for m in per_v.values()]
                fused_all = fuse_positions_by_vehicle(flat)
                if not fused_all:
                    legacy = fuse_positions(flat)
                    if legacy:
                        print(f"FUSED POSITION: lon={legacy[0]:.3f}, lat={legacy[1]:.3f}")
                else:
                    for vehicle, (lon, lat) in sorted(fused_all.items()):
                        n = len(sensor_latest.get(vehicle, {}))
                        print(f"FUSED {vehicle}: lon={lon:.3f}, lat={lat:.3f} ({n} sensor(s))")
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
