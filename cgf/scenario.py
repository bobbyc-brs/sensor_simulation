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
          "start_s": 0, "stop_s": null
        }
      ]
    }
"""
import json

from gateways.dis_pdu import ENTITY_TYPES, FORCE_NAMES

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
        'update_s': float(raw.get('update_s', defaults['update_s'])),
    }


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
    entities = [entity_spec(e, i, defaults) for i, e in enumerate(raw.get('entities', []))]
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
