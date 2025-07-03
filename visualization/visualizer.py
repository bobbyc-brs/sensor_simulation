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
            for port, points in sensor_history.items():
                xs, ys = zip(*points) if points else ([], [])
                ax1.plot(xs, ys, marker='o', label=f'Sensor {port}')
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
            if fused_history:
                xs, ys = zip(*fused_history)
                ax2.plot(xs, label='Fused X')
                ax2.plot(ys, label='Fused Y')
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
