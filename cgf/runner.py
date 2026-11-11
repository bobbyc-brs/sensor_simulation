"""CGF runner: play a scenario file as DIS Entity State PDUs, in real time.

One process for all entities (CR-002/CR-003). Each entity is stepped every
STEP_S, sent every update_s while visible, and removed with a Remove Entity PDU
at its stop_s (unless on_stop is "silent") and on exit (SIGINT/SIGTERM or the
scenario's duration_s). An entity with restart_s reappears then, same ID.
A scenario with "repeat": true starts again from t=0 after each duration_s;
entities present in both cycles keep their IDs and simply move, and only those
absent at the new start are removed (CR-005).

Send policy per entity (CR-005): "fixed" sends every update_s; "dead_reckoning"
sends only when a receiver's linear (FPW) extrapolation of the last PDU would be
off by more than dr_threshold_m or dr_threshold_deg, plus a heartbeat every
heartbeat_s (IEEE 1278.1 defaults: 1 m, 3°, 5 s).

    python -m cgf.runner scenarios/ottawa-mixed.json [--dest 127.0.0.1 --port 3800]
"""
import argparse
import signal
import sys
import time

from cgf.motion import Mover
from cgf.scenario import ScenarioError, load_scenario
from gateways.dis_output import DisOutput, add_output_args
from gateways.dis_pdu import DR_FPW, ecef, pack_entity_state, pack_remove_entity, velocity_ecef

STEP_S = 0.1
RATE_REPORT_S = 10.0


def dotted(entity_id):
    return '.'.join(str(v) for v in entity_id)


class Track:
    """Runtime state of one scenario entity: motion plus send schedule."""

    def __init__(self, spec, phase_s):
        self.spec = spec
        self.phase_s = phase_s
        self.mover = Mover(spec)
        self.visible = False
        self.next_send = spec['start_s'] + phase_s
        self.last_sent = None     # (t, ecef, ecef velocity, heading) of the last PDU — dead reckoning

    def _now_kinematics(self):
        m = self.mover
        return (ecef(m.lat, m.lon, m.alt_m),
                velocity_ecef(m.lat, m.lon, m.heading, m.speed, m.vertical))

    def dr_due(self, t):
        """Dead-reckoning policy: would the receiver's extrapolation be off, or is a heartbeat due?"""
        s = self.spec
        if self.last_sent is None:
            return True
        t0, pos0, vel0, heading0 = self.last_sent
        dt = t - t0
        if dt >= s['heartbeat_s'] - 1e-6:
            return True
        pos, _ = self._now_kinematics()
        error_m = sum((p - (p0 + v0 * dt)) ** 2 for p, p0, v0 in zip(pos, pos0, vel0)) ** 0.5
        heading_error = abs((self.mover.heading - heading0 + 180.0) % 360.0 - 180.0)
        return error_m > s['dr_threshold_m'] or heading_error > s['dr_threshold_deg']

    def due(self, t):
        if self.spec['send'] == 'dead_reckoning':
            return self.dr_due(t)
        return t >= self.next_send

    def sent(self, t):
        """Record a send at time t."""
        if self.spec['send'] == 'dead_reckoning':
            pos, vel = self._now_kinematics()
            self.last_sent = (t, pos, vel, self.mover.heading)
            return
        self.next_send += self.spec['update_s']
        if self.next_send <= t:               # fell behind: resynchronise
            self.next_send = t + self.spec['update_s']

    def active_at(self, t):
        s = self.spec
        if s['restart_s'] is not None and t >= s['restart_s']:
            return True
        return t >= s['start_s'] and (s['stop_s'] is None or t < s['stop_s'])

    def entity_state(self, exercise):
        m, s = self.mover, self.spec
        pitch, roll = m.attitude()
        return pack_entity_state(
            s['id'], s['force'], s['type'], s['callsign'],
            m.lat, m.lon, m.alt_m, m.heading, pitch, roll,
            ground_speed_ms=m.speed, vertical_ms=m.vertical, exercise=exercise,
            dr_algorithm=DR_FPW if s['send'] == 'dead_reckoning' else 0)


def tick(tracks, t, exercise):
    """Advance every track to time t; return (PDUs to send, log lines)."""
    pdus, log = [], []
    for track in tracks:
        spec = track.spec
        if t > spec['start_s']:
            track.mover.step(STEP_S)
        if track.active_at(t):
            if not track.visible:
                track.visible = True
                track.next_send = min(track.next_send, t)
                track.last_sent = None            # a (re)appearing entity sends at once
                log.append(f'[CGF] t={t:6.1f}s  appear {dotted(spec["id"])} {spec["callsign"]}')
            if track.due(t):
                pdus.append(track.entity_state(exercise))
                track.sent(t)
        elif track.visible:
            track.visible = False
            if spec['on_stop'] == 'remove':
                pdus.append(pack_remove_entity(spec['id'], exercise=exercise))
                log.append(f'[CGF] t={t:6.1f}s  remove {dotted(spec["id"])} {spec["callsign"]}')
            else:
                log.append(f'[CGF] t={t:6.1f}s  silent {dotted(spec["id"])} {spec["callsign"]} (no Remove Entity)')
    return pdus, log


def restart_cycle(tracks, exercise):
    """Fresh tracks for a repeating scenario's next cycle; PDUs removing what will not be there."""
    fresh = [Track(t.spec, phase_s=t.phase_s) for t in tracks]
    removes = []
    for old, new in zip(tracks, fresh):
        if old.visible and not new.active_at(STEP_S):
            removes.append(pack_remove_entity(old.spec['id'], exercise=exercise))
    return fresh, removes


def main():
    parser = argparse.ArgumentParser(description='Play a CGF scenario file as DIS Entity State PDUs.')
    parser.add_argument('scenario', help='Scenario JSON file, e.g. scenarios/ottawa-mixed.json')
    parser.add_argument('--exercise', type=int, default=1, help='DIS exercise ID (default: 1)')
    parser.add_argument('--duration', type=float, default=None,
                        help="Stop after this many seconds (default: the scenario's duration_s, else run until stopped)")
    add_output_args(parser)
    args = parser.parse_args()

    try:
        scenario = load_scenario(args.scenario)
    except (OSError, ScenarioError) as exc:
        sys.exit(f'[CGF] {exc}')
    duration = args.duration if args.duration is not None else scenario['duration_s']
    repeat = scenario['repeat'] and args.duration is None

    specs = scenario['entities']
    tracks = [Track(spec, phase_s=spec['update_s'] * i / len(specs)) for i, spec in enumerate(specs)]
    output = DisOutput.from_args(args)

    print(f'[CGF] {scenario["name"]}: {len(tracks)} entities → {output.describe()}'
          + (f', {duration:.0f} s cycles, repeating' if repeat
             else f', {duration:.0f} s' if duration else ', until stopped'))
    for spec in specs:
        if spec['ownship']:
            print(f'[CGF] ownship {dotted(spec["id"])} {spec["callsign"]}'
                  f' — moving-map: listen --ownship {dotted(spec["id"])}')

    stopping = []

    def shutdown(sig=None, frame=None):
        # SIGINT and SIGTERM can both arrive (Ctrl-C reaches the process group); act once.
        if stopping:
            return
        stopping.append(sig)
        removes = [pack_remove_entity(t.spec['id'], exercise=args.exercise) for t in tracks if t.visible]
        output.send(removes)
        print(f'[CGF] Sent Remove Entity for {len(removes)} entities; {output.close()}; exiting.')
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    start = time.monotonic()
    t = 0.0
    window_pdus, window_start, next_report = 0, start, RATE_REPORT_S
    cycle_start = 0.0
    while duration is None or repeat or t < duration:
        if repeat and t - cycle_start >= duration - 1e-9:
            tracks[:], removes = restart_cycle(tracks, args.exercise)
            output.send(removes)
            cycle_start = t
            print(f'[CGF] t={t:6.1f}s  cycle restart ({len(removes)} removed)')
        t += STEP_S
        delay = start + t - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        pdus, log = tick(tracks, round(t - cycle_start, 6), args.exercise)
        for line in log:
            print(line)
        if pdus:
            output.send(pdus)
            window_pdus += len(pdus)
        if t >= next_report - 1e-9:
            now = time.monotonic()
            visible = sum(1 for tr in tracks if tr.visible)
            lag = now - (start + t)
            print(f'[CGF] t={t:6.1f}s  {window_pdus / (now - window_start):6.1f} PDU/s  '
                  f'{visible} visible  lag {lag * 1000:4.0f} ms')
            window_pdus, window_start, next_report = 0, now, next_report + RATE_REPORT_S
    shutdown()


if __name__ == '__main__':
    main()
