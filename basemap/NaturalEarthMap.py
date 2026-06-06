"""Eastern Canada basemap — NE1 georeferenced raster with vector fallback."""

from __future__ import annotations

import math
import os
import xml.etree.ElementTree as ET
from typing import List, Optional, Tuple

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.collections import PatchCollection
from matplotlib.patches import Polygon as MplPolygon
from matplotlib.ticker import FuncFormatter


class NaturalEarthMap:
    """
    Basemap for Eastern Canada.

    Preferred: a georeferenced NE1 raster PNG (+ .aux.xml sidecar) placed in
    the same directory as this file. The image is cropped to bounds once and
    cached in memory.

    Fallback: Natural Earth vector shapefiles via cartopy, drawn as matplotlib
    polygon patches.

    Usage::

        fig, ax = plt.subplots(figsize=(10, 6.5))
        m = NaturalEarthMap()
        m.draw(ax)
        fig.tight_layout()

    Natural Earth 1 rasters: https://www.naturalearthdata.com/downloads/10m-raster-data/10m-natural-earth-1/
    """

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
        image_path: Optional[str] = None,
    ) -> None:
        """
        Parameters
        ----------
        bounds :
            Dict with lon_min/lon_max/lat_min/lat_max. Defaults to Eastern Canada corridor.
        resolution :
            Vector fallback resolution: '10m', '50m', or '110m'.
        image_path :
            Path to a georeferenced PNG with a .aux.xml sidecar. If None, the
            directory containing this file is scanned for a matching pair.
        """
        self.bounds: dict = dict(self.DEFAULT_BOUNDS if bounds is None else bounds)
        self.resolution: str = resolution
        self._land_geoms: Optional[List] = None
        self._image_cache: Optional[Tuple] = None

        if image_path is None:
            image_path = self._find_raster()
        self._image_path: Optional[str] = image_path

    # ------------------------------------------------------------------
    # Raster path
    # ------------------------------------------------------------------

    def _find_raster(self) -> Optional[str]:
        """Return the first .png with a matching .aux.xml in the basemap directory."""
        here = os.path.dirname(os.path.abspath(__file__))
        for name in sorted(os.listdir(here)):
            if name.lower().endswith('.png') and os.path.exists(os.path.join(here, name + '.aux.xml')):
                return os.path.join(here, name)
        return None

    def _parse_geotransform(self) -> List[float]:
        """Read GDAL GeoTransform from the .aux.xml sidecar."""
        tree = ET.parse(self._image_path + '.aux.xml')
        return [float(x.strip()) for x in tree.find('GeoTransform').text.split(',')]

    def _load_image(self) -> Tuple:
        """Crop raster to map bounds; cache and return (rgb_array, [lon_min, lon_max, lat_min, lat_max])."""
        if self._image_cache is not None:
            return self._image_cache

        from PIL import Image
        Image.MAX_IMAGE_PIXELS = None  # known large but safe file

        gt = self._parse_geotransform()
        # gt: [origin_lon, px_lon, 0, origin_lat, 0, -px_lat]
        b = self.bounds

        img = Image.open(self._image_path)
        W, H = img.size

        x0 = max(0, int((b['lon_min'] - gt[0]) / gt[1]))
        x1 = min(W, int((b['lon_max'] - gt[0]) / gt[1]) + 1)
        y0 = max(0, int((gt[3] - b['lat_max']) / abs(gt[5])))
        y1 = min(H, int((gt[3] - b['lat_min']) / abs(gt[5])) + 1)

        extent = [
            gt[0] + x0 * gt[1],       # lon_min
            gt[0] + x1 * gt[1],       # lon_max
            gt[3] - y1 * abs(gt[5]),  # lat_min
            gt[3] - y0 * abs(gt[5]),  # lat_max
        ]

        self._image_cache = (np.array(img.crop((x0, y0, x1, y1))), extent)
        return self._image_cache

    # ------------------------------------------------------------------
    # Vector fallback path
    # ------------------------------------------------------------------

    def _load_land(self) -> List:
        """Download (once) and cache Natural Earth land geometries via cartopy."""
        if self._land_geoms is not None:
            return self._land_geoms
        try:
            import cartopy.io.shapereader as shpreader
        except ImportError as exc:
            raise ImportError(
                "cartopy is required when no georeferenced raster is available. "
                "Install with: pip install cartopy"
            ) from exc
        path = shpreader.natural_earth(resolution=self.resolution, category='physical', name='land')
        self._land_geoms = list(shpreader.Reader(path).geometries())
        return self._land_geoms

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _mean_lat(self) -> float:
        return (self.bounds['lat_min'] + self.bounds['lat_max']) / 2.0

    def _aspect(self) -> float:
        """Geographic aspect: 1 deg lat = this many display units per 1 deg lon."""
        return 1.0 / max(0.01, abs(math.cos(math.radians(self._mean_lat()))))

    def _set_axes(self, ax, title: str) -> None:
        b = self.bounds
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
        ax.grid(True, linestyle=':', alpha=0.4, color='#445566', zorder=2)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def draw(self, ax, title: str = 'Eastern Canada') -> None:
        """Draw the basemap (raster if available, otherwise vector) onto ax."""
        if self._image_path:
            img_arr, extent = self._load_image()
            ax.imshow(
                img_arr, extent=extent, origin='upper',
                aspect='auto', interpolation='bilinear', zorder=0,
            )
        else:
            self._draw_vector(ax)
        self._set_axes(ax, title)

    def _draw_vector(self, ax) -> None:
        from shapely.geometry import box as shapely_box
        b = self.bounds
        clip_box = shapely_box(b['lon_min'], b['lat_min'], b['lon_max'], b['lat_max'])

        patches = []
        for geom in self._load_land():
            clipped = geom.intersection(clip_box)
            if clipped.is_empty:
                continue
            for part in getattr(clipped, 'geoms', [clipped]):
                if hasattr(part, 'exterior'):
                    patches.append(MplPolygon(list(part.exterior.coords), closed=True))

        ax.set_facecolor('#b8d4e8')
        ax.add_collection(PatchCollection(
            patches, facecolor='#d4e6c3', edgecolor='#6a8f5e', linewidth=0.4, zorder=1,
        ))

    def save(
        self,
        path: str,
        figsize: Optional[Tuple[float, float]] = None,
        dpi: Optional[int] = None,
        title: str = 'Eastern Canada',
    ) -> None:
        """Render the basemap and save to a PNG file."""
        fig, ax = plt.subplots(figsize=figsize or self.DEFAULT_FIGSIZE)
        self.draw(ax, title=title)
        fig.tight_layout()
        fig.savefig(path, dpi=dpi or self.DEFAULT_DPI)
        plt.close(fig)
