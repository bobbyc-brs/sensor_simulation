import argparse
import subprocess
import sys
import time
import signal

from geo.sim_control import init_time_scale
from geo.eastern_canada import (
    AIRPORTS,
    DEFAULT_CRUISE_SPEED_KTS,
    DEFAULT_FLIGHT_ROUTES,
    airport_position,
    route_label,
    route_for_vehicle_index,
)

processes = []

def launch_vehicle(idx, origin_icao, dest_icao, name, speed_kts):
    cmd = [
        sys.executable, '-m', 'vehicles.vehicle_sim',
        '--origin-airport', origin_icao,
        '--dest-airport', dest_icao,
        '--name', name,
        '--speed-kts', str(speed_kts),
    ]
    return subprocess.Popen(cmd)

def launch_sensor(idx, name, sensor_type='noisy', tacan_lat=None, tacan_lon=None):
    if sensor_type == 'noisy':
        cmd = [sys.executable, '-m', 'sensors.noisy_sensor', '--name', name]
    elif sensor_type == 'adas':
        cmd = [sys.executable, '-m', 'sensors.adas_sensor', '--name', name]
    elif sensor_type == 'tacan':
        if tacan_lat is None or tacan_lon is None:
            raise ValueError('TACAN sensor requires radar lat/lon')
        cmd = [
            sys.executable, '-m', 'sensors.tacan_sensor', '--name', name,
            '--radar-lat', str(tacan_lat), '--radar-lon', str(tacan_lon),
        ]
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
    parser = argparse.ArgumentParser(
        description="Simulation Manager — Eastern Canada airport flights and sensor fusion"
    )
    parser.add_argument('-v', '--num-vehicles', type=int, default=1, help='Number of aircraft')
    parser.add_argument('-s', '--num-sensors', type=int,
                        help='Number of sensors (default: 3; one each: noisy, adas, tacan)')
    parser.add_argument('--sensor-type', type=str, nargs=2, action='append', metavar=('IDX', 'TYPE'),
                        help='Sensor type by index: noisy, adas, tacan')
    parser.add_argument('--tacan-pos', type=float, nargs=3, action='append', metavar=('IDX', 'LAT', 'LON'),
                        help='TACAN sensor index and radar position: --tacan-pos <idx> <lat> <lon>')
    parser.add_argument('--tacan-airport', type=str, nargs=2, action='append', metavar=('IDX', 'ICAO'),
                        help='Place TACAN at airport: --tacan-airport <idx> YHZ')
    parser.add_argument('--speed-kts', type=float, default=DEFAULT_CRUISE_SPEED_KTS,
                        help=f'Cruise speed for all flights (default: {DEFAULT_CRUISE_SPEED_KTS})')
    parser.add_argument('--headless', '--no-visualize', action='store_true',
                        help='Do not launch any visualization')
    parser.add_argument('--web', action='store_true',
                        help='Live map in browser at http://127.0.0.1:8765/ (recommended)')
    parser.add_argument('--window', action='store_true',
                        help='Live map in a matplotlib desktop window (needs local X11/Wayland)')
    parser.add_argument('--web-port', type=int, default=8765, help='Port for --web visualizer')
    args = parser.parse_args()

    num_vehicles = args.num_vehicles
    if args.num_sensors is None:
        num_sensors = 3
        sensor_types = ['noisy', 'adas', 'tacan']
    else:
        num_sensors = args.num_sensors
        sensor_types = ['noisy'] * num_sensors

    if args.sensor_type:
        for entry in args.sensor_type:
            idx, typ = entry
            idx = int(idx)
            if 1 <= idx <= num_sensors:
                sensor_types[idx - 1] = typ.lower()

    tacan_pos_map = {}
    if args.tacan_pos:
        for entry in args.tacan_pos:
            idx, lat, lon = map(float, entry)
            tacan_pos_map[int(idx)] = (lat, lon)
    if args.tacan_airport:
        for entry in args.tacan_airport:
            idx, icao = entry
            icao = icao.upper()
            tacan_pos_map[int(idx)] = airport_position(icao)

    init_time_scale(1.0)
    print(f"Eastern Canada airports: {', '.join(f'{k} ({v['name']})' for k, v in AIRPORTS.items())}")
    print(f"Launching {num_vehicles} aircraft and {num_sensors} sensors at {args.speed_kts:.0f} kt cruise...")

    vehicle_info = []
    exited_logged = set()
    for i in range(num_vehicles):
        origin_icao, dest_icao = DEFAULT_FLIGHT_ROUTES[i % len(DEFAULT_FLIGHT_ROUTES)]
        name = f"flight{i + 1}"
        lat1, lon1, lat2, lon2, dist_km, duration_s = route_for_vehicle_index(i)
        p = launch_vehicle(i, origin_icao, dest_icao, name, args.speed_kts)
        processes.append(p)
        vehicle_info.append({
            'proc': p, 'name': name, 'idx': i,
            'origin': origin_icao, 'dest': dest_icao,
        })
        print(
            f"  {name}: {route_label(origin_icao, dest_icao)} — "
            f"{dist_km:.0f} km, ~{duration_s / 60:.0f} min"
        )

    sensor_info = []
    default_tacan_lat, default_tacan_lon = airport_position('YHZ')
    for i, stype in enumerate(sensor_types):
        idx = i + 1
        name = f"sensor{i + 1}"
        if stype == 'tacan':
            tlat, tlon = tacan_pos_map.get(idx, (default_tacan_lat, default_tacan_lon))
        else:
            tlat, tlon = None, None
        p = launch_sensor(i, name, sensor_type=stype, tacan_lat=tlat, tacan_lon=tlon)
        processes.append(p)
        loc = f' @ ({tlat:.3f}, {tlon:.3f})' if stype == 'tacan' else ''
        sensor_info.append({
            'proc': p, 'name': name, 'type': stype, 'idx': i,
            'tacan_lat': tlat, 'tacan_lon': tlon,
        })
        print(f"  Sensor {name} ({stype}{loc})")

    p = launch_fusion()
    processes.append(p)
    fusion_info = {'proc': p, 'name': 'fusion'}
    print("  Fusion app")

    visualizer_proc = None
    if not args.headless:
        use_web = args.web or not args.window
        try:
            if use_web:
                cmd = [sys.executable, '-m', 'visualization.web_visualizer', '--port', str(args.web_port)]
                visualizer_proc = subprocess.Popen(cmd)
                processes.append(visualizer_proc)
                print(f"  Web visualizer → http://127.0.0.1:{args.web_port}/  (open in your browser)")
            else:
                visualizer_proc = subprocess.Popen([sys.executable, '-m', 'visualization.visualizer'])
                processes.append(visualizer_proc)
                print("  Desktop visualizer (matplotlib window)")
        except Exception as e:
            print(f"[WARN] Could not start visualization: {e}")

    def signal_handler(sig, frame):
        stop_all()
        sys.exit(0)
    signal.signal(signal.SIGINT, signal_handler)

    import socket
    import struct
    import threading
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
                sock.recvfrom(1024)
                with activity_lock:
                    last_activity_time[0] = time.time()
            except socket.timeout:
                continue
        sock.close()

    threading.Thread(target=monitor_multicast, daemon=True).start()

    try:
        while True:
            for v in vehicle_info:
                if v['proc'].poll() is not None and v['name'] not in exited_logged:
                    exited_logged.add(v['name'])
                    print(f"[LOG] {v['name']} ({v['origin']}→{v['dest']}) finished, code {v['proc'].returncode}")
            for s in sensor_info:
                if s['proc'].poll() is not None:
                    print(f"[LOG] Sensor {s['name']} exited ({s['proc'].returncode}), restarting...")
                    new_proc = launch_sensor(
                        s['idx'], s['name'], sensor_type=s['type'],
                        tacan_lat=s.get('tacan_lat'), tacan_lon=s.get('tacan_lon'),
                    )
                    old = s['proc']
                    s['proc'] = new_proc
                    if old in processes:
                        processes[processes.index(old)] = new_proc
                    else:
                        processes.append(new_proc)
            if fusion_info['proc'].poll() is not None:
                print(f"[LOG] Fusion app exited with code {fusion_info['proc'].returncode}")

            all_aircraft_done = all(v['proc'].poll() is not None for v in vehicle_info)
            with activity_lock:
                inactive_secs = time.time() - last_activity_time[0]
            if all_aircraft_done and inactive_secs > 30:
                print("[INFO] All flights complete; stopping simulation processes.")
                for proc in processes:
                    if visualizer_proc is not None and proc == visualizer_proc:
                        continue
                    try:
                        proc.terminate()
                    except Exception:
                        pass
                stop_monitor.set()
                break
            if inactive_secs > 120:
                print("[INFO] No sensor activity for 120s; stopping.")
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