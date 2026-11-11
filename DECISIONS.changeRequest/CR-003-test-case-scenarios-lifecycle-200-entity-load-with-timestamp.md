# CR-003 — Test-case scenarios: lifecycle, 200-entity load with timestamps, UTM zone crossing
**Date:** 2026-11-10  **From:** moving-map-display-agent  **Target:** Sensors
**Status:** Processed — 477c126

### Proposed change

Add **test-case scenarios** in the CR-002 scenario-file format, each named for
the moving-map requirement it exercises. Depends on CR-002. Requested by Bobby,
2026-11-10.

1. **Lifecycle** — `scenarios/lifecycle.json` plus the scenario-file features it needs:
   - an entity that **appears late** (start time 20 s);
   - an entity that **goes silent** (stops sending without a Remove Entity) —
     moving-map must drop it after 12 s;
   - an entity **removed** (Remove Entity), then **reappearing** with the same
     ID 10 s later;
   - **duplicate entity numbers on different sites** (1.42.5 and 2.42.5),
     which must stay separate entities.
2. **Load** — `scenarios/load-200.json` or a generator flag: **200 entities**
   (mixed types from CR-002) within 100 NM, each at a 1 s update rate, for
   moving-map's ≥ 30 fps / 200-entity requirement (UN-005). Put the **send time**
   in the PDU timestamp field (DIS relative timestamp: units of 3600 s / 2³¹
   past the hour, low bit 0) so moving-map can measure its < 50 ms
   PDU-to-entity-table latency.
3. **UTM zone crossing** — `scenarios/zone-crossing.json`: the ownship
   helicopter flies west across **78°W** (zone 18 → 17), e.g. Ottawa towards
   Pembroke, with other entities on both sides of the line. Exercises
   moving-map FR-002 (zone transitions) — DD-006 Known Gaps.

### Rationale

- These are the moving-map TEST-PLAN cases nothing currently exercises: entity
  lifecycle (stale, remove, reappear), the 200-entity stress case, processing
  latency, and zone transitions.

### Acceptance

- `lifecycle`: with `cargo run -- listen --seconds 60`, the late entity
  appears at ~20 s; the silent one disappears ~12 s after its last PDU; the
  removed one disappears at once and returns; 1.42.5 and 2.42.5 both tracked.
- `load-200`: moving-map reports 200 tracked, `malformed=0`; sustained PDU
  rate ≈ 200/s measured from Sensors' side.
- `zone-crossing`: helicopter positions straddle 78°W over the run.

### Known gaps / questions

- Whether the 200-entity load runs as 200 processes or one process is the
  implementer's call — one process is likely necessary.

### Processed — Sensors, 2026-11-10, commit 477c126

**What was done:**

- **Scenario format** gains `on_stop` (`remove` or `silent`) and `restart_s`
  (reappear, same ID), plus a seeded `generate` block for large scenarios. All
  are documented in `scenarios/README.md`.
- **`lifecycle.json`:**
  - LATE 1.42.1 starts at 20 s.
  - SILENT 1.42.2 goes silent at 25 s with no Remove Entity.
  - REMOVED 1.42.3 is removed at 30 s and reappears at 40 s.
  - DUP-A 1.42.5 and DUP-B 2.42.5 run throughout.
- **`load-200.json`** runs in one process, as the CR expected.
  - It holds the ownship plus 199 generated entities (seed 2026), cycling all 12
    CR-002 types across all four sides, within 98.7 NM of YOW, at 1 s updates.
  - Send phases are staggered, so the rate is a steady 200 PDU/s with no
    once-a-second burst.
- **Send-time timestamps:** every PDU, from the CGF and the CR-001 gateway alike,
  carries its send time in the DIS relative timestamp format. That is units of
  3600/2³¹ s past the hour in the upper 31 bits, low bit 0, stamped as the
  datagram leaves.
- **`zone-crossing.json`** differs from the CR's example. Pembroke is at about
  77.1°W, east of the zone line, so an Ottawa–Pembroke flight never crosses 78°W.
  - The helicopter instead flies 77.99°W → 78.03°W near Bancroft/Maynooth, then
    turns back.
  - EAST-CAR and EAST-HRS sit east of the line, WEST-TRK and WEST-TNK west of it.

**Verified 2026-11-10:**

- **Unit tests:** 36/36 pass. They cover lifecycle send and remove timings, the
  generator (200 entities, all types and forces, within 100 NM, deterministic),
  195–205 PDUs in every second, the crossing, and timestamp encoding and
  on-the-wire stamping.
- **Live `lifecycle`** (`listen --seconds 63`):
  - LATE first appears at frame 21, about 20 s in.
  - SILENT disappears 10–11 frames after its last PDU. Frames are 1.0–1.2 s
    apart, so that is about 11–13 s, consistent with `ENTITY_TIMEOUT_SECS = 12`.
  - REMOVED is gone at once at 30 s, absent until 40 s, then back under the same ID.
  - 1.42.5 and 2.42.5 stay separate throughout.
  - `malformed=0`; 232 PDUs sent, 232 received.
- **Live `load-200`** (`listen --ownship 1.42.1 --range-nm 100`):
  - 200 tracked with `malformed=0`; 6600 PDUs sent, 6600 received.
  - The runner reported 199.9, 200.1 and 200.0 PDU/s, lagging real time by 6–7 ms.
  - All 200 were removed on exit.
- **Live `zone-crossing`** (`listen --ownship 1.42.1 --range-nm 10`): the
  ownship-centred map read UTM zone 18 up to 77.9985°W and zone 17 from
  78.0000°W on, reaching 78.0241°W. `malformed=0`.
  - Its last frame shows zone 18 again. That is a shutdown artefact: the
    ownship's Remove was handled one redraw before the others, so the map
    re-centred on EAST-CAR.

**Not done:**

- **Latency:** this repo doesn't measure moving-map's PDU-to-table latency; only
  the send-time stamps it needs are in place.
