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

def launch_sensor(idx, name, sensor_type='noisy', tacan_x=None, tacan_y=None):
    if sensor_type == 'noisy':
        cmd = [sys.executable, '-m', 'sensors.noisy_sensor', '--name', name]
    elif sensor_type == 'adas':
        cmd = [sys.executable, '-m', 'sensors.adas_sensor', '--name', name]
    elif sensor_type == 'tacan':
        if tacan_x is None or tacan_y is None:
            raise ValueError('TACAN sensor requires --tacan-x and --tacan-y')
        cmd = [sys.executable, '-m', 'sensors.tacan_sensor', '--name', name,
               '--radar-x-pos', str(tacan_x), '--radar-y-pos', str(tacan_y)]
    else:
        raise ValueError(f'Unknown sensor type: {sensor_type}')
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
    parser.add_argument('--sensor-type', type=str, choices=['noisy','adas','tacan','all'], default='noisy', help='Type of sensor to launch (default: noisy)')
    parser.add_argument('--tacan-x', type=float, nargs='*', help='TACAN radar x positions (for each TACAN sensor)')
    parser.add_argument('--tacan-y', type=float, nargs='*', help='TACAN radar y positions (for each TACAN sensor)')
    parser.add_argument('--delta', type=float, default=135.0, help='Delta angle (degrees) between start and end for each vehicle (default: 135)')
    parser.add_argument('--headless', '--no-visualize', action='store_true', help='Do not launch the visualization app (use --headless or --no-visualize)')
    args = parser.parse_args()

    num_vehicles = args.num_vehicles
    num_sensors = args.num_sensors
    sensor_type = args.sensor_type
    tacan_xs = args.tacan_x if args.tacan_x else []
    tacan_ys = args.tacan_y if args.tacan_y else []
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
    sensor_types_to_launch = []
    if sensor_type == 'all':
        # Launch equal number of each type if possible
        n_each = max(1, num_sensors // 3)
        sensor_types_to_launch = (
            [('noisy', None, None)] * n_each +
            [('adas', None, None)] * n_each +
            [('tacan', tacan_xs[i] if i < len(tacan_xs) else 0.0, tacan_ys[i] if i < len(tacan_ys) else 0.0) for i in range(n_each)]
        )
        # If num_sensors is not divisible by 3, fill with noisy
        while len(sensor_types_to_launch) < num_sensors:
            sensor_types_to_launch.append(('noisy', None, None))
    else:
        for i in range(num_sensors):
            if sensor_type == 'tacan':
                x = tacan_xs[i] if i < len(tacan_xs) else 0.0
                y = tacan_ys[i] if i < len(tacan_ys) else 0.0
                sensor_types_to_launch.append(('tacan', x, y))
            else:
                sensor_types_to_launch.append((sensor_type, None, None))

    for i, (stype, tx, ty) in enumerate(sensor_types_to_launch):
        name = f"sensor{i+1}"
        p = launch_sensor(i, name, sensor_type=stype, tacan_x=tx, tacan_y=ty)
        processes.append(p)
        sensor_info.append({'proc': p, 'name': name, 'type': stype, 'idx': i, 'tacan_x': tx, 'tacan_y': ty})
        print(f"  Sensor {name} ({stype}{' @ ('+str(tx)+','+str(ty)+')' if stype=='tacan' else ''}) (multicast)")

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

    import socket, struct, threading, time
    from multicast_config import SENSOR_MCAST_GRP, SENSOR_MCAST_PORT
    last_activity_time = [time.time()]
    stop_monitor = threading.Event()
    activity_lock = threading.Lock()

    def monitor_multicast():
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('', SENSOR_MCAST_PORT))
        mreq = struct.pack('4sl', socket.inet_aton(SENSOR_MCAST_GRP), socket.INADDR_ANY)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        sock.settimeout(1.0)
        while not stop_monitor.is_set():
            try:
                data, _ = sock.recvfrom(1024)
                with activity_lock:
                    last_activity_time[0] = time.time()
            except socket.timeout:
                continue
        sock.close()

    monitor_thread = threading.Thread(target=monitor_multicast, daemon=True)
    monitor_thread.start()

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
                    new_proc = launch_sensor(s['idx'], s['name'], sensor_type=s['type'], tacan_x=s.get('tacan_x'), tacan_y=s.get('tacan_y'))
                    s['proc'] = new_proc
                    # Update processes list
                    for idx, proc in enumerate(processes):
                        if proc == s['proc']:
                            processes[idx] = new_proc
                            break
                    else:
                        processes.append(new_proc)
            # Check fusion app
            if fusion_info['proc'].poll() is not None:
                print(f"[LOG] Fusion app exited with code {fusion_info['proc'].returncode}")

            # Check for inactivity
            with activity_lock:
                inactive_secs = time.time() - last_activity_time[0]
            if inactive_secs > 60:
                print("[INFO] No multicast activity for 60 seconds. Stopping all simulation processes except visualization.")
                # Stop all except visualization
                for proc in processes:
                    if visualizer_proc is not None and proc == visualizer_proc:
                        continue
                    try:
                        proc.terminate()
                    except Exception:
                        pass
                stop_monitor.set()
                break
            time.sleep(1)
    except KeyboardInterrupt:
        stop_monitor.set()
        stop_all()


if __name__ == "__main__":
    main()
