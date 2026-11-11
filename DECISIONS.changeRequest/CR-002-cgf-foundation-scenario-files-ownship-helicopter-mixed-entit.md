# CR-002 — CGF foundation: scenario files, ownship helicopter, mixed entity types and sides (incl. cars, trucks, school buses, horses), current-bearing heading
**Date:** 2026-11-10  **From:** moving-map-display-agent  **Target:** Sensors
**Status:** Pending

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
