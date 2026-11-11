"""Unit tests for gateways/dis_gateway.py — PDU layout per CR-001.

Run from the project root:  python -m unittest discover -s tests -t .
"""
import math
import struct
import unittest

from gateways.dis_gateway import (
    EntityIds,
    fuse_readings,
    parse_sensor,
    ecef,
    heading_axes,
    pack_entity_state,
    pack_remove_entity,
    parse_vehicle,
)

YOW = {'name': 'flight3', 'lat': 45.3225, 'lon': -75.6692,
       'heading_deg': 90.0, 'alt_ft': 35000.0, 'speed_kts': 450.0}


class EntityStateTest(unittest.TestCase):
    def setUp(self):
        self.pdu = pack_entity_state(YOW, 3, exercise=1, site=1, app=42, force=3)

    def test_length_and_header(self):
        self.assertEqual(len(self.pdu), 144)
        version, exercise, pdu_type, family, _ts, length, _status, _pad = struct.unpack_from('>BBBBIHBB', self.pdu, 0)
        self.assertEqual((version, exercise, pdu_type, family, length), (7, 1, 1, 1, 144))

    def test_ids_type_and_marking(self):
        self.assertEqual(struct.unpack_from('>HHH', self.pdu, 12), (1, 42, 3))
        self.assertEqual(struct.unpack_from(">BB", self.pdu, 18), (3, 0))
        self.assertEqual(struct.unpack_from('>BBH', self.pdu, 20), (1, 2, 124))
        self.assertEqual(self.pdu[128:140], b'\x01flight3\0\0\0\0')

    def test_location_round_trips_to_geodetic(self):
        x, y, z = struct.unpack_from('>ddd', self.pdu, 48)
        self.assertEqual((x, y, z), ecef(YOW['lat'], YOW['lon'], YOW['alt_ft'] * 0.3048))
        lon = math.degrees(math.atan2(y, x))
        self.assertAlmostEqual(lon, YOW['lon'], places=9)

    def test_velocity_is_level_and_east(self):
        vx, vy, vz = struct.unpack_from('>fff', self.pdu, 36)
        self.assertAlmostEqual(math.sqrt(vx * vx + vy * vy + vz * vz), 450 * 0.514444, places=2)
        east = (-math.sin(math.radians(YOW['lon'])), math.cos(math.radians(YOW['lon'])), 0.0)
        self.assertAlmostEqual(vx * east[0] + vy * east[1], 450 * 0.514444, places=2)

    def test_orientation_matches_heading_axes(self):
        psi, theta, phi = struct.unpack_from('>fff', self.pdu, 72)
        _, want_psi, want_theta = heading_axes(YOW['lat'], YOW['lon'], YOW['heading_deg'])
        self.assertAlmostEqual(psi, want_psi, places=6)
        self.assertAlmostEqual(theta, want_theta, places=6)
        self.assertEqual(phi, 0.0)

    def test_long_callsign_truncated_to_11(self):
        pdu = pack_entity_state(dict(YOW, name='ABCDEFGHIJKLMNOP'), 1)
        self.assertEqual(pdu[128:140], b'\x01ABCDEFGHIJK')


class RemoveEntityTest(unittest.TestCase):
    def test_layout(self):
        pdu = pack_remove_entity(3, exercise=1, site=1, app=42)
        self.assertEqual(len(pdu), 28)
        self.assertEqual(struct.unpack_from('>BBBB', pdu, 0), (7, 1, 12, 5))
        self.assertEqual(struct.unpack_from('>H', pdu, 8), (28,))
        self.assertEqual(struct.unpack_from('>HHHHHHI', pdu, 12), (0, 0, 0, 1, 42, 3, 0))


class ParseAndIdsTest(unittest.TestCase):
    def test_parse_vehicle(self):
        state = parse_vehicle('vehicle,flight1,45.322500,-75.669200,0.1234,87.0,35000,450')
        self.assertEqual(state['name'], 'flight1')
        self.assertEqual(state['heading_deg'], 87.0)
        self.assertIsNone(parse_vehicle('sensor,x,1,2'))
        self.assertIsNone(parse_vehicle('vehicle,f,a,b,c,d,e,f'))

    def test_parse_sensor(self):
        noisy = parse_sensor('sensor,sensor1,45.300000,-75.600000,0.5000,50.0,flight2')
        self.assertEqual((noisy['lat'], noisy['lon'], noisy['noise_std'], noisy['vehicle']),
                         (45.3, -75.6, 50.0, 'flight2'))
        self.assertEqual(parse_sensor('sensor,r1,45.3,-75.6,0.5,TACAN,flight2')['noise_std'], 150.0)
        self.assertIsNone(parse_sensor('sensor,r1,45.3,-75.6,0.5,TACAN,'))
        self.assertIsNone(parse_sensor('vehicle,flight1,45.3,-75.6,0.1,87.0,35000,450'))

    def test_fuse_readings_weights_by_inverse_variance(self):
        readings = {
            'a': {'lat': 45.0, 'lon': -75.0, 'noise_std': 100.0},
            'b': {'lat': 46.0, 'lon': -76.0, 'noise_std': 200.0},
        }
        lat, lon = fuse_readings(readings)
        self.assertAlmostEqual(lat, 45.2)   # weights 4:1
        self.assertAlmostEqual(lon, -75.2)

    def test_entity_ids_stable(self):
        ids = EntityIds()
        self.assertEqual(ids.get('flight3'), 3)
        self.assertEqual(ids.get('alpha'), 1)
        self.assertEqual(ids.get('flight1'), 2)   # 1 already taken
        self.assertEqual(ids.get('flight3'), 3)


if __name__ == '__main__':
    unittest.main()
