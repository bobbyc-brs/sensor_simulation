# sensor_simulation

A modular sensor-fusion simulator in Python. Aircraft fly great-circle routes between real Eastern Canada airports; sensors add noise and rebroadcast positions; a fusion node estimates the best fix. Processes communicate over UDP multicast on localhost.

## Features

- **Realistic flights** — WGS84 lat/lon, great-circle paths, cruise speed (default 450 kt), climb/cruise/descent altitude
- **Six airports** — St. John's, Halifax, Quebec City, Montreal, Toronto, Ottawa
- **Three sensor types** — noisy (Gaussian error in meters), ADAS (~15 s updates), TACAN (rotating dish)
- **Weighted fusion** — inverse-variance blend using reported noise / sensor type
- **Live map** — browser UI (default) or optional matplotlib window; time-scale controls to speed up or slow down the sim

## Requirements

- Python 3.10+
- Dependencies: `pip install -r requirements.txt` (matplotlib for visualization)

## Quick start

From the project root:

```bash
pip install -r requirements.txt
python simulation_manager.py
```

Open **http://127.0.0.1:8765/** in your browser. Use the **time scale** buttons (0.25×–50×) to accelerate or slow the simulation without changing cruise speed.

Run only **one** `simulation_manager.py` at a time. Stop with Ctrl+C before starting again.

## Eastern Canada airports

| ICAO | Airport | Region |
|------|---------|--------|
| YYT | St. John's | NL |
| YHZ | Halifax | NS |
| YQB | Quebec City | QC |
| YUL | Montreal | QC |
| YYZ | Toronto | ON |
| YOW | Ottawa | ON |

Default routes (by aircraft index): YYT→YYZ, YHZ→YUL, YQB→YYZ, YUL→YOW, YYZ→YHZ, YOW→YHZ.

Static map with airports and routes:

```bash
python -m geo.plot_airports_map
```

Writes `geo/eastern_canada_airports.png`.

## Simulation manager

```bash
python simulation_manager.py              # 1 aircraft, 1 radar + noisy + ADAS, web map
python simulation_manager.py -v 10 -r 7 # 10 aircraft, 7 TACAN radars (+ 1 noisy + 1 ADAS)
python simulation_manager.py -v 5 -r 3 --num-noisy 0 --num-adas 0   # aircraft + radars only
python simulation_manager.py --scenario complex   # same as -v 10 -r 7 --num-noisy 2 --num-adas 2
python simulation_manager.py --speed-kts 500
python simulation_manager.py --headless   # no visualizer
```

| Option | Description |
|--------|-------------|
| `-v`, `--num-vehicles` | Number of aircraft (default: 1) |
| `-r`, `--num-radars` | Number of TACAN radar sensors at airports YHZ→YUL→YYZ→… (default: 1) |
| `--num-noisy` | High-rate noisy sensors (default: 1) |
| `--num-adas` | ADAS sensors (default: 1) |
| `--scenario` | Named preset: `complex` (= 10 aircraft, 7 radars, 2 noisy, 2 ADAS) |
| `-s`, `--num-sensors` | Legacy: all noisy (prefer `-r` / `--num-noisy` / `--num-adas`) |
| `--speed-kts` | Cruise groundspeed in knots (default: 450) |
| `--sensor-type <idx> <type>` | Per-sensor type: `noisy`, `adas`, `tacan` |
| `--tacan-pos <idx> <lat> <lon>` | TACAN radar position (degrees) |
| `--tacan-airport <idx> <ICAO>` | TACAN at an airport, e.g. `--tacan-airport 1 YHZ` |
| `--headless`, `--no-visualize` | Do not start a visualizer |
| `--web` | Browser map at `http://127.0.0.1:8765/` (default) |
| `--window` | Matplotlib desktop window instead of browser |
| `--web-port` | Port for web UI (default: 8765) |

> `-h` is reserved for help. Use `--headless` or `--no-visualize` for no GUI.

### Time scale

The web UI writes `.sim_time_scale.json` (gitignored). Aircraft read it each tick so **10×** advances the flight ten times faster in wall-clock time while keeping 450 kt cruise physics.

### Sensor types

- **noisy** — Gaussian position noise (default 50 m), rebroadcast every vehicle update
- **adas** — Sparse updates (~15 s average)
- **tacan** — Publishes when the rotating beam aligns with the aircraft; default radar at YHZ

### Examples

```bash
# Faster cruise (still “real” speed; shorter wall-clock at 1× time scale)
python simulation_manager.py --speed-kts 600

# Three aircraft, web map
python simulation_manager.py -v 3

# Ten aircraft, seven radars (plus 2 noisy + 2 ADAS)
python simulation_manager.py -v 10 -r 7 --num-noisy 2 --num-adas 2
# or the same layout as a preset:
python simulation_manager.py --scenario complex

# TACAN at Halifax and Montreal
python simulation_manager.py -s 5 \
  --sensor-type 1 tacan --tacan-airport 1 YHZ \
  --sensor-type 2 adas \
  --sensor-type 3 tacan --tacan-airport 3 YUL
```

## Directory structure

```
geo/                  # Airports, routes, great-circle math, map drawing, time-scale file
vehicles/             # Aircraft simulator (multicast position stream)
sensors/              # noisy_sensor, adas_sensor, tacan_sensor
fusion/               # Multicast fusion app
gateways/             # DIS encoding (dis_pdu), output (dis_output), dis_gateway for airport flights
cgf/                  # CGF: scenario files → DIS entities (scenario, motion, runner)
scenarios/            # CGF scenario files (JSON) — see scenarios/README.md
recordings/           # DIS regression vectors, pcap + raw — see recordings/README.md
devel-scripts/        # Developer scripts (regenerate the recordings)
tests/                # Unit tests (python -m unittest discover -s tests -t .)
visualization/        # web_visualizer (default), visualizer (desktop), shared plot helpers
simulation_manager.py # Orchestrates all processes
multicast_config.py   # Shared multicast groups/ports
requirements.txt
```

`simulation_manager_v2.py` is a legacy pre-multicast orchestrator and is not used by the current stack.

## Manual components

Run from the project root with `python -m ...`:

```bash
# Aircraft
python -m vehicles.vehicle_sim --origin-airport YHZ --dest-airport YUL --name AC123

# Sensors
python -m sensors.noisy_sensor --name sensor1
python -m sensors.adas_sensor --name sensor2
python -m sensors.tacan_sensor --name tacan1 --radar-lat 44.881 --radar-lon -63.508

# Fusion
python -m fusion.fusion_app

# DIS gateway (see "DIS output")
python -m gateways.dis_gateway --dest 127.0.0.1 --port 3800

# Visualization (simulation should already be producing multicast traffic)
python -m visualization.web_visualizer
python -m visualization.visualizer   # desktop window; needs local display
```

## Multicast architecture

| Stage | Group:port | Listeners |
|-------|------------|-----------|
| Aircraft → sensors | `224.1.1.1:5004` | Sensors only |
| Sensors → fusion / viz | `224.1.1.2:5005` | Fusion, visualizers |

Defined in `multicast_config.py`. Stages are separated so fusion and visualization do not receive raw aircraft truth on the vehicle group.

### Message formats

- Vehicle: `vehicle,name,lat,lon,progress,heading_deg,alt_ft,speed_kts`
- Sensor: `sensor,name,lat,lon,progress,noise_or_type,vehicle` (target aircraft callsign, e.g. `flight3`)

## DIS output

`gateways/dis_gateway.py` re-emits every aircraft as an IEEE 1278.1 (DIS 7)
**Entity State PDU** over UDP, so a DIS consumer such as
`~/Projects/moving-map-display` can show the scenario. Standard library only; the
traffic stays on the LAN. Added per CR-001 in `DECISIONS.changeRequest/`.

- **Sends** one 144-byte Entity State PDU per aircraft on each vehicle message
  (every 2 s), and a heartbeat at least every 5 s.
- **Removes** each entity with a Remove Entity PDU (type 12) on SIGINT/SIGTERM,
  or after 30 s without updates.
- **Identifies** aircraft as `1.42.N` (site.application.entity), where `N` is the
  number in the callsign (`flight3` → 3): civil airliner type 1.2.39.87.0.0.0
  (CR-002; DIS country 39 = Canada), force 3 (Neutral), the callsign as marking.
- **Optionally adds sensed tracks** (`--dis-fused`): each aircraft's fused sensor
  position becomes a separate entity `2.42.N`, force 0 (Other — shown as Unknown),
  marked `S:<callsign>`.

```bash
# Terminal 1 — Sensors: truth only, or add --dis-fused for sensed tracks too
python simulation_manager.py -v 3 --dis --headless
python simulation_manager.py -v 3 --dis --dis-fused --headless

# Terminal 2 — moving-map-display
cd ~/Projects/moving-map-display
cargo run -- listen --range-nm 200 --seconds 30
```

DIS goes to **UDP port 3800** by default, the same default as moving-map-display
(Bobby, 2026-11-10; moving-map DD-007), so neither side needs `--port`. Ports
3801–3809 are kept for private test runs on one machine.

`--dis-dest 192.168.1.255` broadcasts to the LAN instead of `127.0.0.1`;
`--dis-port` changes the port. The gateway itself also takes `--exercise`,
`--site`, `--app`, `--force` and `--fused-site` — see `--help`.

### Output options: multicast, recording, faults

Every DIS sender — the gateway and the CGF runner — shares one output path
(`gateways/dis_output.py`, CR-004). On `simulation_manager.py` each option is
`--dis-<name>`; on `gateways.dis_gateway` and `cgf.runner` it is `--<name>`.

| Option | Effect |
|---|---|
| `--dis-dest 239.1.2.3` | Multicast: sets `IP_MULTICAST_TTL`; `--dis-iface <ip>` picks the interface. Matches moving-map `listen --group 239.1.2.3 --iface <ip>` |
| `--dis-ttl N` | IP TTL for every datagram, unicast too (default 1 — DIS stays on the LAN) |
| `--dis-bundle K` | Pack up to K PDUs per datagram (DIS 7 bundling, ≤ 1400 bytes) |
| `--dis-record F.pcap` / `--dis-record-raw F.bin` | Append every datagram sent to a libpcap file / back to back |
| `--dis-fault-truncate P` | Cut a fraction P of Entity State PDUs short, length field unchanged |
| `--dis-fault-garbage P` | Add a random-byte datagram after a valid one with probability P |
| `--dis-fault-unknown-types` | Interleave valid Fire, Detonation, Collision and Create Entity PDUs |
| `--dis-fault-v6` / `--dis-fault-other-exercise N` | Send 10 % of Entity State PDUs as version 6 / with exercise N |
| `--dis-fault-loss P` / `-reorder P` / `-duplicate P` | Drop / swap with the next / repeat each valid datagram |
| `--dis-fault-seed N` | Repeatable faults |

On exit the sender prints what it did and **what a receiver should have
counted**. Truncated and garbage datagrams always travel alone and always fail
at their first header, so each is exactly one `malformed` at moving-map:

```bash
python simulation_manager.py --scenario-file scenarios/ottawa-mixed.json --dis \
  --dis-fault-truncate 0.05 --dis-fault-garbage 0.02 --dis-fault-unknown-types --headless
#   faults: truncated 61, garbage 21, unknown-type 106, ...
#   receiver should count: datagrams=1220 pdus=1138 malformed=82 ...
```

Every PDU's timestamp field carries its DIS relative send time (CR-003).

Heading is the aircraft's current great-circle bearing to its destination,
re-computed each update (CR-002; before that it was the initial bearing).

**Known gap:** sensors report position only, so a sensed track borrows
altitude, heading and speed from its aircraft's truth.

## CGF scenarios

Sensors can also act as a small **CGF** (computer-generated forces): a JSON
scenario file declares entities — any DIS type, any side, waypoints, start/stop
times, one ownship — and `cgf/runner.py` plays them as DIS in real time, one
process for all entities. It replaces the airport flights for that run, and
drives moving-map-display test cases (CR-002).

```bash
# Terminal 1 — Sensors
python simulation_manager.py --scenario-file scenarios/ottawa-mixed.json --dis --headless
# Terminal 2 — moving-map-display, centred on the ownship helicopter
cargo run -- listen --ownship 1.42.1 --range-nm 25 --seconds 60
```

`ottawa-mixed.json` flies a friendly utility helicopter (ownship) over Ottawa —
a 180° reversal, then a 20 s hover — among cars, trucks, buses, a school bus,
horses, tanks, an AFV, an attack helicopter, a patrol craft and an airliner, on
all four sides. Test-case scenarios for moving-map (CR-003) cover entity
lifecycle (late, silent, removed and re-added, duplicate numbers on two sites),
a 200-entity load at 200 PDU/s, and a UTM zone crossing at 78°W. Every PDU
carries its send time in the timestamp field, for latency measurement.

File format, entity-type catalogue, the scenario list and the motion model:
[`scenarios/README.md`](scenarios/README.md).

## Visualization

**Web (recommended):** `simulation_manager.py` starts `visualization.web_visualizer` by default.

- Left panel: map, aircraft truth (blue), sensor dots, fused ★
- Right panel: fused track **per aircraft** (one colored star/trail per flight)
- Time scale buttons above the map

**Desktop:** `python simulation_manager.py --window` or `python -m visualization.visualizer` (requires a working X11/Wayland display on the same machine).

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `ModuleNotFoundError: multicast_config` | Run from project root; use `python -m package.module` |
| No browser map | Open http://127.0.0.1:8765/ ; check nothing else is bound to the port |
| Duplicate or frozen sim | Stop all: `pkill -f simulation_manager.py` and related `python -m` processes; start once |
| No matplotlib window | Use the web UI (default), not `--window` |
| Flight takes hours | Expected at 450 kt on long routes; use time scale **10×** or higher |
| `ModuleNotFoundError: matplotlib` | `pip install -r requirements.txt` |

## Extending

- Add airports and routes in `geo/eastern_canada.py`
- Add sensor types under `sensors/`; teach `fusion/fusion_app.py` and `visualization/plot_live.py` any new noise labels
- Adjust map extent in `MAP_BOUNDS` and `geo/map_plot.py`

## Development history

See [DEVELOPMENT_LOG.md](DEVELOPMENT_LOG.md) for a chronological record of features and changes (including when `web_visualizer` was added vs the original desktop `visualizer`).

## Contributing

Pull requests and issues are welcome.

## License

MIT License. See LICENSE.