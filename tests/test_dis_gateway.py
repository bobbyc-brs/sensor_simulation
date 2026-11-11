"""Unit tests for gateways/dis_gateway.py — vehicle/sensor parsing, fusion, IDs (CR-001).

PDU byte layout is tested in test_dis_pdu.py.
Run from the project root:  python -m unittest discover -s tests -t .
"""
import struct
import unittest

from gateways.dis_gateway import (
    EntityIds,
    aircraft_pdu,
    fuse_readings,
    parse_sensor,
    parse_vehicle,
)

YOW = {'name': 'flight3', 'lat': 45.3225, 'lon': -75.6692,
       'heading_deg': 90.0, 'alt_ft': 35000.0, 'speed_kts': 450.0}


class AircraftPduTest(unittest.TestCase):
    def test_airliner_type_force_and_marking(self):
        pdu = aircraft_pdu(YOW, (1, 42, 3), force=3, exercise=1)
        self.assertEqual(len(pdu), 144)
        self.assertEqual(struct.unpack_from('>HHH', pdu, 12), (1, 42, 3))
        self.assertEqual(pdu[18], 3)
        self.assertEqual(struct.unpack_from('>BBHBBBB', pdu, 20), (1, 2, 124, 87, 0, 0, 0))
        self.assertEqual(pdu[128:140], b'\x01flight3\0\0\0\0')


class ParseTest(unittest.TestCase):
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
