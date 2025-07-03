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
### 1. Vehicle Simulator
Simulate a vehicle moving from P1 to P2, broadcasting position:
```bash
python vehicles/vehicle_sim.py --p1 0 0 --p2 10 10 --port 9001 --name vehicle1
```

When using the simulation manager, vehicle paths are automatically generated:
- Each vehicle starts at a unique position on a circle (evenly spaced)
- Each vehicle's destination is 'delta' degrees further around the circle from its start
- The `--delta` argument (default: 135) controls the angular separation between start and end for each vehicle

### 2. Noisy Sensor
Listen to a vehicle, add noise, rebroadcast on a new port:
```bash
python sensors/noisy_sensor.py --listen_port 9001 --broadcast_port 9101 --noise_std 0.5 --name sensor1
```

### 3. Sensor Fusion
Fuse all sensor outputs (add more ports for more sensors):
```bash
python fusion/fusion_app.py --sensor_ports 9101
```

### 4. Visualization
Visualize sensor and fused positions in real time:
```bash
python visualization/visualizer.py --sensor_ports 9101 9102 9103
```

- Listens to the same UDP ports as the fusion app to receive sensor data.
- Imports and uses the fusion logic from `fusion/fusion_app.py` to compute and plot the fused position in real time.
- Uses matplotlib to display:
  - One plot showing all sensor positions (with noise, color-coded by sensor)
  - Another plot showing the fused position over time.
- The visualizer does not interfere with the running fusion app; both can run in parallel.

## Extending
- Add more vehicles (different ports, names)
- Add more sensors (each listens to a vehicle, broadcasts on a unique port)
- The fusion app can listen to as many sensors as you run

## Contributing
Pull requests and issues are welcome! Please open an issue to discuss major changes.

## License
MIT License. See LICENSE for details.
