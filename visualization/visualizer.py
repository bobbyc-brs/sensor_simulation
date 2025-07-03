# Suppress matplotlib deprecation warnings (e.g., get_cmap) that clutter terminal output.
# This is useful when matplotlib is installed system-wide and cannot be upgraded.
# Only warnings from matplotlib are suppressed; critical errors will still show.
import warnings
warnings.filterwarnings("ignore", category=UserWarning, module="matplotlib")
try:
    from matplotlib import MatplotlibDeprecationWarning
    warnings.filterwarnings("ignore", category=MatplotlibDeprecationWarning)
except ImportError:
    pass

import socket
import struct
import argparse
import threading
import queue
import time
from multicast_config import SENSOR_MCAST_GRP, SENSOR_MCAST_PORT
import matplotlib.pyplot as plt
from collections import defaultdict
import fusion.fusion_app as fusion_app

# Use same message format as fusion_app

def multicast_listener(q, stop_event):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('', SENSOR_MCAST_PORT))
    mreq = struct.pack('4sl', socket.inet_aton(SENSOR_MCAST_GRP), socket.INADDR_ANY)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    sock.settimeout(0.2)
    while not stop_event.is_set():
        try:
            data, _ = sock.recvfrom(1024)
            try:
                text = data.decode()
                parts = text.strip().split(',')
                if parts[0] == 'sensor' and len(parts) >= 6:
                    msg = {'type': 'sensor', 'name': parts[1], 'x': float(parts[2]), 'y': float(parts[3]), 't': float(parts[4]), 'noise_std': float(parts[5])}
                    q.put((parts[1], msg))
                elif parts[0] == 'vehicle' and len(parts) >= 5:
                    msg = {'type': 'vehicle', 'name': parts[1], 'x': float(parts[2]), 'y': float(parts[3]), 't': float(parts[4])}
                    q.put((parts[1], msg))
                # Optionally handle 'fused' messages here
            except Exception:
                continue
        except socket.timeout:
            continue
    sock.close()

def main():
    parser = argparse.ArgumentParser(description="Visualization for Sensor Fusion Simulation (UDP multicast)")
    parser.add_argument('--interval', type=float, default=0.1, help='Visualization update interval (default: 0.1s)')
    args = parser.parse_args()

    q = queue.Queue()
    stop_event = threading.Event()
    t = threading.Thread(target=multicast_listener, args=(q, stop_event), daemon=True)
    t.start()
    threads = [t]

    # Store history for plotting
    sensor_history = defaultdict(list)  # name -> list of (x, y)
    fused_history = []  # list of (x, y)
    last_data = {}  # name -> latest msg

    # Assign a color and name for each sensor (up to 10 for tab10 colormap)
    import matplotlib.cm as cm
    color_map = cm.get_cmap('tab10')
    name_colors = {}
    def get_color(name):
        if name not in name_colors:
            name_colors[name] = color_map(len(name_colors) % 10)
        return name_colors[name]

    plt.ion()
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 6))
    ax1.set_title('Sensor Positions')
    ax1.set_xlabel('X')
    ax1.set_ylabel('Y')
    ax2.set_title('Fused Position Over Time')
    ax2.set_xlabel('Time Step')
    ax2.set_ylabel('Fused X, Y')

    try:
        step = 0
        while True:
            # Gather all new data
            while not q.empty():
                name, msg = q.get()
                last_data[name] = msg
                if msg['type'] == 'sensor':
                    sensor_history[name].append((msg['x'], msg['y']))
                elif msg['type'] == 'vehicle':
                    # Optionally plot vehicle trajectories as well
                    pass
            # Plot sensor positions and latest fused position
            ax1.clear()
            ax1.set_title('Sensor Positions')
            ax1.set_xlabel('X')
            ax1.set_ylabel('Y')
            ax1.set_xlim(-12, 12)
            ax1.set_ylim(-12, 12)
            for name, points in sensor_history.items():
                xs, ys = zip(*points) if points else ([], [])
                ax1.plot(xs, ys, marker='o', label=name, color=get_color(name))
            # Compute and store fused position on every loop if possible
            sensor_msgs = [msg for msg in last_data.values() if msg['type'] == 'sensor']
            if sensor_msgs:
                fused = fusion_app.fuse_positions(sensor_msgs)
                if fused:
                    fused_history.append(fused)
            # Plot latest fused position as a black star
            if fused_history:
                fx, fy = fused_history[-1]
                ax1.plot(fx, fy, marker='*', color='black', markersize=14, label='Fused')
            ax1.legend()

            # Plot fused position trajectory (X vs Y)
            ax2.clear()
            ax2.set_title('Fused Position Trajectory')
            ax2.set_xlabel('Fused X')
            ax2.set_ylabel('Fused Y')
            ax2.set_xlim(-12, 12)
            ax2.set_ylim(-12, 12)
            if fused_history:
                xs, ys = zip(*fused_history)
                # print(f"[DEBUG] Plotting {len(xs)} fused points")
                ax2.plot(xs, ys, marker='*', color='black', label='Fused Trajectory')
                ax2.legend()
            plt.pause(args.interval)
            step += 1
    except KeyboardInterrupt:
        stop_event.set()
        for t in threads:
            t.join()
        print("Visualization stopped.")
    plt.ioff()
    plt.show()

if __name__ == "__main__":
    main()
