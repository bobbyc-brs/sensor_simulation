"""Unit tests for cgf/replay.py — pcap reading and replay timing (CR-005 item 4).

Run from the project root:  python -m unittest discover -s tests -t .
"""
import os
import socket
import struct
import tempfile
import time
import unittest

from cgf.replay import PcapError, read_udp, replay
from gateways.dis_output import DisOutput, PcapWriter
from gateways.dis_pdu import pack_remove_entity
from tests.test_dis_output import Collector


def ipv4_udp(payload, dst_port=3800, frag=0, proto=17):
    udp = struct.pack('>HHHH', 40000, dst_port, 8 + len(payload), 0) + payload
    return struct.pack('>BBHHHBBH4s4s', 0x45, 0, 20 + len(udp), 1, frag, 1, proto, 0,
                       socket.inet_aton('10.0.0.1'), socket.inet_aton('10.0.0.2')) + udp


def write_pcap(path, frames, link, order='<', nano=False):
    """frames: [(capture time s, frame bytes)]."""
    magic = 0xA1B23C4D if nano else 0xA1B2C3D4
    with open(path, 'wb') as fh:
        fh.write(struct.pack(order + 'IHHiIII', magic, 2, 4, 0, 0, 65535, link))
        for t, frame in frames:
            sec = int(t)
            frac = int(round((t - sec) * (1e9 if nano else 1e6)))
            fh.write(struct.pack(order + 'IIII', sec, frac, len(frame), len(frame)) + frame)


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class Sink:
    def __init__(self):
        self.sent = []

    def send_raw(self, datagram):
        self.sent.append(datagram)


class ReadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, 'x.pcap')
        self.payloads = [pack_remove_entity((1, 42, i)) for i in range(1, 4)]

    def tearDown(self):
        self.tmp.cleanup()

    def test_sensors_own_recording(self):
        datagrams, counts = read_udp('recordings/ottawa-mixed.pcap')
        self.assertEqual(len(datagrams), 554)
        with open('recordings/ottawa-mixed.bin', 'rb') as fh:
            self.assertEqual(b''.join(p for _, _, p in datagrams), fh.read())
        self.assertEqual(counts['skipped_other'] + counts['skipped_fragments'], 0)

    def test_link_types_byte_orders_and_resolutions(self):
        eth = lambda ip: b'\x02' * 6 + b'\x02' * 6 + b'\x08\x00' + ip
        vlan = lambda ip: b'\x02' * 12 + b'\x81\x00\x00\x05' + b'\x08\x00' + ip
        sll = lambda ip: bytes(14) + b'\x08\x00' + ip
        sll2 = lambda ip: b'\x08\x00' + bytes(18) + ip
        cases = [(1, eth, '<', False), (1, vlan, '>', False), (101, lambda ip: ip, '<', True),
                 (228, lambda ip: ip, '>', True), (113, sll, '<', False), (276, sll2, '<', False)]
        for link, wrap, order, nano in cases:
            with self.subTest(link=link, order=order, nano=nano):
                frames = [(1000.0 + 0.25 * i, wrap(ipv4_udp(p))) for i, p in enumerate(self.payloads)]
                write_pcap(self.path, frames, link, order, nano)
                datagrams, _ = read_udp(self.path)
                self.assertEqual([p for _, _, p in datagrams], self.payloads)
                self.assertAlmostEqual(datagrams[2][0] - datagrams[0][0], 0.5, places=6)

    def test_skips_fragments_non_udp_and_other_ports(self):
        frames = [(1.0, ipv4_udp(self.payloads[0])),
                  (1.1, ipv4_udp(self.payloads[1], frag=0x2000)),        # more-fragments set
                  (1.2, ipv4_udp(self.payloads[1], proto=6)),            # TCP
                  (1.3, ipv4_udp(self.payloads[2], dst_port=5004))]
        write_pcap(self.path, frames, 101)
        datagrams, counts = read_udp(self.path, only_port=3800)
        self.assertEqual([p for _, _, p in datagrams], [self.payloads[0]])
        self.assertEqual((counts['skipped_fragments'], counts['skipped_other'], counts['skipped_port']), (1, 1, 1))

    def test_rejects_pcapng_and_non_pcap(self):
        with open(self.path, 'wb') as fh:
            fh.write(b'\x0a\x0d\x0d\x0a' + bytes(40))
        with self.assertRaisesRegex(PcapError, 'editcap'):
            read_udp(self.path)
        with self.assertRaises(PcapError):
            read_udp('recordings/ottawa-mixed.bin')


class ReplayTimingTest(unittest.TestCase):
    def test_offsets_scaled_by_speed(self):
        clock = FakeClock()
        sink = Sink()
        datagrams = [(50.0, 3800, b'a'), (50.5, 3800, b'b'), (52.0, 3800, b'c')]
        times = []
        original = sink.send_raw
        sink.send_raw = lambda d: (times.append(clock.now - 100.0), original(d))
        wall = replay(datagrams, sink, speed=2.0, clock=clock.clock, sleep=clock.sleep)
        self.assertEqual(sink.sent, [b'a', b'b', b'c'])
        self.assertEqual(times, [0.0, 0.25, 1.0])
        self.assertAlmostEqual(wall, 1.0)

    def test_real_time_within_2_percent(self):
        tmp = tempfile.TemporaryDirectory()
        path = os.path.join(tmp.name, 'x.pcap')
        writer = PcapWriter(path, ('127.0.0.1', 40000), ('127.0.0.1', 3800), 1)
        for i in range(40):                                   # 40 datagrams over 1.95 s
            writer.write(pack_remove_entity((1, 42, i + 1)), 5000.0 + 0.05 * i)
        writer.close()
        datagrams, _ = read_udp(path)
        rx = Collector()
        out = DisOutput(port=rx.port)
        wall = replay(datagrams, out, speed=1.5)
        out.close()
        got = rx.finish()
        tmp.cleanup()
        self.assertEqual(len(got), 40)
        self.assertEqual(got, [p for _, _, p in datagrams])
        expected = 1.95 / 1.5
        self.assertLess(abs(wall - expected) / expected, 0.02, (wall, expected))


if __name__ == '__main__':
    unittest.main()
