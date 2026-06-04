"""
Named simulation scenarios and helpers to build sensor layouts from counts.

Run presets:  python simulation_manager.py --scenario complex
Run counts:   python simulation_manager.py -v 10 -r 7
"""

from typing import Any, Dict, List, Tuple

from geo.eastern_canada import AIRPORTS, airport_position, flight_duration_s, haversine_distance_m

# TACAN radar sites cycle through these airports (east → west).
TACAN_AIRPORT_ORDER: List[str] = ['YHZ', 'YUL', 'YYZ', 'YOW', 'YQB', 'YYT']

SCENARIOS: Dict[str, Dict[str, Any]] = {
    'complex': {
        'description': '10 aircraft, 7 radars (plus 2 noisy + 2 ADAS). Same as -v 10 -r 7 --num-noisy 2 --num-adas 2.',
        'num_vehicles': 10,
        'num_noisy': 2,
        'num_adas': 2,
        'num_radars': 7,
        'routes': [
            ('YYT', 'YYZ'),
            ('YHZ', 'YUL'),
            ('YQB', 'YYZ'),
            ('YUL', 'YOW'),
            ('YYZ', 'YHZ'),
            ('YOW', 'YHZ'),
            ('YYT', 'YHZ'),
            ('YHZ', 'YQB'),
            ('YQB', 'YUL'),
            ('YOW', 'YYT'),
        ],
    },
}


def scenario_names() -> List[str]:
    return sorted(SCENARIOS.keys())


def get_scenario(name: str) -> Dict[str, Any]:
    key = name.lower()
    if key not in SCENARIOS:
        raise KeyError(f"Unknown scenario {name!r}. Choose from: {', '.join(scenario_names())}")
    return SCENARIOS[key]


def route_for_scenario_index(
    index: int, routes: List[Tuple[str, str]], speed_kts: float
) -> Tuple[str, str, float, float, float, float, float, float]:
    """Return (origin, dest, lat1, lon1, lat2, lon2, distance_km, duration_s)."""
    origin_icao, dest_icao = routes[index % len(routes)]
    lat1, lon1 = airport_position(origin_icao)
    lat2, lon2 = airport_position(dest_icao)
    dist_m = haversine_distance_m(lat1, lon1, lat2, lon2)
    duration = flight_duration_s(lat1, lon1, lat2, lon2, speed_kts)
    return origin_icao, dest_icao, lat1, lon1, lat2, lon2, dist_m / 1000.0, duration


def sensor_specs_from_counts(
    num_noisy: int = 1,
    num_adas: int = 1,
    num_radars: int = 1,
) -> List[Dict[str, Any]]:
    """Build sensor process specs: noisy + ADAS + TACAN radars at airports."""
    specs: List[Dict[str, Any]] = []
    noisy_sigmas = (35.0, 85.0, 50.0)
    for i in range(num_noisy):
        specs.append({
            'name': f'noisy{i + 1}',
            'type': 'noisy',
            'noise_std': noisy_sigmas[i % len(noisy_sigmas)],
        })
    for i in range(num_adas):
        specs.append({
            'name': f'adas{i + 1}',
            'type': 'adas',
        })
    for i in range(num_radars):
        icao = TACAN_AIRPORT_ORDER[i % len(TACAN_AIRPORT_ORDER)]
        specs.append({
            'name': f'tacan_{icao.lower()}',
            'type': 'tacan',
            'tacan_airport': icao,
        })
    return specs