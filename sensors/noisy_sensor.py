import socket
import argparse
import random
import time

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

    recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    recv_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    recv_sock.bind(('127.0.0.1', args.listen_port))
    recv_sock.settimeout(args.interval)
    send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    send_addr = ('127.0.0.1', args.broadcast_port)

    print(f"Listening for vehicle on UDP {args.listen_port}, broadcasting noisy data on UDP {args.broadcast_port}")

    while True:
        try:
            data, _ = recv_sock.recvfrom(1024)
            v = parse_vehicle_msg(data)
            if v is None:
                continue
            # Add Gaussian noise
            noisy_x = v['x'] + random.gauss(0, args.noise_std)
            noisy_y = v['y'] + random.gauss(0, args.noise_std)
            # For now, error profile is just the stddev
            msg = f"{args.name},{noisy_x:.3f},{noisy_y:.3f},{v['t']:.3f},{args.noise_std:.3f}"
            send_sock.sendto(msg.encode(), send_addr)
            print(f"Broadcast: {msg}")
        except socket.timeout:
            continue
        except KeyboardInterrupt:
            print("Sensor stopped.")
            break

if __name__ == "__main__":
    main()
