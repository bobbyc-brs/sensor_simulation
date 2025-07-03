import socket
import time
import argparse
import math
import signal
import sys

from multicast_config import VEHICLE_MCAST_GRP, VEHICLE_MCAST_PORT

def interpolate(p1, p2, t):
    return (
        p1[0] + (p2[0] - p1[0]) * t,
        p1[1] + (p2[1] - p1[1]) * t,
    )

def main():
    parser = argparse.ArgumentParser(description="Vehicle Simulator: Moves from P1 to P2 and broadcasts position over UDP.")
    parser.add_argument('--p1', type=float, nargs=2, required=True, help='Start position x y')
    parser.add_argument('--p2', type=float, nargs=2, required=True, help='End position x y')
    # Multicast group/port are now used for all communication
    parser.add_argument('--interval', type=float, default=0.1, help='Broadcast interval in seconds')
    parser.add_argument('--duration', type=float, default=10.0, help='Time to move from P1 to P2 (seconds)')
    parser.add_argument('--name', type=str, default='vehicle1', help='Vehicle name/id')
    args = parser.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    # Set TTL for multicast (1 = local network only)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
    addr = (VEHICLE_MCAST_GRP, VEHICLE_MCAST_PORT)

    def signal_handler(sig, frame):
        sock.close()
        sys.exit(0)
    signal.signal(signal.SIGINT, signal_handler)

    time.sleep(1)
    print(f"Vehicle {args.name} started at {args.p1} moving to {args.p2} (broadcasting to multicast {VEHICLE_MCAST_GRP}:{VEHICLE_MCAST_PORT})")
    
    start_time = time.time()
    while True:
        elapsed = time.time() - start_time
        t = min(elapsed / args.duration, 1.0)
        pos = interpolate(args.p1, args.p2, t)
        msg = f"vehicle,{args.name},{pos[0]:.3f},{pos[1]:.3f},{t:.3f}"
        sock.sendto(msg.encode(), addr)
        print(f"Broadcast: {msg}")
        if t >= 1.0:
            break
        time.sleep(args.interval)

if __name__ == "__main__":
    main()
