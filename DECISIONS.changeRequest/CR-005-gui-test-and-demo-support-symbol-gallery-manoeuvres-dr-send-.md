# CR-005 — GUI test and demo support: symbol gallery, manoeuvres, DR send policy, pcap replay, demo tour
**Date:** 2026-11-10  **From:** moving-map-display  **Target:** Sensors
**Status:** Processed — 72897b4

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

### Processed — Sensors, 2026-11-11, commit 72897b4

All five items are done, in priority order. The checks used moving-map's
prebuilt GUI at 7bf85c8, rebuilt at 23:43 — Sensors ran it from
`target/debug/` and built nothing in that tree — plus `listen`, on private
ports 3803–3804.

1. **`symbol-gallery.json`** — 73 entities: a hovering ownship plus 4 forces × 18 types.
   - **Types:** the 12 catalogue types and the 6 raw types as filed.
   - **Generated:** `devel-scripts/make-symbol-gallery.py` writes the file.
   - **Layout, differing from the CR:** 18 columns at about 0.3 NM is 5.1 NM
     wide, too wide for `--range-nm 2`. So the grid is two bands of 9 columns,
     with the ownship between them.
   - **Spacing, differing from the CR:** columns are 0.4 NM apart and rows
     0.35 NM. At 0.3 NM the GUI's ~45 px symbols touched. The furthest cell is
     about 2.4 NM out, and a 1280×800 GUI at 2 NM shows about ±2.6 NM vertically.
   - **Screenshot** (`gui --ownship 1.42.1 --range-nm 2`): every one of the 72
     cells shows, with blue/red/green/yellow rows and rectangle/diamond/square/
     quatrefoil frames. The submarine has the subsurface frame and the UAV,
     ship, infantry and `?` icons show, with 0 bad PDUs.
2. **`ownship-manoeuvres.json`** — this needed two new waypoint forms:
   - **`{"orbit": {...}}`** expands to a point every 30° round a closed circle.
   - **`yaw_dps`** turns the heading on the spot during a hold, with no roll.

   Its 16-minute loop, stepped offline:
   - Right turns total 1363° and left turns 976°, so both directions get full orbits.
   - The heading crosses north 9 times, including the 355° → 005° leg.
   - The hover yaws 359° at zero speed. Pitch reaches 20° and roll 23.7°.

   A track-up screenshot mid-orbit (heading 129°) put all four references at
   the correct relative bearings, with the north arrow pointing lower left.
3. **Dead-reckoning send policy** — `"send": "dead_reckoning"`, opt-in per
   entity or in `defaults`.
   - **Rule:** send when the linear FPW extrapolation of the last PDU, ECEF
     position plus ECEF velocity × dt, is more than `dr_threshold_m` (1 m) off,
     or heading is more than `dr_threshold_deg` (3°) off. Also send a heartbeat
     every `heartbeat_s` (5 s).
   - **On the wire:** the PDU declares dead-reckoning algorithm 2 (FPW).
   - **Default unchanged:** fixed `update_s` stays the default, and its output is
     byte-identical, with algorithm 0.
   - **Measured:** parked, exactly one PDU every 5.0 s. Steady straight motion
     sends 5 s heartbeats only. An orbiting helicopter averages a 1.4 s gap.
     Unit tests cover all three.
4. **`cgf.replay`** — sends each UDP payload byte for byte at its capture time
   offset ÷ `--speed`, with no restamping and no faults. It also takes `--loop`,
   `--gap` and `--only-port`.
   - **Reads:** classic libpcap in both byte orders, µs and ns, with Ethernet
     (VLAN tags skipped), raw IPv4 and Linux SLL/SLL2. IP fragments are skipped
     and counted.
   - **pcapng:** refused, with the `editcap -F pcap` command to convert it.
   - **Measured:** `ottawa-mixed.pcap` at ×4, captured on the receiving side, is
     **byte-identical to `ottawa-mixed.bin`** (554/554). Timing was within 0.01 %
     of span ÷ speed, and `lifecycle.pcap` at ×4 within 0.00 %.
   - **Live at ×1 into `listen`:** the same 13 entities, 554 sent and 554
     received, `malformed=0`, all removed as recorded.
5. **`demo-tour.json`** — a 600 s cycle with a new scenario-level `"repeat": true`.
   - **Restart:** entities present in both cycles keep their IDs and simply
     reposition. Only those absent at the new start get a Remove Entity.
   - **Route:** the ownship flies YOW → Parliament → over the river (30 s hover,
     6°/s yaw) → Rockcliffe → YOW, and is parked at YOW by 591 s.
   - **Events:** VIPER1 appears at 100 s, comes within 1.8 km at about 221 s, and
     is removed at 450 s. A friendly convoy runs throughout. UAV-X goes silent at
     300 s, and CAR2 is removed at 360 s. All of it stays within 15.3 NM of YOW.
   - **Send policy:** everything except the ownship (0.2 s fixed) sends by dead
     reckoning.
   - **Live 640 s into `listen`:** every event happened at its scripted time.
     The 600 s restart removed exactly CONVOY-AFV and CONVOY-TNK, CAR2 and
     UAV-X reappeared, and the ownship stayed tracked without a gap. 4858 sent,
     4858 received, `malformed=0`, 6.6–10.3 PDU/s.
   - **GUI screenshot at 222 s** shows VIPER1 ahead and closing, the convoy,
     traffic, and UAV-X's orbit trail.

**Also:** a parked fixed-wing entity now starts at rest; it used to start at
cruise speed and drift.

**Tests:** 74/74. They cover gallery coverage, the manoeuvres, orbit and yaw
validation, the DR policy (5.0 ± 0.1 s heartbeat, turning, the algorithm byte),
pcap reading of every link type, replay timing within 2 %, and the demo's events
and restart.

**Not done / notes:**
- **GUI checks are screenshots.** The rotation through north was checked as one
  track-up frame plus offline heading data, not as continuous video.
- **Convoy spacing:** the three vehicles are about 300 m apart, so at 5 NM
  their symbols and labels overlap.
