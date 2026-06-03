"""Shared simulation time-scale control (read by aircraft, written by web UI)."""
import json
from pathlib import Path

CONTROL_PATH = Path(__file__).resolve().parent.parent / '.sim_time_scale.json'

DEFAULT_TIME_SCALE = 1.0
VALID_SCALES = (0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0)


def read_time_scale(default: float = DEFAULT_TIME_SCALE) -> float:
    try:
        with CONTROL_PATH.open() as f:
            return max(0.01, float(json.load(f).get('time_scale', default)))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return default


def write_time_scale(scale: float) -> float:
    scale = max(0.01, float(scale))
    CONTROL_PATH.write_text(json.dumps({'time_scale': scale}, indent=0) + '\n')
    return scale


def init_time_scale(scale: float = DEFAULT_TIME_SCALE) -> None:
    write_time_scale(scale)