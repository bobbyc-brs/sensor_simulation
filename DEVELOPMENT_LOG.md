# Development log

Chronological record of major changes to **sensor_simulation**. For usage and CLI reference, see [README.md](README.md).

Format: **date (approx.)** — summary — key files / commits where known.

---

## 2025-07 — Initial simulator

- Vehicle moves between two Cartesian points; sensors add noise; fusion via weighted average.
- Per-process UDP ports (later replaced by multicast).
- **Commit:** `db61de7` — initial vehicle, sensor, fusion modules.

## 2025-07 — Visualization and simulation manager

- `visualization/visualizer.py` — matplotlib desktop UI (two panels: sensors + fused).
- `simulation_manager.py` — launches vehicles, sensors, fusion, visualizer.
- **Commits:** `9fca01a`, `e6b6b32`, README restructure.

## 2025-07 — Multicast architecture

- All stages on UDP multicast (`multicast_config.py`): aircraft → sensors → fusion/viz.
- Prevents fusion/visualizer from reading raw vehicle truth on the sensor channel.
- **Commit:** `964dd3e` (noted as work-in-progress in message).

## 2025-07 — Multiple sensor types

- **noisy** — Gaussian error on position.
- **adas** — sparse updates (~15 s).
- **tacan** — rotating dish; bearing gate before publish.
- Manager defaults to one of each when `-s` omitted.
- **Commit:** `a2e675c`.

## 2025-07 — Manager CLI simplification

- Default vehicle/sensor counts; repeatable `--sensor-type`, `--tacan-pos`.
- **Commits:** `91552ce`, `e950004`.

## 2026-06-02 — Exploration and backup

- Local backup before pull: `../backup_02June` (full copy of repo).
- Confirmed `origin/main` already up to date; no new remote commits at pull time.
- Runtime notes: fusion initially dropped ADAS/TACAN (non-numeric `noise_std`); long flights at 450 kt; desktop viz not visible when launched from agent environment.

## 2026-06-02 — Eastern Canada airport flights

- Replaced abstract circle paths (radius 10, `--delta`) with **real airports** and **great-circle** routes (lat/lon).
- Six airports: YYT, YHZ, YQB, YUL, YYZ, YOW (YQT/Thunder Bay removed from map extent west of Toronto).
- `vehicles/vehicle_sim.py` — `--origin-airport` / `--dest-airport`, cruise speed, altitude profile.
- `geo/eastern_canada.py` — airports, routes, haversine, interpolation.
- `geo/map_plot.py` — simplified land background; map bounds lon −80.5…−54, lat 40…54.
- Noisy sensor: noise in **meters**, converted to degrees at latitude.
- TACAN: `--radar-lat` / `--radar-lon` (legacy `--radar-x-pos` / `--radar-y-pos` aliases).
- **Commit:** `d4b0d82` (with items below).

## 2026-06-02 — Fusion fixes for all sensor types

- `fusion/fusion_app.py` — numeric weights for `ADAS` / `TACAN` string labels.
- **Commit:** `d4b0d82`.

## 2026-06-02 — Web visualizer (new)

- **Not present before** `d4b0d82`; only `visualization/visualizer.py` (TkAgg desktop) existed.
- `visualization/web_visualizer.py` — HTTP server, live PNG, auto-refresh browser UI.
- `visualization/mcast_feed.py`, `visualization/plot_live.py` — shared multicast + plotting for web and desktop.
- `simulation_manager.py` — **web map default**; `--window` for desktop; `--web-port`.
- Typical URL: http://127.0.0.1:8765/

## 2026-06-02 — Simulation time scale

- `geo/sim_control.py` + `.sim_time_scale.json` (gitignored) — wall-clock speed multiplier without changing cruise knots.
- Web UI buttons: 0.25×, 0.5×, 1×, 2×, 5×, 10×, 20×, 50×.
- `vehicles/vehicle_sim.py` reads scale each tick.
- **Commit:** `d4b0d82`.

## 2026-06-02 — Map UI improvements

- Squarer map extent; cropped west of Toronto.
- **Fused panel** uses same map background as track panel (not bare lon/lat axes only).
- Static reference map: `python -m geo.plot_airports_map` → `geo/eastern_canada_airports.png`.

## 2026-06-02 — Documentation and packaging

- README rewritten: quick start, web UI, time scale, airports, troubleshooting.
- `requirements.txt` — `matplotlib>=3.8`; stdlib for everything else.
- **Commit:** `d4b0d82` pushed to `origin/main`.

---

## Where things are documented

| Topic | Location |
|--------|----------|
| How to run, CLI flags, multicast | [README.md](README.md) |
| History and design timeline | This file (`DEVELOPMENT_LOG.md`) |
| Airport coordinates and routes | `geo/eastern_canada.py` |
| Legacy pre-multicast manager | `simulation_manager_v2.py` (unused) |

---

## Open / follow-up ideas

- [ ] Reduce fusion log spam in terminal.
- [ ] Log vehicle “arrived” once (manager currently can repeat exit messages).
- [ ] Optional `--realistic` vs fast-default time scale for demos.
- [ ] Cartopy or higher-fidelity coastline (optional dependency).
- [ ] Automated tests (multicast message parsing, great-circle distance).

---

*Add new entries at the top of the dated section for your session, or append under the latest date.*