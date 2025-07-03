import socket
import argparse
import threading
import queue
import time
import matplotlib.pyplot as plt
from collections import defaultdict
import fusion.fusion_app as fusion_app

# Use same message format as fusion_app

def sensor_listener(port, q, stop_event):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('127.0.0.1', port))
    sock.settimeout(0.2)
    while not stop_event.is_set():
        try:
            data, _ = sock.recvfrom(1024)
            msg = fusion_app.parse_sensor_msg(data)
            if msg:
                q.put((port, msg))
        except socket.timeout:
            continue
    sock.close()

def main():
    parser = argparse.ArgumentParser(description="Visualization for Sensor Fusion Simulation")
    parser.add_argument('--sensor_ports', type=int, nargs='+', required=True, help='UDP ports to listen to sensors')
    parser.add_argument('--interval', type=float, default=0.1, help='Visualization update interval (default: 0.1s)')
    args = parser.parse_args()

    q = queue.Queue()
    stop_event = threading.Event()
    threads = []
    for port in args.sensor_ports:
        t = threading.Thread(target=sensor_listener, args=(port, q, stop_event), daemon=True)
        t.start()
        threads.append(t)

    # Store history for plotting
    sensor_history = defaultdict(list)  # port -> list of (x, y)
    fused_history = []  # list of (x, y)
    last_data = {}  # port -> latest msg

    # Assign a color and name for each sensor
    import matplotlib.colormaps as mcolormaps
    sensor_ports = args.sensor_ports
    color_map = mcolormaps.get_cmap('tab10')
    # Evenly space colors for each port
    port_colors = [color_map(i / max(1, len(sensor_ports)-1)) for i in range(len(sensor_ports))]
    port_to_color = {port: port_colors[i] for i, port in enumerate(sensor_ports)}
    port_to_name = {port: None for port in sensor_ports}  # Will be filled in as data arrives

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
                port, msg = q.get()
                last_data[port] = msg
                sensor_history[port].append((msg['x'], msg['y']))
            # Plot sensor positions
            ax1.clear()
            ax1.set_title('Sensor Positions')
            ax1.set_xlabel('X')
            ax1.set_ylabel('Y')
            ax1.set_xlim(-12, 12)
            ax1.set_ylim(-12, 12)
            for port, points in sensor_history.items():
                xs, ys = zip(*points) if points else ([], [])
                # Try to get sensor name from last_data if available
                name = last_data[port]['name'] if port in last_data and 'name' in last_data[port] else f'Sensor {port}'
                port_to_name[port] = name
                ax1.plot(xs, ys, marker='o', label=name, color=port_to_color[port])
            ax1.legend()
            # Plot fused position
            if last_data:
                fused = fusion_app.fuse_positions(list(last_data.values()))
                if fused:
                    fused_history.append(fused)
            ax2.clear()
            ax2.set_title('Fused Position Over Time')
            ax2.set_xlabel('Time Step')
            ax2.set_ylabel('Fused X, Y')
            ax2.set_xlim(-12, 12)
            ax2.set_ylim(-12, 12)
            if fused_history:
                xs, ys = zip(*fused_history)
                ax2.plot(xs, label='Fused_alg1 X', color='black', linestyle='-')
                ax2.plot(ys, label='Fused_alg1 Y', color='black', linestyle='--')
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
