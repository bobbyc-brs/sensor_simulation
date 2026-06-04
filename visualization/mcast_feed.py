"""Multicast listeners for vehicle and sensor position streams."""
import queue
import socket
import struct
import threading

from multicast_config import SENSOR_MCAST_GRP, SENSOR_MCAST_PORT, VEHICLE_MCAST_GRP, VEHICLE_MCAST_PORT


def parse_sensor(parts):
    noise_raw = parts[5]
    try:
        noise_std = float(noise_raw)
    except ValueError:
        noise_std = {'ADAS': 200.0, 'TACAN': 150.0}.get(noise_raw, 100.0)
    vehicle = parts[6] if len(parts) >= 7 else ''
    return {
        'type': 'sensor',
        'name': parts[1],
        'lat': float(parts[2]),
        'lon': float(parts[3]),
        't': float(parts[4]),
        'noise_std': noise_std,
        'vehicle': vehicle,
    }


def multicast_listener(q, stop_event):
    def bind_mcast(group, port):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('', port))
        mreq = struct.pack('4sl', socket.inet_aton(group), socket.INADDR_ANY)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        sock.settimeout(0.2)
        return sock

    socks = [
        bind_mcast(SENSOR_MCAST_GRP, SENSOR_MCAST_PORT),
        bind_mcast(VEHICLE_MCAST_GRP, VEHICLE_MCAST_PORT),
    ]
    while not stop_event.is_set():
        for sock in socks:
            try:
                data, _ = sock.recvfrom(1024)
                text = data.decode()
                parts = text.strip().split(',')
                if parts[0] == 'sensor' and len(parts) >= 6:
                    q.put((parts[1], parse_sensor(parts)))
                elif parts[0] == 'vehicle' and len(parts) >= 5:
                    q.put((parts[1], {
                        'type': 'vehicle',
                        'name': parts[1],
                        'lat': float(parts[2]),
                        'lon': float(parts[3]),
                        't': float(parts[4]),
                    }))
            except socket.timeout:
                continue
            except Exception:
                continue
    for sock in socks:
        sock.close()


def start_feed():
    q = queue.Queue()
    stop_event = threading.Event()
    threading.Thread(target=multicast_listener, args=(q, stop_event), daemon=True).start()
    return q, stop_event