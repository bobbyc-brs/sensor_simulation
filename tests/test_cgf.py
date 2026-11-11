"""Unit tests for the CGF (CR-002): scenario parsing, motion, current-bearing heading.

Run from the project root:  python -m unittest discover -s tests -t .
"""
import copy
import unittest

from cgf.motion import Mover, bearing_deg, distance_m
from cgf.runner import STEP_S, Track, tick
from cgf.scenario import ScenarioError, build_scenario, load_scenario
from gateways.dis_pdu import ENTITY_TYPES
from geo.eastern_canada import airport_position, initial_bearing_deg, interpolate_great_circle
from vehicles.vehicle_sim import current_heading

YOW = (45.3225, -75.6692)
NM = 1852.0

MINIMAL = {
    'entities': [
        {'callsign': 'A', 'type': 'car', 'force': 'neutral', 'speed_kts': 40,
         'waypoints': [[45.40, -75.70, 70], [45.41, -75.70, 70]]},
    ]
}


def spec_for(motion_type, speed_kts, waypoints, loop=False):
    raw = {'entities': [{'callsign': 'T', 'type': motion_type, 'force': 1, 'speed_kts': speed_kts,
                         'loop': loop, 'waypoints': waypoints}]}
    return build_scenario(raw)['entities'][0]


class ScenarioFileTest(unittest.TestCase):
    def test_ottawa_mixed_meets_cr002(self):
        sc = load_scenario('scenarios/ottawa-mixed.json')
        entities = sc['entities']
        self.assertEqual({e['force'] for e in entities}, {0, 1, 2, 3})
        self.assertEqual({e['type'] for e in entities}, set(ENTITY_TYPES.values()))
        ownships = [e for e in entities if e['ownship']]
        self.assertEqual(len(ownships), 1)
        self.assertEqual(ownships[0]['type'], ENTITY_TYPES['utility_helicopter'])
        self.assertEqual(ownships[0]['force'], 1)
        for e in entities:
            for wp in e['waypoints']:
                self.assertLess(distance_m(*YOW, wp['lat'], wp['lon']), 25 * NM, e['callsign'])

    def test_defaults_and_units(self):
        e = build_scenario(MINIMAL)['entities'][0]
        self.assertEqual(e['id'], (1, 42, 1))
        self.assertEqual(e['force'], 3)
        self.assertAlmostEqual(e['speed_ms'], 40 * 0.514444)
        self.assertEqual(e['motion'], 'land')
        self.assertEqual(e['waypoints'][0]['alt_m'], 70.0)

    def test_numeric_type_and_explicit_id(self):
        raw = copy.deepcopy(MINIMAL)
        raw['entities'][0].update(type=[1, 2, 124, 20, 0, 0, 0], id=[2, 42, 5])
        e = build_scenario(raw)['entities'][0]
        self.assertEqual(e['type'], (1, 2, 124, 20, 0, 0, 0))
        self.assertEqual(e['motion'], 'helicopter')
        self.assertEqual(e['id'], (2, 42, 5))

    def test_rejects_bad_scenarios(self):
        dup = copy.deepcopy(MINIMAL)
        dup['entities'].append(dict(dup['entities'][0], callsign='B', entity=1))   # A is entity 1 too
        two_ownships = copy.deepcopy(MINIMAL)
        two_ownships['entities'].append(dict(two_ownships['entities'][0], callsign='B', entity=2))
        for e in two_ownships['entities']:
            e['ownship'] = True
        unknown_type = copy.deepcopy(MINIMAL)
        unknown_type['entities'][0]['type'] = 'spaceship'
        no_speed = copy.deepcopy(MINIMAL)
        del no_speed['entities'][0]['speed_kts']
        for name, raw in (('duplicate id', dup), ('two ownships', two_ownships),
                          ('unknown type', unknown_type), ('no speed', no_speed)):
            with self.subTest(name), self.assertRaises(ScenarioError):
                build_scenario(raw)


class MotionTest(unittest.TestCase):
    def run_mover(self, mover, seconds):
        for _ in range(int(round(seconds / STEP_S))):
            mover.step(STEP_S)

    def test_heading_is_current_bearing(self):
        # A long east-west leg: the great-circle bearing changes along the way.
        spec = spec_for('civil_airliner', 400, [[50.0, -100.0, 10000], [50.0, -60.0, 10000]])
        mover = Mover(spec)
        start = mover.heading
        self.run_mover(mover, 3600)
        want = bearing_deg(mover.lat, mover.lon, 50.0, -60.0)
        self.assertAlmostEqual(mover.heading, want, delta=0.1)
        self.assertGreater(abs(mover.heading - start), 5.0)

    def test_turn_rolls_and_climb_pitches(self):
        spec = spec_for('utility_helicopter', 90,
                        [[45.40, -75.70, 200], [45.42, -75.70, 200], [45.40, -75.70, 400]])
        mover = Mover(spec)
        rolls, pitches = [], []
        for _ in range(int(240 / STEP_S)):
            mover.step(STEP_S)
            pitch, roll = mover.attitude()
            rolls.append(abs(roll))
            pitches.append(abs(pitch))
        self.assertGreater(max(rolls), 10.0)
        self.assertGreater(max(pitches), 2.0)

    def test_hover_holds_position_at_zero_speed(self):
        spec = spec_for('utility_helicopter', 90,
                        [[45.40, -75.70, 200], {'lat': 45.41, 'lon': -75.70, 'alt_m': 150, 'hold_s': 30},
                         [45.42, -75.70, 200]])
        mover = Mover(spec)
        for _ in range(int(300 / STEP_S)):
            mover.step(STEP_S)
            if mover.hold_until is not None:
                break
        self.assertIsNotNone(mover.hold_until, 'never reached the hover')
        lat, lon = mover.lat, mover.lon
        self.run_mover(mover, 10)
        self.assertEqual(mover.speed, 0.0)
        self.assertLess(distance_m(lat, lon, mover.lat, mover.lon), 1.0)
        self.assertEqual(mover.attitude()[1], 0.0)
        self.run_mover(mover, 60)
        self.assertGreater(mover.speed, 0.0)   # left the hover

    def test_ground_entities_stay_level(self):
        mover = Mover(spec_for('car', 50, [[45.40, -75.70, 70], [45.41, -75.69, 70], [45.40, -75.68, 70]]))
        for _ in range(int(120 / STEP_S)):
            mover.step(STEP_S)
            self.assertEqual(mover.attitude(), (0.0, 0.0))


class RunnerTickTest(unittest.TestCase):
    def test_start_and_stop_send_and_remove(self):
        raw = copy.deepcopy(MINIMAL)
        raw['entities'][0].update(start_s=2.0, stop_s=4.0)
        track = Track(build_scenario(raw)['entities'][0], phase_s=0.0)
        sent = []
        t = 0.0
        while t < 5.0:
            t += STEP_S
            pdus, _ = tick([track], round(t, 6), exercise=1)
            sent += [(round(t, 1), p[2]) for p in pdus]
        types = [pdu_type for _, pdu_type in sent]
        self.assertEqual(sent[0][0], 2.0)              # nothing before start_s
        self.assertEqual(types.count(12), 1)          # one Remove Entity at stop_s
        self.assertEqual(sent[-1], (4.0, 12))


class VehicleSimHeadingTest(unittest.TestCase):
    def test_current_heading_follows_great_circle(self):
        lat1, lon1 = airport_position('YYT')
        lat2, lon2 = airport_position('YYZ')
        initial = initial_bearing_deg(lat1, lon1, lat2, lon2)
        mid_lat, mid_lon = interpolate_great_circle(lat1, lon1, lat2, lon2, 0.5)
        mid = current_heading(mid_lat, mid_lon, lat2, lon2, initial)
        self.assertAlmostEqual(mid, initial_bearing_deg(mid_lat, mid_lon, lat2, lon2))
        self.assertGreater(abs(mid - initial), 3.0)    # the old fixed bearing was wrong here
        self.assertEqual(current_heading(lat2, lon2, lat2, lon2, 123.0), 123.0)


if __name__ == '__main__':
    unittest.main()
