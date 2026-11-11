# Scenarios — CGF scenario files

Each `.json` file here is a named, repeatable set of DIS entities that
`cgf/runner.py` plays in real time, as Entity State PDUs. They exist to drive
`~/Projects/moving-map-display` test cases (CR-002, CR-003). The parent
[`README.md`](../README.md) covers the rest of Sensors.

```bash
python simulation_manager.py --scenario-file scenarios/ottawa-mixed.json --dis --headless
python -m cgf.runner scenarios/ottawa-mixed.json --port 3000        # same, without the manager
```

| File | Exercises |
|---|---|
| `ottawa-mixed.json` | Ownship utility helicopter (1.42.1) over Ottawa with a 180° reversal and a 20 s hover; every CR-002 entity type on all four sides, within 25 NM of YOW |

---

## Format

Standard-library `json`. Top level:

| Key | Meaning |
|---|---|
| `name`, `description` | Free text, printed at start |
| `duration_s` | Optional; the runner stops (sending Remove Entity for everything) after this long. Omit to run until Ctrl-C |
| `defaults` | `site` (1), `app` (42), `update_s` (1.0) for every entity |
| `entities` | List of entity objects, below |

Each entity:

| Key | Meaning |
|---|---|
| `callsign` | Required; sent as the 11-character marking |
| `type` | A catalogue name (below) or 7 integers `[kind, domain, country, category, subcategory, specific, extra]` |
| `force` | `friendly`/`opposing`/`neutral`/`unknown` (or `other`), or 0–255 |
| `entity` | Entity number, with `site`/`app` from `defaults`; or `id: [site, app, entity]`. Defaults to its position in the list |
| `ownship` | `true` for at most one entity; the runner prints its ID for `listen --ownship` |
| `speed_kts` / `speed_ms` | Cruise speed; required |
| `waypoints` | `[lat, lon, alt_m]`, or `{"lat", "lon", "alt_m", "hold_s", "speed_kts"}`. `hold_s` stops and holds there (a hover), still sending |
| `loop` | Return to the first waypoint after the last; otherwise park at the last, still sending |
| `start_s`, `stop_s` | Appear at `start_s`; at `stop_s`, send Remove Entity and stop |
| `update_s` | Seconds between Entity State PDUs (default 1.0) |
| `motion` | Override the motion model: `land`, `lifeform`, `surface`, `helicopter`, `fixed_wing` |

**Entity type catalogue** (`gateways/dis_pdu.py`, CR-002 table): `car`,
`cargo_truck`, `bus`, `school_bus`, `horse`, `horse_with_rider`, `tank`, `afv`,
`utility_helicopter`, `attack_helicopter`, `patrol_craft`, `civil_airliner`.

## Motion

Entities travel **in straight lines between waypoints**; road-following is
future work (Bobby, CR-002). `cgf/motion.py` limits turn rate, acceleration and
climb by motion model, so corners are rounded and orientation is real:

| Model | Turn | Accel | Climb | Pitch / roll |
|---|---|---|---|---|
| `land` | 20°/s | 2 m/s² | 2 m/s | level |
| `lifeform` | 45°/s | 1 m/s² | 1 m/s | level |
| `surface` | 8°/s | 0.5 m/s² | 0.5 m/s | level |
| `helicopter` | 6°/s (20°/s yaw in a hover) | 2 m/s² | 5 m/s | bank atan(v·ω/g); climb angle minus atan(a/g) |
| `fixed_wing` | 3°/s | 1.5 m/s² | 10 m/s | bank atan(v·ω/g); climb angle |

Heading is the current bearing to the next waypoint, re-computed every 0.1 s
step. Terrain is not modelled: a ground entity's altitude is whatever its
waypoints say.
