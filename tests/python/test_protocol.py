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
    def test_crc_is_x25(self):
        self.assertEqual(protocol.crc16(b"", b"123456789"), 0x906E)

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

    def test_all_lights_command_targets_address_zero(self):
        phone_key = bytes.fromhex("A1A2A3A4")
        packet = protocol.CommandBuilder(10).light(
            protocol.ALL_LIGHTS_ADDRESS, phone_key, protocol.light_off()
        )
        _, body = decode(packet, phone_key)
        self.assertEqual(body[4], 2 | (2 << 4))
        self.assertEqual(body[5], 0)
        self.assertEqual(body[6], 0)

    def test_describe_discovery_names_device_type(self):
        key = protocol.DEFAULT_ENCRYPT_KEY
        header = bytes(b ^ key[i] for i, b in enumerate((0x10, 0x01, 0x00, 0x00)))
        payload = header + bytes.fromhex("EC0BF10A52F2") + (43733).to_bytes(2, "little") + bytes(4)
        info = protocol.describe_broadcast(payload, bytes.fromhex("A1A2A3A4"))
        self.assertEqual(info["device_type"], 43733)
        self.assertEqual(info["device_type_name"], "Panel 8")
        self.assertEqual(info["did"], "EC0BF10A52F2")
        self.assertIn("Panel 8", protocol.describe_action(info))
        self.assertEqual(protocol.device_type_name(0x1234), "unknown type 0x1234")

    def test_checksum_uses_the_key_of_each_frame_type(self):
        phone_key = bytes.fromhex("A1A2A3A4")
        # Discovery broadcasts are plain (real light), scans use the default key
        discovery = protocol.describe_broadcast(
            bytes.fromhex("4e6c7625ec0bf10a7edea1a85e367bc4"), phone_key
        )
        self.assertEqual(discovery["key"], "not encrypted")
        self.assertTrue(discovery["checksum_ok"])
        scan = protocol.describe_broadcast(protocol.CommandBuilder(5).scan(), phone_key)
        self.assertEqual(scan["kind"], "scan")
        self.assertTrue(scan["checksum_ok"])
        bind = protocol.CommandBuilder(5).bind(
            bytes.fromhex("EC0BF10A52F2"), 3, phone_key, bytes.fromhex("5E367BC4")
        )
        self.assertIsNone(protocol.describe_broadcast(bind, phone_key)["checksum_ok"])

    def test_brightness_command_has_no_on_bit_and_minimum_five(self):
        self.assertEqual(protocol.light_brightness(64), bytes((64,)))
        self.assertEqual(protocol.light_brightness(0), bytes((5,)))
        self.assertEqual(protocol.light_brightness(200), bytes((127,)))
        self.assertEqual(protocol.describe_command(protocol.light_brightness(64)), "brightness 50%")

    def test_light_by_type_matches_the_app(self):
        # The BRMesh app's "all on" / "all off" decrypt to 43 2a a8 00 80 / 00
        # (captured from a private mesh, so checked decrypted, not as raw frames)
        key = bytes.fromhex("A1A2A3A4")
        on = protocol.CommandBuilder(174).light_by_type(43050, key, bytes((0x80,)))
        off = protocol.CommandBuilder(176).light_by_type(43050, key, protocol.light_off())
        self.assertTrue(protocol.describe_broadcast(on, key)["data"].startswith("432aa80080"))
        self.assertTrue(protocol.describe_broadcast(off, key)["data"].startswith("432aa80000"))
        info = protocol.describe_broadcast(off, key)
        self.assertTrue(info["checksum_ok"])
        self.assertEqual(info["target_device_type"], 43050)
        self.assertEqual(protocol.describe_action(info), "all Light RGBCW lights: light off")

    def test_group_commands_match_the_app(self):
        # Decrypted app captures: add lights 2 and 4 to group "Flur" (id 1),
        # then switch the group off
        key = bytes.fromhex("A1A2A3A4")
        builder = protocol.CommandBuilder(1)
        add = protocol.describe_broadcast(builder.assign_group(4, key, 1), key)
        self.assertTrue(add["data"].startswith("210401"))
        self.assertFalse(add["forward"])
        self.assertEqual(protocol.describe_action(add), "put the light at mesh address 4 into group 1")
        remove = protocol.describe_broadcast(builder.assign_group(4, key, 0), key)
        self.assertTrue(remove["data"].startswith("210400"))
        self.assertEqual(
            protocol.describe_action(remove), "remove the light at mesh address 4 from its group"
        )
        off = protocol.describe_broadcast(
            builder.light_by_type(43050, key, protocol.light_off(), group=1), key
        )
        self.assertTrue(off["data"].startswith("432aa80100"))
        self.assertEqual(protocol.describe_action(off), "group 1 Light RGBCW lights: light off")

    def test_effect_matches_the_app(self):
        # Decrypted app captures: "Romantic" slow / fast on mesh address 16
        key = bytes.fromhex("A1A2A3A4")
        builder = protocol.CommandBuilder(1)
        slow = protocol.describe_broadcast(builder.effect(16, key, 1, bytes((0x43, 0x02))), key)
        fast = protocol.describe_broadcast(builder.effect(16, key, 100, bytes((0x43, 0x02))), key)
        self.assertTrue(slow["data"].startswith("4810014302"))
        self.assertTrue(fast["data"].startswith("4810644302"))
        self.assertEqual(
            protocol.describe_action(fast),
            "effect fade magenta, red at speed 100 on mesh address 16",
        )

    def test_scene_encodes_colours_like_the_app(self):
        # Decrypted captures: "Romantic" = fade magenta, red; "Full color fade"
        # = fade red, magenta, blue, cyan, green, yellow (the app's default list)
        key = bytes.fromhex("A1A2A3A4")
        c = protocol.EFFECT_COLORS
        builder = protocol.CommandBuilder(1)
        romantic = builder.scene(16, key, 1, protocol.EFFECT_MODE_FADE, [c["magenta"], c["red"]])
        self.assertTrue(protocol.describe_broadcast(romantic, key)["data"].startswith("4810014302"))
        full = builder.scene(
            16, key, 1, protocol.EFFECT_MODE_FADE,
            [c["red"], c["magenta"], c["blue"], c["cyan"], c["green"], c["yellow"]],
        )
        self.assertTrue(protocol.describe_broadcast(full, key)["data"].startswith("881001420301050406"))
        # "Fresh" (app Mod3: cyan, blue, green) at speed 42 = the third capture
        fresh = builder.scene(16, key, 42, protocol.EFFECT_MODE_FADE, [c["cyan"], c["blue"], c["green"]])
        self.assertTrue(protocol.describe_broadcast(fresh, key)["data"].startswith("58102a450104"))
        single = builder.scene(16, key, 50, protocol.EFFECT_MODE_JUMP, [c["red"]])
        self.assertTrue(protocol.describe_broadcast(single, key)["data"].startswith("4810320200"))

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

    def _heartbeat(self, mesh_address, phone_key, subtype=4):
        data = bytes((0x20 | subtype, mesh_address & 0xFF, 9)) + bytes(9)
        return bytes(
            protocol.package_body(3, mesh_address >> 8, 42, phone_key[3], False, data, phone_key)
        )

    def test_parse_heartbeat(self):
        key = bytes.fromhex("A1A2A3A4")
        beat = protocol.parse_heartbeat(self._heartbeat(7, key), key)
        self.assertEqual(beat, protocol.Heartbeat(mesh_address=7, group_address=9))

    def test_parse_heartbeat_high_address_bits(self):
        key = bytes.fromhex("A1A2A3A4")
        beat = protocol.parse_heartbeat(self._heartbeat(0x105, key), key)
        self.assertEqual(beat.mesh_address, 0x105)

    def test_parse_heartbeat_wrong_key_fails_checksum(self):
        payload = self._heartbeat(7, bytes.fromhex("A1A2A3A4"))
        self.assertIsNone(protocol.parse_heartbeat(payload, bytes.fromhex("31323334")))

    def test_parse_heartbeat_ignores_other_types(self):
        key = bytes.fromhex("A1A2A3A4")
        self.assertIsNone(protocol.parse_heartbeat(self._heartbeat(7, key, subtype=0xB), key))
        discovery = bytes.fromhex("4E6C7A79EC0BF10A52F2A1A85E367BC4")
        self.assertIsNone(protocol.parse_heartbeat(discovery, key))

    def test_describe_heartbeat(self):
        key = bytes.fromhex("A1A2A3A4")
        info = protocol.describe_broadcast(self._heartbeat(7, key), key)
        self.assertEqual(info["kind"], "heartbeat")
        self.assertEqual(info["sequence"], 42)
        self.assertTrue(info["checksum_ok"])

    def test_describe_time_sync_from_brmesh_app(self):
        # Captured from the BRMesh app (key "3077"), diagnostics 2026-10-11
        raw = bytes.fromhex("6db64368931ddd5d9405223809f603cc5089f6655ff821b0")
        info = protocol.describe_broadcast(raw, bytes.fromhex("33303737"))
        self.assertTrue(info["checksum_ok"])
        self.assertEqual(info["control_type"], 9)
        self.assertEqual(info["mesh_address"], 0)
        self.assertEqual(
            protocol.describe_action(info),
            "time sync: 2026-10-11 22:29:49 (weekday 0)",
        )

    def test_describe_new_protocol_frame(self):
        payload = bytes.fromhex("a55a") + bytes(20)
        info = protocol.describe_broadcast(payload, bytes.fromhex("A1A2A3A4"))
        self.assertEqual(info["kind"], "new protocol")
        self.assertIsNone(protocol.parse_heartbeat(payload, bytes.fromhex("A1A2A3A4")))

    def test_describe_discovery(self):
        payload = bytes.fromhex("4E6C7A79EC0BF10A52F2A1A85E367BC4")
        info = protocol.describe_broadcast(payload, bytes.fromhex("A1A2A3A4"))
        self.assertEqual(info["kind"], "discovery")

    # Relayed commands captured from real lights (diagnostics, 2026-10-06)
    RELAYED = {
        "6db64368931dddaf07391bad876f9a5ed20755f7cb6b38db": (170, 7, "00"),
        "6db64368931ddda907381bae876f9a5ed20755f7cb6bcb98": (172, 4, "00"),
        "6db64368931ddda807f64bae746f9a5ead7855f7cb6ba879": (173, 4, "f3000000" "7f7f"),
    }

    def test_describe_relayed_commands_from_real_lights(self):
        key = bytes.fromhex("A1A2A3A4")
        for raw, (seq, mesh, command) in self.RELAYED.items():
            info = protocol.describe_broadcast(bytes.fromhex(raw), key)
            self.assertEqual(info["frame"], "rf")
            self.assertEqual(info["kind"], "control")
            self.assertTrue(info["checksum_ok"])
            self.assertEqual(info["sequence"], seq)
            self.assertEqual(info["mesh_address"], mesh)
            self.assertEqual(info["command"], command)

    def test_our_command_unwraps_to_same_body(self):
        key = bytes.fromhex("A1A2A3A4")
        packet = protocol.CommandBuilder(169).light(7, key, protocol.light_off())
        info = protocol.describe_broadcast(packet, key)
        self.assertEqual((info["kind"], info["sequence"], info["mesh_address"]), ("control", 170, 7))
        self.assertEqual(packet.hex(), "6db64368931dddaf07391bad876f9a5ed20755f7cb6b38db")

    def test_discovery_reports_mesh_address(self):
        # Same light (533B) before and after the BRMesh app changed its address
        before = protocol.parse_broadcast(bytes.fromhex("4e6c7fceec0bf10a533ba1a85e367bc4"))
        after = protocol.parse_broadcast(bytes.fromhex("4e6d72d4ec0bf10a533ba1a85e367bc4"))
        self.assertEqual((before.mesh_address, after.mesh_address), (4, 9))

    def test_heartbeat_with_app_key_from_real_light(self):
        # Captured heartbeat, encrypted with the BRMesh app's key
        raw = bytes.fromhex("6eb67248403a373d30063d3634333739")
        beat = protocol.parse_heartbeat(raw, bytes.fromhex("34333739"))
        self.assertEqual(beat, protocol.Heartbeat(mesh_address=9, group_address=0))
        self.assertIsNone(protocol.parse_heartbeat(raw, bytes.fromhex("A1A2A3A4")))

    def test_describe_command(self):
        cases = {
            "00": "light off",
            "80": "light on",
            "f2": "light on, brightness 90%",
            "ff5555550000": "color RGB(85, 85, 85), brightness 100%",
            "a20000007f7f": "white, brightness 27%",
            "ff00ff000000": "color RGB(255, 0, 0), brightness 100%",
        }
        for command, expected in cases.items():
            self.assertEqual(protocol.describe_command(bytes.fromhex(command)), expected)

    def test_describe_action_from_real_broadcasts(self):
        key = bytes.fromhex("A1A2A3A4")
        def action(raw, **extra):
            info = protocol.describe_broadcast(bytes.fromhex(raw), key)
            return protocol.describe_action({**info, **extra})
        self.assertEqual(
            action("6db64368931ddd7607254bae783acf0bd20755f7cb6b9979"),
            "color RGB(85, 85, 85), brightness 100%",
        )
        self.assertEqual(
            action("4e6c7625ec0bf10a7edea1a85e367bc4"),
            "discovery: 7EDE (Light RGBW) announces itself (reports mesh address 13)",
        )
        self.assertEqual(
            action("6e587fb4d5a6a3a0a597a9aba1a2a3a4", header_mesh=4),
            "heartbeat from mesh address 4",
        )


if __name__ == "__main__":
    unittest.main()
