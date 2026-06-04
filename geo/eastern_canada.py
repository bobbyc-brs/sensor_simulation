"""
Eastern Canada airports, map extent, and great-circle flight geometry.
Positions are WGS84 decimal degrees (lat, lon).

Airport coordinates match the Canada Flight Supplement (CFS) reference points
cited on each airport's Wikipedia article, cross-checked with the OurAirports
open dataset (https://ourairports.com/data/). Refresh with:
  python3 -m geo.fetch_airport_coords
"""
import math
from typing import Dict, List, Tuple

# Six major airports spaced across Atlantic Canada, Quebec, and Ontario.
AIRPORTS: Dict[str, dict] = {
    'YYT': {
        'name': "St. John's",
        'city': "St. John's, NL",
        'lat': 47.6186111,
        'lon': -52.7525000,
    },
    'YHZ': {
        'name': 'Halifax',
        'city': 'Halifax, NS',
        'lat': 44.8797222,
        'lon': -63.5102778,
    },
    'YQB': {
        'name': 'Quebec City',
        'city': 'Quebec City, QC',
        'lat': 46.7911111,
        'lon': -71.3933333,
    },
    'YUL': {
        'name': 'Montreal',
        'city': 'Montreal, QC',
        'lat': 45.4705556,
        'lon': -73.7408333,
    },
    'YYZ': {
        'name': 'Toronto',
        'city': 'Toronto, ON',
        'lat': 43.6772222,
        'lon': -79.6305556,
    },
    'YOW': {
        'name': 'Ottawa',
        'city': 'Ottawa, ON',
        'lat': 45.3225000,
        'lon': -75.6691667,
    },
}

# Map view: Maritimes → Ontario/Quebec corridor (no Great Lakes west of Toronto).
# ~10% wider than prior bounds so YYT (≈52.75°W) stays inside the frame.
MAP_BOUNDS = {
    'lon_min': -81.8,
    'lon_max': -51.2,
    'lat_min': 38.6,
    'lat_max': 55.4,
}

# Default cruise speed for commercial jets (knots).
DEFAULT_CRUISE_SPEED_KTS = 450.0
KTS_TO_MPS = 0.514444
EARTH_RADIUS_M = 6_371_000.0
DEFAULT_CRUISE_ALT_FT = 35_000.0

# Diverse origin–destination pairs (ICAO codes).
DEFAULT_FLIGHT_ROUTES: List[Tuple[str, str]] = [
    ('YYT', 'YYZ'),   # St. John's → Toronto (long Atlantic + inland)
    ('YHZ', 'YUL'),   # Halifax → Montreal
    ('YQB', 'YYZ'),   # Quebec City → Toronto
    ('YUL', 'YOW'),   # Montreal → Ottawa
    ('YYZ', 'YHZ'),   # Toronto → Halifax
    ('YOW', 'YHZ'),   # Ottawa → Halifax
]


def airport_position(icao: str) -> Tuple[float, float]:
    """Return (lat, lon) for an airport ICAO code."""
    ap = AIRPORTS[icao]
    return ap['lat'], ap['lon']


def haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in meters."""
    phi1, lam1, phi2, lam2 = map(math.radians, (lat1, lon1, lat2, lon2))
    dphi = phi2 - phi1
    dlam = lam2 - lam1
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def initial_bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Forward azimuth from point 1 to point 2, degrees clockwise from north."""
    phi1, lam1, phi2, lam2 = map(math.radians, (lat1, lon1, lat2, lon2))
    dlam = lam2 - lam1
    x = math.sin(dlam) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlam)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def _to_unit_xyz(lat_deg: float, lon_deg: float) -> Tuple[float, float, float]:
    phi, lam = math.radians(lat_deg), math.radians(lon_deg)
    return (
        math.cos(phi) * math.cos(lam),
        math.cos(phi) * math.sin(lam),
        math.sin(phi),
    )


def _from_unit_xyz(x: float, y: float, z: float) -> Tuple[float, float]:
    lat = math.degrees(math.asin(max(-1.0, min(1.0, z))))
    lon = math.degrees(math.atan2(y, x))
    return lat, lon


def interpolate_great_circle(
    lat1: float, lon1: float, lat2: float, lon2: float, fraction: float
) -> Tuple[float, float]:
    """Position along great-circle path; fraction in [0, 1]."""
    f = max(0.0, min(1.0, fraction))
    if f <= 0.0:
        return lat1, lon1
    if f >= 1.0:
        return lat2, lon2
    x1, y1, z1 = _to_unit_xyz(lat1, lon1)
    x2, y2, z2 = _to_unit_xyz(lat2, lon2)
    dot = max(-1.0, min(1.0, x1 * x2 + y1 * y2 + z1 * z2))
    omega = math.acos(dot)
    if omega < 1e-12:
        return lat1, lon1
    s1 = math.sin((1.0 - f) * omega) / math.sin(omega)
    s2 = math.sin(f * omega) / math.sin(omega)
    return _from_unit_xyz(s1 * x1 + s2 * x2, s1 * y1 + s2 * y2, s1 * z1 + s2 * z2)


def flight_duration_s(
    lat1: float, lon1: float, lat2: float, lon2: float, speed_kts: float = DEFAULT_CRUISE_SPEED_KTS
) -> float:
    """Time to fly great-circle route at constant groundspeed."""
    speed_mps = speed_kts * KTS_TO_MPS
    if speed_mps <= 0:
        raise ValueError('speed_kts must be positive')
    return haversine_distance_m(lat1, lon1, lat2, lon2) / speed_mps


def cruise_altitude_ft(fraction: float, cruise_alt_ft: float = DEFAULT_CRUISE_ALT_FT) -> float:
    """Simple altitude profile: climb first 8%, cruise, descend last 8%."""
    f = max(0.0, min(1.0, fraction))
    if f < 0.08:
        return cruise_alt_ft * (f / 0.08)
    if f > 0.92:
        return cruise_alt_ft * ((1.0 - f) / 0.08)
    return cruise_alt_ft


def route_for_vehicle_index(index: int) -> Tuple[str, str, float, float, float, float]:
    """
    Return (origin_lat, origin_lon, dest_lat, dest_lon, distance_km, duration_s)
    for vehicle index using DEFAULT_FLIGHT_ROUTES.
    """
    origin_icao, dest_icao = DEFAULT_FLIGHT_ROUTES[index % len(DEFAULT_FLIGHT_ROUTES)]
    lat1, lon1 = airport_position(origin_icao)
    lat2, lon2 = airport_position(dest_icao)
    dist_m = haversine_distance_m(lat1, lon1, lat2, lon2)
    duration = flight_duration_s(lat1, lon1, lat2, lon2)
    return lat1, lon1, lat2, lon2, dist_m / 1000.0, duration


def route_label(origin_icao: str, dest_icao: str) -> str:
    o = AIRPORTS[origin_icao]
    d = AIRPORTS[dest_icao]
    return f"{origin_icao} ({o['city']}) → {dest_icao} ({d['city']})"


def meters_to_degree_noise(lat_deg: float, noise_m: float) -> Tuple[float, float]:
    """Approximate 1-sigma lat/lon noise in degrees for east/north Gaussian error (meters)."""
    lat_scale = 111_320.0
    lon_scale = 111_320.0 * max(0.01, math.cos(math.radians(lat_deg)))
    return noise_m / lat_scale, noise_m / lon_scale