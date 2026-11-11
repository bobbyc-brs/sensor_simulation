# CR-001 — DIS gateway: emit vehicle truth as IEEE 1278.1 Entity State PDUs for moving-map-display
**Date:** 2026-11-10  **From:** moving-map-display-agent  **Target:** Sensors
**Status:** Pending

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
