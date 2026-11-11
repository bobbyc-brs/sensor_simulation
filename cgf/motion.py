"""Kinematic waypoint follower for CGF entities (CR-002).

Entities fly or drive **straight** between waypoints — no road-following
(future work, per Bobby) — with limited turn rate, acceleration and climb, so
corners are rounded and orientation is real:

- heading is the current track, re-computed every step toward the next waypoint;
- roll is the coordinated-turn bank, atan(v·ω/g), for air entities;
- pitch is the climb angle, and a helicopter also pitches nose-down to
  accelerate (−atan(a/g)) and nose-up to slow into a hover;
- during a hold, a waypoint's yaw_dps turns the heading on the spot (a hover
  pedal turn), with no roll because the entity is not moving.

Deterministic: the same spec and step size give the same track.
"""
import math

EARTH_R = 6371008.8   # mean radius, metres — adequate for steering over < 200 km
G = 9.80665

# Per motion class: turn rate (deg/s), acceleration (m/s²), climb rate (m/s)
LIMITS = {
    'land':       {'turn_dps': 20.0, 'accel': 2.0, 'climb': 2.0},
    'lifeform':   {'turn_dps': 45.0, 'accel': 1.0, 'climb': 1.0},
    'surface':    {'turn_dps': 8.0,  'accel': 0.5, 'climb': 0.5},
    'helicopter': {'turn_dps': 6.0,  'accel': 2.0, 'climb': 5.0},
    'fixed_wing': {'turn_dps': 3.0,  'accel': 1.5, 'climb': 10.0},
}
AIR_CLASSES = ('helicopter', 'fixed_wing')
HOVER_YAW_DPS = 20.0     # a helicopter below HOVER_SPEED_MS can yaw on the spot
HOVER_SPEED_MS = 2.0
STOP_CAPTURE_M = 3.0
MIN_CAPTURE_M = 15.0
MAX_BANK_DEG = 45.0
MAX_PITCH_DEG = 20.0


def bearing_deg(lat1, lon1, lat2, lon2):
    """Initial great-circle bearing from point 1 to point 2, degrees [0, 360)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return math.degrees(math.atan2(y, x)) % 360.0


def distance_m(lat1, lon1, lat2, lon2):
    """Great-circle (haversine) distance in metres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R * math.asin(min(1.0, math.sqrt(h)))


def destination(lat, lon, heading_deg, dist_m):
    """Point reached travelling dist_m along heading_deg from (lat, lon)."""
    p1, l1 = math.radians(lat), math.radians(lon)
    th, d = math.radians(heading_deg), dist_m / EARTH_R
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(th))
    l2 = l1 + math.atan2(math.sin(th) * math.sin(d) * math.cos(p1),
                         math.cos(d) - math.sin(p1) * math.sin(p2))
    return math.degrees(p2), (math.degrees(l2) + 540.0) % 360.0 - 180.0


def wrap180(deg):
    return (deg + 180.0) % 360.0 - 180.0


def _clamp(value, limit):
    return max(-limit, min(limit, value))


class Mover:
    """One entity's kinematic state, advanced with step(dt)."""

    def __init__(self, spec):
        self.spec = spec
        self.limits = LIMITS[spec['motion']]
        self.waypoints = spec['waypoints']
        first = self.waypoints[0]
        self.lat, self.lon, self.alt_m = first['lat'], first['lon'], first['alt_m']
        self.index = 1 if len(self.waypoints) > 1 else 0
        self.parked = len(self.waypoints) == 1
        self.hold_until = None
        self.t = 0.0
        target = self.waypoints[self.index]
        self.heading = bearing_deg(self.lat, self.lon, target['lat'], target['lon']) if not self.parked else 0.0
        # Fixed-wing aircraft cannot start from rest; everything else accelerates
        # away. A parked entity (one waypoint) starts and stays at rest.
        moving_fixed_wing = spec['motion'] == 'fixed_wing' and not self.parked
        self.speed = spec['speed_ms'] if moving_fixed_wing else 0.0
        self.vertical = 0.0
        self.turn_rate_dps = 0.0
        self.accel = 0.0

    # -- state read by the runner -------------------------------------------

    def attitude(self):
        """(pitch_deg, roll_deg): non-zero only for air entities."""
        if self.spec['motion'] not in AIR_CLASSES:
            return 0.0, 0.0
        roll = math.degrees(math.atan(self.speed * math.radians(self.turn_rate_dps) / G))
        if self.spec['motion'] == 'helicopter':
            pitch = (math.degrees(math.atan2(self.vertical, max(self.speed, 20.0)))
                     - math.degrees(math.atan(self.accel / G)))
        else:
            pitch = math.degrees(math.atan2(self.vertical, max(self.speed, 1.0)))
        return _clamp(pitch, MAX_PITCH_DEG), _clamp(roll, MAX_BANK_DEG)

    # -- integration ----------------------------------------------------------

    def _stops_at(self, waypoint):
        is_last = self.index == len(self.waypoints) - 1
        return waypoint['hold_s'] > 0 or (is_last and not self.spec['loop'])

    def _advance(self):
        self.index += 1
        if self.index >= len(self.waypoints):
            if self.spec['loop']:
                self.index = 0
            else:
                self.index = len(self.waypoints) - 1
                self.parked = True

    def step(self, dt):
        self.t += dt
        lim = self.limits
        holding = self.parked or (self.hold_until is not None and self.t < self.hold_until)
        if self.hold_until is not None and not holding:
            self.hold_until = None
            self._advance()
            holding = self.parked

        target = self.waypoints[self.index]
        dist = distance_m(self.lat, self.lon, target['lat'], target['lon'])
        error = 0.0
        yaw = 0.0
        if holding:
            want_speed = 0.0
            if self.hold_until is not None:
                yaw = target['yaw_dps'] * dt
        else:
            cruise = target['speed_ms'] if target['speed_ms'] is not None else self.spec['speed_ms']
            want_speed = cruise
            if self._stops_at(target):
                want_speed = min(cruise, max(0.5, math.sqrt(2 * lim['accel'] * max(dist - 1.0, 0.0))))
            error = wrap180(bearing_deg(self.lat, self.lon, target['lat'], target['lon']) - self.heading)
            if self.spec['motion'] != 'fixed_wing':
                # Slow down for sharp turns, as a driver or pilot would.
                want_speed *= max(0.2, math.cos(math.radians(min(abs(error), 90.0))))

        turn_dps = lim['turn_dps']
        if self.spec['motion'] == 'helicopter' and self.speed < HOVER_SPEED_MS:
            turn_dps = HOVER_YAW_DPS
        turn = yaw if yaw else _clamp(error, turn_dps * dt)
        self.turn_rate_dps = turn / dt
        self.heading = (self.heading + turn) % 360.0

        dv = _clamp(want_speed - self.speed, lim['accel'] * dt)
        self.speed = max(0.0, self.speed + dv)
        self.accel = dv / dt

        self.vertical = _clamp((target['alt_m'] - self.alt_m) * 0.2, lim['climb'])
        self.alt_m += self.vertical * dt

        if self.speed > 0.0:
            self.lat, self.lon = destination(self.lat, self.lon, self.heading, self.speed * dt)

        if holding:
            return
        dist = distance_m(self.lat, self.lon, target['lat'], target['lon'])
        if self._stops_at(target):
            if dist <= STOP_CAPTURE_M or (dist < 10.0 and self.speed < 1.0):
                # The braking curve has slowed it below ~1 m/s; stop dead so a
                # hover holds its point instead of coasting.
                self.speed, self.accel = 0.0, 0.0
                if target['hold_s'] > 0:
                    self.hold_until = self.t + target['hold_s']
                else:
                    self.parked = True
        else:
            turn_radius = self.speed / math.radians(turn_dps) if turn_dps > 0 else 0.0
            if dist <= max(MIN_CAPTURE_M, turn_radius):
                self._advance()
