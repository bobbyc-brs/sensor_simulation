"""Render live Eastern Canada map + tracks to matplotlib axes."""
from collections import defaultdict

from matplotlib import colormaps

import fusion.fusion_app as fusion_app
from basemap import NaturalEarthMap

_basemap = NaturalEarthMap()


class LivePlotState:
    def __init__(self):
        self.sensor_history = defaultdict(list)
        self.vehicle_history = defaultdict(list)
        # Per-aircraft fused track: vehicle -> [(lon, lat), ...]
        self.fused_history = defaultdict(list)
        self.last_data = {}
        # vehicle -> sensor_name -> latest sensor msg for that aircraft
        self.sensor_latest = defaultdict(dict)
        self._color_map = colormaps['tab20']
        self._name_colors = {}

    def ingest(self, q):
        while not q.empty():
            name, msg = q.get()
            if msg['type'] == 'sensor':
                vehicle = msg.get('vehicle') or ''
                if vehicle:
                    self.sensor_latest[vehicle][name] = msg
                self.sensor_history[name].append((msg['lon'], msg['lat']))
            elif msg['type'] == 'vehicle':
                self.last_data[name] = msg
                self.vehicle_history[name].append((msg['lon'], msg['lat']))

    def _color(self, name):
        if name not in self._name_colors:
            self._name_colors[name] = self._color_map(len(self._name_colors) % 20)
        return self._name_colors[name]

    def _compute_fused_by_vehicle(self):
        """Return {vehicle: (lon, lat)} using latest sensor report per sensor per aircraft."""
        result = {}
        for vehicle, readings in self.sensor_latest.items():
            fused_msgs = [
                {
                    'x': m['lon'],
                    'y': m['lat'],
                    'noise_std': m['noise_std'],
                    'name': m['name'],
                    'vehicle': vehicle,
                }
                for m in readings.values()
            ]
            if not fused_msgs:
                continue
            pos = fusion_app.fuse_positions(fused_msgs)
            if pos:
                result[vehicle] = pos
        return result

    def update(self, q, ax_map, ax_fused):
        self.ingest(q)
        fused_by_vehicle = self._compute_fused_by_vehicle()
        for vehicle, pos in fused_by_vehicle.items():
            self.fused_history[vehicle].append(pos)

        ax_map.clear()
        _basemap.draw(ax_map, title='All tracks')

        for name, points in self.vehicle_history.items():
            if not points:
                continue
            xs, ys = zip(*points)
            color = self._color(name)
            ax_map.plot(xs, ys, '-', color=color, linewidth=1.2, alpha=0.85, label=f'{name} (truth)')
            ax_map.plot(xs[-1], ys[-1], 'o', color=color, markersize=5)

        for name, points in self.sensor_history.items():
            if not points:
                continue
            xs, ys = zip(*points)
            ax_map.plot(
                xs, ys, 'o', linestyle='None', markersize=3,
                color=self._color(name), alpha=0.7, label=name,
            )

        for vehicle, (lon, lat) in fused_by_vehicle.items():
            ax_map.plot(
                lon, lat, marker='*', linestyle='None',
                color=self._color(vehicle), markersize=12, zorder=10,
            )

        handles, labels = ax_map.get_legend_handles_labels()
        if labels:
            ax_map.legend(loc='upper left', fontsize=6, ncol=2)

        ax_fused.clear()
        _basemap.draw(ax_fused, title='Fused position (per aircraft)')
        for vehicle, history in self.fused_history.items():
            if not history:
                continue
            color = self._color(vehicle)
            lons, lats = zip(*history)
            ax_fused.plot(lons, lats, '-', color=color, linewidth=1.0, alpha=0.65, zorder=6)
            ax_fused.plot(lons, lats, '*', color=color, markersize=5, zorder=8)
            ax_fused.plot(
                lons[-1], lats[-1], '*', color=color, markersize=12,
                label=vehicle, zorder=9,
            )
        if ax_fused.get_legend_handles_labels()[1]:
            ax_fused.legend(loc='upper left', fontsize=6, ncol=2)
