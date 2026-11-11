"""Unit tests for gateways/dis_pdu.py — byte layout (CR-001), entity types and orientation (CR-002).

Run from the project root:  python -m unittest discover -s tests -t .
"""
import math
import struct
import unittest

from gateways.dis_pdu import (
    ENTITY_TYPES,
    ecef,
    ned_axes,
    orientation,
    pack_entity_state,
    pack_remove_entity,
)

YOW = (45.3225, -75.6692)

# CR-002 table: name → (wire bytes 20–27 as kind, domain, country, cat, subcat, specific, extra).
# Country is the SISO code for Canada, 39 — the CR's 124 is ISO's, and Lesotho in DIS.
CR002_TABLE = {
    'car':                (1, 1, 39, 81, 10, 0, 0),
    'cargo_truck':        (1, 1, 39, 83, 0, 0, 0),
    'bus':                (1, 1, 39, 82, 0, 0, 0),
    'school_bus':         (1, 1, 39, 82, 12, 0, 0),
    'horse':              (3, 1, 39, 200, 80, 0, 0),
    'horse_with_rider':   (3, 1, 39, 200, 90, 0, 0),
    'tank':               (1, 1, 39, 1, 0, 0, 0),
    'afv':                (1, 1, 39, 2, 0, 0, 0),
    'utility_helicopter': (1, 2, 39, 21, 0, 0, 0),
    'attack_helicopter':  (1, 2, 39, 20, 0, 0, 0),
    'patrol_craft':       (1, 3, 39, 7, 0, 0, 0),
    'civil_airliner':     (1, 2, 39, 87, 0, 0, 0),
}


def reference_heading_axes(lat, lon, heading_deg):
    """CR-001's tested reference encoder (level body x-axis → psi, theta)."""
    la, lo, hd = map(math.radians, (lat, lon, heading_deg))
    north = (-math.sin(la) * math.cos(lo), -math.sin(la) * math.sin(lo), math.cos(la))
    east = (-math.sin(lo), math.cos(lo), 0.0)
    bx = [math.cos(hd) * n + math.sin(hd) * e for n, e in zip(north, east)]
    return bx, math.atan2(bx[1], bx[0]), -math.asin(bx[2])


def local_attitude(lat, lon, psi, theta, phi):
    """Independent inverse: DIS Euler angles → (heading, pitch, roll) degrees in local NED."""
    cps, sps = math.cos(psi), math.sin(psi)
    cth, sth = math.cos(theta), math.sin(theta)
    cph, sph = math.cos(phi), math.sin(phi)
    # Columns of Rz(psi)·Ry(theta)·Rx(phi): the body axes expressed in ECEF.
    bx = (cps * cth, sps * cth, -sth)
    by = (cps * sth * sph - sps * cph, sps * sth * sph + cps * cph, cth * sph)
    bz = (cps * sth * cph + sps * sph, sps * sth * cph - cps * sph, cth * cph)
    n, e, d = ned_axes(lat, lon)
    dot = lambda a, b: sum(x * y for x, y in zip(a, b))
    heading = math.degrees(math.atan2(dot(bx, e), dot(bx, n))) % 360.0
    pitch = math.degrees(-math.asin(dot(bx, d)))
    roll = math.degrees(math.atan2(dot(by, d), dot(bz, d)))
    return heading, pitch, roll


def pdu(**over):
    kw = dict(entity_id=(1, 42, 3), force=3, entity_type=ENTITY_TYPES['civil_airliner'],
              marking='flight3', lat=YOW[0], lon=YOW[1], alt_m=10668.0, heading_deg=90.0,
              ground_speed_ms=450 * 0.514444)
    kw.update(over)
    return pack_entity_state(**kw)


class EntityStateLayoutTest(unittest.TestCase):
    def test_length_and_header(self):
        p = pdu()
        self.assertEqual(len(p), 144)
        version, exercise, pdu_type, family, _ts, length, _status, _pad = struct.unpack_from('>BBBBIHBB', p, 0)
        self.assertEqual((version, exercise, pdu_type, family, length), (7, 1, 1, 1, 144))

    def test_ids_force_and_marking(self):
        p = pdu()
        self.assertEqual(struct.unpack_from('>HHH', p, 12), (1, 42, 3))
        self.assertEqual(struct.unpack_from('>BB', p, 18), (3, 0))
        self.assertEqual(p[128:140], b'\x01flight3\0\0\0\0')
        self.assertEqual(pdu(marking='ABCDEFGHIJKLMNOP')[128:140], b'\x01ABCDEFGHIJK')

    def test_every_cr002_type_byte_for_byte(self):
        self.assertEqual(set(ENTITY_TYPES), set(CR002_TABLE))
        for name, fields in CR002_TABLE.items():
            with self.subTest(name=name):
                want = struct.pack('>BBHBBBB', *fields)
                self.assertEqual(pdu(entity_type=ENTITY_TYPES[name])[20:28], want)

    def test_country_is_siso_canada(self):
        for name, fields in ENTITY_TYPES.items():
            with self.subTest(name=name):
                self.assertEqual(fields[2], 39)
                self.assertEqual(struct.unpack_from('>H', pdu(entity_type=fields), 22)[0], 39)

    def test_location_is_ecef(self):
        x, y, z = struct.unpack_from('>ddd', pdu(), 48)
        self.assertEqual((x, y, z), ecef(YOW[0], YOW[1], 10668.0))

    def test_velocity_level_east(self):
        vx, vy, vz = struct.unpack_from('>fff', pdu(), 36)
        speed = 450 * 0.514444
        self.assertAlmostEqual(math.sqrt(vx * vx + vy * vy + vz * vz), speed, places=2)
        _, east, _ = ned_axes(*YOW)
        self.assertAlmostEqual(vx * east[0] + vy * east[1] + vz * east[2], speed, places=2)

    def test_velocity_climb(self):
        vx, vy, vz = struct.unpack_from('>fff', pdu(ground_speed_ms=0.0, vertical_ms=5.0), 36)
        _, _, down = ned_axes(*YOW)
        self.assertAlmostEqual(vx * down[0] + vy * down[1] + vz * down[2], -5.0, places=4)


class OrientationTest(unittest.TestCase):
    def test_level_matches_cr001_reference(self):
        for heading in (0.0, 45.0, 90.0, 213.0, 359.0):
            psi, theta, phi = orientation(YOW[0], YOW[1], heading)
            _, want_psi, want_theta = reference_heading_axes(YOW[0], YOW[1], heading)
            self.assertAlmostEqual(psi, want_psi, places=9)
            self.assertAlmostEqual(theta, want_theta, places=9)
            self.assertAlmostEqual(local_attitude(YOW[0], YOW[1], psi, theta, phi)[2], 0.0, places=9)

    def test_pitch_and_roll_round_trip(self):
        for lat, lon in (YOW, (45.05, -78.02), (-33.9, 151.2)):
            for heading, pitch, roll in ((30.0, 10.0, 25.0), (250.0, -8.0, -30.0), (90.0, 0.0, 15.0)):
                with self.subTest(lat=lat, heading=heading, pitch=pitch, roll=roll):
                    got = local_attitude(lat, lon, *orientation(lat, lon, heading, pitch, roll))
                    self.assertAlmostEqual(got[0], heading, places=6)
                    self.assertAlmostEqual(got[1], pitch, places=6)
                    self.assertAlmostEqual(got[2], roll, places=6)

    def test_packed_orientation_carries_roll(self):
        psi, theta, phi = struct.unpack_from('>fff', pdu(roll_deg=20.0, pitch_deg=5.0), 72)
        _, pitch, roll = local_attitude(YOW[0], YOW[1], psi, theta, phi)
        self.assertAlmostEqual(roll, 20.0, places=3)    # float32 on the wire
        self.assertAlmostEqual(pitch, 5.0, places=3)


class RemoveEntityTest(unittest.TestCase):
    def test_layout(self):
        p = pack_remove_entity((1, 42, 3), exercise=1)
        self.assertEqual(len(p), 28)
        self.assertEqual(struct.unpack_from('>BBBB', p, 0), (7, 1, 12, 5))
        self.assertEqual(struct.unpack_from('>H', p, 8), (28,))
        self.assertEqual(struct.unpack_from('>HHHHHHI', p, 12), (0, 0, 0, 1, 42, 3, 0))


if __name__ == '__main__':
    unittest.main()
