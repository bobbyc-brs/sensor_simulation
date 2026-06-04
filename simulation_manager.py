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
from geo.scenarios import (
    get_scenario,
    route_for_scenario_index,
    scenario_names,
    sensor_specs_from_counts,
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


def launch_sensor(
    idx,
    name,
    sensor_type='noisy',
    tacan_lat=None,
    tacan_lon=None,
    noise_std=None,
):
    if sensor_type == 'noisy':
        cmd = [sys.executable, '-m', 'sensors.noisy_sensor', '--name', name]
        if noise_std is not None:
            cmd.extend(['--noise_std', str(noise_std)])
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


def _cli_overrides_counts(args) -> bool:
    """True if the user set aircraft/radar/sensor counts on the command line."""
    return any(
        x is not None
        for x in (
            args.num_vehicles,
            args.num_radars,
            args.num_noisy,
            args.num_adas,
            args.num_sensors,
        )
    )


def _resolve_layout(args):
    """Return (num_vehicles, sensor_specs, scenario_routes, scenario_label)."""
    scenario = get_scenario(args.scenario) if args.scenario else None
    scenario_routes = scenario.get('routes') if scenario else None
    scenario_label = None
    if scenario:
        scenario_label = f"{args.scenario} — {scenario['description']}"

    if _cli_overrides_counts(args) or not scenario:
        num_vehicles = args.num_vehicles if args.num_vehicles is not None else 1
        if args.num_sensors is not None and args.num_radars is None and args.num_noisy is None and args.num_adas is None:
            sensor_specs = [
                {'name': f'sensor{i + 1}', 'type': 'noisy'}
                for i in range(args.num_sensors)
            ]
        else:
            num_noisy = args.num_noisy if args.num_noisy is not None else 1
            num_adas = args.num_adas if args.num_adas is not None else 1
            num_radars = args.num_radars if args.num_radars is not None else 1
            sensor_specs = sensor_specs_from_counts(num_noisy, num_adas, num_radars)
    else:
        num_vehicles = scenario['num_vehicles']
        sensor_specs = sensor_specs_from_counts(
            scenario.get('num_noisy', 1),
            scenario.get('num_adas', 1),
            scenario.get('num_radars', 1),
        )

    if args.sensor_type:
        sensor_types = [spec['type'] for spec in sensor_specs]
        for entry in args.sensor_type:
            idx, typ = entry
            idx = int(idx)
            if 1 <= idx <= len(sensor_types):
                sensor_types[idx - 1] = typ.lower()
                sensor_specs[idx - 1]['type'] = typ.lower()

    return num_vehicles, sensor_specs, scenario_routes, scenario_label


def main():
    parser = argparse.ArgumentParser(
        description="Simulation Manager — Eastern Canada airport flights and sensor fusion",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python simulation_manager.py -v 10 -r 7
  python simulation_manager.py -v 5 -r 3 --num-noisy 0 --num-adas 0
  python simulation_manager.py --scenario complex
        """,
    )
    parser.add_argument(
        '-v', '--num-vehicles', type=int, default=None,
        help='Number of aircraft (default: 1, or from --scenario)',
    )
    parser.add_argument(
        '-r', '--num-radars', type=int, default=None,
        help='Number of TACAN radar sensors, placed at airports YHZ→YUL→YYZ→… (default: 1)',
    )
    parser.add_argument(
        '--num-noisy', type=int, default=None,
        help='Number of high-rate noisy position sensors (default: 1)',
    )
    parser.add_argument(
        '--num-adas', type=int, default=None,
        help='Number of ADAS sensors with sparse updates (default: 1)',
    )
    parser.add_argument(
        '--scenario',
        type=str,
        choices=scenario_names(),
        help='Named preset (e.g. complex = -v 10 -r 7 --num-noisy 2 --num-adas 2)',
    )
    parser.add_argument(
        '-s', '--num-sensors', type=int,
        help='Legacy: total sensors, all noisy (use -r / --num-noisy / --num-adas instead)',
    )
    parser.add_argument('--sensor-type', type=str, nargs=2, action='append', metavar=('IDX', 'TYPE'),
                        help='Override sensor type by index: noisy, adas, tacan')
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

    num_vehicles, sensor_specs, scenario_routes, scenario_label = _resolve_layout(args)
    num_sensors = len(sensor_specs)
    num_radars = sum(1 for s in sensor_specs if s['type'] == 'tacan')

    tacan_pos_map = {}
    if args.tacan_pos:
        for entry in args.tacan_pos:
            idx, lat, lon = map(float, entry)
            tacan_pos_map[int(idx)] = (lat, lon)
    if args.tacan_airport:
        for entry in args.tacan_airport:
            idx, icao = entry
            tacan_pos_map[int(idx)] = airport_position(icao.upper())
    for i, spec in enumerate(sensor_specs):
        if spec.get('tacan_airport'):
            tacan_pos_map[i + 1] = airport_position(spec['tacan_airport'].upper())

    init_time_scale(1.0)
    print(f"Eastern Canada airports: {', '.join(f'{k} ({v['name']})' for k, v in AIRPORTS.items())}")
    if scenario_label:
        print(f"Scenario: {scenario_label}")
    print(
        f"Launching {num_vehicles} aircraft, {num_radars} radar(s), "
        f"{num_sensors} sensor(s) total at {args.speed_kts:.0f} kt cruise..."
    )

    vehicle_info = []
    exited_logged = set()
    for i in range(num_vehicles):
        if scenario_routes:
            origin_icao, dest_icao, lat1, lon1, lat2, lon2, dist_km, duration_s = (
                route_for_scenario_index(i, scenario_routes, args.speed_kts)
            )
        else:
            origin_icao, dest_icao = DEFAULT_FLIGHT_ROUTES[i % len(DEFAULT_FLIGHT_ROUTES)]
            lat1, lon1, lat2, lon2, dist_km, duration_s = route_for_vehicle_index(i)
        name = f"flight{i + 1}"
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
    for i, spec in enumerate(sensor_specs):
        idx = i + 1
        name = spec.get('name', f'sensor{idx}')
        stype = spec['type'].lower()
        noise_std = spec.get('noise_std')
        if stype == 'tacan':
            tlat, tlon = tacan_pos_map.get(idx, (default_tacan_lat, default_tacan_lon))
        else:
            tlat, tlon = None, None
        p = launch_sensor(
            i, name, sensor_type=stype, tacan_lat=tlat, tacan_lon=tlon, noise_std=noise_std,
        )
        processes.append(p)
        loc = ''
        if stype == 'tacan':
            loc = f' @ ({tlat:.3f}, {tlon:.3f})'
            for icao, ap in AIRPORTS.items():
                if abs(ap['lat'] - tlat) < 0.01 and abs(ap['lon'] - tlon) < 0.01:
                    loc = f' @ {icao}'
                    break
        extra = f', σ={noise_std:.0f} m' if stype == 'noisy' and noise_std is not None else ''
        sensor_info.append({
            'proc': p, 'name': name, 'type': stype, 'idx': i,
            'tacan_lat': tlat, 'tacan_lon': tlon, 'noise_std': noise_std,
        })
        print(f"  Sensor {name} ({stype}{loc}{extra})")

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
                        noise_std=s.get('noise_std'),
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