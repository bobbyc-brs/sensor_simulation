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
        raw['entities'][0].update(type=[1, 2, 39, 20, 0, 0, 0], id=[2, 42, 5])
        e = build_scenario(raw)['entities'][0]
        self.assertEqual(e['type'], (1, 2, 39, 20, 0, 0, 0))
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



def run_ticks(tracks, seconds):
    """Tick tracks for seconds; returns [(t, pdu_type, (site, app, entity))]."""
    import struct
    sent, t = [], 0.0
    while t < seconds - 1e-9:
        t = round(t + STEP_S, 6)
        pdus, _ = tick(tracks, t, exercise=1)
        for p in pdus:
            offset = 12 if p[2] == 1 else 18          # Entity State ID, or Remove's receiving ID
            sent.append((t, p[2], struct.unpack_from('>HHH', p, offset)))
    return sent


class LifecycleTest(unittest.TestCase):
    """CR-003 scenarios/lifecycle.json, stepped offline."""

    @classmethod
    def setUpClass(cls):
        sc = load_scenario('scenarios/lifecycle.json')
        tracks = [Track(spec, 0.0) for spec in sc['entities']]
        cls.sent = run_ticks(tracks, 60.0)

    def times(self, entity_id, pdu_type):
        return [t for t, kind, eid in self.sent if eid == entity_id and kind == pdu_type]

    def test_late_entity_first_sent_at_20s(self):
        self.assertEqual(self.times((1, 42, 1), 1)[0], 20.0)

    def test_silent_entity_stops_without_remove(self):
        self.assertLess(self.times((1, 42, 2), 1)[-1], 25.0)
        self.assertEqual(self.times((1, 42, 2), 12), [])

    def test_removed_entity_returns_with_same_id(self):
        state = self.times((1, 42, 3), 1)
        self.assertEqual(self.times((1, 42, 3), 12), [30.0])
        self.assertFalse([t for t in state if 30.0 <= t < 40.0])
        self.assertEqual(min(t for t in state if t >= 40.0), 40.0)

    def test_duplicate_numbers_on_two_sites(self):
        self.assertGreater(len(self.times((1, 42, 5), 1)), 50)
        self.assertGreater(len(self.times((2, 42, 5), 1)), 50)

    def test_restart_needs_stop(self):
        raw = copy.deepcopy(MINIMAL)
        raw['entities'][0]['restart_s'] = 10
        with self.assertRaises(ScenarioError):
            build_scenario(raw)


class GeneratorTest(unittest.TestCase):
    def test_load_200(self):
        sc = load_scenario('scenarios/load-200.json')
        entities = sc['entities']
        self.assertEqual(len(entities), 200)
        self.assertEqual({e['type'] for e in entities}, set(ENTITY_TYPES.values()))
        self.assertEqual({e['force'] for e in entities}, {0, 1, 2, 3})
        self.assertTrue(all(e['update_s'] == 1.0 for e in entities))
        for e in entities:
            for wp in e['waypoints']:
                self.assertLess(distance_m(*YOW, wp['lat'], wp['lon']), 100 * NM, e['callsign'])

    def test_seeded_and_deterministic(self):
        a = load_scenario('scenarios/load-200.json')['entities']
        b = load_scenario('scenarios/load-200.json')['entities']
        self.assertEqual(a, b)

    def test_rate_is_200_per_second(self):
        sc = load_scenario('scenarios/load-200.json')
        n = len(sc['entities'])
        tracks = [Track(spec, spec['update_s'] * i / n) for i, spec in enumerate(sc['entities'])]
        sent = run_ticks(tracks, 20.0)
        per_second = [sum(1 for t, kind, _ in sent if kind == 1 and s < t <= s + 1) for s in range(5, 20)]
        self.assertTrue(all(195 <= c <= 205 for c in per_second), per_second)


class ZoneCrossingTest(unittest.TestCase):
    def test_ownship_crosses_78w_and_entities_straddle(self):
        sc = load_scenario('scenarios/zone-crossing.json')
        tracks = [Track(spec, 0.0) for spec in sc['entities']]
        heli = tracks[0].mover
        lons = []
        for _ in range(int(60 / STEP_S)):
            for track in tracks:
                track.mover.step(STEP_S)
            lons.append(heli.lon)
        self.assertGreater(lons[0], -78.0)
        self.assertLess(min(lons), -78.0)
        others = [t.mover.lon for t in tracks[1:]]
        self.assertTrue(any(lon > -78.0 for lon in others) and any(lon < -78.0 for lon in others))


# ---------------------------------------------------------------------------
# CR-005
# ---------------------------------------------------------------------------

class SymbolGalleryTest(unittest.TestCase):
    def test_grid_covers_every_force_and_type(self):
        sc = load_scenario('scenarios/symbol-gallery.json')
        ownship, cells = sc['entities'][0], sc['entities'][1:]
        self.assertTrue(ownship['ownship'])
        self.assertEqual(len(cells), 4 * 18)
        raw_types = {(1, 4, 39, 2, 0, 0, 0), (1, 2, 39, 1, 0, 0, 0), (1, 2, 39, 50, 0, 0, 0),
                     (1, 3, 39, 1, 0, 0, 0), (3, 1, 39, 1, 0, 0, 0), (9, 1, 0, 0, 0, 0, 0)}
        self.assertEqual({c['type'] for c in cells}, set(ENTITY_TYPES.values()) | raw_types)
        for force in range(4):
            self.assertEqual(len({c['type'] for c in cells if c['force'] == force}), 18)
        prefix = {1: 'F-', 2: 'O-', 3: 'N-', 0: 'U-'}
        for c in cells:
            self.assertTrue(c['callsign'].startswith(prefix[c['force']]), c['callsign'])
            self.assertLessEqual(len(c['callsign']), 11)

    def test_static_and_within_view(self):
        sc = load_scenario('scenarios/symbol-gallery.json')
        tracks = [Track(spec, 0.0) for spec in sc['entities']]
        start = [(t.mover.lat, t.mover.lon) for t in tracks]
        for _ in range(int(20 / STEP_S)):
            for t in tracks:
                t.mover.step(STEP_S)
        for (lat, lon), t in zip(start, tracks):
            self.assertLess(distance_m(lat, lon, t.mover.lat, t.mover.lon), 0.01, t.spec['callsign'])
            self.assertLess(distance_m(45.40, -75.70, lat, lon), 2.5 * NM)


class ManoeuvresTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sc = load_scenario('scenarios/ownship-manoeuvres.json')
        mover = Mover(sc['entities'][0])
        cls.samples = []
        for _ in range(int(1000 / STEP_S)):
            mover.step(STEP_S)
            cls.samples.append((mover.heading, mover.speed, mover.hold_until is not None,
                                mover.turn_rate_dps) + mover.attitude())

    def test_orbits_both_ways(self):
        right = sum(r * STEP_S for _, v, _, r, _, _ in self.samples if v > 5 and r > 0)
        left = -sum(r * STEP_S for _, v, _, r, _, _ in self.samples if v > 5 and r < 0)
        self.assertGreater(right, 360.0)
        self.assertGreater(left, 360.0)

    def test_heading_crosses_north(self):
        crossings = sum(1 for (a, *_), (b, *_) in zip(self.samples, self.samples[1:])
                        if (a > 340 and b < 20) or (a < 20 and b > 340))
        self.assertGreaterEqual(crossings, 1)

    def test_hover_yaws_a_full_turn(self):
        yaw = sum(abs(r) * STEP_S for _, v, holding, r, _, _ in self.samples if holding and v == 0.0)
        self.assertAlmostEqual(yaw, 360.0, delta=10.0)

    def test_pitch_and_roll(self):
        self.assertGreater(max(abs(p) for *_, p, _ in self.samples), 5.0)
        self.assertGreater(max(abs(r) for *_, r in self.samples), 15.0)


class WaypointFeatureTest(unittest.TestCase):
    def test_orbit_expands_to_a_closed_circle(self):
        raw = copy.deepcopy(MINIMAL)
        raw['entities'][0]['waypoints'] = [
            {'orbit': {'centre': [45.4, -75.7], 'radius_m': 1000, 'alt_m': 100, 'direction': 'ccw', 'start_deg': 90}}]
        wps = build_scenario(raw)['entities'][0]['waypoints']
        self.assertEqual(len(wps), 13)
        self.assertEqual((wps[0]['lat'], wps[0]['lon']), (wps[-1]['lat'], wps[-1]['lon']))
        for w in wps:
            self.assertAlmostEqual(distance_m(45.4, -75.7, w['lat'], w['lon']), 1000.0, delta=0.5)
        self.assertAlmostEqual(bearing_deg(45.4, -75.7, wps[1]['lat'], wps[1]['lon']), 60.0, delta=0.1)

    def test_yaw_needs_a_hold(self):
        raw = copy.deepcopy(MINIMAL)
        raw['entities'][0]['waypoints'][0] = {'lat': 45.4, 'lon': -75.7, 'alt_m': 70, 'yaw_dps': 5}
        with self.assertRaises(ScenarioError):
            build_scenario(raw)

    def test_parked_fixed_wing_stays_put(self):
        mover = Mover(spec_for('civil_airliner', 200, [[45.4, -75.7, 1500]]))
        for _ in range(100):
            mover.step(STEP_S)
        self.assertEqual(mover.speed, 0.0)
        self.assertLess(distance_m(45.4, -75.7, mover.lat, mover.lon), 0.01)


def dr_send_times(entity, seconds):
    sc = build_scenario({'entities': [dict(entity, callsign='X', force=3, send='dead_reckoning')]})
    track = Track(sc['entities'][0], 0.0)
    times, pdus_out, t = [], [], 0.0
    while t < seconds - 1e-9:
        t = round(t + STEP_S, 6)
        pdus, _ = tick([track], t, exercise=1)
        for p in pdus:
            if p[2] == 1:
                times.append(t)
                pdus_out.append(p)
    return times, pdus_out


class DeadReckoningPolicyTest(unittest.TestCase):
    def test_parked_entity_heartbeats_every_5s(self):
        times, _ = dr_send_times({'type': 'car', 'speed_kts': 0, 'waypoints': [[45.4, -75.7, 70]]}, 61)
        gaps = [b - a for a, b in zip(times, times[1:])]
        self.assertEqual(len(times), 13)
        for gap in gaps:
            self.assertAlmostEqual(gap, 5.0, delta=0.1)

    def test_steady_straight_motion_is_heartbeat_only(self):
        times, _ = dr_send_times({'type': 'car', 'speed_kts': 40,
                                  'waypoints': [[45.4, -75.7, 70], [45.6, -75.7, 70]]}, 120)
        late = [b - a for a, b in zip(times, times[1:]) if a > 40]     # after reaching cruise speed
        self.assertTrue(late)
        self.assertTrue(all(abs(g - 5.0) <= 0.1 for g in late), late)

    def test_turning_entity_sends_more_often(self):
        times, _ = dr_send_times({'type': 'utility_helicopter', 'speed_kts': 90, 'loop': True,
                                  'waypoints': [{'orbit': {'centre': [45.4, -75.7], 'radius_m': 1500,
                                                           'alt_m': 200}}]}, 300)
        gaps = [b - a for a, b in zip(times, times[1:]) if a > 60]
        self.assertLess(sum(gaps) / len(gaps), 2.5)

    def test_dr_algorithm_byte(self):
        _, pdus = dr_send_times({'type': 'car', 'speed_kts': 0, 'waypoints': [[45.4, -75.7, 70]]}, 1)
        self.assertEqual(pdus[0][88], 2)                       # FPW
        fixed = Track(build_scenario(MINIMAL)['entities'][0], 0.0)
        self.assertEqual(fixed.entity_state(1)[88], 0)          # default output unchanged

    def test_send_policy_validated(self):
        raw = copy.deepcopy(MINIMAL)
        raw['entities'][0]['send'] = 'sometimes'
        with self.assertRaises(ScenarioError):
            build_scenario(raw)


class DemoTourTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scenario = load_scenario('scenarios/demo-tour.json')
        cls.tracks = [Track(spec, 0.0) for spec in cls.scenario['entities']]
        cls.log, t = [], 0.0
        while t < 600 - 1e-9:
            t = round(t + STEP_S, 6)
            _, lines = tick(cls.tracks, t, exercise=1)
            cls.log += lines

    def test_ten_minute_repeating_cycle(self):
        self.assertEqual(self.scenario['duration_s'], 600.0)
        self.assertTrue(self.scenario['repeat'])

    def test_within_25_nm_and_all_forces(self):
        for e in self.scenario['entities']:
            for w in e['waypoints']:
                self.assertLess(distance_m(*YOW, w['lat'], w['lon']), 25 * NM, e['callsign'])
        self.assertEqual({e['force'] for e in self.scenario['entities']}, {0, 1, 2, 3})

    def test_scripted_events(self):
        joined = '\n'.join(self.log)
        self.assertIn('silent 1.42.9 UAV-X', joined)
        self.assertIn('remove 1.42.8 CAR2', joined)
        self.assertIn('appear 1.42.2 VIPER1', joined)
        self.assertIn('remove 1.42.2 VIPER1', joined)

    def test_ownship_home_before_the_cycle_ends(self):
        heli = self.tracks[0].mover
        self.assertTrue(heli.parked)
        self.assertLess(distance_m(heli.lat, heli.lon, *YOW), 20.0)

    def test_restart_removes_only_what_the_new_cycle_lacks(self):
        from cgf.runner import restart_cycle
        fresh, removes = restart_cycle(self.tracks, exercise=1)
        import struct
        removed = sorted(struct.unpack_from('>HHH', r, 18)[2] for r in removes)
        # Visible at 600 s but not at the new start: the two late convoy vehicles.
        self.assertEqual(removed, [4, 5])
        self.assertEqual([t.phase_s for t in fresh], [t.phase_s for t in self.tracks])

    def test_repeat_needs_duration(self):
        raw = copy.deepcopy(MINIMAL)
        raw['repeat'] = True
        with self.assertRaises(ScenarioError):
            build_scenario(raw)

if __name__ == '__main__':
    unittest.main()
