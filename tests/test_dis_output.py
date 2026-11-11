"""Unit tests for gateways/dis_output.py — send path, timestamps (CR-003).

Run from the project root:  python -m unittest discover -s tests -t .
"""
import socket
import struct
import time
import unittest

from gateways.dis_output import DisOutput
from gateways.dis_pdu import pack_remove_entity, relative_timestamp, timestamp_seconds


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


if __name__ == '__main__':
    unittest.main()
