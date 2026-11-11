"""DIS gateway: re-emit vehicle truth as IEEE 1278.1 (DIS 7) Entity State PDUs.

Subscribes to the vehicle multicast stream (VEHICLE_MCAST_GRP:VEHICLE_MCAST_PORT)
and sends one 144-byte Entity State PDU per aircraft — on every vehicle message
and at least every HEARTBEAT_S. On exit (SIGINT/SIGTERM) sends a Remove Entity
PDU for each known entity. Standard library only; LAN only. Per CR-001.

Aircraft are civil airliners, DIS type 1.2.124.87.0.0.0 (CR-002), force 3.

With --fused, also subscribes to the sensor stream (SENSOR_MCAST_GRP), fuses the
latest report per sensor per aircraft (fusion_app.fuse_positions, 1/sigma^2
weighting) and emits each sensed track as a separate entity: site --fused-site,
same entity number as its aircraft, force 0 (Other), marking "S:<callsign>".
Sensors report position only, so a sensed track borrows altitude, heading and
speed from its aircraft's truth (CR-001 known gap).
"""
import argparse
import re
import select
import signal
import socket
import struct
import sys
import time

from fusion.fusion_app import fuse_positions
from gateways.dis_output import DisOutput, add_output_args
from gateways.dis_pdu import (
    ENTITY_TYPES,
    FORCE_NEUTRAL,
    FORCE_OTHER,
    FT_TO_M,
    KTS_TO_MS,
    pack_entity_state,
    pack_remove_entity,
)
from multicast_config import (
    SENSOR_MCAST_GRP,
    SENSOR_MCAST_PORT,
    VEHICLE_MCAST_GRP,
    VEHICLE_MCAST_PORT,
)

AIRLINER_TYPE = ENTITY_TYPES['civil_airliner']
HEARTBEAT_S = 5.0      # DIS heartbeat; moving-map drops an entity after 12 s of silence
STALE_S = 30.0         # no vehicle message for this long → remove the entity
READING_MAX_AGE_S = 15.0   # sensor reports older than this drop out of the fusion
SENSOR_NOISE_M = {'ADAS': 200.0, 'TACAN': 150.0}   # as fusion_app
DEFAULT_NOISE_M = 100.0


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


def aircraft_pdu(state, entity_id, force, exercise):
    """Entity State PDU for one parsed vehicle state (airliner, level flight)."""
    return pack_entity_state(
        entity_id, force, AIRLINER_TYPE, state['name'],
        state['lat'], state['lon'], state['alt_ft'] * FT_TO_M, state['heading_deg'],
        ground_speed_ms=state['speed_kts'] * KTS_TO_MS, exercise=exercise)


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


def main():
    parser = argparse.ArgumentParser(
        description='Re-emit vehicle truth (and optionally sensed tracks) as DIS 7 Entity State PDUs (UDP, LAN only).'
    )
    add_output_args(parser)
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

    output = DisOutput.from_args(args)
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

    def full_id(key):
        kind, name = key
        return (site_force(kind)[0], args.app, entity_ids.get(name))

    def send_state(key, now):
        entity = entities[key]
        output.send([aircraft_pdu(entity['state'], full_id(key), site_force(key[0])[1], args.exercise)])
        entity['last_tx'] = now

    def send_remove(key):
        output.send([pack_remove_entity(full_id(key), exercise=args.exercise)])

    def update(key, state, now):
        if key not in entities:
            print(f'[DIS] New {key[0]} entity {".".join(map(str, full_id(key)))} = {state["name"]}')
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
        print(f'[DIS] Sent Remove Entity for {len(entities)} entities; {output.close()}; exiting.')
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    fused_note = f', sensed tracks on site {args.fused_site} force {FORCE_OTHER}' if args.fused else ''
    print(
        f'[DIS] {VEHICLE_MCAST_GRP}:{VEHICLE_MCAST_PORT} → {output.describe()}  '
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
