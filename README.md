# sensor_simulation

A modular, extensible sensor-fusion simulator in Python. Simulate multiple vehicles, noisy sensors, and a fusion node using UDP sockets on localhost.

## Features
- Multiple vehicles, each broadcasting their position
- Multiple sensors, each listening to a vehicle, adding noise, and rebroadcasting
- Sensor fusion app that fuses all sensor data into a best estimate

## Directory Structure
```
vehicles/           # Vehicle simulators
sensors/            # Noisy sensor modules
fusion/             # Sensor fusion application
requirements.txt    # Python dependencies
LICENSE             # MIT License
README.md           # Project overview and usage
```

## Usage

### Part 1: Simulation Manager (Recommended)
The simulation manager is the main entry point for running the full sensor fusion simulation. It launches all vehicles, sensors, the fusion app, and the visualization app by default, using UDP multicast for all inter-process communication.

**Basic Example:**
```bash
python simulation_manager.py
```

```bash
python simulation_manager.py -v 2 -s 3
```

- `-v`, `--num-vehicles`: Number of vehicles to simulate (default: 1)
- `-s`, `--num-sensors`: Number of sensors to simulate (default: one of each type)
- `--sensor-type <idx> <type>`: (Repeatable) Specify the type for a sensor index (1-based). Types: `noisy`, `adas`, `tacan`. Example: `--sensor-type 1 tacan --sensor-type 2 adas --sensor-type 3 tacan`
- `--tacan-pos <idx> <x> <y>`: (Repeatable) Specify the position of a TACAN sensor by its index (1-based), e.g. `--tacan-pos 1 0 0`.
- `--delta`: Angular separation (degrees) between vehicle start and end points (default: 135)
- `--headless`, `--no-visualize`: Do not launch the visualization app (default: visualization is launched)

> **Note:** The `-h` flag is reserved for help and cannot be used for headless mode. Use `--headless` or `--no-visualize` instead.

#### Sensor Types
- **noisy**: Standard noisy sensor (default for unspecified sensors)
- **adas**: ADAS sensor (publishes vehicle info every ~15s, with random jitter)
- **tacan**: TACAN sensor (requires position, simulates a rotating radar dish)

---

### Per-Sensor Configuration
You can specify the type of each sensor individually using `--sensor-type <idx> <type>`. Any sensor index not specified will default to `noisy`.

You can also assign positions to TACAN sensors using `--tacan-pos <idx> <x> <y>`.

**Vehicle Examples:**
- Change vehicle path angle:
  ```bash
  python simulation_manager.py -v 2 -s 3 --delta 90
  ```
- Run without visualization:
  ```bash
  python simulation_manager.py -v 2 -s 3 --headless
  # or
  python simulation_manager.py -v 2 -s 3 --no-visualize
  ```

**Sensor Examples:**
- Launch 5 sensors: sensor 1 is TACAN at (0,0), sensor 2 is ADAS, sensor 3 is TACAN at (10,10), others default to noisy:
  ```bash
  python simulation_manager.py -s 5 \
    --sensor-type 1 tacan --tacan-pos 1 0 0 \
    --sensor-type 2 adas \
    --sensor-type 3 tacan --tacan-pos 3 10 10
  ```
- Launch 4 sensors: sensor 2 is ADAS, sensor 4 is TACAN at (5,5):
  ```bash
  python simulation_manager.py -s 4 \
    --sensor-type 2 adas \
    --sensor-type 4 tacan --tacan-pos 4 5 5
  ```
- Launch 3 sensors, all default to noisy:
  ```bash
  python simulation_manager.py -s 3
  ```
- Launch 2 vehicles and 4 sensors, mixing types:
  ```bash
  python simulation_manager.py -v 2 -s 4 \
    --sensor-type 1 tacan --tacan-pos 1 0 0 \
    --sensor-type 2 adas
  ```
- Launch 6 sensors, only sensors 2 and 4 are TACAN at different positions:
  ```bash
  python simulation_manager.py -s 6 \
    --sensor-type 2 tacan --tacan-pos 2 2 2 \
    --sensor-type 4 tacan --tacan-pos 4 8 8
  ```

All components are launched using Python's module mode (`python -m ...`) from the project root, ensuring correct imports and multicast configuration.

---

### Part 2: Running Components Manually (Advanced/Debugging)

#### 2.1 Vehicle Simulator
Simulate a vehicle moving from P1 to P2, broadcasting position to the vehicle multicast group:
```bash
python -m vehicles.vehicle_sim --p1 0 0 --p2 10 10 --name vehicle1
```

#### 2.2 Noisy Sensor
Listen to all vehicles via multicast, add noise, rebroadcast to the sensor multicast group:
```bash
python -m sensors.noisy_sensor --name sensor1
```

#### 2.3 Sensor Fusion
Fuse all sensor outputs received via multicast:
```bash
python -m fusion.fusion_app
```

#### 2.4 Visualization
Visualize sensor and fused positions in real time (listens to sensor multicast group):
```bash
python -m visualization.visualizer
```

> **Important:** All commands above must be run from the project root directory (`/home/bobbyc/Projects/Sensors`) to ensure correct imports and multicast configuration.

---

### Multicast Architecture

- **Vehicle → Sensor:**
  - Vehicles broadcast to `VEHICLE_MCAST_GRP:VEHICLE_MCAST_PORT` (see `multicast_config.py`)
  - Only sensors listen on this group/port
- **Sensor → Fusion/Visualization:**
  - Sensors broadcast to `SENSOR_MCAST_GRP:SENSOR_MCAST_PORT`
  - Only fusion and visualization apps listen on this group/port

This ensures each stage only receives the data it is supposed to, preventing "cheating" or cross-stage eavesdropping.

---

### Troubleshooting

- **ModuleNotFoundError: No module named 'multicast_config'**
  - Make sure you are running all commands from the project root (`/home/bobbyc/Projects/Sensors`)
  - Always use `python -m ...` (module mode), not `python script.py`, for all components

A separate visualization app (`visualization/visualizer.py`) displays real-time positions of all sensors and the fused position. The simulation manager launches this by default unless you use `--headless` or `--no-visualize`.

- Sensor positions are color-coded and labeled by name.
- Fused position is plotted as `Fused_alg1`.
- Axes are scaled to match the simulation area (radius=10, axes: -12 to 12).

To run the visualizer manually:
```bash
python -m visualization.visualizer
```
To disable visualization when running the simulation manager, use:
```bash
python simulation_manager.py --headless
# or
python simulation_manager.py --no-visualize
```

## Extending
- Add more vehicles (different ports, names)
- Add more sensors (each listens to a vehicle, broadcasts on a unique port)
- The fusion app can listen to as many sensors as you run

## Contributing
Pull requests and issues are welcome! Please open an issue to discuss major changes.

## License
MIT License. See LICENSE for details.
