import argparse
import subprocess
import sys
import time
import signal

VEHICLE_BASE_PORT = 9001
SENSOR_BASE_PORT = 9101

processes = []

def launch_vehicle(idx, p1, p2, port, name):
    cmd = [sys.executable, 'vehicles/vehicle_sim.py',
           '--p1', str(p1[0]), str(p1[1]),
           '--p2', str(p2[0]), str(p2[1]),
           '--port', str(port),
           '--name', name]
    return subprocess.Popen(cmd)

def launch_sensor(idx, listen_port, broadcast_port, name):
    cmd = [sys.executable, 'sensors/noisy_sensor.py',
           '--listen_port', str(listen_port),
           '--broadcast_port', str(broadcast_port),
           '--name', name]
    return subprocess.Popen(cmd)

def launch_fusion(sensor_ports):
    ports = [str(p) for p in sensor_ports]
    cmd = [sys.executable, 'fusion/fusion_app.py', '--sensor_ports'] + ports
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
    parser.add_argument('-h','--headless', '--no-visualize', action='store_true', help='Do not launch the visualization app')
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
    vehicle_ports = []
    vehicle_info = []
    for i, (p1, p2) in enumerate(vehicle_paths):
        port = VEHICLE_BASE_PORT + i
        vehicle_ports.append(port)
        name = f"vehicle{i+1}"
        p = launch_vehicle(i, p1, p2, port, name)
        processes.append(p)
        vehicle_info.append({'proc': p, 'name': name, 'type': 'vehicle', 'idx': i})
        print(f"  Vehicle {name} on port {port} from {p1} to {p2}")

    # Launch sensors (each sensor listens to a vehicle)
    sensor_ports = []
    sensor_info = []
    for i in range(num_sensors):
        listen_port = vehicle_ports[i % num_vehicles]
        broadcast_port = SENSOR_BASE_PORT + i
        sensor_ports.append(broadcast_port)
        name = f"sensor{i+1}"
        p = launch_sensor(i, listen_port, broadcast_port, name)
        processes.append(p)
        sensor_info.append({'proc': p, 'name': name, 'type': 'sensor', 'idx': i, 'listen_port': listen_port, 'broadcast_port': broadcast_port})
        print(f"  Sensor {name} listens to vehicle port {listen_port}, broadcasts on {broadcast_port}")

    # Launch fusion app
    p = launch_fusion(sensor_ports)
    processes.append(p)
    fusion_info = {'proc': p, 'name': 'fusion', 'type': 'fusion'}
    print(f"  Fusion app listening to sensor ports: {sensor_ports}")

    # Launch visualization app unless headless
    visualizer_proc = None
    if not args.headless:
        try:
            import sys
            vis_ports = [str(p) for p in sensor_ports]
            cmd = [sys.executable, '-m', 'visualization.visualizer', '--sensor_ports'] + vis_ports
            visualizer_proc = subprocess.Popen(cmd)
            processes.append(visualizer_proc)
            print(f"  Visualization app started for sensor ports: {sensor_ports}")
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
