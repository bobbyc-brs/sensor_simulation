import argparse
import subprocess
import sys
import time
import signal

VEHICLE_BASE_PORT = 9001
SENSOR_BASE_PORT = 9101

processes = []

def launch_vehicle(idx, p1, p2, name):
    cmd = [sys.executable, '-m', 'vehicles.vehicle_sim',
           '--p1', str(p1[0]), str(p1[1]),
           '--p2', str(p2[0]), str(p2[1]),
           '--name', name]
    return subprocess.Popen(cmd)

def launch_sensor(idx, name):
    cmd = [sys.executable, '-m', 'sensors.noisy_sensor',
           '--name', name]
    return subprocess.Popen(cmd)

def launch_fusion():
    cmd = [sys.executable, '-m', 'fusion.fusion_app']
    return subprocess.Popen(cmd)

def stop_all():
    print("\nStopping all simulation processes...")
    for p in processes:
        if p.poll() is None:
            p.terminate()
    time.sleep(1)
    for p in processes:
        if p.poll() is None:
            p.kill()
    print("All processes stopped.")

def main():
    parser = argparse.ArgumentParser(description="Simulation Manager for sensor_simulation")
    parser.add_argument('-v', '--num-vehicles', type=int, default=1, help='Number of vehicles')
    parser.add_argument('-s', '--num-sensors', type=int, default=1, help='Number of sensors')
    parser.add_argument('--delta', type=float, default=135.0, help='Delta angle (degrees) between start and end for each vehicle (default: 135)')
    parser.add_argument('--headless', '--no-visualize', action='store_true', help='Do not launch the visualization app (use --headless or --no-visualize)')
    args = parser.parse_args()

    num_vehicles = args.num_vehicles
    num_sensors = args.num_sensors
    delta_deg = args.delta

    # Place vehicles on a circle:
    #   - Each vehicle starts at a unique position on the circle (evenly spaced, using polar coordinates)
    #   - Each vehicle's destination is 'delta' degrees further around the circle from its starting point
    #   - The --delta argument controls the angular separation between start and end (default: 135 degrees)
    import math
    radius = 10.0
    center = (0.0, 0.0)
    vehicle_paths = []
    for i in range(num_vehicles):
        theta = 2 * math.pi * i / num_vehicles
        theta2 = theta + math.radians(delta_deg)
        start = (center[0] + radius * math.cos(theta), center[1] + radius * math.sin(theta))
        end = (center[0] + radius * math.cos(theta2), center[1] + radius * math.sin(theta2))
        vehicle_paths.append((start, end))

    print(f"Launching {num_vehicles} vehicles and {num_sensors} sensors...")

    # Launch vehicles
    vehicle_info = []
    for i, (p1, p2) in enumerate(vehicle_paths):
        name = f"vehicle{i+1}"
        p = launch_vehicle(i, p1, p2, name)
        processes.append(p)
        vehicle_info.append({'proc': p, 'name': name, 'type': 'vehicle', 'idx': i})
        print(f"  Vehicle {name} from {p1} to {p2} (multicast)")

    # Launch sensors (each sensor listens to all vehicles via multicast)
    sensor_info = []
    for i in range(num_sensors):
        name = f"sensor{i+1}"
        p = launch_sensor(i, name)
        processes.append(p)
        sensor_info.append({'proc': p, 'name': name, 'type': 'sensor', 'idx': i})
        print(f"  Sensor {name} (multicast)")

    # Launch fusion app
    p = launch_fusion()
    processes.append(p)
    fusion_info = {'proc': p, 'name': 'fusion', 'type': 'fusion'}
    print(f"  Fusion app (multicast)")

    # Launch visualization app unless headless
    visualizer_proc = None
    if not args.headless:
        try:
            cmd = [sys.executable, '-m', 'visualization.visualizer']
            visualizer_proc = subprocess.Popen(cmd)
            processes.append(visualizer_proc)
            print(f"  Visualization app started (multicast)")
        except Exception as e:
            print(f"[WARN] Could not start visualization app: {e}")

    def signal_handler(sig, frame):
        stop_all()
        sys.exit(0)
    signal.signal(signal.SIGINT, signal_handler)

    try:
        while True:
            # Check vehicles
            for v in vehicle_info:
                if v['proc'].poll() is not None:
                    print(f"[LOG] Vehicle {v['name']} exited with code {v['proc'].returncode}")
            # Check sensors and restart if needed
            for s in sensor_info:
                if s['proc'].poll() is not None:
                    print(f"[LOG] Sensor {s['name']} exited with code {s['proc'].returncode}, restarting...")
                    new_proc = launch_sensor(s['idx'], s['listen_port'], s['broadcast_port'], s['name'])
                    s['proc'] = new_proc
                    idx = processes.index(s['proc']) if s['proc'] in processes else None
                    if idx is not None:
                        processes[idx] = new_proc
                    else:
                        processes.append(new_proc)
            # Check fusion app
            if fusion_info['proc'].poll() is not None:
                print(f"[LOG] Fusion app exited with code {fusion_info['proc'].returncode}")
            time.sleep(1)
    except KeyboardInterrupt:
        stop_all()

if __name__ == "__main__":
    main()
