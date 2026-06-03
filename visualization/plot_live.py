"""Render live Eastern Canada map + tracks to matplotlib axes."""
from collections import defaultdict

from matplotlib import colormaps

import fusion.fusion_app as fusion_app
from geo.map_plot import draw_eastern_canada_map


class LivePlotState:
    def __init__(self):
        self.sensor_history = defaultdict(list)
        self.vehicle_history = defaultdict(list)
        self.fused_history = []
        self.last_data = {}
        self._color_map = colormaps['tab10']
        self._name_colors = {}

    def ingest(self, q):
        while not q.empty():
            name, msg = q.get()
            self.last_data[name] = msg
            if msg['type'] == 'sensor':
                self.sensor_history[name].append((msg['lon'], msg['lat']))
            elif msg['type'] == 'vehicle':
                self.vehicle_history[name].append((msg['lon'], msg['lat']))

    def _color(self, name):
        if name not in self._name_colors:
            self._name_colors[name] = self._color_map(len(self._name_colors) % 10)
        return self._name_colors[name]

    def _compute_fused(self):
        sensor_msgs = [m for m in self.last_data.values() if m['type'] == 'sensor']
        if not sensor_msgs:
            return None
        fused_msgs = [
            {'x': m['lon'], 'y': m['lat'], 'noise_std': m['noise_std'], 'name': m['name']}
            for m in sensor_msgs
        ]
        return fusion_app.fuse_positions(fused_msgs)

    def update(self, q, ax_map, ax_fused):
        self.ingest(q)
        fused = self._compute_fused()
        if fused:
            self.fused_history.append(fused)

        ax_map.clear()
        draw_eastern_canada_map(ax_map, show_routes=False, title='All tracks')

        for name, points in self.vehicle_history.items():
            if not points:
                continue
            xs, ys = zip(*points)
            ax_map.plot(xs, ys, '-', color='#2e86c1', linewidth=1.2, alpha=0.85, label=f'{name} (truth)')
            ax_map.plot(xs[-1], ys[-1], 'o', color='#2e86c1', markersize=5)

        for name, points in self.sensor_history.items():
            if not points:
                continue
            xs, ys = zip(*points)
            ax_map.plot(
                xs, ys, 'o', linestyle='None', markersize=3,
                color=self._color(name), alpha=0.7, label=name,
            )

        if fused:
            ax_map.plot(
                fused[0], fused[1], marker='*', linestyle='None',
                color='black', markersize=14, label='Fused', zorder=10,
            )

        handles, labels = ax_map.get_legend_handles_labels()
        if labels:
            ax_map.legend(loc='upper left', fontsize=7)

        ax_fused.clear()
        draw_eastern_canada_map(
            ax_fused, show_routes=False, show_airport_labels=False,
            title='Fused position',
        )
        if self.fused_history:
            lons, lats = zip(*self.fused_history)
            ax_fused.plot(lons, lats, '-', color='#333333', linewidth=1.0, alpha=0.6, zorder=6)
            ax_fused.plot(lons, lats, '*', color='black', markersize=7, label='Fused', zorder=8)
            ax_fused.plot(lons[-1], lats[-1], '*', color='#c0392b', markersize=14, zorder=9)
        if self.fused_history and ax_fused.get_legend_handles_labels()[1]:
            ax_fused.legend(loc='upper left', fontsize=7)