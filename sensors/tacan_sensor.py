import socket
import struct
import argparse
import math
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

def angle_between(x1, y1, x2, y2):
    return math.degrees(math.atan2(y2 - y1, x2 - x1)) % 360

def main():
    parser = argparse.ArgumentParser(description="TACAN Sensor: Rotating dish radar sensor")
    parser.add_argument('--radar-x-pos', type=float, required=True, help='Radar base station X position')
    parser.add_argument('--radar-y-pos', type=float, required=True, help='Radar base station Y position')
    parser.add_argument('--rotation-period', type=float, default=60.0, help='Full rotation period in seconds (default: 60)')
    parser.add_argument('--name', type=str, default='tacan1', help='Sensor name/id')
    args = parser.parse_args()

    recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    recv_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    recv_sock.bind(('', VEHICLE_MCAST_PORT))
    mreq = struct.pack('4sl', socket.inet_aton(VEHICLE_MCAST_GRP), socket.INADDR_ANY)
    recv_sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    recv_sock.settimeout(0.5)

    send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    send_sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
    send_addr = (SENSOR_MCAST_GRP, SENSOR_MCAST_PORT)

    print(f"TACAN sensor started at ({args.radar_x_pos}, {args.radar_y_pos}). Rotating dish.")

    published_this_rotation = set()
    start_time = time.time()
    tol = 1.0  # degree tolerance

    while True:
        try:
            now = time.time()
            elapsed = (now - start_time) % args.rotation_period
            dish_angle = (elapsed / args.rotation_period) * 360.0
            data, _ = recv_sock.recvfrom(1024)
            v = parse_vehicle_msg(data)
            if not v:
                continue
            veh_angle = angle_between(args.radar_x_pos, args.radar_y_pos, v['x'], v['y'])
            veh_id = v['name']
            angle_diff = (veh_angle - dish_angle + 360) % 360
            if angle_diff > 180:
                angle_diff = 360 - angle_diff
            # Only publish if within tol and not already published this rotation
            if angle_diff <= tol and veh_id not in published_this_rotation:
                msg = f"sensor,{args.name},{v['x']:.3f},{v['y']:.3f},{v['t']:.3f},TACAN"
                send_sock.sendto(msg.encode(), send_addr)
                print(f"TACAN Broadcast: {msg}")
                published_this_rotation.add(veh_id)
            # Reset published set at start of rotation
            if elapsed < 0.5:
                published_this_rotation.clear()
        except socket.timeout:
            continue
        except KeyboardInterrupt:
            print("TACAN sensor stopped.")
            break

if __name__ == "__main__":
    main()
