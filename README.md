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
The simulation manager is the main entry point for running the full sensor fusion simulation. It launches all vehicles, sensors, the fusion app, and the visualization app by default.

**Basic Example:**
```bash
python simulation_manager.py -v 2 -s 3
```

- `-v`, `--num-vehicles`: Number of vehicles to simulate
- `-s`, `--num-sensors`: Number of noisy sensors
- `--delta`: Angular separation (degrees) between vehicle start and end points (default: 135)
- `-h`, `--headless`, `--no-visualize`: Do not launch the visualization app (default: visualization is launched)

**Examples:**
- Change vehicle path angle:
  ```bash
  python simulation_manager.py -v 2 -s 3 --delta 90
  ```
- Run without visualization:
  ```bash
  python simulation_manager.py -v 2 -s 3 -h
  # or
  python simulation_manager.py -v 2 -s 3 --headless
  ```

---

### Part 2: Running Components Manually (Advanced/Debugging)

#### 2.1 Vehicle Simulator
Simulate a vehicle moving from P1 to P2, broadcasting position:
```bash
python vehicles/vehicle_sim.py --p1 0 0 --p2 10 10 --port 9001 --name vehicle1
```

When using the simulation manager, vehicle paths are automatically generated:
- Each vehicle starts at a unique position on a circle (evenly spaced)
- Each vehicle's destination is 'delta' degrees further around the circle from its start
- The `--delta` argument (default: 135) controls the angular separation between start and end for each vehicle

#### 2.2 Noisy Sensor
Listen to a vehicle, add noise, rebroadcast on a new port:
```bash
python sensors/noisy_sensor.py --listen_port 9001 --broadcast_port 9101 --noise_std 0.5 --name sensor1
```

#### 2.3 Sensor Fusion
Fuse all sensor outputs (add more ports for more sensors):
```bash
python fusion/fusion_app.py --sensor_ports 9101
```

#### 2.4 Visualization
Visualize sensor and fused positions in real time:
```bash
python visualization/visualizer.py --sensor_ports 9101 9102 9103
```

A separate visualization app (`visualization/visualizer.py`) displays real-time positions of all sensors and the fused position. The simulation manager launches this by default unless you use `-h`, `--headless`, or `--no-visualize`.

- Sensor positions are color-coded and labeled by name.
- Fused position is plotted as `Fused_alg1`.
- Axes are scaled to match the simulation area (radius=10, axes: -12 to 12).

To run the visualizer manually:
```bash
python -m visualization.visualizer --sensor_ports <sensor_port1> [<sensor_port2> ...]
```
To disable visualization when running the simulation manager, use:
```bash
python simulation_manager.py -h
# or
python simulation_manager.py --headless
```

## Extending
- Add more vehicles (different ports, names)
- Add more sensors (each listens to a vehicle, broadcasts on a unique port)
- The fusion app can listen to as many sensors as you run

## Contributing
Pull requests and issues are welcome! Please open an issue to discuss major changes.

## License
MIT License. See LICENSE for details.
