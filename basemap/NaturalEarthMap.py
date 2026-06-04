"""Eastern Canada basemap backed by Natural Earth shapefiles (via cartopy)."""

from __future__ import annotations

import math
from typing import List, Optional, Tuple

import matplotlib.pyplot as plt
from matplotlib.collections import PatchCollection
from matplotlib.patches import Polygon as MplPolygon
from matplotlib.ticker import FuncFormatter


class NaturalEarthMap:
    """
    Basemap backed by Natural Earth shapefiles, rendered on a plain matplotlib Axes.

    Land polygons are downloaded once by cartopy and cached locally. The map uses
    a lon/lat (plate carrée) coordinate system with a geographic aspect correction
    so one degree of latitude and one degree of longitude represent the same ground
    distance at the centre of the map.

    Usage::

        fig, ax = plt.subplots(figsize=(10, 6.5))
        m = NaturalEarthMap()
        m.draw(ax)
        fig.tight_layout()

        # Pixel coordinate conversion (requires finalised layout):
        px, py = m.to_pixel(45.47, -73.74, ax)   # Montreal → (x, y) from top-left
        lat, lon = m.from_pixel(282, 762, ax)      # pixel → geographic

    Natural Earth data is downloaded once and cached by cartopy (typically in
    ~/.local/share/cartopy/).
    """

    # Eastern Canada corridor: Maritimes → Ontario/Quebec, wide enough for YYT.
    DEFAULT_BOUNDS: dict = {
        'lon_min': -81.8,
        'lon_max': -51.2,
        'lat_min': 38.6,
        'lat_max': 55.4,
    }
    DEFAULT_FIGSIZE: Tuple[float, float] = (10, 6.5)
    DEFAULT_DPI: int = 150

    def __init__(
        self,
        bounds: Optional[dict] = None,
        resolution: str = '50m',
    ) -> None:
        """
        Parameters
        ----------
        bounds :
            Dict with keys lon_min, lon_max, lat_min, lat_max.
            Defaults to the Eastern Canada corridor.
        resolution :
            Natural Earth resolution: '10m' (finest), '50m', or '110m' (coarsest).
        """
        self.bounds: dict = dict(self.DEFAULT_BOUNDS if bounds is None else bounds)
        self.resolution: str = resolution
        self._land_geoms: Optional[List] = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_land(self) -> List:
        """Download (once) and return cached Natural Earth land geometries."""
        if self._land_geoms is not None:
            return self._land_geoms
        try:
            import cartopy.io.shapereader as shpreader
        except ImportError as exc:
            raise ImportError(
                "cartopy is required for NaturalEarthMap. "
                "Install with: pip install cartopy"
            ) from exc
        path = shpreader.natural_earth(
            resolution=self.resolution,
            category='physical',
            name='land',
        )
        self._land_geoms = list(shpreader.Reader(path).geometries())
        return self._land_geoms

    def _mean_lat(self) -> float:
        return (self.bounds['lat_min'] + self.bounds['lat_max']) / 2.0

    def _aspect(self) -> float:
        """Degrees-latitude per degrees-longitude aspect at the map centre."""
        return 1.0 / max(0.01, abs(math.cos(math.radians(self._mean_lat()))))

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def draw(self, ax, title: str = 'Eastern Canada') -> None:
        """
        Draw water background, Natural Earth land, and grid onto ax.
        Clips land polygons to bounds. Does not draw airports or routes.
        """
        from shapely.geometry import box as shapely_box

        b = self.bounds
        clip_box = shapely_box(b['lon_min'], b['lat_min'], b['lon_max'], b['lat_max'])

        patches = []
        for geom in self._load_land():
            clipped = geom.intersection(clip_box)
            if clipped.is_empty:
                continue
            parts = getattr(clipped, 'geoms', [clipped])
            for part in parts:
                if hasattr(part, 'exterior'):
                    patches.append(MplPolygon(list(part.exterior.coords), closed=True))

        ax.set_facecolor('#b8d4e8')
        ax.add_collection(
            PatchCollection(
                patches,
                facecolor='#d4e6c3',
                edgecolor='#6a8f5e',
                linewidth=0.4,
                zorder=1,
            )
        )

        ax.set_xlim(b['lon_min'], b['lon_max'])
        ax.set_ylim(b['lat_min'], b['lat_max'])
        ax.set_aspect(self._aspect(), adjustable='box')
        ax.xaxis.set_major_formatter(
            FuncFormatter(lambda lon, _: f'{abs(lon):.0f}°W' if lon < 0 else f'{lon:.0f}°')
        )
        ax.yaxis.set_major_formatter(
            FuncFormatter(lambda lat, _: f'{lat:.0f}°N')
        )
        ax.set_xlabel('Longitude')
        ax.set_ylabel('Latitude')
        ax.set_title(title)
        ax.grid(True, linestyle=':', alpha=0.4, color='#445566', zorder=0)

    # ------------------------------------------------------------------
    # Coordinate conversion
    # ------------------------------------------------------------------

    def to_pixel(self, lat: float, lon: float, ax) -> Tuple[float, float]:
        """
        Convert (lat, lon) to pixel (x, y) measured from the top-left corner
        of the figure. Triggers a layout pass to ensure the axes transform is
        finalised (equivalent to what occurs when saving the figure).

        Returns floats; round to int for integer pixel positions.
        """
        fig = ax.get_figure()
        fig.canvas.draw()
        display_x, display_y = ax.transData.transform([(lon, lat)])[0]
        fig_h_px = fig.get_figheight() * fig.dpi
        return float(display_x), float(fig_h_px - display_y)

    def from_pixel(self, x: float, y: float, ax) -> Tuple[float, float]:
        """
        Convert pixel (x, y) from the top-left of the figure to (lat, lon).
        """
        fig = ax.get_figure()
        fig.canvas.draw()
        fig_h_px = fig.get_figheight() * fig.dpi
        lon, lat = ax.transData.inverted().transform([(x, fig_h_px - y)])[0]
        return float(lat), float(lon)

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def save(
        self,
        path: str,
        figsize: Optional[Tuple[float, float]] = None,
        dpi: Optional[int] = None,
        title: str = 'Eastern Canada',
    ) -> None:
        """Render the basemap and save to a PNG file."""
        figsize = figsize or self.DEFAULT_FIGSIZE
        dpi = dpi or self.DEFAULT_DPI
        fig, ax = plt.subplots(figsize=figsize)
        self.draw(ax, title=title)
        fig.tight_layout()
        fig.savefig(path, dpi=dpi)
        plt.close(fig)
