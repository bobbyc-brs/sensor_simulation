# CR-002 — CGF foundation: scenario files, ownship helicopter, mixed entity types and sides (incl. cars, trucks, school buses, horses), current-bearing heading
**Date:** 2026-11-10  **From:** moving-map-display-agent  **Target:** Sensors
**Status:** Processed — 1f3f99a

### Proposed change

Turn Sensors into a small **CGF** (computer-generated forces) for
moving-map-display's test cases. This CR is the foundation that CR-003 and
CR-004 build on. Requested by Bobby, 2026-11-10.

1. **Scenario file** (stdlib `json`), e.g. `scenarios/<name>.json`, run by
   `python simulation_manager.py --scenario-file scenarios/<name>.json --dis`.
   Each entity declares: callsign, DIS entity type (7 numbers), force ID,
   waypoints (lat, lon, alt m), speed (kt or m/s), start time, optional stop
   time, and `ownship: true` for one entity. The existing airport routes keep
   working; a scenario is an alternative source of entities, not a replacement.
   Entities move **straight between waypoints** — road-following is explicitly
   future work (Bobby).
2. **Ownship helicopter.** A scenario entity flown on waypoints around Ottawa
   at low level (e.g. 150–500 m), including at least one 180° turn and one
   hover (speed 0, holding position, still heart-beating). Send real
   orientation: heading = current track, pitch/roll non-zero in turns and
   climbs, not fixed values.
3. **Mix of entity types and sides**, including Bobby's civilian traffic.
   Codes verified 2026-11-10 against Wireshark `packet-dis.c`
   (kind.domain.country.category.subcategory.specific.extra; country 124 = Canada):

   | Entity | DIS type | Force |
   |---|---|---|
   | Car (generic) | 1.1.124.81.10.0.0 | 3 neutral |
   | Cargo truck (single unit) | 1.1.124.83.0.0.0 | 3 neutral |
   | Bus | 1.1.124.82.0.0.0 | 3 neutral |
   | **School bus** | 1.1.124.82.12.0.0 | 3 neutral |
   | **Horse** | 3.1.124.200.80.0.0 (life form, mammal, horse) | 3 neutral |
   | Horse with rider | 3.1.124.200.90.0.0 | 0 unknown |
   | Tank | 1.1.124.1.0.0.0 | 1 friendly / 2 opposing |
   | Armoured fighting vehicle | 1.1.124.2.0.0.0 | 2 opposing |
   | Utility helicopter (ownship) | 1.2.124.21.0.0.0 | 1 friendly |
   | Attack helicopter | 1.2.124.20.0.0.0 | 2 opposing |
   | Light patrol craft (Ottawa River) | 1.3.124.7.0.0.0 | 3 neutral |
   | Civil airliner (existing routes) | 1.2.124.87.0.0.0 (civilian fixed wing, large) | 3 neutral |

   Ship a scenario `scenarios/ottawa-mixed.json` using **all four sides**
   (friendly 1, opposing 2, neutral 3, unknown 0) and every row above, within
   ~25 NM of YOW, with realistic speeds (horse ~4–10 kt, car ~30–55 kt, school
   bus ~25–40 kt, tank ~15–25 kt).
4. **Heading fix** (from CR-001's open item): send the **current** bearing each
   update, not the initial great-circle bearing, for both airport routes and
   scenario entities.

### Rationale

- moving-map is ownship-centred (REQUIREMENTS UN-001); nothing plays ownship today.
- Friend/foe-at-a-glance (UN-002) and the symbol work for the new civilian and
  animal types need real, varied DIS entity types on all four sides.
- A scenario file makes each test case named and repeatable instead of a set of
  CLI switches; CR-003 adds test-case scenarios in the same format.
- Constraints unchanged: stdlib only, no internet access, DIS on the LAN.

### Acceptance

```bash
# Sensors
python simulation_manager.py --scenario-file scenarios/ottawa-mixed.json --dis --headless
# moving-map-display
cargo run -- listen --port 3000 --ownship <helicopter s.a.e> --range-nm 25 --seconds 60
```

- moving-map centres on the helicopter; all scenario entities tracked;
  `malformed=0`; F, A, N and U statuses all present.
- `cargo run -- parse-stdin` on a captured PDU of each row decodes the exact
  entity type and force above.
- Helicopter heading in moving-map tracks its turns (no fixed bearing); pitch/roll
  non-zero during turns.
- Unit tests: scenario parsing; current-bearing heading; one packed PDU per
  table row checked byte for byte at offsets 20–27.

### Known gaps / questions

- Exact speeds and waypoint placement are the implementer's call; keep the
  scenario readable.
- moving-map does not yet map these types to symbols (its PLAN Phase 1); the
  entity table will show `?` for Activity until it does — not a Sensors issue.

### Processed — Sensors, 2026-11-10, commit 1f3f99a

**What was done:**

- **Scenario files:** stdlib JSON, run by
  `simulation_manager.py --scenario-file <file> --dis` or `python -m cgf.runner <file>`.
  - Each entity takes everything the CR asked for, plus `hold_s` per waypoint,
    `loop`, `update_s` and a `motion` override.
  - `type` is a catalogue name (`school_bus`) or the 7 numbers.
  - The loader validates the file and refuses duplicate IDs, a second ownship,
    an unknown type or a missing speed.
  - The format is documented in `scenarios/README.md`.
- **One process for all entities** (`cgf/runner.py`): steps every 0.1 s in real
  time and sends Remove Entity at `stop_s` and on exit.
  - Scenario mode replaces the airport flights for that run, which keep working
    without `--scenario-file`.
  - It needs its own manager path because the airport loop stops after 120 s
    without sensor traffic.
- **Motion** (`cgf/motion.py`): straight legs between waypoints with no
  road-following. Turn rate, acceleration and climb are limited per model (land,
  lifeform, surface, helicopter, fixed wing).
  - Heading is the current bearing to the next waypoint.
  - Roll is the coordinated-turn bank. Pitch is the climb angle, plus nose-down
    to accelerate for a helicopter.
- **`ottawa-mixed.json`:** HELO1, utility helicopter 1.42.1, friendly, ownship,
  at 150–400 m.
  - Its loop opens with a true 180° reversal (Parliament → LeBreton → back
    east), then a 20 s hover at Rideau Hall.
  - 12 more entities cover every table row on all four sides, all within
    16.7 NM of YOW. Two tanks cover the 1/2 force split.
- **Encoding split:** `gateways/dis_pdu.py` holds the encoding, the entity-type
  catalogue (the CR table verbatim) and full heading/pitch/roll orientation.
  `gateways/dis_output.py` holds the send path, shared by the gateway and the
  CGF, ready for CR-004.
- **Gateway:** airliners now go out as 1.2.124.87.0.0.0.
- **Heading fix:** `vehicles/vehicle_sim.py` sends the current great-circle
  bearing to the destination on every update.

**Verified 2026-11-10:**

- **Unit tests:** 25/25 pass. They check bytes 20–27 for every table row,
  orientation against CR-001's reference encoder, pitch/roll round trips at three
  locations, scenario validation, motion (current bearing, turn roll, hover,
  level ground entities) and `vehicle_sim` current bearing.
- **Listener run:** `--scenario-file scenarios/ottawa-mixed.json --dis --headless`
  against `listen --port 3000 --ownship 1.42.1 --range-nm 25 --seconds 66`.
  - 13 tracked with `malformed=0`; 1129 PDUs sent, 1129 received.
  - The map centre equals HELO1's position; F, A, N and U are all present.
  - All 13 were gone at the first redraw after SIGINT.
- **`parse-stdin` capture:** a second run captured to raw. Every entity decodes
  with the exact type and force in the table.
  - HELO1's decoded heading follows the reversal, 241° → 360° → 32°, over about 25 s.
- **Pitch and roll from the wire:** moving-map doesn't decode them, so they were
  read from the captured bytes with the test suite's independent inverse. Roll
  reached 25° in the turn; pitch ran −11° accelerating to +19° slowing.
- **Airport-mode regression:** CR-001 `-v 3 --dis --dis-fused` gave 6 tracked,
  `malformed=0`, all removed on exit.
- **Heading fix:** proved by unit test only (YYT→YYZ, more than 3° off the
  initial bearing at the midpoint). A 22 s live run is too short to show it.

**Known gaps:**

- **Terrain:** not modelled; a ground entity's altitude is its waypoint altitude.
- **Ground-vehicle pitch and roll:** sent as 0.
- **Entity types:** taken from this CR's table. Not independently re-checked —
  this machine has no Wireshark or tshark.

### Addendum — Wireshark (tshark 4.2.6) check of the entity types, 2026-11-10

Closes the "no Wireshark here" gap above. Each CR-002 type was packed and decoded
with Wireshark's DIS dissector (`tshark -V`).

- **Category names match the table for every row:** Car (81), Bus (82), Single Unit
  Cargo Truck (83), Tank (1), Armored Fighting Vehicle (2), Utility Helicopter (21),
  Attack Helicopter (20), Light/Patrol Craft (7), and Civilian Fixed Wing
  Aircraft, Large (87).
- **Five codes are unconfirmed.** Wireshark prints these as bare numbers, with no
  name: car subcategory 10, school bus subcategory 12, and life-form category 200
  with horse subcategories 80 and 90. The dissector neither confirms nor refutes them.
- **Finding — country 124 is Lesotho, not Canada.** DIS uses the SISO-REF-010
  country enumeration, not ISO 3166; 124 is Canada's ISO numeric code. Decoding
  test PDUs that differed only in country gave:
  - 39 = **Canada**, 124 = **Lesotho**
  - 225 = United States, 224 = United Kingdom

  Every PDU Sensors has sent since CR-001 therefore says Lesotho. The fix is 124 →
  39 in `gateways/dis_pdu.py`'s catalogue and the tests, plus regenerated recordings.
  - **Not changed yet:** the value came from the CR-001/CR-002 tables shared with
    moving-map-display (its DD-004), so it is raised with moving-map-display and
    Bobby first.
  - **No effect on moving-map today:** its entity table does not use the country.
