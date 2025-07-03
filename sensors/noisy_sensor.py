import socket
import struct
import argparse
import random
import time
from multicast_config import VEHICLE_MCAST_GRP, VEHICLE_MCAST_PORT, SENSOR_MCAST_GRP, SENSOR_MCAST_PORT

def parse_vehicle_msg(msg):
    # Format: name,x,y,t
    parts = msg.decode().strip().split(',')
    if len(parts) != 4:
        return None
    return {
        'name': parts[0],
        'x': float(parts[1]),
        'y': float(parts[2]),
        't': float(parts[3]),
    }

def main():
    parser = argparse.ArgumentParser(description="Noisy Sensor: Listens to vehicle, adds noise, rebroadcasts.")
    parser.add_argument('--listen_port', type=int, required=True, help='UDP port to listen for vehicle position')
    parser.add_argument('--broadcast_port', type=int, required=True, help='UDP port to broadcast noisy position')
    parser.add_argument('--noise_std', type=float, default=0.5, help='Stddev of Gaussian noise (meters)')
    parser.add_argument('--interval', type=float, default=0.1, help='Broadcast interval (default: 0.1s)')
    parser.add_argument('--name', type=str, default='sensor1', help='Sensor name/id')
    args = parser.parse_args()

    # Multicast receive socket for vehicles
    recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    recv_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    recv_sock.bind(('', VEHICLE_MCAST_PORT))
    mreq = struct.pack('4sl', socket.inet_aton(VEHICLE_MCAST_GRP), socket.INADDR_ANY)
    recv_sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    recv_sock.settimeout(args.interval)
    # Multicast send socket for sensors
    send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    send_sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
    send_addr = (SENSOR_MCAST_GRP, SENSOR_MCAST_PORT)

    print(f"Listening for vehicle on UDP {args.listen_port}, broadcasting noisy data on UDP {args.broadcast_port}")

    while True:
        try:
            data, _ = recv_sock.recvfrom(1024)
            try:
                text = data.decode()
                parts = text.strip().split(',')
                if len(parts) >= 5 and parts[0] == 'sensor':
                    continue  # ignore sensor messages
                if len(parts) < 5 or parts[0] != 'vehicle':
                    continue
                # Parse vehicle message
                v = {'name': parts[1], 'x': float(parts[2]), 'y': float(parts[3]), 't': float(parts[4])}
            except Exception:
                continue
            # Add Gaussian noise
            noisy_x = v['x'] + random.gauss(0, args.noise_std)
            noisy_y = v['y'] + random.gauss(0, args.noise_std)
            msg = f"sensor,{args.name},{noisy_x:.3f},{noisy_y:.3f},{v['t']:.3f},{args.noise_std:.3f}"
            send_sock.sendto(msg.encode(), send_addr)
            print(f"Broadcast: {msg}")
        except socket.timeout:
            continue
        except KeyboardInterrupt:
            print("Sensor stopped.")
            break

if __name__ == "__main__":
    main()
