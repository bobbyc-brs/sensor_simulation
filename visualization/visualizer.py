import warnings
warnings.filterwarnings("ignore", category=UserWarning, module="matplotlib")
try:
    from matplotlib import MatplotlibDeprecationWarning
    warnings.filterwarnings("ignore", category=MatplotlibDeprecationWarning)
except ImportError:
    pass

import argparse
import matplotlib
matplotlib.use('TkAgg')
import matplotlib.pyplot as plt  # noqa: E402

from visualization.mcast_feed import start_feed
from visualization.plot_live import LivePlotState
from geo.map_plot import draw_eastern_canada_map


def _raise_window(fig):
    try:
        mgr = fig.canvas.manager
        if hasattr(mgr, 'window'):
            win = mgr.window
            win.lift()
            win.attributes('-topmost', True)
            win.after(800, lambda: win.attributes('-topmost', False))
        elif hasattr(mgr, 'show'):
            mgr.show()
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(description="Desktop window — Eastern Canada live map")
    parser.add_argument('--interval', type=float, default=0.5, help='Plot refresh interval (seconds)')
    args = parser.parse_args()

    q, stop_event = start_feed()
    state = LivePlotState()

    plt.ion()
    fig, (ax_map, ax_fused) = plt.subplots(1, 2, figsize=(14, 7))
    fig.canvas.manager.set_window_title('Sensors — Eastern Canada')
    draw_eastern_canada_map(ax_map, show_routes=True, title='Live tracks (Eastern Canada)')
    fig.show()
    _raise_window(fig)
    print('Desktop visualizer: look for window titled "Sensors — Eastern Canada"')
    print('If you do not see it, use: python -m visualization.web_visualizer')

    try:
        while True:
            state.update(q, ax_map, ax_fused)
            fig.canvas.draw_idle()
            fig.canvas.flush_events()
            plt.pause(args.interval)
    except KeyboardInterrupt:
        stop_event.set()
        print('Visualization stopped.')
    plt.ioff()


if __name__ == '__main__':
    main()