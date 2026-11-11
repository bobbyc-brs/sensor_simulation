"""DIS gateway: re-emit vehicle truth as IEEE 1278.1 (DIS 7) Entity State PDUs.

Subscribes to the vehicle multicast stream (VEHICLE_MCAST_GRP:VEHICLE_MCAST_PORT)
and sends one 144-byte Entity State PDU per aircraft over UDP — on every vehicle
message and at least every HEARTBEAT_S. On exit (SIGINT/SIGTERM) sends a Remove
Entity PDU for each known entity. Standard library only; LAN only. Per CR-001.

With --fused, also subscribes to the sensor stream (SENSOR_MCAST_GRP), fuses the
latest report per sensor per aircraft (fusion_app.fuse_positions, 1/sigma^2
weighting) and emits each sensed track as a separate entity: site --fused-site,
same entity number as its aircraft, force 0 (Other), marking "S:<callsign>".
Sensors report position only, so a sensed track borrows altitude, heading and
speed from its aircraft's truth (CR-001 known gap).
"""
import argparse
import math
import re
import select
import signal
import socket
import struct
import sys
import time

from fusion.fusion_app import fuse_positions
from multicast_config import (
    SENSOR_MCAST_GRP,
    SENSOR_MCAST_PORT,
    VEHICLE_MCAST_GRP,
    VEHICLE_MCAST_PORT,
)

# DIS 7 constants
PROTOCOL_VERSION = 7
PDU_ENTITY_STATE = 1
PDU_REMOVE_ENTITY = 12
FAMILY_ENTITY_INFO = 1
FAMILY_SIMULATION_MGMT = 5
ENTITY_STATE_LEN = 144
REMOVE_ENTITY_LEN = 28

# Entity type: platform / air / Canada (country 124)
KIND_PLATFORM = 1
DOMAIN_AIR = 2
COUNTRY_CANADA = 124

HEARTBEAT_S = 5.0      # DIS heartbeat; moving-map drops an entity after 12 s of silence
STALE_S = 30.0         # no vehicle message for this long → remove the entity
READING_MAX_AGE_S = 15.0   # sensor reports older than this drop out of the fusion

FORCE_OTHER = 0        # sensed tracks; moving-map shows it as Unknown
FORCE_NEUTRAL = 3      # civil aircraft (Bobby, CR-001 decisions 2026-11-10)
SENSOR_NOISE_M = {'ADAS': 200.0, 'TACAN': 150.0}   # as fusion_app
DEFAULT_NOISE_M = 100.0

FT_TO_M = 0.3048
KTS_TO_MS = 0.514444

# WGS84
A, F = 6378137.0, 1 / 298.257223563
E2 = F * (2 - F)


def ecef(lat, lon, h):
    """WGS84 geodetic (deg, deg, metres) to ECEF metres."""
    la, lo = math.radians(lat), math.radians(lon)
    n = A / math.sqrt(1 - E2 * math.sin(la) ** 2)
    return ((n + h) * math.cos(la) * math.cos(lo),
            (n + h) * math.cos(la) * math.sin(lo),
            (n * (1 - E2) + h) * math.sin(la))


def heading_axes(lat, lon, heading_deg):
    """Unit vector of a level body x-axis in ECEF, and its psi/theta (radians)."""
    la, lo, hd = map(math.radians, (lat, lon, heading_deg))
    north = (-math.sin(la) * math.cos(lo), -math.sin(la) * math.sin(lo), math.cos(la))
    east = (-math.sin(lo), math.cos(lo), 0.0)
    bx = [math.cos(hd) * n + math.sin(hd) * e for n, e in zip(north, east)]
    return bx, math.atan2(bx[1], bx[0]), -math.asin(bx[2])


def pack_header(exercise, pdu_type, family, length):
    """12-byte DIS 7 PDU header; timestamp 0, status 0."""
    return struct.pack('>BBBBIHBB', PROTOCOL_VERSION, exercise, pdu_type, family,
                       0, length, 0, 0)


def pack_marking(callsign):
    """12-byte entity marking: ASCII character set, 11 bytes NUL-padded."""
    text = callsign.encode('ascii', errors='replace')[:11]
    return bytes([1]) + text.ljust(11, b'\0')


def pack_entity_state(state, entity_id, exercise=1, site=1, app=42, force=1):
    """Entity State PDU (144 bytes) for one aircraft state dict."""
    lat, lon = state['lat'], state['lon']
    alt_m = state['alt_ft'] * FT_TO_M
    bx, psi, theta = heading_axes(lat, lon, state['heading_deg'])
    speed_ms = state['speed_kts'] * KTS_TO_MS
    velocity = [speed_ms * c for c in bx]

    pdu = b''.join((
        pack_header(exercise, PDU_ENTITY_STATE, FAMILY_ENTITY_INFO, ENTITY_STATE_LEN),
        struct.pack('>HHH', site, app, entity_id),
        struct.pack('>BB', force, 0),
        struct.pack('>BBHBBBB', KIND_PLATFORM, DOMAIN_AIR, COUNTRY_CANADA, 0, 0, 0, 0),
        bytes(8),                                   # alternative entity type
        struct.pack('>fff', *velocity),
        struct.pack('>ddd', *ecef(lat, lon, alt_m)),
        struct.pack('>fff', psi, theta, 0.0),       # phi: level flight
        struct.pack('>I', 0),                       # appearance
        bytes(40),                                  # dead reckoning parameters
        pack_marking(state['name']),
        struct.pack('>I', 0),                       # capabilities
    ))
    assert len(pdu) == ENTITY_STATE_LEN
    return pdu


def pack_remove_entity(entity_id, exercise=1, site=1, app=42, request_id=0):
    """Remove Entity PDU (28 bytes) addressed to one aircraft."""
    pdu = b''.join((
        pack_header(exercise, PDU_REMOVE_ENTITY, FAMILY_SIMULATION_MGMT, REMOVE_ENTITY_LEN),
        struct.pack('>HHH', 0, 0, 0),               # originating ID
        struct.pack('>HHH', site, app, entity_id),  # receiving ID
        struct.pack('>I', request_id),
    ))
    assert len(pdu) == REMOVE_ENTITY_LEN
    return pdu


def parse_vehicle(msg):
    """Parse 'vehicle,name,lat,lon,progress,heading_deg,alt_ft,speed_kts'; None if not one."""
    parts = msg.strip().split(',')
    if len(parts) != 8 or parts[0] != 'vehicle':
        return None
    try:
        return {
            'name': parts[1],
            'lat': float(parts[2]),
            'lon': float(parts[3]),
            'heading_deg': float(parts[5]),
            'alt_ft': float(parts[6]),
            'speed_kts': float(parts[7]),
        }
    except ValueError:
        return None


def parse_sensor(msg):
    """Parse 'sensor,name,lat,lon,progress,noise_or_type,vehicle'; None if not one."""
    parts = msg.strip().split(',')
    if len(parts) < 7 or parts[0] != 'sensor' or not parts[6]:
        return None
    try:
        noise_m = float(parts[5])
    except ValueError:
        noise_m = SENSOR_NOISE_M.get(parts[5], DEFAULT_NOISE_M)
    try:
        return {
            'sensor': parts[1],
            'lat': float(parts[2]),
            'lon': float(parts[3]),
            'noise_std': noise_m,
            'vehicle': parts[6],
        }
    except ValueError:
        return None


def fuse_readings(readings):
    """Weighted (lat, lon) of {sensor: reading}; reuses fusion_app's weighting."""
    as_xy = [{'x': r['lat'], 'y': r['lon'], 'noise_std': r['noise_std']} for r in readings.values()]
    return fuse_positions(as_xy)


class EntityIds:
    """Stable 1-based entity IDs per callsign.

    A callsign ending in digits ('flight3') takes that number, so IDs survive a
    gateway restart; anything else takes the next free number.
    """

    def __init__(self):
        self.by_name = {}

    def get(self, name):
        if name in self.by_name:
            return self.by_name[name]
        used = set(self.by_name.values())
        match = re.search(r'(\d+)$', name)
        wanted = int(match.group(1)) if match else 0
        if 1 <= wanted <= 0xFFFF and wanted not in used:
            entity_id = wanted
        else:
            entity_id = 1
            while entity_id in used:
                entity_id += 1
        self.by_name[name] = entity_id
        return entity_id


def open_multicast_socket(group, port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('', port))
    mreq = struct.pack('4sl', socket.inet_aton(group), socket.INADDR_ANY)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    return sock


def open_dis_socket():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    # Harmless for unicast; required when --dest is a broadcast address.
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    return sock


def main():
    parser = argparse.ArgumentParser(
        description='Re-emit vehicle truth (and optionally sensed tracks) as DIS 7 Entity State PDUs (UDP, LAN only).'
    )
    parser.add_argument('--dest', default='127.0.0.1',
                        help='DIS destination address; a broadcast address such as 192.168.1.255 works (default: 127.0.0.1)')
    parser.add_argument('--port', type=int, default=3000, help='DIS UDP port (default: 3000)')
    parser.add_argument('--exercise', type=int, default=1, help='DIS exercise ID (default: 1)')
    parser.add_argument('--site', type=int, default=1, help='DIS site ID for aircraft truth (default: 1)')
    parser.add_argument('--app', type=int, default=42, help='DIS application ID (default: 42)')
    parser.add_argument('--force', type=int, default=FORCE_NEUTRAL,
                        help='Force ID for aircraft truth: 0 other, 1 friendly, 2 opposing, 3 neutral (default: 3)')
    parser.add_argument('--fused', action='store_true',
                        help='Also emit fused sensor tracks as separate entities (force 0, site --fused-site)')
    parser.add_argument('--fused-site', type=int, default=2, help='DIS site ID for sensed tracks (default: 2)')
    args = parser.parse_args()
    if args.fused and args.fused_site == args.site:
        parser.error('--fused-site must differ from --site, or sensed IDs collide with truth')

    tx = open_dis_socket()
    dest = (args.dest, args.port)
    entity_ids = EntityIds()   # shared: truth 1.42.N and its sensed track 2.42.N
    # (kind, name) -> {'state', 'last_rx', 'last_tx'}; kind is 'truth' or 'fused'
    entities = {}
    readings = {}              # aircraft name -> {sensor name: reading + 'rx'}
    rx_vehicle = open_multicast_socket(VEHICLE_MCAST_GRP, VEHICLE_MCAST_PORT)
    rx_sockets = [rx_vehicle]
    if args.fused:
        rx_sockets.append(open_multicast_socket(SENSOR_MCAST_GRP, SENSOR_MCAST_PORT))

    def site_force(kind):
        if kind == 'truth':
            return args.site, args.force
        return args.fused_site, FORCE_OTHER

    def send_state(key, now):
        kind, name = key
        site, force = site_force(kind)
        entity = entities[key]
        pdu = pack_entity_state(entity['state'], entity_ids.get(name),
                                exercise=args.exercise, site=site, app=args.app, force=force)
        tx.sendto(pdu, dest)
        entity['last_tx'] = now

    def send_remove(key):
        kind, name = key
        site, _ = site_force(kind)
        tx.sendto(pack_remove_entity(entity_ids.get(name), exercise=args.exercise,
                                     site=site, app=args.app), dest)

    def update(key, state, now):
        kind, name = key
        if key not in entities:
            site, _ = site_force(kind)
            print(f'[DIS] New {kind} entity {site}.{args.app}.{entity_ids.get(name)} = {state["name"]}')
            entities[key] = {'last_tx': 0.0}
        entities[key].update(state=state, last_rx=now)
        send_state(key, now)

    shutting_down = []

    def shutdown(sig, frame):
        # A Ctrl-C reaches the whole process group, so SIGINT and the manager's
        # SIGTERM can both arrive; act on the first only.
        if shutting_down:
            return
        shutting_down.append(sig)
        for key in entities:
            send_remove(key)
        print(f'[DIS] Sent Remove Entity for {len(entities)} entities; exiting.')
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    fused_note = f', sensed tracks on site {args.fused_site} force {FORCE_OTHER}' if args.fused else ''
    print(
        f'[DIS] {VEHICLE_MCAST_GRP}:{VEHICLE_MCAST_PORT} → {args.dest}:{args.port}  '
        f'exercise={args.exercise} site={args.site} app={args.app} force={args.force}{fused_note}'
    )

    while True:
        ready, _, _ = select.select(rx_sockets, [], [], 1.0)
        now = time.monotonic()
        for sock in ready:
            text = sock.recv(1024).decode(errors='replace')
            if sock is rx_vehicle:
                state = parse_vehicle(text)
                if state is not None:
                    update(('truth', state['name']), state, now)
                continue
            reading = parse_sensor(text)
            if reading is None:
                continue
            reading['rx'] = now
            per_sensor = readings.setdefault(reading['vehicle'], {})
            per_sensor[reading['sensor']] = reading
            truth = entities.get(('truth', reading['vehicle']))
            if truth is None:
                continue   # no altitude/heading/speed to borrow yet
            fresh = {k: r for k, r in per_sensor.items() if now - r['rx'] <= READING_MAX_AGE_S}
            fused = fuse_readings(fresh)
            if fused is None:
                continue
            state = dict(truth['state'], lat=fused[0], lon=fused[1],
                         name=f'S:{reading["vehicle"]}')
            update(('fused', reading['vehicle']), state, now)

        for key in list(entities):
            entity = entities[key]
            if now - entity['last_rx'] > STALE_S:
                send_remove(key)
                del entities[key]
                print(f'[DIS] {key[0]} {key[1]} silent for {STALE_S:.0f} s; sent Remove Entity')
            elif now - entity['last_tx'] >= HEARTBEAT_S:
                send_state(key, now)


if __name__ == '__main__':
    main()
