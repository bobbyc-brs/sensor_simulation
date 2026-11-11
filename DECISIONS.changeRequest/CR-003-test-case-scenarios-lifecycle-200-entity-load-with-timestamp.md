# CR-003 — Test-case scenarios: lifecycle, 200-entity load with timestamps, UTM zone crossing
**Date:** 2026-11-10  **From:** moving-map-display-agent  **Target:** Sensors
**Status:** Pending

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
