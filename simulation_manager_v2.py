import argparse
import subprocess
import sys
import time
import signal
import threading
import socket

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
    parser.add_argument('--headless', '--no-visualize', action='store_true', help='Do not launch the visualization app (use --headless or --no-visualize)')
    parser.add_argument('--idle-timeout-minutes', type=int, default=5, help='Stop if no UDP positional updates for this many minutes (default: 5)')
    args = parser.parse_args()

    # --- UDP positional update monitor ---
    UDP_MONITOR_PORT = 9999  # Dedicated port for monitoring
    last_update_time = [time.time()]
    stop_udp_listener = threading.Event()
    def udp_update_listener():
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('127.0.0.1', UDP_MONITOR_PORT))
        sock.settimeout(1.0)
        while not stop_udp_listener.is_set():
            try:
                data, _ = sock.recvfrom(4096)
                last_update_time[0] = time.time()
            except socket.timeout:
                continue
        sock.close()
    udp_thread = threading.Thread(target=udp_update_listener, daemon=True)
    udp_thread.start()

    # Helper to forward UDP traffic to monitor port using socat
    def socat_forward_cmd(src_port):
        return ["socat", f"UDP-RECV:{src_port},fork", f"UDP-SENDTO:127.0.0.1:{UDP_MONITOR_PORT}"]
    socat_procs = []

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
        # Forward all vehicle UDP broadcasts to monitor port
        socat_procs.append(subprocess.Popen(socat_forward_cmd(port), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))

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
        # Forward all sensor UDP broadcasts to monitor port
        socat_procs.append(subprocess.Popen(socat_forward_cmd(broadcast_port), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))

    # Launch fusion app
    p = launch_fusion(sensor_ports)
    processes.append(p)
    fusion_info = {'proc': p, 'name': 'fusion', 'type': 'fusion'}
    print(f"  Fusion app listening to sensor ports: {sensor_ports}")
    # Optionally: forward fusion UDP output if it broadcasts (add here if needed)

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
        for p in socat_procs:
            p.terminate()
        stop_udp_listener.set()
        sys.exit(0)
    signal.signal(signal.SIGINT, signal_handler)

    idle_limit = args.idle_timeout_minutes * 60
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
            if time.time() - last_update_time[0] > idle_limit:
                print(f"[TIMEOUT] No UDP positional updates for {args.idle_timeout_minutes} minutes. Shutting down.")
                stop_all()
                for p in socat_procs:
                    p.terminate()
                stop_udp_listener.set()
                break
            time.sleep(1)
    except KeyboardInterrupt:
        stop_all()
        for p in socat_procs:
            p.terminate()
        stop_udp_listener.set()

if __name__ == "__main__":
    main()
