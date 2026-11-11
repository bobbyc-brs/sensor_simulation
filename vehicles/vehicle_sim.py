import socket
import time
import argparse
import signal
import sys

from multicast_config import VEHICLE_MCAST_GRP, VEHICLE_MCAST_PORT
from geo.eastern_canada import (
    DEFAULT_CRUISE_SPEED_KTS,
    airport_position,
    cruise_altitude_ft,
    flight_duration_s,
    initial_bearing_deg,
    interpolate_great_circle,
    route_label,
)
from geo.sim_control import read_time_scale

ARRIVED_DEG = 1e-6   # closer than this to the destination, keep the last heading


def current_heading(lat, lon, dest_lat, dest_lon, last_heading):
    """Great-circle bearing from the current position to the destination (CR-002).

    The initial bearing drifts from the true track on long routes; this is the
    track the aircraft is actually flying now. At the destination the bearing is
    undefined, so the last heading is kept.
    """
    if abs(lat - dest_lat) < ARRIVED_DEG and abs(lon - dest_lon) < ARRIVED_DEG:
        return last_heading
    return initial_bearing_deg(lat, lon, dest_lat, dest_lon)


def main():
    parser = argparse.ArgumentParser(
        description="Aircraft simulator: great-circle flight between airports (lat/lon), UDP multicast."
    )
    parser.add_argument('--origin-airport', type=str, help='Origin ICAO code (e.g. YYZ)')
    parser.add_argument('--dest-airport', type=str, help='Destination ICAO code (e.g. YHZ)')
    parser.add_argument('--origin-lat', type=float, help='Origin latitude (decimal degrees)')
    parser.add_argument('--origin-lon', type=float, help='Origin longitude (decimal degrees)')
    parser.add_argument('--dest-lat', type=float, help='Destination latitude')
    parser.add_argument('--dest-lon', type=float, help='Destination longitude')
    parser.add_argument('--speed-kts', type=float, default=DEFAULT_CRUISE_SPEED_KTS,
                        help=f'Cruise groundspeed in knots (default: {DEFAULT_CRUISE_SPEED_KTS})')
    parser.add_argument('--interval', type=float, default=2.0,
                        help='Position broadcast interval in seconds (default: 2.0)')
    parser.add_argument('--name', type=str, default='vehicle1', help='Aircraft callsign / id')
    args = parser.parse_args()

    if args.origin_airport and args.dest_airport:
        lat1, lon1 = airport_position(args.origin_airport.upper())
        lat2, lon2 = airport_position(args.dest_airport.upper())
        origin_icao = args.origin_airport.upper()
        dest_icao = args.dest_airport.upper()
    elif None not in (args.origin_lat, args.origin_lon, args.dest_lat, args.dest_lon):
        lat1, lon1 = args.origin_lat, args.origin_lon
        lat2, lon2 = args.dest_lat, args.dest_lon
        origin_icao = dest_icao = None
    else:
        parser.error('Provide --origin-airport and --dest-airport, or all four lat/lon arguments.')

    duration = flight_duration_s(lat1, lon1, lat2, lon2, args.speed_kts)
    bearing = initial_bearing_deg(lat1, lon1, lat2, lon2)
    heading = bearing

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
    addr = (VEHICLE_MCAST_GRP, VEHICLE_MCAST_PORT)

    def signal_handler(sig, frame):
        sock.close()
        sys.exit(0)
    signal.signal(signal.SIGINT, signal_handler)

    if origin_icao and dest_icao:
        route_desc = route_label(origin_icao, dest_icao)
    else:
        route_desc = f'({lat1:.3f}, {lon1:.3f}) → ({lat2:.3f}, {lon2:.3f})'

    print(
        f"Aircraft {args.name}: {route_desc}\n"
        f"  Cruise {args.speed_kts:.0f} kt, duration {duration/60:.1f} min, "
        f"bearing {bearing:.0f}°, multicast {VEHICLE_MCAST_GRP}:{VEHICLE_MCAST_PORT}"
    )

    time.sleep(1)
    start_time = time.time()
    arrived = False
    while True:
        time_scale = read_time_scale()
        elapsed = time.time() - start_time
        t = min(elapsed * time_scale / duration, 1.0) if duration > 0 else 1.0
        lat, lon = interpolate_great_circle(lat1, lon1, lat2, lon2, t)
        heading = current_heading(lat, lon, lat2, lon2, heading)

        if t >= 1.0:
            if not arrived:
                print(f"Aircraft {args.name} arrived at {dest_icao or 'destination'}. Parked.")
                arrived = True
            alt_ft = 0
            speed = 0
        else:
            alt_ft = cruise_altitude_ft(t)
            speed = args.speed_kts

        # vehicle,callsign,lat,lon,progress,heading_deg,alt_ft,speed_kts
        msg = (
            f"vehicle,{args.name},{lat:.6f},{lon:.6f},{t:.4f},"
            f"{heading:.1f},{alt_ft:.0f},{speed:.0f}"
        )
        sock.sendto(msg.encode(), addr)
        if not arrived:
            print(f"Broadcast: {msg}")
        time.sleep(args.interval / max(time_scale, 0.01) if not arrived else args.interval)

if __name__ == "__main__":
    main()