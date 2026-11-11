# Recordings — DIS regression vectors

Short, fault-free recordings of each CGF scenario, kept as fixed test vectors
for `~/Projects/moving-map-display` until a capture from a real simulator exists
(CR-004). Each scenario has two files with the same datagrams:

| Format | Use |
|---|---|
| `<name>.bin` | PDUs back to back — `cargo run -- parse recordings/<name>.bin` reads it directly |
| `<name>.pcap` | libpcap, Ethernet/IPv4/UDP with TTL 1 — opens in Wireshark or `tcpdump -r` |

Each scenario was recorded on its own UDP port, so tell Wireshark it is DIS:

```bash
tshark -r recordings/ottawa-mixed.pcap  -d udp.port==3901,dis -V   # lifecycle 3902, load-200 3903, zone-crossing 3904
```

Checked 2026-11-10 with tshark 4.2.6: every field of all 4562 PDUs matches the
raw bytes and moving-map's `parse` (CR-004 addendum). Wireshark decodes DIS
country 124 as **Lesotho** — Canada is 39 — so the recordings were
regenerated with country 39 on 2026-11-10; see the CR-002 addendum.

| Scenario | Length | PDUs | Entity State / Remove Entity |
|---|---|---|---|
| `ottawa-mixed` | 30 s | 554 | 541 / 13 |
| `lifecycle` | 60 s | 242 | 237 / 5 |
| `load-200` | 15 s | 3220 | 3020 / 200 |
| `zone-crossing` | 60 s | 546 | 541 / 5 |

Every recording ends with Remove Entity for each entity still visible. Recorded
2026-11-10; every PDU decodes with moving-map's `parse`, and `tcpdump -r` reads
one packet per PDU (TESTLOG-style evidence in CR-004's Processed note).

**What differs between runs:** PDU timestamps and the pcap times are wall-clock,
so a re-recording is not byte-identical. Entity IDs, types, forces, markings
and tracks are the same for the same scenario.

Regenerate (overwrites these files, about 60 s):

```bash
devel-scripts/record-regression-vectors.sh
```

The MAC addresses in the pcap frames are placeholders (`02:00:00:00:00:0x`); the
IP addresses, ports, TTL and payloads are what was actually sent.
