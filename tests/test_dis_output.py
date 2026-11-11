"""Unit tests for gateways/dis_output.py — timestamps (CR-003); faults, bundling,
recording, multicast and option forwarding (CR-004).

Run from the project root:  python -m unittest discover -s tests -t .
"""
import argparse
import os
import socket
import struct
import tempfile
import threading
import time
import unittest

from gateways.dis_output import MAX_DATAGRAM, DisOutput, add_output_args, forward_output_args
from gateways.dis_pdu import (
    ENTITY_TYPES,
    pack_entity_state,
    pack_remove_entity,
    relative_timestamp,
    split_pdus,
    timestamp_seconds,
)


def entity_states(n):
    return [pack_entity_state((1, 42, i % 50 + 1), 3, ENTITY_TYPES['car'], f'C{i}',
                              45.4, -75.7, 70.0, 90.0, ground_speed_ms=10.0) for i in range(n)]


class Collector:
    """Receive on a background thread while the test sends, as a live listener would.

    Sending hundreds of datagrams before reading any overflows the kernel's
    receive buffer (capped by rmem_max) and silently drops some.
    """

    def __init__(self):
        self.sock = receiver()
        self.port = self.sock.getsockname()[1]
        self.datagrams = []
        self.sock.settimeout(0.05)
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        idle = 0
        while not (self.stop.is_set() and idle >= 4):
            try:
                self.datagrams.append(self.sock.recv(65535))
                idle = 0
            except socket.timeout:
                idle += 1

    def finish(self):
        self.stop.set()
        self.thread.join()
        self.sock.close()
        return self.datagrams


def receiver_counts(datagrams, exercise=None):
    """Count as moving-map's Receiver does: split by header length, 1 malformed per bad datagram."""
    c = dict(datagrams=0, pdus=0, malformed=0, other_exercise=0)
    for d in datagrams:
        c['datagrams'] += 1
        pdus, ok = split_pdus(d)
        if not ok:
            c['malformed'] += 1
        for p in pdus:
            if exercise is not None and p[1] != exercise:
                c['other_exercise'] += 1
            else:
                c['pdus'] += 1
    return c


def receiver():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('127.0.0.1', 0))
    sock.settimeout(2.0)
    return sock


class TimestampTest(unittest.TestCase):
    def test_encoding(self):
        ts = relative_timestamp(7200.0 + 1800.0)         # half past the hour
        self.assertEqual(ts & 1, 0)                       # relative
        self.assertEqual(ts >> 1, 2 ** 30)
        self.assertAlmostEqual(timestamp_seconds(ts), 1800.0, places=4)
        self.assertEqual(relative_timestamp(3600.0), 0)   # wraps on the hour

    def test_send_time_stamped_on_the_wire(self):
        rx = receiver()
        out = DisOutput(dest='127.0.0.1', port=rx.getsockname()[1])
        before = time.time()
        out.send([pack_remove_entity((1, 42, 1))])
        after = time.time()
        data = rx.recv(2048)
        out.close()
        rx.close()
        sent_s = timestamp_seconds(struct.unpack_from('>I', data, 4)[0])
        lo, hi = before % 3600 - 1e-3, after % 3600 + 1e-3
        if hi < lo:                                      # the hour rolled over mid-test
            self.assertTrue(sent_s >= lo or sent_s <= hi)
        else:
            self.assertTrue(lo <= sent_s <= hi, (lo, sent_s, hi))



class FaultTest(unittest.TestCase):
    def run_faults(self, n=600, bundle=1, **faults):
        rx = Collector()
        out = DisOutput(port=rx.port, bundle=bundle, faults={'seed': 7, **faults})
        for i in range(0, n, 10):
            out.send(entity_states(10))
            if i % 100 == 0:
                out.send([pack_remove_entity((1, 42, 1))])
            time.sleep(0.002)
        out.close()
        return out.counts, rx.finish()

    def test_all_faults_receiver_counts_match_summary(self):
        counts, got = self.run_faults(truncate=0.05, garbage=0.03, unknown_types=True, v6=True,
                                      other_exercise=9, loss=0.05, reorder=0.05, duplicate=0.05, bundle=3)
        for name in ('truncated', 'garbage', 'unknown_types', 'v6', 'other_exercise',
                     'lost_datagrams', 'reordered', 'duplicated', 'bundled'):
            self.assertGreater(counts[name], 0, name)
        seen = receiver_counts(got)
        self.assertEqual(seen['datagrams'], counts['datagrams'])
        self.assertEqual(seen['pdus'], counts['pdus'])
        self.assertEqual(seen['malformed'], counts['malformed'])
        self.assertEqual(counts['malformed'], counts['truncated'] + counts['garbage'])
        filtered = receiver_counts(got, exercise=1)
        self.assertEqual(filtered['other_exercise'], counts['other_exercise_delivered'])

    def test_truncated_keeps_length_field(self):
        _, got = self.run_faults(n=200, truncate=0.2)
        short = [d for d in got if len(d) < 144 and len(d) != 28]
        self.assertTrue(short)
        for d in short:
            if len(d) >= 10:
                self.assertEqual(struct.unpack_from('>H', d, 8)[0], 144)

    def test_unknown_types_are_valid_pdus(self):
        counts, got = self.run_faults(n=300, unknown_types=True)
        types = [p[2] for d in got for p in split_pdus(d)[0]]
        self.assertTrue({2, 3, 4, 11} <= set(types), set(types))
        self.assertEqual(receiver_counts(got)['malformed'], 0)

    def test_bundles_respect_k_and_mtu(self):
        counts, got = self.run_faults(n=300, bundle=20)
        self.assertTrue(all(len(d) <= MAX_DATAGRAM for d in got))
        self.assertEqual(max(len(split_pdus(d)[0]) for d in got), MAX_DATAGRAM // 144)
        counts, got = self.run_faults(n=300, bundle=4)
        self.assertEqual(max(len(split_pdus(d)[0]) for d in got), 4)

    def test_seed_repeats(self):
        a, _ = self.run_faults(n=200, truncate=0.1, loss=0.1, seed=3)
        b, _ = self.run_faults(n=200, truncate=0.1, loss=0.1, seed=3)
        self.assertEqual(a, b)


class RecordingTest(unittest.TestCase):
    def test_pcap_and_raw(self):
        rx = Collector()
        port = rx.port
        with tempfile.TemporaryDirectory() as tmp:
            pcap, raw = os.path.join(tmp, 'x.pcap'), os.path.join(tmp, 'x.bin')
            for _ in range(2):                                      # second run appends
                out = DisOutput(port=port, record=pcap, record_raw=raw, ttl=1)
                out.send(entity_states(5) + [pack_remove_entity((1, 42, 1))])
                out.close()
            sent = rx.finish()
            with open(raw, 'rb') as fh:
                raw_bytes = fh.read()
            with open(pcap, 'rb') as fh:
                pcap_bytes = fh.read()

        self.assertEqual(raw_bytes, b''.join(sent))
        pdus, ok = split_pdus(raw_bytes)
        self.assertTrue(ok)
        self.assertEqual(len(pdus), 12)

        magic, major, minor, _, _, snaplen, link = struct.unpack_from('<IHHiIII', pcap_bytes, 0)
        self.assertEqual((magic, major, minor, link), (0xA1B2C3D4, 2, 4, 1))
        offset, payloads = 24, []
        while offset < len(pcap_bytes):
            _, _, incl, orig = struct.unpack_from('<IIII', pcap_bytes, offset)
            frame = pcap_bytes[offset + 16: offset + 16 + incl]
            offset += 16 + incl
            self.assertEqual(incl, orig)
            self.assertEqual(frame[12:14], b'\x08\x00')              # IPv4
            ip = frame[14:34]
            self.assertEqual(ip[9], 17)                              # UDP
            self.assertEqual(ip[8], 1)                               # TTL
            total = sum(struct.unpack('>10H', ip))
            while total > 0xFFFF:
                total = (total & 0xFFFF) + (total >> 16)
            self.assertEqual(total, 0xFFFF)                          # header checksum valid
            self.assertEqual(struct.unpack_from('>H', frame, 36)[0], port)
            payloads.append(frame[42:])
        self.assertEqual(payloads, sent)


class SocketOptionTest(unittest.TestCase):
    def test_multicast_ttl_1_by_default(self):
        out = DisOutput(dest='239.1.2.3', port=3999)
        self.assertTrue(out.multicast)
        self.assertEqual(out.sock.getsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL), 1)
        self.assertEqual(out.sock.getsockopt(socket.IPPROTO_IP, socket.IP_TTL), 1)
        out.close()

    def test_multicast_iface(self):
        out = DisOutput(dest='239.1.2.3', port=3999, iface='127.0.0.1', ttl=2)
        raw = out.sock.getsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, 4)
        self.assertEqual(socket.inet_ntoa(raw), '127.0.0.1')
        self.assertEqual(out.sock.getsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL), 2)
        out.close()

    def test_unicast_ttl_1(self):
        out = DisOutput()
        self.assertFalse(out.multicast)
        self.assertEqual(out.sock.getsockopt(socket.IPPROTO_IP, socket.IP_TTL), 1)
        out.close()


class ForwardingTest(unittest.TestCase):
    def test_manager_flags_reach_the_runner_unchanged(self):
        manager = argparse.ArgumentParser()
        add_output_args(manager, prefix='dis-')
        m = manager.parse_args(['--dis-dest', '239.1.2.3', '--dis-iface', '10.0.0.5', '--dis-bundle', '4',
                                '--dis-fault-truncate', '0.05', '--dis-fault-unknown-types',
                                '--dis-fault-other-exercise', '9', '--dis-record', 'x.pcap'])
        forwarded = forward_output_args(m, prefix='dis-')
        runner = argparse.ArgumentParser()
        add_output_args(runner)
        r = runner.parse_args(forwarded)
        self.assertEqual((r.dest, r.iface, r.bundle, r.fault_truncate, r.fault_unknown_types,
                          r.fault_other_exercise, r.record, r.port, r.ttl),
                         ('239.1.2.3', '10.0.0.5', 4, 0.05, True, 9, 'x.pcap', 3000, 1))
        self.assertEqual(forward_output_args(manager.parse_args([]), prefix='dis-'), [])


if __name__ == '__main__':
    unittest.main()
