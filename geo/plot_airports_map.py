"""Generate static Eastern Canada airport map PNG."""
import os

from geo.map_plot import save_airports_map

if __name__ == '__main__':
    out = os.path.join(os.path.dirname(__file__), 'eastern_canada_airports.png')
    save_airports_map(out)
    print(f"Saved map to {out}")