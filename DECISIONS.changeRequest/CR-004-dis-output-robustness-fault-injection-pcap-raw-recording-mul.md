# CR-004 — DIS output robustness: fault injection, pcap/raw recording, multicast
**Date:** 2026-11-10  **From:** moving-map-display-agent  **Target:** Sensors
**Status:** Pending

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
