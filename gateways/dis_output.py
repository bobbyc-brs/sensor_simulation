"""DIS output: the one place PDUs leave Sensors (gateway and CGF both use it).

OUTPUT_OPTIONS defines the output flags once; the gateway and CGF runner add
them bare (--dest), and simulation_manager.py adds them prefixed (--dis-dest)
and forwards them, so the three can never drift apart.
"""
import socket
import struct
import time

from gateways.dis_pdu import relative_timestamp

OUTPUT_OPTIONS = (
    ('dest', {'default': '127.0.0.1',
              'help': 'DIS destination address; a broadcast address such as 192.168.1.255 works (default: 127.0.0.1)'}),
    ('port', {'type': int, 'default': 3000, 'help': 'DIS UDP port (default: 3000)'}),
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


class DisOutput:
    """Sends PDUs over UDP, one datagram per PDU.

    Every PDU's timestamp is set at the moment it is sent (CR-003), so a receiver
    can measure its own PDU-to-display latency against the send time.
    """

    def __init__(self, dest='127.0.0.1', port=3000):
        self.dest = (dest, port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        # Harmless for unicast; required when dest is a broadcast address.
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.pdus_sent = 0

    @classmethod
    def from_args(cls, args):
        return cls(dest=args.dest, port=args.port)

    def describe(self):
        return f'{self.dest[0]}:{self.dest[1]}'

    def send(self, pdus):
        """Send a batch of PDUs (bytes)."""
        for pdu in pdus:
            self.sock.sendto(stamp(pdu, time.time()), self.dest)
            self.pdus_sent += 1

    def close(self):
        """Close the socket; returns a one-line summary."""
        self.sock.close()
        return f'{self.pdus_sent} PDUs sent'
