"""Tests for the pure-Python BRMesh protocol port.

Run with: python -m unittest discover -s tests/python
"""

import importlib.util
import sys
from pathlib import Path
import unittest

_PATH = Path(__file__).parents[2] / "custom_components" / "fastcon" / "protocol.py"
_spec = importlib.util.spec_from_file_location("fastcon_protocol", _PATH)
protocol = importlib.util.module_from_spec(_spec)
sys.modules["fastcon_protocol"] = protocol
_spec.loader.exec_module(protocol)


def decode(packet: bytes, key: bytes | None):
    """Undo whitening/framing and decrypt, returning (header, data)."""
    buf = bytearray(15) + bytearray(packet)
    protocol.whiten(buf)
    frame = buf[15:]
    header = bytes(protocol.reverse_8(b) for b in frame[:6])
    body = bytearray(frame[6:-2])
    crc = frame[-2] | (frame[-1] << 8)
    assert crc == protocol.crc16(protocol.FASTCON_ADDRESS, bytes(body)), "bad CRC"
    for i in range(4):
        body[i] ^= protocol.DEFAULT_ENCRYPT_KEY[i]
    real_key = key or protocol.DEFAULT_ENCRYPT_KEY
    for i in range(len(body) - 4):
        body[4 + i] ^= real_key[i & 3]
    assert body[3] == sum(b for i, b in enumerate(body) if i != 3) & 0xFF, "bad checksum"
    return header, bytes(body)


class ProtocolTest(unittest.TestCase):
    def test_crc_matches_ccitt_false(self):
        self.assertEqual(protocol.crc16(b"", b"123456789"), 0x29B1)

    def test_whitening_is_its_own_inverse(self):
        data = bytearray(range(40))
        protocol.whiten(data)
        self.assertNotEqual(data, bytearray(range(40)))
        protocol.whiten(data)
        self.assertEqual(data, bytearray(range(40)))

    def test_packet_fits_legacy_advertisement(self):
        packet = protocol.CommandBuilder(1).scan()
        # 3 (flags) + 1 (len) + 1 (type) + 2 (company id) + 24 = 31 bytes
        self.assertEqual(len(packet), 24)

    def test_scan_command_round_trip(self):
        header, body = decode(protocol.CommandBuilder(1).scan(), None)
        self.assertEqual(header, bytes((0x71, 0x0F, 0x55, 0xC3, 0xC2, 0xC1)))
        self.assertEqual(body[0], 0x00)  # cmd 0, not forwarded
        self.assertEqual(body[1], 2)  # sequence incremented from 1
        self.assertEqual(body[2], 0xFF)  # no key
        self.assertEqual(body[4:], bytes(12))

    def test_light_command_round_trip(self):
        phone_key = bytes.fromhex("A1A2A3A4")
        cmd = protocol.light_rgb(255, 0, 0, 100)
        packet = protocol.CommandBuilder(10).light(7, phone_key, cmd)
        _, body = decode(packet, phone_key)
        self.assertEqual(body[0], 0x80 | (5 << 4))  # forward, single control
        self.assertEqual(body[2], phone_key[3])
        self.assertEqual(body[4], 2 | (7 << 4))
        self.assertEqual(body[5], 7)
        self.assertEqual(body[6:12], bytes((0x80 | 100, 0, 255, 0, 0, 0)))

    def test_bind_command_round_trip(self):
        phone_key = bytes.fromhex("A1A2A3A4")
        device_key = bytes.fromhex("5E367BC4")
        did = bytes.fromhex("EC0BF10A52F2")
        packet = protocol.CommandBuilder(1).bind(did, 3, phone_key, device_key)
        _, body = decode(packet, device_key)
        self.assertEqual(body[0], 2 << 4)
        self.assertEqual(body[4:], did + bytes((3, 1)) + phone_key)

    def test_sequence_wraps(self):
        builder = protocol.CommandBuilder(255)
        _, body = decode(builder.scan(), None)
        self.assertEqual(body[1], 1)

    def test_parse_discovery_broadcast(self):
        # Sample from src/bletools.cpp
        payload = bytes.fromhex("4E6C7A79EC0BF10A52F2A1A85E367BC4")
        found = protocol.parse_broadcast(payload)
        self.assertIsNotNone(found)
        self.assertEqual(found.did.hex().upper(), "EC0BF10A52F2")
        self.assertEqual(found.name, "52F2")
        self.assertEqual(found.device_type, protocol.LIGHT_RGBW)
        self.assertEqual(found.key.hex().upper(), "5E367BC4")

    def test_parse_ignores_other_broadcasts(self):
        self.assertIsNone(protocol.parse_broadcast(bytes(16)))
        self.assertIsNone(protocol.parse_broadcast(b"\x4e"))

    def test_rgb_handles_black(self):
        self.assertEqual(protocol.light_rgb(0, 0, 0, 10), bytes((0x8A, 0, 0, 0, 0, 0)))


if __name__ == "__main__":
    unittest.main()
