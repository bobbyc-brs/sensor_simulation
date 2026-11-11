"""Scenario files for the CGF: load, validate and expand to a list of entity specs.

A scenario is JSON (stdlib json). Format, per CR-002 — see scenarios/README.md:

    {
      "name": "ottawa-mixed",
      "description": "...",
      "duration_s": null,                       # optional; run until stopped
      "defaults": {"site": 1, "app": 42, "update_s": 1.0},
      "entities": [
        {
          "callsign": "HELO1",
          "type": "utility_helicopter",          # catalogue name, or 7 numbers
          "force": "friendly",                   # or 0..3
          "entity": 1,                           # or "id": [site, app, entity]
          "ownship": true,
          "speed_kts": 90,                       # or "speed_ms"
          "waypoints": [[45.42, -75.70, 150],    # lat, lon, alt_m
                        {"lat": 45.43, "lon": -75.68, "alt_m": 120, "hold_s": 30}],
          "loop": true,
          "start_s": 0, "stop_s": null,
          "on_stop": "remove",                   # or "silent": stop without Remove Entity
          "restart_s": null                      # reappear, same ID, after stop_s
        }
      ],
      "generate": [ {"count": 199, "seed": 1, ...} ]   # seeded random entities (CR-003)
    }
"""
import json
import math
import random

from gateways.dis_pdu import ENTITY_TYPES, FORCE_NAMES

# Generator defaults per catalogue type: force, speed range (kt), altitude range (m)
TYPE_DEFAULTS = {
    'car':                {'force': 3, 'speed_kts': (30, 55), 'alt_m': (60, 120)},
    'cargo_truck':        {'force': 3, 'speed_kts': (30, 50), 'alt_m': (60, 120)},
    'bus':                {'force': 3, 'speed_kts': (20, 40), 'alt_m': (60, 120)},
    'school_bus':         {'force': 3, 'speed_kts': (25, 40), 'alt_m': (60, 120)},
    'horse':              {'force': 3, 'speed_kts': (4, 10), 'alt_m': (60, 120)},
    'horse_with_rider':   {'force': 0, 'speed_kts': (4, 10), 'alt_m': (60, 120)},
    'tank':               {'force': 1, 'speed_kts': (15, 25), 'alt_m': (60, 120)},
    'afv':                {'force': 2, 'speed_kts': (15, 30), 'alt_m': (60, 120)},
    'utility_helicopter': {'force': 1, 'speed_kts': (80, 120), 'alt_m': (150, 600)},
    'attack_helicopter':  {'force': 2, 'speed_kts': (90, 140), 'alt_m': (150, 600)},
    'patrol_craft':       {'force': 3, 'speed_kts': (10, 25), 'alt_m': (45, 45)},
    'civil_airliner':     {'force': 3, 'speed_kts': (180, 250), 'alt_m': (1500, 6000)},
}
# How far a generated entity's waypoints wander from its start, by motion model (km)
LEG_KM = {'land': 3.0, 'lifeform': 1.0, 'surface': 3.0, 'helicopter': 10.0, 'fixed_wing': 30.0}
NM_KM = 1.852

KTS_TO_MS = 0.514444
MOTION_CLASSES = ('land', 'lifeform', 'surface', 'helicopter', 'fixed_wing')
HELICOPTER_CATEGORIES = range(20, 30)   # air-domain categories 20–29 are rotary wing


class ScenarioError(ValueError):
    """A scenario file that cannot be run, with the reason."""


def motion_class(entity_type):
    """Default motion model for a 7-number DIS entity type."""
    kind, domain, _country, category = entity_type[:4]
    if kind == 3:
        return 'lifeform'
    if domain == 2:
        return 'helicopter' if category in HELICOPTER_CATEGORIES else 'fixed_wing'
    if domain == 3:
        return 'surface'
    return 'land'


def _entity_type(value, where):
    if isinstance(value, str):
        if value not in ENTITY_TYPES:
            raise ScenarioError(f'{where}: unknown type {value!r}; known: {", ".join(sorted(ENTITY_TYPES))}')
        return ENTITY_TYPES[value]
    if isinstance(value, list) and len(value) == 7 and all(isinstance(v, int) for v in value):
        return tuple(value)
    raise ScenarioError(f'{where}: type must be a catalogue name or 7 integers')


def _force(value, where):
    if isinstance(value, str) and value in FORCE_NAMES:
        return FORCE_NAMES[value]
    if isinstance(value, int) and 0 <= value <= 255:
        return value
    raise ScenarioError(f'{where}: force must be 0-255 or one of {", ".join(FORCE_NAMES)}')


def _speed_ms(spec, where, required=True):
    if 'speed_ms' in spec:
        return float(spec['speed_ms'])
    if 'speed_kts' in spec:
        return float(spec['speed_kts']) * KTS_TO_MS
    if required:
        raise ScenarioError(f'{where}: needs speed_kts or speed_ms')
    return None


def _waypoint(value, where):
    if isinstance(value, list) and len(value) == 3:
        return {'lat': float(value[0]), 'lon': float(value[1]), 'alt_m': float(value[2]),
                'hold_s': 0.0, 'speed_ms': None}
    if isinstance(value, dict) and {'lat', 'lon', 'alt_m'} <= value.keys():
        return {'lat': float(value['lat']), 'lon': float(value['lon']), 'alt_m': float(value['alt_m']),
                'hold_s': float(value.get('hold_s', 0.0)),
                'speed_ms': _speed_ms(value, where, required=False)}
    raise ScenarioError(f'{where}: waypoint must be [lat, lon, alt_m] or an object with lat, lon, alt_m')


def entity_spec(raw, index, defaults):
    """Validate one scenario entity and return a normalised dict."""
    where = f'entity {index} ({raw.get("callsign", "?")})'
    if 'callsign' not in raw:
        raise ScenarioError(f'{where}: needs a callsign')
    entity_type = _entity_type(raw.get('type'), where)
    if 'id' in raw:
        entity_id = tuple(int(v) for v in raw['id'])
        if len(entity_id) != 3:
            raise ScenarioError(f'{where}: id must be [site, app, entity]')
    else:
        entity_id = (int(raw.get('site', defaults['site'])), int(raw.get('app', defaults['app'])),
                     int(raw.get('entity', index + 1)))
    if not all(1 <= v <= 0xFFFE for v in entity_id):
        raise ScenarioError(f'{where}: id values must be 1-65534')
    waypoints = [_waypoint(w, f'{where} waypoint {i + 1}') for i, w in enumerate(raw.get('waypoints', []))]
    if not waypoints:
        raise ScenarioError(f'{where}: needs at least one waypoint')
    motion = raw.get('motion', motion_class(entity_type))
    if motion not in MOTION_CLASSES:
        raise ScenarioError(f'{where}: motion must be one of {", ".join(MOTION_CLASSES)}')
    start_s = float(raw.get('start_s', 0.0))
    stop_s = raw.get('stop_s')
    if stop_s is not None and float(stop_s) <= start_s:
        raise ScenarioError(f'{where}: stop_s must be after start_s')
    on_stop = raw.get('on_stop', 'remove')
    if on_stop not in ('remove', 'silent'):
        raise ScenarioError(f'{where}: on_stop must be "remove" or "silent"')
    restart_s = raw.get('restart_s')
    if restart_s is not None and (stop_s is None or float(restart_s) <= float(stop_s)):
        raise ScenarioError(f'{where}: restart_s needs a stop_s and must come after it')
    return {
        'callsign': str(raw['callsign']),
        'type': entity_type,
        'force': _force(raw.get('force', 0), where),
        'id': entity_id,
        'ownship': bool(raw.get('ownship', False)),
        'speed_ms': _speed_ms(raw, where),
        'waypoints': waypoints,
        'loop': bool(raw.get('loop', False)),
        'motion': motion,
        'start_s': start_s,
        'stop_s': None if stop_s is None else float(stop_s),
        'on_stop': on_stop,
        'restart_s': None if restart_s is None else float(restart_s),
        'update_s': float(raw.get('update_s', defaults['update_s'])),
    }


def _offset(lat, lon, rng, max_km):
    """A point uniformly distributed within max_km of (lat, lon) — flat-earth, fine under 200 km."""
    r_km = max_km * math.sqrt(rng.random())
    theta = rng.uniform(0, 2 * math.pi)
    dlat = r_km * math.cos(theta) / 111.32
    dlon = r_km * math.sin(theta) / (111.32 * math.cos(math.radians(lat)))
    return lat + dlat, lon + dlon


def generated_entities(gen, where):
    """Expand one "generate" block into raw entity dicts (deterministic for a seed).

    Keys: count, seed, centre [lat, lon], radius_nm, types (catalogue names,
    cycled for an even mix), site, app, first_entity, callsign_prefix, update_s,
    waypoints (per entity, default 3).
    """
    try:
        count = int(gen['count'])
        centre_lat, centre_lon = (float(v) for v in gen['centre'])
        radius_km = float(gen['radius_nm']) * NM_KM
    except (KeyError, TypeError, ValueError) as exc:
        raise ScenarioError(f'{where}: needs count, centre [lat, lon] and radius_nm') from exc
    types = gen.get('types', sorted(TYPE_DEFAULTS))
    unknown = [t for t in types if t not in TYPE_DEFAULTS]
    if unknown:
        raise ScenarioError(f'{where}: unknown types {unknown}')
    rng = random.Random(gen.get('seed', 0))
    first = int(gen.get('first_entity', 1))
    prefix = gen.get('callsign_prefix', 'G')
    n_waypoints = int(gen.get('waypoints', 3))

    out = []
    for i in range(count):
        name = types[i % len(types)]
        defaults = TYPE_DEFAULTS[name]
        leg_km = LEG_KM[motion_class(ENTITY_TYPES[name])]
        start = _offset(centre_lat, centre_lon, rng, max(radius_km - leg_km, 0.0))
        waypoints = []
        for _ in range(n_waypoints):
            lat, lon = _offset(start[0], start[1], rng, leg_km)
            waypoints.append([round(lat, 6), round(lon, 6), round(rng.uniform(*defaults['alt_m']))])
        out.append({
            'callsign': f'{prefix}{first + i}',
            'type': name,
            'force': defaults['force'],
            'site': gen.get('site', 1),
            'app': gen.get('app', 42),
            'entity': first + i,
            'speed_kts': round(rng.uniform(*defaults['speed_kts']), 1),
            'update_s': gen.get('update_s', 1.0),
            'loop': True,
            'waypoints': waypoints,
        })
    return out


def load_scenario(path):
    """Read and validate a scenario file; returns a dict with 'entities' expanded."""
    with open(path, encoding='utf-8') as fh:
        try:
            raw = json.load(fh)
        except json.JSONDecodeError as exc:
            raise ScenarioError(f'{path}: not valid JSON — {exc}') from exc
    return build_scenario(raw, source=str(path))


def build_scenario(raw, source='<scenario>'):
    """Validate an already-parsed scenario dict."""
    defaults = {'site': 1, 'app': 42, 'update_s': 1.0}
    defaults.update(raw.get('defaults', {}))
    raw_entities = list(raw.get('entities', []))
    for g, gen in enumerate(raw.get('generate', [])):
        raw_entities += generated_entities(gen, f'{source} generate[{g}]')
    entities = [entity_spec(e, i, defaults) for i, e in enumerate(raw_entities)]
    if not entities:
        raise ScenarioError(f'{source}: no entities')

    seen = {}
    for e in entities:
        if e['id'] in seen:
            raise ScenarioError(
                f'{source}: {e["callsign"]} and {seen[e["id"]]} share entity ID {".".join(map(str, e["id"]))}')
        seen[e['id']] = e['callsign']
    ownships = [e['callsign'] for e in entities if e['ownship']]
    if len(ownships) > 1:
        raise ScenarioError(f'{source}: more than one ownship ({", ".join(ownships)})')

    duration = raw.get('duration_s')
    return {
        'name': raw.get('name', source),
        'description': raw.get('description', ''),
        'duration_s': None if duration is None else float(duration),
        'entities': entities,
    }
