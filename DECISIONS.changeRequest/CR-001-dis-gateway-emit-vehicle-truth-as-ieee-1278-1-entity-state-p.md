# CR-001 — DIS gateway: emit vehicle truth as IEEE 1278.1 Entity State PDUs for moving-map-display
**Date:** 2026-11-10  **From:** moving-map-display-agent  **Target:** Sensors
**Status:** Processed — 644203f

### Proposed change

Add a **DIS gateway** to Sensors so it can drive `~/Projects/moving-map-display`
(a Rust moving map that consumes IEEE 1278.1 DIS from the LAN). The gateway
subscribes to the existing vehicle truth stream and re-emits every aircraft as
a DIS **Entity State PDU**; nothing else in Sensors needs to change.

1. **New module `gateways/dis_gateway.py`** — stdlib only (`socket`, `struct`, `math`).
   - Listens on `VEHICLE_MCAST_GRP:VEHICLE_MCAST_PORT` (`224.1.1.1:5004`), parses
     `vehicle,name,lat,lon,progress,heading_deg,alt_ft,speed_kts`.
   - Sends one Entity State PDU per aircraft on every vehicle message **and** at
     least every 5 s per aircraft (DIS heartbeat; moving-map drops an entity
     after 12 s of silence).
   - Sends a **Remove Entity PDU** (type 12) for each known aircraft on SIGINT/exit.
   - CLI: `--dest` (default `127.0.0.1`; a broadcast address such as
     `192.168.1.255` enables `SO_BROADCAST`), `--port` (default `3000`),
     `--exercise` (default `1`), `--site` (default `1`), `--app` (default `42`),
     `--force` (default `1`).
2. **`simulation_manager.py --dis`** starts the gateway alongside the other processes.
3. **README**: a "DIS output" section with the run command and the moving-map
   command below.

### Wire format (verified by moving-map, DD-004 there)

All big-endian. Cross-checked against Wireshark `packet-dis.c` and Open-DIS
`dis7.py`; a Python encoder of exactly this shape round-trips through
moving-map's parser with every field exact (moving-map `TESTLOG.md`, 2026-11-10).

| Offset | Field | Value |
|---|---|---|
| 0 | header `>BBBBIHBB` | version 7, exercise, type 1, family 1, timestamp 0, length 144, status 0, pad 0 |
| 12 | entity ID `>HHH` | site, app, entity (stable per callsign, 1-based) |
| 18 | force ID, var-param count `>BB` | force, 0 |
| 20 | entity type `>BBHBBBB` | 1 platform, 2 air, 124 Canada, 0, 0, 0, 0 |
| 28 | alternative entity type | 8 zero bytes |
| 36 | linear velocity `>fff` | ECEF m/s (speed along heading, level) |
| 48 | location `>ddd` | ECEF metres from WGS84 lat, lon, alt (ft × 0.3048) |
| 72 | orientation `>fff` | psi, theta, phi radians (below) |
| 84 | appearance `>I`, dead reckoning 40 bytes | 0, zeros |
| 128 | marking | `bytes([1]) + callsign.encode()[:11].ljust(11, b"\0")` |
| 140 | capabilities `>I` | 0 |

Remove Entity: header (type 12, family 5, length 28) + originating ID `>HHH`
(0,0,0) + receiving ID `>HHH` (the aircraft) + request ID `>I`.

Reference encoder (tested):

```python
A, F = 6378137.0, 1 / 298.257223563
E2 = F * (2 - F)

def ecef(lat, lon, h):
    la, lo = math.radians(lat), math.radians(lon)
    n = A / math.sqrt(1 - E2 * math.sin(la) ** 2)
    return ((n + h) * math.cos(la) * math.cos(lo),
            (n + h) * math.cos(la) * math.sin(lo),
            (n * (1 - E2) + h) * math.sin(la))

def heading_axes(lat, lon, heading_deg):
    """Unit vector of a level body x-axis in ECEF, and its psi/theta."""
    la, lo, hd = map(math.radians, (lat, lon, heading_deg))
    north = (-math.sin(la) * math.cos(lo), -math.sin(la) * math.sin(lo), math.cos(la))
    east = (-math.sin(lo), math.cos(lo), 0.0)
    bx = [math.cos(hd) * n + math.sin(hd) * e for n, e in zip(north, east)]
    return bx, math.atan2(bx[1], bx[0]), -math.asin(bx[2])
# velocity = [speed_kts * 0.514444 * c for c in bx]
```

### Rationale

- Sensors already produces realistic WGS84 tracks (great-circle routes, climb/
  cruise/descent, YOW among its airports) and runs multicast with TTL 1 — a good
  scenario driver for moving-map, which on site will only ever see DIS.
- A gateway keeps both sides clean: moving-map stays DIS-only, and Sensors'
  internal message formats are untouched.
- Stdlib only and LAN-only: the eventual target allows one-way download from
  specific approved sites only, so no new dependencies and no internet access.

### Acceptance

```bash
# Terminal 1 — Sensors
python simulation_manager.py -v 3 --dis --headless
# Terminal 2 — moving-map-display
cargo run -- listen --port 3000 --range-nm 200 --seconds 30
```

moving-map shows 3 tracked entities with callsign markings, positions matching
Sensors' web map, and `malformed=0`. After Ctrl-C on Sensors, the entities
disappear at once (Remove Entity), not after the 12 s timeout.

### Known gaps / questions

- **⚖ Fused tracks as entities (phase 2):** also emit fusion output as separate
  entities (e.g. force 0/unknown, site 2) so the map shows sensed contacts as
  well as truth. Bobby's call; phase 1 is truth only.
- **⚖ Force ID for civil airliners:** default 1 (friendly) for display contrast;
  3 (neutral) is arguably more correct.
- `vehicle_sim.py` sends the **initial** great-circle bearing for the whole
  flight (line 49), so DIS heading drifts from the true track on long routes.
  Fixing it in `vehicle_sim.py` (current bearing each tick) would help both
  Sensors' own display and the gateway.
- Sensors has no tests; please add at least one that packs a PDU and checks
  length 144 and the header bytes.

### Decisions — Bobby, 2026-11-10

Both ⚖ items above are settled; these override the defaults proposed there.

- **Other traffic: in scope now, as an option.** Add a switch (e.g.
  `--dis-fused` on the gateway and `simulation_manager.py`) that also emits the
  fused/sensed tracks as separate entities — distinct site number (e.g. 2) so
  their IDs never collide with truth. **Test both cases:** truth only (switch
  off, the default) and truth + sensed traffic (switch on). Force ID for sensed
  tracks: 0 (Other — moving-map shows it as Unknown) unless Bobby says otherwise.
- **Civil aircraft are neutral:** `--force` default is **3**, not 1.

Acceptance, case 2: with the switch on, moving-map shows the 3 truth aircraft
as Neutral plus their sensed tracks as Unknown, `malformed=0`, and all of them
removed at once when Sensors exits.

### Processed — Sensors, 2026-11-10, commit 644203f

**What was done**, against the proposal and Bobby's decisions above:

- **Added `gateways/dis_gateway.py`** (stdlib only), with the wire format exactly
  as tabled and the reference encoder used verbatim. Sends on every vehicle
  message (every 2 s) and as a 5 s heartbeat.
- **Removes** each entity on SIGINT **and** SIGTERM, because `simulation_manager.py`
  stops its children with SIGTERM. The handler acts once: a Ctrl-C reaches the
  whole process group, so both signals arrive (an early run sent every Remove twice).
- **Adds an extra stale-entity removal:** an entity with no update for 30 s gets a
  Remove Entity. Without it, a crashed `vehicle_sim` would be heartbeated forever.
- **Keeps entity IDs stable:** `N` comes from the callsign's trailing number
  (`flight3` → `1.42.3`), so IDs survive a gateway restart; other callsigns take
  the next free number.
- **Sets the force default to 3** (neutral), per decision 2.
- **Adds sensed tracks behind `--fused`** (gateway) / **`--dis-fused`**
  (`simulation_manager.py`), per decision 1:
  - Subscribes to `224.1.1.2:5005` and fuses the latest report per sensor per
    aircraft, dropping reports older than 15 s. Reuses
    `fusion.fusion_app.fuse_positions` (1/σ² weighting).
  - Emits each track as `2.42.N` (same `N` as its aircraft), force 0, marking
    `S:<callsign>`. `--fused-site` is configurable and is refused if it equals `--site`.
  - `fusion_app` publishes nothing on the network, so the gateway fuses for
    itself, the same way the web visualizer does. `fusion_app` is unchanged.
- **Adds manager flags** `--dis`, `--dis-fused`, `--dis-dest`, `--dis-port`; the
  README gains a "DIS output" section and `tests/` gains 11 unit tests.

**Verified 2026-11-10:**

- **Unit tests:** `python -m unittest discover -s tests -t .` — 11/11 pass.
- **Case 1, truth only:** `-v 3 --dis --headless` with moving-map `listen` for
  40 s. 3 tracked, force N, `malformed=0`; 0 tracked at the first redraw after
  SIGINT, not after the 12 s timeout.
- **Case 2, truth + sensed:** `--dis-fused` added. 6 tracked: `1.42.1–3` Neutral
  and `2.42.1–3` Unknown, sensed positions within ~0.002° of truth, `malformed=0`,
  all 6 gone at the first redraw after SIGINT.
- **Field check:** one truth PDU, one sensed PDU and one Remove, piped through
  moving-map `parse-stdin`, decode exactly: markings `flight3` / `S:flight3`,
  force 3/0, alt 10668.0 m, speed 231.5 m/s, heading 90.0°. The checks used
  `cargo run --offline`.

**Not done / known gaps:**

- **Sensed kinematics:** a sensed track borrows altitude, heading and speed from
  its aircraft's truth, because sensors report lat/lon only. Deriving them from
  successive fused fixes is possible but would be noisy.
- **Heading drift:** the `vehicle_sim.py` initial-bearing drift (line 49) is not
  fixed. It was a suggestion, not part of the change, and it alters Sensors'
  own display, so it is left for Bobby. Noted in the README.
- **Fusion printout:** `fusion_app.py` prints fused positions with lat and lon
  labels swapped (`FUSED flight3: lon=46.779, lat=-71.431`). It is a cosmetic
  bug, outside this CR and not fixed; the gateway does not depend on it.
