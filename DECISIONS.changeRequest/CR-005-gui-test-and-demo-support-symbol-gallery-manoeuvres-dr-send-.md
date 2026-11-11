# CR-005 — GUI test and demo support: symbol gallery, manoeuvres, DR send policy, pcap replay, demo tour
**Date:** 2026-11-10  **From:** moving-map-display  **Target:** Sensors
**Status:** Pending

### Proposed change

moving-map now has a touch-screen GUI (moving-map DD-011, commit
`7bf85c8`; `cargo run -- gui`): APP-6A frames from the DIS entity type, track-up / north-up,
dead reckoning for 5 s, stale dimming at 7 s, trails, MGRS readout. Requested
by Bobby, 2026-11-10: "figure out what else would be useful in Sensors to
test/demo it all". Five items, in priority order; each is independent.

1. **`symbol-gallery.json` — every frame and icon, static, in one view.**
   A 4 × N grid of stationary entities ~0.3 NM apart around a fixed point
   (e.g. 45.40°N 75.70°W), one **row per force** (friendly, opposing,
   neutral, unknown) and one **column per type**: the 12 catalogue types plus
   raw types that reach the remaining frames and icons:
   - subsurface: `[1, 4, 39, 2, 0, 0, 0]` (submarine);
   - military fixed wing: `[1, 2, 39, 1, 0, 0, 0]`; UAV: `[1, 2, 39, 50, 0, 0, 0]`;
   - surface ship other than patrol craft: `[1, 3, 39, 1, 0, 0, 0]`;
   - dismounted person: `[3, 1, 39, 1, 0, 0, 0]`;
   - unknown kind: `[9, 1, 0, 0, 0, 0, 0]`.
   Callsigns name the cell (e.g. `F-TANK`, `U-SUB`). Ownship a hovering
   helicopter at the centre. Runs until Ctrl-C.
2. **`ownship-manoeuvres.json` — track-up and heading wrap.** Ownship
   helicopter: a full 360° orbit (both directions), a straight leg on heading
   355° → 005° (crossing north), a hover with a slow 360° yaw, and a climb /
   descent (pitch) with a level banked turn (roll). Three or four ground
   entities at known bearings as references.
3. **DIS-realistic send policy (optional per entity / scenario):**
   `"send": "dead_reckoning"` — send an Entity State only when the receiver's
   linear dead-reckoned position would be > `dr_threshold_m` (default 1 m)
   or heading > `dr_threshold_deg` (default 3°) off, **plus a heartbeat every
   5 s** (IEEE 1278.1 defaults). Today every entity sends at a fixed
   `update_s`, which a real simulator does not; the GUI's 7 s stale threshold
   and 5 s dead reckoning assume the real behaviour.
4. **Replay a pcap at recorded timing:** `python -m cgf.replay <file.pcap>
   [--port 3800] [--speed 1.0] [--loop]` — send each UDP payload at its
   capture timestamp. Works on Sensors' own recordings now and on a **real
   simulator capture** later (moving-map PLAN ⚖ "real DIS capture"), with no
   scenario engine involved. Stdlib only (`struct` reading libpcap).
5. **`demo-tour.json` — a 10-minute scripted demo, looped.** Ownship helicopter
   transits from YOW past the river; on the way: a hostile attack helicopter
   closes from ahead and turns away; a convoy (truck, AFV, tank) moves along a
   leg; a school bus and cars as neutral traffic; one unknown that goes silent
   (stale, then dropped) and one Remove Entity; a horse with rider. Enough
   variety to show every GUI feature without explanation.

### Rationale

- Item 1 is the only way to check all 16 frame shapes (4 dimensions × 4
  affiliations) and every icon at a glance; ottawa-mixed reaches 7 of them.
- Item 2 exercises the rotation code where it is most likely wrong: heading
  wrap through 000°, orbits, and attitude decode (moving-map now decodes
  pitch / roll from psi/theta/phi — Sensors already sends them, CR-002).
- Item 3 makes stale-dimming and dead-reckoning tests meaningful; fixed 1 s
  updates never exercise either.
- Item 4 is the path for a real simulator capture, and lets a demo run from a
  file on a machine without the scenario engine.
- Constraints unchanged: stdlib only, port 3800 default, TTL 1, no internet.

### Acceptance

```bash
python -m cgf.runner scenarios/symbol-gallery.json
# moving-map:  cargo run -- gui --ownship <printed id> --range-nm 2
#   → every cell visible, correct frame and colour per row
python -m cgf.runner scenarios/ownship-manoeuvres.json
#   → gui --track-up: map rotates smoothly through north, no jump at 360/0
python -m cgf.replay recordings/ottawa-mixed.pcap --speed 1
#   → moving-map `listen` / `gui` show the same 13 entities as the live run
```

- Item 3: with `"send": "dead_reckoning"`, a parked entity sends one PDU per
  5 s (± 0.1 s); a turning entity sends more often; unit tests for both.
- Item 4: replaying a pcap sends the same number of datagrams as it holds,
  and total wall time is within 2 % of the capture's span ÷ `--speed`.

### Known gaps / questions

- Item 5's route and timings are the implementer's call; keep it within
  25 NM of YOW so it fits a 25 NM display.
- If item 3 changes default behaviour, keep `update_s` as the default and make
  `dead_reckoning` opt-in, so CR-003's timing tests stay valid.
