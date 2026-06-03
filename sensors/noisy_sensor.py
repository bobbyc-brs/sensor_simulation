import socket
import struct
import argparse
import random
import math
import time
from multicast_config import VEHICLE_MCAST_GRP, VEHICLE_MCAST_PORT, SENSOR_MCAST_GRP, SENSOR_MCAST_PORT
from geo.eastern_canada import meters_to_degree_noise

def main():
    parser = argparse.ArgumentParser(description="Noisy Sensor: Listens to vehicle multicast, adds noise, rebroadcasts to sensor multicast.")
    parser.add_argument('--noise_std', type=float, default=50.0, help='Stddev of Gaussian position noise (meters)')
    parser.add_argument('--interval', type=float, default=0.1, help='Receive timeout / poll interval (default: 0.1s)')
    parser.add_argument('--name', type=str, default='sensor1', help='Sensor name/id')
    args = parser.parse_args()

    recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    recv_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    recv_sock.bind(('', VEHICLE_MCAST_PORT))
    mreq = struct.pack('4sl', socket.inet_aton(VEHICLE_MCAST_GRP), socket.INADDR_ANY)
    recv_sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    recv_sock.settimeout(args.interval)

    send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    send_sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
    send_addr = (SENSOR_MCAST_GRP, SENSOR_MCAST_PORT)

    print(
        f"Listening on {VEHICLE_MCAST_GRP}:{VEHICLE_MCAST_PORT}, "
        f"noise σ={args.noise_std} m → {SENSOR_MCAST_GRP}:{SENSOR_MCAST_PORT}"
    )

    while True:
        try:
            data, _ = recv_sock.recvfrom(1024)
            try:
                text = data.decode()
                parts = text.strip().split(',')
                if len(parts) >= 5 and parts[0] == 'sensor':
                    continue
                if len(parts) < 5 or parts[0] != 'vehicle':
                    continue
                lat = float(parts[2])
                lon = float(parts[3])
                t_prog = float(parts[4])
            except Exception:
                continue
            dlat_sig, dlon_sig = meters_to_degree_noise(lat, args.noise_std)
            noisy_lat = lat + random.gauss(0, dlat_sig)
            noisy_lon = lon + random.gauss(0, dlon_sig)
            msg = f"sensor,{args.name},{noisy_lat:.6f},{noisy_lon:.6f},{t_prog:.4f},{args.noise_std:.1f}"
            send_sock.sendto(msg.encode(), send_addr)
            print(f"Broadcast: {msg}")
        except socket.timeout:
            continue
        except KeyboardInterrupt:
            print("Sensor stopped.")
            break

if __name__ == "__main__":
    main()