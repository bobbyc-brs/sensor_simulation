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
python simulation_manager.py              # 1 aircraft, 3 sensors, web map
python simulation_manager.py -v 3         # three aircraft on preset routes
python simulation_manager.py --speed-kts 500
python simulation_manager.py --headless   # no visualizer
```

| Option | Description |
|--------|-------------|
| `-v`, `--num-vehicles` | Number of aircraft (default: 1) |
| `-s`, `--num-sensors` | Sensor count (default: 3 — noisy, adas, tacan) |
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
- Sensor: `sensor,name,lat,lon,progress,noise_or_type` (`noise` in meters for noisy; `ADAS` / `TACAN` for others)

## Visualization

**Web (recommended):** `simulation_manager.py` starts `visualization.web_visualizer` by default.

- Left panel: map, aircraft truth (blue), sensor dots, fused ★
- Right panel: same map with fused track
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

## Contributing

Pull requests and issues are welcome.

## License

MIT License. See LICENSE.