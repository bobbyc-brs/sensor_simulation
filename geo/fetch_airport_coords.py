#!/usr/bin/env python3
"""
Fetch WGS84 airport coordinates from the OurAirports open dataset.

Data: https://ourairports.com/data/ (airports.csv, ~monthly updates)
OurAirports aggregates official government and AIP sources worldwide.

Developer tool: needs internet access. Never run on the target system; the
simulator does not use it. Prints coordinates only — copy them into
geo/eastern_canada.py by hand.
"""

from __future__ import annotations

import csv
import sys
import urllib.request

OURAIRPORTS_CSV = 'https://davidmegginson.github.io/ourairports-data/airports.csv'

ICAO_BY_IATA = {
    'YYT': 'CYYT',
    'YHZ': 'CYHZ',
    'YQB': 'CYQB',
    'YUL': 'CYUL',
    'YYZ': 'CYYZ',
    'YOW': 'CYOW',
}


def load_ourairports() -> dict[str, tuple[float, float, str]]:
    req = urllib.request.Request(OURAIRPORTS_CSV, headers={'User-Agent': 'Sensors/1.0'})
    text = urllib.request.urlopen(req, timeout=60).read().decode('utf-8')
    rows = {}
    for row in csv.DictReader(text.splitlines()):
        ident = row['ident']
        if ident in ICAO_BY_IATA.values():
            rows[ident] = (
                float(row['latitude_deg']),
                float(row['longitude_deg']),
                row.get('name', ''),
            )
    return rows


def main() -> int:
    codes = sys.argv[1:] if len(sys.argv) > 1 else list(ICAO_BY_IATA)
    data = load_ourairports()
    missing = []
    for code in codes:
        icao = ICAO_BY_IATA.get(code.upper(), code.upper())
        if icao not in data:
            print(f'{code} ({icao}): not found in OurAirports')
            missing.append(code)
            continue
        lat, lon, name = data[icao]
        print(f'{code} ({icao}): {lat:.7f}, {lon:.7f}  # {name}')
    return 1 if missing else 0


if __name__ == '__main__':
    raise SystemExit(main())