import socket
import struct
import argparse
import random
import time
from multicast_config import VEHICLE_MCAST_GRP, VEHICLE_MCAST_PORT, SENSOR_MCAST_GRP, SENSOR_MCAST_PORT

def parse_vehicle_msg(msg):
    parts = msg.decode().strip().split(',')
    if len(parts) < 5 or parts[0] != 'vehicle':
        return None
    return {
        'name': parts[1],
        'x': float(parts[2]),
        'y': float(parts[3]),
        't': float(parts[4]),
    }

def main():
    parser = argparse.ArgumentParser(description="ADAS Sensor: Publishes vehicle info at random intervals (~15s)")
    parser.add_argument('--interval', type=float, default=15.0, help='Average broadcast interval (seconds)')
    parser.add_argument('--name', type=str, default='adas1', help='Sensor name/id')
    args = parser.parse_args()

    recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    recv_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    recv_sock.bind(('', VEHICLE_MCAST_PORT))
    mreq = struct.pack('4sl', socket.inet_aton(VEHICLE_MCAST_GRP), socket.INADDR_ANY)
    recv_sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    recv_sock.settimeout(1.0)

    send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    send_sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
    send_addr = (SENSOR_MCAST_GRP, SENSOR_MCAST_PORT)

    print(f"ADAS sensor started. Listening on {VEHICLE_MCAST_GRP}:{VEHICLE_MCAST_PORT}, broadcasting to {SENSOR_MCAST_GRP}:{SENSOR_MCAST_PORT}")

    last_publish = {}  # vehicle_name -> last publish time
    publish_interval = {}  # vehicle_name -> randomized interval

    while True:
        try:
            data, _ = recv_sock.recvfrom(1024)
            v = parse_vehicle_msg(data)
            if not v:
                continue
            now = time.time()
            veh = v['name']
            if veh not in last_publish:
                last_publish[veh] = 0
                publish_interval[veh] = random.uniform(args.interval * 0.8, args.interval * 1.2)
            if now - last_publish[veh] >= publish_interval[veh]:
                msg = f"sensor,{args.name},{v['x']:.3f},{v['y']:.3f},{v['t']:.3f},ADAS"
                send_sock.sendto(msg.encode(), send_addr)
                print(f"ADAS Broadcast: {msg}")
                last_publish[veh] = now
                publish_interval[veh] = random.uniform(args.interval * 0.8, args.interval * 1.2)
        except socket.timeout:
            continue
        except KeyboardInterrupt:
            print("ADAS sensor stopped.")
            break

if __name__ == "__main__":
    main()
