"""DIS 7 (IEEE 1278.1) PDU encoding: Entity State, Remove Entity, and filler PDUs.

Pure functions, standard library only. Wire layout per CR-001 (cross-checked by
moving-map-display, DD-004 there); entity types per CR-002.
"""
import math
import struct

PROTOCOL_VERSION = 7
PDU_ENTITY_STATE = 1
PDU_REMOVE_ENTITY = 12
FAMILY_ENTITY_INFO = 1
FAMILY_WARFARE = 2
FAMILY_SIMULATION_MGMT = 5
HEADER_LEN = 12
ENTITY_STATE_LEN = 144
REMOVE_ENTITY_LEN = 28

FORCE_OTHER, FORCE_FRIENDLY, FORCE_OPPOSING, FORCE_NEUTRAL = 0, 1, 2, 3
FORCE_NAMES = {'other': 0, 'unknown': 0, 'friendly': 1, 'opposing': 2, 'neutral': 3}

# DIS countries are SISO-REF-010 codes, not ISO 3166: Canada is 39 (ISO's 124 is
# Lesotho in DIS). Confirmed with tshark 4.2.6, 2026-11-10 — CR-002 addendum.
COUNTRY_CANADA = 39

# kind.domain.country.category.subcategory.specific.extra — CR-002 table with the
# country corrected. Category names confirmed by Wireshark's DIS dissector;
# car 10, school bus 12 and life form 200/80/90 have no names there (unconfirmed).
ENTITY_TYPES = {
    'car':                (1, 1, COUNTRY_CANADA, 81, 10, 0, 0),
    'cargo_truck':        (1, 1, COUNTRY_CANADA, 83, 0, 0, 0),
    'bus':                (1, 1, COUNTRY_CANADA, 82, 0, 0, 0),
    'school_bus':         (1, 1, COUNTRY_CANADA, 82, 12, 0, 0),
    'horse':              (3, 1, COUNTRY_CANADA, 200, 80, 0, 0),
    'horse_with_rider':   (3, 1, COUNTRY_CANADA, 200, 90, 0, 0),
    'tank':               (1, 1, COUNTRY_CANADA, 1, 0, 0, 0),
    'afv':                (1, 1, COUNTRY_CANADA, 2, 0, 0, 0),
    'utility_helicopter': (1, 2, COUNTRY_CANADA, 21, 0, 0, 0),
    'attack_helicopter':  (1, 2, COUNTRY_CANADA, 20, 0, 0, 0),
    'patrol_craft':       (1, 3, COUNTRY_CANADA, 7, 0, 0, 0),
    'civil_airliner':     (1, 2, COUNTRY_CANADA, 87, 0, 0, 0),
}

# PDU types moving-map does not decode, for --fault-unknown-types:
# (type, family, length in bytes)
FILLER_PDUS = (
    (2, FAMILY_WARFARE, 96),           # Fire
    (3, FAMILY_WARFARE, 104),          # Detonation
    (4, FAMILY_ENTITY_INFO, 60),       # Collision
    (11, FAMILY_SIMULATION_MGMT, 28),  # Create Entity
)

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


def ned_axes(lat, lon):
    """North, east and down unit vectors in ECEF at (lat, lon)."""
    la, lo = math.radians(lat), math.radians(lon)
    north = (-math.sin(la) * math.cos(lo), -math.sin(la) * math.sin(lo), math.cos(la))
    east = (-math.sin(lo), math.cos(lo), 0.0)
    down = (-math.cos(la) * math.cos(lo), -math.cos(la) * math.sin(lo), -math.sin(la))
    return north, east, down


def _ned_to_ecef(vec_ned, axes):
    a, b, c = vec_ned
    north, east, down = axes
    return [a * n + b * e + c * d for n, e, d in zip(north, east, down)]


def body_axes_ned(heading, pitch, roll):
    """Body x, y, z axes in local NED for heading/pitch/roll in radians (z-y-x order)."""
    ch, sh = math.cos(heading), math.sin(heading)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cr, sr = math.cos(roll), math.sin(roll)
    x = (ch * cp, sh * cp, -sp)
    y = (ch * sp * sr - sh * cr, sh * sp * sr + ch * cr, cp * sr)
    z = (ch * sp * cr + sh * sr, sh * sp * cr - ch * sr, cp * cr)
    return x, y, z


def orientation(lat, lon, heading_deg, pitch_deg=0.0, roll_deg=0.0):
    """DIS Euler angles (psi, theta, phi) in radians, relative to ECEF.

    Builds the body axes in local NED, rotates them into ECEF, and reads off the
    z-y-x Euler angles. For level flight this equals CR-001's heading_axes().
    """
    axes = ned_axes(lat, lon)
    bx, by, bz = (_ned_to_ecef(v, axes) for v in body_axes_ned(
        math.radians(heading_deg), math.radians(pitch_deg), math.radians(roll_deg)))
    psi = math.atan2(bx[1], bx[0])
    theta = math.atan2(-bx[2], math.hypot(bx[0], bx[1]))
    phi = math.atan2(by[2], bz[2])
    return psi, theta, phi


def velocity_ecef(lat, lon, heading_deg, ground_speed_ms, vertical_ms=0.0):
    """ECEF velocity (m/s) for a ground speed along heading plus a climb rate."""
    hd = math.radians(heading_deg)
    v_ned = (ground_speed_ms * math.cos(hd), ground_speed_ms * math.sin(hd), -vertical_ms)
    return _ned_to_ecef(v_ned, ned_axes(lat, lon))


def relative_timestamp(unix_time):
    """DIS relative timestamp: 31-bit count of 3600/2^31 s past the hour, low bit 0."""
    units = int((unix_time % 3600.0) * (2 ** 31) / 3600.0) & 0x7FFFFFFF
    return units << 1


def timestamp_seconds(timestamp):
    """Inverse of relative_timestamp: seconds past the hour."""
    return (timestamp >> 1) * 3600.0 / (2 ** 31)


def pack_header(exercise, pdu_type, family, length, timestamp=0, version=PROTOCOL_VERSION):
    """12-byte PDU header; status 0."""
    return struct.pack('>BBBBIHBB', version, exercise, pdu_type, family,
                       timestamp, length, 0, 0)


def pack_marking(text):
    """12-byte entity marking: ASCII character set, 11 bytes NUL-padded."""
    raw = text.encode('ascii', errors='replace')[:11]
    return bytes([1]) + raw.ljust(11, b'\0')


def pack_entity_state(entity_id, force, entity_type, marking, lat, lon, alt_m,
                      heading_deg, pitch_deg=0.0, roll_deg=0.0,
                      ground_speed_ms=0.0, vertical_ms=0.0, exercise=1, timestamp=0):
    """Entity State PDU (144 bytes). entity_id is (site, app, entity)."""
    psi, theta, phi = orientation(lat, lon, heading_deg, pitch_deg, roll_deg)
    pdu = b''.join((
        pack_header(exercise, PDU_ENTITY_STATE, FAMILY_ENTITY_INFO, ENTITY_STATE_LEN, timestamp),
        struct.pack('>HHH', *entity_id),
        struct.pack('>BB', force, 0),
        struct.pack('>BBHBBBB', *entity_type),
        bytes(8),                                   # alternative entity type
        struct.pack('>fff', *velocity_ecef(lat, lon, heading_deg, ground_speed_ms, vertical_ms)),
        struct.pack('>ddd', *ecef(lat, lon, alt_m)),
        struct.pack('>fff', psi, theta, phi),
        struct.pack('>I', 0),                       # appearance
        bytes(40),                                  # dead reckoning parameters
        pack_marking(marking),
        struct.pack('>I', 0),                       # capabilities
    ))
    assert len(pdu) == ENTITY_STATE_LEN
    return pdu


def pack_remove_entity(entity_id, exercise=1, request_id=0, timestamp=0):
    """Remove Entity PDU (28 bytes) addressed to entity_id (site, app, entity)."""
    pdu = b''.join((
        pack_header(exercise, PDU_REMOVE_ENTITY, FAMILY_SIMULATION_MGMT, REMOVE_ENTITY_LEN, timestamp),
        struct.pack('>HHH', 0, 0, 0),               # originating ID
        struct.pack('>HHH', *entity_id),            # receiving ID
        struct.pack('>I', request_id),
    ))
    assert len(pdu) == REMOVE_ENTITY_LEN
    return pdu


def pack_filler(pdu_type, family, length, exercise=1):
    """A well-formed PDU of a type the receiver may not decode: header + zero body."""
    return pack_header(exercise, pdu_type, family, length) + bytes(length - HEADER_LEN)


def split_pdus(data):
    """Split back-to-back PDUs by header length, as moving-map does.

    Returns (list of PDU byte strings, ok). ok is False when a header is short,
    its length is under 12, or a PDU runs past the end of the data.
    """
    out, offset = [], 0
    while offset < len(data):
        if len(data) - offset < HEADER_LEN:
            return out, False
        length = struct.unpack_from('>H', data, offset + 8)[0]
        if length < HEADER_LEN or offset + length > len(data):
            return out, False
        out.append(data[offset:offset + length])
        offset += length
    return out, True
