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
| `lifecycle.json` | CR-003: LATE (1.42.1) appears at 20 s; SILENT (1.42.2) stops at 25 s with no Remove Entity; REMOVED (1.42.3) is removed at 30 s and reappears at 40 s; DUP-A/DUP-B share entity number 5 on sites 1 and 2 |
| `load-200.json` | CR-003: ownship plus 199 seeded entities of every type within 100 NM of YOW, 1 s updates — 200 PDU/s |
| `zone-crossing.json` | CR-003: ownship helicopter crosses 78°W westward (UTM 18 → 17) about 30 s in, near Bancroft/Maynooth, then turns back; entities on both sides of the line |

Every PDU's timestamp is the DIS relative time it was sent (units of 3600/2³¹ s
past the hour, low bit 0), so a receiver can measure its own latency. The runner
prints its PDU rate and how far it lags real time every 10 s.

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
| `start_s`, `stop_s` | Appear at `start_s`; stop at `stop_s` |
| `on_stop` | `remove` (default): send Remove Entity at `stop_s`. `silent`: just stop sending, so the receiver must time the entity out |
| `restart_s` | Reappear, same ID, at this time (after `stop_s`) |
| `update_s` | Seconds between Entity State PDUs (default 1.0) |
| `motion` | Override the motion model: `land`, `lifeform`, `surface`, `helicopter`, `fixed_wing` |

**Generated entities** — a top-level `generate` list adds seeded random
entities, so a load test stays readable. Each block: `count`, `seed`, `centre`
`[lat, lon]`, `radius_nm`, and optionally `types` (catalogue names, cycled for
an even mix; default all), `site`, `app`, `first_entity`, `callsign_prefix`,
`update_s`, `waypoints` (per entity, default 3). Force, speed and altitude
come from per-type defaults in `cgf/scenario.py`; every generated entity loops.
The same seed always gives the same entities.

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
