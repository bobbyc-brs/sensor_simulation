import socket
import struct
import argparse
import time
from multicast_config import VEHICLE_MCAST_GRP, VEHICLE_MCAST_PORT, SENSOR_MCAST_GRP, SENSOR_MCAST_PORT
from geo.eastern_canada import initial_bearing_deg

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
    parser = argparse.ArgumentParser(description="TACAN Sensor: Rotating dish radar sensor")
    parser.add_argument('--radar-lat', type=float, help='Radar latitude (decimal degrees)')
    parser.add_argument('--radar-lon', type=float, help='Radar longitude (decimal degrees)')
    parser.add_argument('--radar-x-pos', type=float, help='Alias for radar longitude')
    parser.add_argument('--radar-y-pos', type=float, help='Alias for radar latitude')
    parser.add_argument('--rotation-period', type=float, default=60.0, help='Full rotation period in seconds (default: 60)')
    parser.add_argument('--name', type=str, default='tacan1', help='Sensor name/id')
    args = parser.parse_args()

    radar_lat = args.radar_lat if args.radar_lat is not None else args.radar_y_pos
    radar_lon = args.radar_lon if args.radar_lon is not None else args.radar_x_pos
    if radar_lat is None or radar_lon is None:
        parser.error('TACAN requires --radar-lat and --radar-lon (or legacy --radar-y-pos / --radar-x-pos).')

    recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    recv_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    recv_sock.bind(('', VEHICLE_MCAST_PORT))
    mreq = struct.pack('4sl', socket.inet_aton(VEHICLE_MCAST_GRP), socket.INADDR_ANY)
    recv_sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    recv_sock.settimeout(0.5)

    send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    send_sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
    send_addr = (SENSOR_MCAST_GRP, SENSOR_MCAST_PORT)

    print(f"TACAN sensor at lat={radar_lat:.4f}, lon={radar_lon:.4f}. Rotating dish.")

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
            veh_angle = initial_bearing_deg(radar_lat, radar_lon, v['x'], v['y'])
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
