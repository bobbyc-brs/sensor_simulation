"""Replay a pcap's UDP payloads at their recorded timing (CR-005 item 4).

    python -m cgf.replay recordings/ottawa-mixed.pcap [--port 3800] [--speed 1.0] [--loop]

Sends every UDP payload in the capture, byte for byte, at its capture time
offset ÷ --speed: no re-stamping, no faults, no scenario engine. Works on
Sensors' own recordings and on a real simulator's capture. Standard library only.

Reads classic libpcap — either byte order, microsecond or nanosecond
timestamps — with link types Ethernet (VLAN tags skipped), raw IPv4, and Linux
cooked capture v1/v2. IPv4 fragments are skipped and counted. pcapng is not
read: convert it first with `editcap -F pcap in.pcapng out.pcap`.
"""
import argparse
import signal
import struct
import sys
import time

from gateways.dis_output import DEFAULT_PORT, DisOutput

LINKTYPE_ETHERNET = 1
LINKTYPE_RAW = 101
LINKTYPE_IPV4 = 228
LINKTYPE_LINUX_SLL = 113
LINKTYPE_LINUX_SLL2 = 276
ETHERTYPE_IPV4 = 0x0800
ETHERTYPE_VLAN = (0x8100, 0x88A8, 0x9100)

MAGIC = {
    b'\xd4\xc3\xb2\xa1': ('<', 1e-6), b'\xa1\xb2\xc3\xd4': ('>', 1e-6),
    b'\x4d\x3c\xb2\xa1': ('<', 1e-9), b'\xa1\xb2\x3c\x4d': ('>', 1e-9),
}
PCAPNG_MAGIC = b'\x0a\x0d\x0d\x0a'


class PcapError(ValueError):
    """A file this reader cannot replay, with the reason."""


def _ipv4_payload(frame, link):
    """The IPv4 packet inside one captured frame, or None for anything else."""
    if link == LINKTYPE_ETHERNET:
        offset, ethertype = 14, struct.unpack_from('>H', frame, 12)[0] if len(frame) >= 14 else 0
        while ethertype in ETHERTYPE_VLAN and len(frame) >= offset + 4:
            ethertype = struct.unpack_from('>H', frame, offset + 2)[0]
            offset += 4
        return frame[offset:] if ethertype == ETHERTYPE_IPV4 else None
    if link in (LINKTYPE_RAW, LINKTYPE_IPV4):
        return frame if frame and frame[0] >> 4 == 4 else None
    if link == LINKTYPE_LINUX_SLL:
        return frame[16:] if len(frame) >= 16 and struct.unpack_from('>H', frame, 14)[0] == ETHERTYPE_IPV4 else None
    if link == LINKTYPE_LINUX_SLL2:
        return frame[20:] if len(frame) >= 20 and struct.unpack_from('>H', frame, 0)[0] == ETHERTYPE_IPV4 else None
    raise PcapError(f'link type {link} is not supported (Ethernet, raw IPv4, Linux SLL/SLL2 are)')


def read_udp(path, only_port=None):
    """Return ([(capture time s, UDP dst port, payload)], counts) from a classic pcap file."""
    with open(path, 'rb') as fh:
        data = fh.read()
    if data[:4] == PCAPNG_MAGIC:
        raise PcapError(f'{path} is pcapng; convert it: editcap -F pcap {path} out.pcap')
    if data[:4] not in MAGIC or len(data) < 24:
        raise PcapError(f'{path} is not a libpcap file')
    order, tick = MAGIC[data[:4]]
    link = struct.unpack_from(order + 'I', data, 20)[0] & 0x0FFFFFFF
    counts = {'frames': 0, 'udp': 0, 'skipped_fragments': 0, 'skipped_other': 0, 'skipped_port': 0}
    out, offset = [], 24
    while offset + 16 <= len(data):
        sec, frac, incl, _orig = struct.unpack_from(order + 'IIII', data, offset)
        frame = data[offset + 16: offset + 16 + incl]
        offset += 16 + incl
        counts['frames'] += 1
        ip = _ipv4_payload(frame, link)
        if ip is None or len(ip) < 20 or ip[9] != 17:
            counts['skipped_other'] += 1
            continue
        flags_frag = struct.unpack_from('>H', ip, 6)[0]
        if flags_frag & 0x3FFF:                  # more-fragments set, or a fragment offset
            counts['skipped_fragments'] += 1
            continue
        udp = ip[(ip[0] & 0x0F) * 4:]
        if len(udp) < 8:
            counts['skipped_other'] += 1
            continue
        dst_port, length = struct.unpack_from('>HH', udp, 2)
        if only_port is not None and dst_port != only_port:
            counts['skipped_port'] += 1
            continue
        out.append((sec + frac * tick, dst_port, udp[8:length]))
        counts['udp'] += 1
    return out, counts


def replay(datagrams, output, speed=1.0, clock=time.monotonic, sleep=time.sleep):
    """Send each payload at its capture offset ÷ speed; returns wall seconds taken."""
    if not datagrams:
        return 0.0
    t0 = datagrams[0][0]
    start = clock()
    for capture_time, _port, payload in datagrams:
        delay = start + (capture_time - t0) / speed - clock()
        if delay > 0:
            sleep(delay)
        output.send_raw(payload)
    return clock() - start


def main():
    parser = argparse.ArgumentParser(description="Replay a pcap's UDP payloads at their recorded timing.")
    parser.add_argument('pcap', help='Classic libpcap file (Sensors recordings/*.pcap, or a real capture)')
    parser.add_argument('--dest', default='127.0.0.1', help='Destination address, unicast/broadcast/multicast (default: 127.0.0.1)')
    parser.add_argument('--port', type=int, default=DEFAULT_PORT, help=f'Destination UDP port (default: {DEFAULT_PORT})')
    parser.add_argument('--iface', default=None, help='Local interface address for multicast output')
    parser.add_argument('--ttl', type=int, default=1, help='IP TTL (default: 1 — LAN only)')
    parser.add_argument('--speed', type=float, default=1.0, help='Playback speed factor (default: 1.0)')
    parser.add_argument('--loop', action='store_true', help='Repeat until Ctrl-C, with --gap between passes')
    parser.add_argument('--gap', type=float, default=1.0, help='Seconds between passes with --loop (default: 1.0)')
    parser.add_argument('--only-port', type=int, default=None,
                        help='Replay only datagrams captured to this UDP port (default: all UDP)')
    args = parser.parse_args()
    if args.speed <= 0:
        parser.error('--speed must be positive')

    try:
        datagrams, counts = read_udp(args.pcap, args.only_port)
    except (OSError, PcapError) as exc:
        sys.exit(f'[REPLAY] {exc}')
    if not datagrams:
        sys.exit(f'[REPLAY] no UDP datagrams to replay in {args.pcap} ({counts})')
    span = datagrams[-1][0] - datagrams[0][0]
    skipped = {k: v for k, v in counts.items() if k.startswith('skipped') and v}
    output = DisOutput(dest=args.dest, port=args.port, iface=args.iface, ttl=args.ttl)
    print(f'[REPLAY] {args.pcap}: {len(datagrams)} UDP datagrams over {span:.2f} s'
          + (f' (skipped {skipped})' if skipped else '')
          + f' → {output.describe()} at ×{args.speed:g}' + (', looping' if args.loop else ''))

    passes = []

    def finish(sig=None, frame=None):
        print(f'[REPLAY] {len(passes)} pass(es); {output.close()}')
        sys.exit(0)

    signal.signal(signal.SIGINT, finish)
    signal.signal(signal.SIGTERM, finish)
    while True:
        wall = replay(datagrams, output, args.speed)
        passes.append(wall)
        expected = span / args.speed
        drift = (wall - expected) / expected * 100 if expected else 0.0
        print(f'[REPLAY] pass {len(passes)}: {len(datagrams)} datagrams in {wall:.2f} s '
              f'(capture span ÷ speed = {expected:.2f} s, {drift:+.2f} %)')
        if not args.loop:
            break
        time.sleep(args.gap)
    finish()


if __name__ == '__main__':
    main()
