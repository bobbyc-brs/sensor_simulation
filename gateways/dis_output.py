"""DIS output: the one place PDUs leave Sensors (gateway and CGF both use it).

OUTPUT_OPTIONS defines the output flags once; the gateway and CGF runner add
them bare (--dest), and simulation_manager.py adds them prefixed (--dis-dest)
and forwards them, so the three can never drift apart.

Per send, in order (CR-003, CR-004):
1. stamp each PDU with its DIS relative send time;
2. per-PDU faults on Entity State PDUs: protocol version 6, another exercise
   ID, truncation (sent alone, length field unchanged), and interleaved valid
   PDUs of types the receiver does not decode;
3. bundle up to --bundle PDUs per datagram (≤ MAX_DATAGRAM bytes);
4. per-datagram faults on valid datagrams: loss, duplication, reordering
   (swap with the next datagram), plus extra random-byte datagrams;
5. send, and record what was sent (pcap and/or raw).

Fault datagrams (truncated, garbage) always travel alone and always fail at
their first header, so each one is exactly one 'malformed' at a receiver that
splits datagrams by header length, as moving-map does. The summary printed on
close says what such a receiver should have counted.
"""
import ipaddress
import os
import random
import socket
import struct
import time

from gateways.dis_pdu import (
    FILLER_PDUS,
    PDU_ENTITY_STATE,
    pack_filler,
    relative_timestamp,
    split_pdus,
)

DEFAULT_PORT = 3800        # Bobby, 2026-11-10 (moving-map DD-007); 3801–3809 for private test runs
MAX_DATAGRAM = 1400       # bytes; keeps bundles inside a 1500-byte Ethernet MTU
FAULT_SHARE = 0.1         # share of Entity State PDUs hit by --fault-v6 / --fault-other-exercise / --fault-unknown-types

OUTPUT_OPTIONS = (
    ('dest', {'default': '127.0.0.1',
              'help': 'DIS destination: unicast, broadcast (e.g. 192.168.1.255) or multicast group (e.g. 239.1.2.3) (default: 127.0.0.1)'}),
    ('port', {'type': int, 'default': DEFAULT_PORT,
              'help': f'DIS UDP port (default: {DEFAULT_PORT}; 3801–3809 are for private test runs)'}),
    ('iface', {'default': None, 'help': 'Local interface address for multicast output (IP_MULTICAST_IF)'}),
    ('ttl', {'type': int, 'default': 1, 'help': 'IP TTL for every DIS datagram; 1 keeps DIS on the LAN (default: 1)'}),
    ('bundle', {'type': int, 'default': 1,
                'help': f'Pack up to K PDUs per datagram (DIS 7 bundling, ≤ {MAX_DATAGRAM} bytes) (default: 1)'}),
    ('record', {'default': None, 'help': 'Append every datagram sent to this libpcap file (Ethernet/IPv4/UDP)'}),
    ('record-raw', {'default': None, 'help': 'Append every datagram sent, back to back, to this raw file'}),
    ('fault-truncate', {'type': float, 'default': 0.0, 'help': 'Fraction P of Entity State PDUs sent cut short, length field unchanged'}),
    ('fault-garbage', {'type': float, 'default': 0.0, 'help': 'Probability P per datagram of an extra random-byte datagram'}),
    ('fault-unknown-types', {'action': 'store_true',
                             'help': 'Interleave valid Fire/Detonation/Collision/Create Entity PDUs'}),
    ('fault-v6', {'action': 'store_true', 'help': 'Send a share of Entity State PDUs as protocol version 6'}),
    ('fault-other-exercise', {'type': int, 'default': None, 'help': 'Send a share of Entity State PDUs with this exercise ID'}),
    ('fault-loss', {'type': float, 'default': 0.0, 'help': 'Probability P of dropping each datagram'}),
    ('fault-reorder', {'type': float, 'default': 0.0, 'help': 'Probability P of swapping a datagram with the next'}),
    ('fault-duplicate', {'type': float, 'default': 0.0, 'help': 'Probability P of sending a datagram twice'}),
    ('fault-seed', {'type': int, 'default': None, 'help': 'Random seed for the faults, for a repeatable run'}),
)


def _attr(prefix, name):
    return (prefix + name).replace('-', '_')


def add_output_args(parser, prefix=''):
    """Add the output options to an argparse parser, e.g. prefix='dis-' → --dis-dest."""
    for name, kwargs in OUTPUT_OPTIONS:
        parser.add_argument(f'--{prefix}{name}', dest=_attr(prefix, name), **kwargs)


def forward_output_args(args, prefix=''):
    """CLI arguments (unprefixed) that reproduce every non-default output option."""
    out = []
    for name, kwargs in OUTPUT_OPTIONS:
        value = getattr(args, _attr(prefix, name))
        if value == kwargs.get('default') or value is None or value is False:
            continue
        out.append(f'--{name}')
        if value is not True:
            out.append(str(value))
    return out


def stamp(pdu, unix_time):
    """Copy of pdu with its header timestamp set to the DIS relative time of unix_time."""
    out = bytearray(pdu)
    struct.pack_into('>I', out, 4, relative_timestamp(unix_time))
    return bytes(out)


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------

def _ip_checksum(header):
    total = sum(struct.unpack('>10H', header))
    while total > 0xFFFF:
        total = (total & 0xFFFF) + (total >> 16)
    return ~total & 0xFFFF


def _dest_mac(dest_ip):
    addr = ipaddress.ip_address(dest_ip)
    if addr.is_multicast:
        low = int(addr) & 0x7FFFFF
        return bytes([0x01, 0x00, 0x5E, low >> 16, (low >> 8) & 0xFF, low & 0xFF])
    if dest_ip.endswith('.255'):
        return b'\xff' * 6
    return bytes([0x02, 0, 0, 0, 0, 0x02])


class PcapWriter:
    """Append UDP datagrams to a libpcap file as Ethernet/IPv4/UDP frames.

    The MAC addresses are locally administered placeholders (02:..); the IPs,
    ports, TTL and payload are what was actually sent.
    """
    LINKTYPE_ETHERNET = 1
    SRC_MAC = bytes([0x02, 0, 0, 0, 0, 0x01])

    def __init__(self, path, src, dst, ttl):
        self.src, self.dst, self.ttl = src, dst, ttl
        self.dst_mac = _dest_mac(dst[0])
        self.ip_id = 0
        new = not os.path.exists(path) or os.path.getsize(path) == 0
        self.fh = open(path, 'ab')
        if new:
            self.fh.write(struct.pack('<IHHiIII', 0xA1B2C3D4, 2, 4, 0, 0, 65535, self.LINKTYPE_ETHERNET))

    def write(self, payload, unix_time):
        udp = struct.pack('>HHHH', self.src[1], self.dst[1], 8 + len(payload), 0) + payload
        self.ip_id = (self.ip_id + 1) & 0xFFFF
        ip = struct.pack('>BBHHHBBH4s4s', 0x45, 0, 20 + len(udp), self.ip_id, 0x4000, self.ttl, 17, 0,
                         socket.inet_aton(self.src[0]), socket.inet_aton(self.dst[0]))
        ip = ip[:10] + struct.pack('>H', _ip_checksum(ip)) + ip[12:]
        frame = self.dst_mac + self.SRC_MAC + b'\x08\x00' + ip + udp
        sec = int(unix_time)
        self.fh.write(struct.pack('<IIII', sec, int((unix_time - sec) * 1e6), len(frame), len(frame)) + frame)

    def close(self):
        self.fh.close()


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

class DisOutput:
    """Sends PDUs over UDP with optional faults, bundling, recording and multicast."""

    def __init__(self, dest='127.0.0.1', port=DEFAULT_PORT, iface=None, ttl=1, bundle=1,
                 record=None, record_raw=None, faults=None):
        self.dest = (dest, port)
        self.bundle = max(1, bundle)
        self.faults = dict(truncate=0.0, garbage=0.0, unknown_types=False, v6=False,
                           other_exercise=None, loss=0.0, reorder=0.0, duplicate=0.0, seed=None)
        self.faults.update(faults or {})
        self.rng = random.Random(self.faults['seed'])
        self.multicast = ipaddress.ip_address(dest).is_multicast

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_TTL, ttl)
        if self.multicast:
            self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl)
            self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
            if iface:
                self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(iface))
        self.sock.bind((iface or '', 0))

        self.pcap = PcapWriter(record, (self._source_ip(iface), self.sock.getsockname()[1]),
                               self.dest, ttl) if record else None
        self.raw = open(record_raw, 'ab') if record_raw else None
        self.held = None                 # (datagram, n_pdus, n_other, copies) awaiting reorder
        self.filler_index = 0
        self.counts = dict(datagrams=0, pdus=0, malformed=0, other_exercise_delivered=0, bundled=0,
                           truncated=0, garbage=0, unknown_types=0, v6=0, other_exercise=0,
                           lost_datagrams=0, lost_pdus=0, reordered=0, duplicated=0)

    @classmethod
    def from_args(cls, args):
        faults = dict(truncate=args.fault_truncate, garbage=args.fault_garbage,
                      unknown_types=args.fault_unknown_types, v6=args.fault_v6,
                      other_exercise=args.fault_other_exercise, loss=args.fault_loss,
                      reorder=args.fault_reorder, duplicate=args.fault_duplicate, seed=args.fault_seed)
        return cls(dest=args.dest, port=args.port, iface=args.iface, ttl=args.ttl, bundle=args.bundle,
                   record=args.record, record_raw=args.record_raw, faults=faults)

    def _source_ip(self, iface):
        """Local address the kernel would send from (for the pcap headers); sends nothing."""
        if iface:
            return iface
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(self.dest)
            return probe.getsockname()[0]
        except OSError:
            return '0.0.0.0'
        finally:
            probe.close()

    def describe(self):
        kind = 'multicast ' if self.multicast else ''
        active = [k for k, v in self.faults.items() if k != 'seed' and v not in (0.0, False, None)]
        extras = []
        if self.bundle > 1:
            extras.append(f'bundle ≤{self.bundle}')
        if active:
            extras.append('faults: ' + ', '.join(active))
        if self.pcap or self.raw:
            extras.append('recording')
        return f'{kind}{self.dest[0]}:{self.dest[1]}' + (f' ({"; ".join(extras)})' if extras else '')

    # -- sending ------------------------------------------------------------

    def _emit(self, datagram, n_pdus, n_other=0, malformed=False):
        """Put one datagram on the wire and record it."""
        now = time.time()
        self.sock.sendto(datagram, self.dest)
        if self.pcap:
            self.pcap.write(datagram, now)
        if self.raw:
            self.raw.write(datagram)
        c = self.counts
        c['datagrams'] += 1
        c['pdus'] += n_pdus
        c['other_exercise_delivered'] += n_other
        c['malformed'] += int(malformed)

    def _garbage(self):
        """Random bytes that fail at the first header, so they count as exactly one malformed."""
        while True:
            data = bytes(self.rng.getrandbits(8) for _ in range(self.rng.randint(1, 200)))
            if split_pdus(data) == ([], False):
                return data

    def _valid_datagram(self, datagram, n_pdus, n_other):
        f, c = self.faults, self.counts
        if f['loss'] and self.rng.random() < f['loss']:
            c['lost_datagrams'] += 1
            c['lost_pdus'] += n_pdus
            return
        copies = 1
        if f['duplicate'] and self.rng.random() < f['duplicate']:
            copies = 2
            c['duplicated'] += 1
        if self.held is None and f['reorder'] and self.rng.random() < f['reorder']:
            self.held = (datagram, n_pdus, n_other, copies)
            c['reordered'] += 1
            return
        for _ in range(copies):
            self._emit(datagram, n_pdus, n_other)
        self._release_held()
        if f['garbage'] and self.rng.random() < f['garbage']:
            self._emit(self._garbage(), 0, malformed=True)
            c['garbage'] += 1

    def _release_held(self):
        if self.held is not None:
            datagram, n_pdus, n_other, copies = self.held
            self.held = None
            for _ in range(copies):
                self._emit(datagram, n_pdus, n_other)

    def send(self, pdus):
        """Send a batch of PDUs (bytes), applying the configured faults."""
        f, c, rng = self.faults, self.counts, self.rng
        now = time.time()
        ready = []                       # (pdu, is_other_exercise)
        for pdu in pdus:
            pdu = bytearray(stamp(pdu, now))
            is_state = pdu[2] == PDU_ENTITY_STATE
            if is_state and f['v6'] and rng.random() < FAULT_SHARE:
                pdu[0] = 6
                c['v6'] += 1
            other = False
            if is_state and f['other_exercise'] is not None and rng.random() < FAULT_SHARE:
                pdu[1] = f['other_exercise']
                other = True
                c['other_exercise'] += 1
            if is_state and f['truncate'] and rng.random() < f['truncate']:
                self._emit(bytes(pdu[:rng.randint(1, len(pdu) - 1)]), 0, malformed=True)
                c['truncated'] += 1
                continue
            ready.append((bytes(pdu), other))
            if is_state and f['unknown_types'] and rng.random() < FAULT_SHARE:
                pdu_type, family, length = FILLER_PDUS[self.filler_index % len(FILLER_PDUS)]
                self.filler_index += 1
                ready.append((stamp(pack_filler(pdu_type, family, length, exercise=pdu[1]), now), other))
                c['unknown_types'] += 1

        # Bundle in order: up to self.bundle PDUs and MAX_DATAGRAM bytes per datagram.
        group, size = [], 0
        for pdu, other in ready + [(None, False)]:
            if group and (pdu is None or len(group) >= self.bundle or size + len(pdu) > MAX_DATAGRAM):
                if len(group) > 1:
                    c['bundled'] += 1
                self._valid_datagram(b''.join(p for p, _ in group), len(group), sum(o for _, o in group))
                group, size = [], 0
            if pdu is not None:
                group.append((pdu, other))
                size += len(pdu)

    def send_raw(self, datagram):
        """Send one datagram exactly as given — no timestamp, faults or bundling (replay, CR-005)."""
        pdus, ok = split_pdus(datagram)
        self._emit(datagram, len(pdus), malformed=not ok)

    @property
    def pdus_sent(self):
        return self.counts['pdus']

    def summary(self):
        c = self.counts
        lines = [f'{c["datagrams"]} datagrams, {c["pdus"]} PDUs sent'
                 + (f' ({c["bundled"]} bundled datagrams)' if c['bundled'] else '')]
        if any(v not in (0.0, False, None) for k, v in self.faults.items() if k != 'seed'):
            lines.append(
                f'faults: truncated {c["truncated"]}, garbage {c["garbage"]}, unknown-type {c["unknown_types"]}, '
                f'v6 {c["v6"]}, other-exercise {c["other_exercise"]}, lost {c["lost_datagrams"]} datagrams '
                f'({c["lost_pdus"]} PDUs), reordered {c["reordered"]}, duplicated {c["duplicated"]}')
            lines.append(
                f'receiver should count: datagrams={c["datagrams"]} pdus={c["pdus"]} malformed={c["malformed"]}'
                f' — of those pdus, {c["other_exercise_delivered"]} carry another exercise ID'
                f' (counted as other-exercise instead when listening with --exercise)')
        return '\n    '.join(lines)

    def close(self):
        """Flush any held datagram, close socket and recordings; returns the summary."""
        self._release_held()
        self.sock.close()
        if self.pcap:
            self.pcap.close()
        if self.raw:
            self.raw.close()
        return self.summary()
