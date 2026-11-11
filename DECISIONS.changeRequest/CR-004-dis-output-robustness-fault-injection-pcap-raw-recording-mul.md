# CR-004 — DIS output robustness: fault injection, pcap/raw recording, multicast
**Date:** 2026-11-10  **From:** moving-map-display-agent  **Target:** Sensors
**Status:** Processed — a1e3ac9

### Proposed change

Make the DIS output **adversarial, recordable, and multicast-capable**, so
moving-map can be tested for robustness and regressions. Independent of
CR-003; builds on the CR-001 gateway. Requested by Bobby, 2026-11-10.

1. **Fault injection** (gateway flags, all off by default), each counted in a
   summary printed on exit:
   - `--fault-truncate P` — send fraction P of PDUs cut short (length field unchanged);
   - `--fault-garbage P` — send random-byte datagrams;
   - `--fault-unknown-types` — interleave valid PDUs of types moving-map does not
     decode (e.g. Fire 2, Detonation 3, Collision 4, Create Entity 11);
   - `--fault-v6` — send a share of Entity State with protocol version 6;
   - `--fault-other-exercise N` — send a share with exercise ID N;
   - `--fault-loss P`, `--fault-reorder P`, `--fault-duplicate P` — drop,
     swap adjacent, or repeat datagrams;
   - `--bundle K` — pack up to K PDUs per datagram (v7 bundling).
2. **Record to file** — `--record <path>`: append every datagram sent, in
   **libpcap** format (UDP over IPv4, stdlib `struct` — no dependencies), so it
   opens in Wireshark and can be fed to moving-map. Also `--record-raw <path>`:
   PDUs back to back, which moving-map's `parse <file>` reads directly.
   Commit one short recording per CR-002/CR-003 scenario under `recordings/`
   (< 1 MB each) as regression vectors.
3. **Multicast output** — `--dest` accepts a multicast group (e.g.
   `239.1.2.3`): set `IP_MULTICAST_TTL` (default 1, LAN only) and optionally
   `IP_MULTICAST_IF` (`--dis-iface <ip>`); pass through as
   `simulation_manager.py --dis-dest/--dis-iface`. Matches moving-map
   `listen --group 239.1.2.3 --iface <ip>`.

### Rationale

- moving-map must count bad input and carry on, never crash; today nothing
  sends it bad input.
- Recordings become fixed test vectors for moving-map's `parse` tests until a
  capture from a real simulator is available.
- The site may use multicast (moving-map PLAN ⚖ "DIS site settings"); both
  sides should be ready for either.
- Constraints unchanged: stdlib only, TTL 1 by default, no internet access.

### Acceptance

```bash
# Faults: moving-map must keep running and its counters must account for them
python simulation_manager.py --scenario-file scenarios/ottawa-mixed.json --dis \
  --dis-fault-truncate 0.05 --dis-fault-garbage 0.02 --dis-fault-unknown-types --headless
cargo run -- listen --port 3000 --seconds 60   # malformed > 0, no crash, entities still tracked
# Recording
cargo run -- parse recordings/ottawa-mixed.bin       # every PDU decodes
# Multicast
cargo run -- listen --port 3000 --group 239.1.2.3 --seconds 30
```

- Gateway's fault summary and moving-map's `malformed` / PDU counters agree.
- The pcap opens in Wireshark (or `tcpdump -r`) with the DIS dissector showing
  Entity State PDUs.

### Known gaps / questions

- Flag names on `simulation_manager.py` (e.g. `--dis-fault-*`) are the
  implementer's call; keep them consistent with `--dis-dest` / `--dis-port`.

### Processed — Sensors, 2026-11-10, commit a1e3ac9

**What was done:** `gateways/dis_output.py` is now the one send path for the
CR-001 gateway and the CR-002 CGF runner. Each option exists once and appears as
`--<name>` on the gateway and runner, and as `--dis-<name>` on
`simulation_manager.py`, matching `--dis-dest` / `--dis-port`.

- **Fault injection,** all off by default:
  - **Flags:** `--fault-truncate P`, `--fault-garbage P`, `--fault-unknown-types`,
    `--fault-v6`, `--fault-other-exercise N`, `--fault-loss P`,
    `--fault-reorder P`, `--fault-duplicate P`, plus `--fault-seed N` for
    repeatable runs.
  - **The "share":** for v6, other-exercise and unknown-types it is 10 % of
    Entity State PDUs. Unknown types cycle Fire 2, Detonation 3, Collision 4 and
    Create Entity 11, each with a correct length.
  - **Designed so counts can agree:** a truncated PDU and every garbage datagram
    travel alone and always fail at the first header. Garbage is regenerated
    until it does. Each is therefore exactly one `malformed` at moving-map,
    never a partial PDU.
  - **Scope of each fault:** loss, duplication and reordering act on valid
    datagrams, including Remove Entity, as a real network would.
  - **The exit summary** prints each fault count and the
    `datagrams/pdus/malformed` a receiver should report.
- **`--bundle K`:** DIS 7 bundling, capped at 1400 bytes per datagram (9 Entity
  States) to stay inside the Ethernet MTU. The gateway sends one PDU at a time,
  so bundling only groups anything in the CGF, which batches each 0.1 s step.
- **Recording:** `--record F.pcap` (libpcap, Ethernet/IPv4/UDP, valid IP header
  checksum, real IPs, ports and TTL, placeholder MACs) and `--record-raw F.bin`.
  Both append, and both record exactly what was sent, faults included.
- **`recordings/`:** fault-free pcap + raw for all four scenarios, 34–627 KB each.
  `devel-scripts/record-regression-vectors.sh` regenerates them.
- **Multicast and TTL:**
  - A multicast `--dest` sets `IP_MULTICAST_TTL` and `IP_MULTICAST_LOOP`, and
    `--iface` sets `IP_MULTICAST_IF`.
  - `--ttl` (default 1) is also applied as `IP_TTL` to unicast and broadcast,
    so every DIS datagram is LAN-only by default.

**Verified 2026-11-10:**

- **Unit tests:** 46/46 pass.
  - A receiver that splits datagrams as moving-map does gets the same
    datagrams/pdus/malformed/other-exercise counts as the summary, with every
    fault on at once.
  - Also covered: truncation keeps the length field, unknown types are valid
    PDUs, bundles respect K and the MTU, seeds repeat, pcap/raw structure and
    checksums, multicast and unicast TTL 1, `IP_MULTICAST_IF`, and manager flags
    reaching the runner unchanged.
- **The CR's fault command** (`listen --seconds 65`): moving-map kept running
  with no panic and 13 tracked throughout.
  - Sensors predicted datagrams=1220, pdus=1138, malformed=82 (61 truncated + 21
    garbage, 106 unknown-type).
  - moving-map ended at exactly datagrams=1220, pdus=1138, malformed=82.
- **Every fault, `--dis-bundle 4 --dis-fault-seed 11`,** against
  `listen --exercise 1`:
  - Sensors: 564 datagrams, 1165 PDUs, malformed 60, 108 of them other-exercise.
  - moving-map: datagrams=564, malformed=60, other-exercise=108, pdus=1057
    (= 1165 − 108).
- **Recordings:** `cargo run -- parse` decodes every PDU in all four `.bin` files
  with no errors: 554, 242, 3220 and 546 PDUs.
  - `tcpdump -r` reads one packet per PDU from each `.pcap`, showing TTL 1,
    DF set and UDP length 144.
- **Multicast:** `--dis-dest 239.1.2.3` against `listen --group 239.1.2.3`.
  553 sent, 553 received, 13 tracked, `malformed=0`, all removed on exit.
  - With TTL 1 these datagrams also left on this machine's wired interface (the
    default route), not only loopback.
- **Airport-mode regression:** CR-001 `--dis-fused` still gave 6 tracked,
  `malformed=0`, all removed.

**Not verified / known gaps:**

- **Wireshark:** the pcap was not opened in Wireshark's DIS dissector — there is
  no Wireshark or tshark on this machine; `tcpdump` was the check.
- **`--iface`:** checked by socket option only, not on a second interface.
- **Lost Removes:** with `--fault-loss`, a Remove Entity can be lost like any
  other datagram. The receiver then times the entity out instead of dropping it
  at once.
- **Re-recordings** are not byte-identical: timestamps and pcap times are wall-clock.

### Addendum — Wireshark (tshark 4.2.6) check of the recordings, 2026-11-10

Closes the "pcap not opened in Wireshark" gap above. The recordings were captured
on ports 3901–3904, not 3000, so they need `tshark -d udp.port==390N,dis`.

- **Three-way agreement.** All 4 recordings — 4562 PDUs, 4302 Entity State and 260
  Remove Entity — were compared PDU by PDU across raw bytes, tshark's DIS dissector
  on the `.pcap`, and moving-map `parse` on the `.bin`. **No field disagreed**:
  PDU type, exercise, version, entity ID, force, all 7 entity-type fields, marking,
  and Remove receiving ID.
  - **ECEF:** tshark matches the bytes to within 5 nm, its print precision.
    Orientation and velocity match to their print precision.
  - **moving-map's lat/lon/alt:** matches the bytes to its 6 dp / 0.1 m printing.
- **Timestamps.** tshark reads Sensors' relative timestamps as the same seconds
  past the hour (e.g. 588.1107 s), confirming the CR-003 encoding independently.
- **Bundling.** Wireshark 4.2.6 dissects only the **first** PDU of a bundled
  datagram. All 30 bundled datagrams in a test capture showed one PDU each, so
  later PDUs in a bundle are invisible in Wireshark; moving-map reads them all.
- **Fault traffic counts differently in Wireshark.** It flags truncated PDUs as
  malformed (8 of 8 in a test capture). It decodes garbage datagrams as junk PDUs
  instead (random type and version, e.g. type 152, version 169), so its malformed
  count is lower than moving-map's.
  - The gateway's "receiver should count" line follows moving-map's
    split-by-length rule, not Wireshark's.

### Correction — Entity State / Remove split, 2026-11-10

The addendum above gives the 4562 recorded PDUs as "4302 Entity State and 260
Remove Entity". That was an addition error. The per-recording counts in
`recordings/README.md` were right all along, and they sum to **4339 Entity State
and 223 Remove Entity**:

| Recording | Entity State | Remove Entity |
|---|---|---|
| ottawa-mixed | 541 | 13 |
| lifecycle | 237 | 5 |
| load-200 | 3020 | 200 |
| zone-crossing | 541 | 5 |

moving-map-display caught this in its re-check (TESTLOG 4985c21). The total of
4562, and the finding that every field agreed, are unaffected.
