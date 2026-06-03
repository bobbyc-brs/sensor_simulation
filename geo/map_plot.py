"""Matplotlib helpers for Eastern Canada map backgrounds (no cartopy required)."""
import math
from typing import List, Optional, Tuple

from matplotlib.patches import Polygon

from geo.eastern_canada import AIRPORTS, DEFAULT_FLIGHT_ROUTES, MAP_BOUNDS

# Simplified land (lon, lat), clipped to MAP_BOUNDS visually.
_LAND_REGIONS: List[List[Tuple[float, float]]] = [
    # Newfoundland & Labrador
    [
        (-54.0, 46.0), (-54.0, 52.5), (-57.5, 52.5), (-59.0, 50.0), (-57.0, 47.0), (-55.0, 46.0),
    ],
    # Nova Scotia, PEI, NB
    [
        (-63.0, 43.5), (-63.0, 47.5), (-66.5, 47.5), (-68.0, 46.0), (-66.0, 44.0), (-64.0, 43.5),
    ],
    # Quebec + St. Lawrence
    [
        (-57.0, 44.0), (-57.0, 54.0), (-70.0, 54.0), (-70.0, 40.5), (-66.0, 44.0), (-63.0, 45.5),
        (-57.0, 44.0),
    ],
    # Southern Ontario (east of Toronto — western edge ~-80.5)
    [
        (-70.0, 40.0), (-70.0, 46.5), (-80.5, 46.5), (-80.5, 40.0), (-74.0, 40.0), (-70.0, 40.0),
    ],
]


def _aspect_correction_lat(mean_lat: float) -> float:
    return 1.0 / max(0.01, abs(math.cos(math.radians(mean_lat))))


def _airport_in_bounds(icao: str) -> bool:
    ap = AIRPORTS[icao]
    b = MAP_BOUNDS
    return b['lon_min'] <= ap['lon'] <= b['lon_max'] and b['lat_min'] <= ap['lat'] <= b['lat_max']


def draw_eastern_canada_map(
    ax,
    *,
    show_routes: bool = True,
    highlight_route: Optional[Tuple[str, str]] = None,
    title: str = 'Eastern Canada',
    show_airport_labels: bool = True,
) -> None:
    """Draw water background, simplified land, airports, and optional route arcs."""
    ax.set_facecolor('#b8d4e8')
    for region in _LAND_REGIONS:
        ax.add_patch(
            Polygon(region, closed=True, facecolor='#e8e0c8', edgecolor='#6b5b4f', linewidth=0.6, zorder=1)
        )
    mean_lat = (MAP_BOUNDS['lat_min'] + MAP_BOUNDS['lat_max']) / 2.0
    ax.set_xlim(MAP_BOUNDS['lon_min'], MAP_BOUNDS['lon_max'])
    ax.set_ylim(MAP_BOUNDS['lat_min'], MAP_BOUNDS['lat_max'])
    ax.set_aspect(_aspect_correction_lat(mean_lat), adjustable='box')
    try:
        ax.set_box_aspect(1)
    except AttributeError:
        pass
    ax.set_xlabel('Longitude (°W)')
    ax.set_ylabel('Latitude (°N)')
    ax.set_title(title)
    ax.grid(True, linestyle=':', alpha=0.45, color='#445566')

    if show_routes:
        for origin, dest in DEFAULT_FLIGHT_ROUTES:
            if not (_airport_in_bounds(origin) and _airport_in_bounds(dest)):
                continue
            o = AIRPORTS[origin]
            d = AIRPORTS[dest]
            lw, alpha, color = 0.8, 0.35, '#888888'
            if highlight_route == (origin, dest):
                lw, alpha, color = 1.5, 0.85, '#c44e00'
            ax.plot(
                [o['lon'], d['lon']],
                [o['lat'], d['lat']],
                linestyle='--',
                color=color,
                linewidth=lw,
                alpha=alpha,
                zorder=2,
            )

    for icao, ap in AIRPORTS.items():
        if not _airport_in_bounds(icao):
            continue
        ax.plot(ap['lon'], ap['lat'], marker='^', color='#1a5276', markersize=9, zorder=4)
        if show_airport_labels:
            ax.annotate(
                f"{icao}\n{ap['name']}",
                (ap['lon'], ap['lat']),
                textcoords='offset points',
                xytext=(6, 6),
                fontsize=7,
                color='#1a252f',
                zorder=5,
            )


def save_airports_map(path: str) -> None:
    """Write a static PNG of airports and default routes."""
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(9, 9))
    draw_eastern_canada_map(ax, show_routes=True)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)