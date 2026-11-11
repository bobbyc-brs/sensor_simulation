"""CGF runner: play a scenario file as DIS Entity State PDUs, in real time.

One process for all entities (CR-002/CR-003). Each entity is stepped every
STEP_S, sent every update_s while visible, and removed with a Remove Entity PDU
at its stop_s and on exit (SIGINT/SIGTERM or the scenario's duration_s).

    python -m cgf.runner scenarios/ottawa-mixed.json [--dest 127.0.0.1 --port 3000]
"""
import argparse
import signal
import sys
import time

from cgf.motion import Mover
from cgf.scenario import ScenarioError, load_scenario
from gateways.dis_output import DisOutput, add_output_args
from gateways.dis_pdu import pack_entity_state, pack_remove_entity

STEP_S = 0.1


def dotted(entity_id):
    return '.'.join(str(v) for v in entity_id)


class Track:
    """Runtime state of one scenario entity: motion plus send schedule."""

    def __init__(self, spec, phase_s):
        self.spec = spec
        self.mover = Mover(spec)
        self.visible = False
        self.next_send = spec['start_s'] + phase_s

    def active_at(self, t):
        stop = self.spec['stop_s']
        return t >= self.spec['start_s'] and (stop is None or t < stop)

    def entity_state(self, exercise):
        m, s = self.mover, self.spec
        pitch, roll = m.attitude()
        return pack_entity_state(
            s['id'], s['force'], s['type'], s['callsign'],
            m.lat, m.lon, m.alt_m, m.heading, pitch, roll,
            ground_speed_ms=m.speed, vertical_ms=m.vertical, exercise=exercise)


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
                log.append(f'[CGF] t={t:6.1f}s  appear {dotted(spec["id"])} {spec["callsign"]}')
            if t >= track.next_send:
                pdus.append(track.entity_state(exercise))
                track.next_send += spec['update_s']
                if track.next_send <= t:          # fell behind: resynchronise
                    track.next_send = t + spec['update_s']
        elif track.visible:
            track.visible = False
            pdus.append(pack_remove_entity(spec['id'], exercise=exercise))
            log.append(f'[CGF] t={t:6.1f}s  remove {dotted(spec["id"])} {spec["callsign"]}')
    return pdus, log


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

    specs = scenario['entities']
    tracks = [Track(spec, phase_s=spec['update_s'] * i / len(specs)) for i, spec in enumerate(specs)]
    output = DisOutput.from_args(args)

    print(f'[CGF] {scenario["name"]}: {len(tracks)} entities → {output.describe()}'
          + (f', {duration:.0f} s' if duration else ', until stopped'))
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
    while duration is None or t < duration:
        t += STEP_S
        delay = start + t - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        pdus, log = tick(tracks, t, args.exercise)
        for line in log:
            print(line)
        if pdus:
            output.send(pdus)
    shutdown()


if __name__ == '__main__':
    main()
