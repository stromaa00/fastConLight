"""BRMesh / Fastcon BLE protocol.

Pure Python port of the firmware protocol (src/bletools.cpp, src/blelight.cpp).
It has no Home Assistant imports so it can be unit tested on its own.
"""

from __future__ import annotations

from dataclasses import dataclass
import random

MANUFACTURER_ID = 0xFFF0
DEFAULT_ENCRYPT_KEY = bytes((0x5E, 0x36, 0x7B, 0xC4))
FASTCON_ADDRESS = bytes((0xC1, 0xC2, 0xC3))
WHITENING_SEED = 0x25

CMD_SCAN = 0
CMD_DISCOVERY_RESPONSE = 2
CMD_SINGLE_CONTROL = 5

# Device type codes (see SPECIFICATION.md section 5)
LIGHT_RGBCW = 43050
LIGHT_RGB = 43168
LIGHT_CCT = 43051
LIGHT_RGBW = 43169
LIGHT_PWR = 43049
LIGHT_W_CW = 43745
LIGHT_BURDEN_W = 43759
LIGHT_BURDEN_CW = 43754
LIGHT_COMPOSE = 43709

LIGHT_TYPE_NAMES = {
    LIGHT_RGBCW: "Light RGBCW",
    LIGHT_RGB: "Light RGB",
    LIGHT_CCT: "Light CCT",
    LIGHT_RGBW: "Light RGBW",
    LIGHT_PWR: "Light PWR",
    LIGHT_W_CW: "Light W/CW",
    LIGHT_BURDEN_W: "Light Burden W",
    LIGHT_BURDEN_CW: "Light Burden CW",
    LIGHT_COMPOSE: "Light Compose",
}


def is_light(device_type: int) -> bool:
    """Return True if the device type is a light."""
    return device_type in LIGHT_TYPE_NAMES


def reverse_8(value: int) -> int:
    """Reverse the bit order of a byte."""
    result = 0
    for i in range(8):
        result |= ((value >> i) & 1) << (7 - i)
    return result


def crc16(addr: bytes, data: bytes) -> int:
    """CRC-16/X-25 (poly 0x1021 reflected, init 0xFFFF, xorout 0xFFFF) over address + data.

    This is what real lights put on the frames they relay. The ESP32 firmware
    used CRC-16/CCITT-FALSE instead; lights accepted that too, but matching
    their own frames is safer.
    """
    crc = 0xFFFF
    for byte in bytes(addr) + bytes(data):
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8408 if crc & 1 else crc >> 1
    return crc ^ 0xFFFF


def whiten(data: bytearray, seed: int = WHITENING_SEED) -> None:
    """Apply the 7-bit LFSR whitening in place (it is its own inverse)."""
    f0 = 1
    f4 = (seed >> 5) & 1
    f8 = (seed >> 4) & 1
    fc = (seed >> 3) & 1
    f10 = (seed >> 2) & 1
    f14 = (seed >> 1) & 1
    f18 = seed & 1

    for i, c in enumerate(data):
        var_c = fc
        var_14 = f14
        var_18 = f18
        var_10 = f10
        var_8 = var_14 ^ f8
        var_4 = var_10 ^ f4
        var_ = var_18 ^ var_c
        var_0 = var_ ^ f0

        data[i] = (
            ((c & 0x80) ^ ((var_8 ^ var_18) << 7))
            + ((c & 0x40) ^ (var_0 << 6))
            + ((c & 0x20) ^ (var_4 << 5))
            + ((c & 0x10) ^ (var_8 << 4))
            + ((c & 0x08) ^ (var_ << 3))
            + ((c & 0x04) ^ (var_10 << 2))
            + ((c & 0x02) ^ (var_14 << 1))
            + ((c & 0x01) ^ (var_18 << 0))
        ) & 0xFF

        f8 = var_4
        fc = var_8
        f10 = var_8 ^ var_c
        f14 = var_0 ^ var_10
        f18 = var_4 ^ var_14
        f0 = var_8 ^ var_18
        f4 = var_0


def get_rf_payload(addr: bytes, data: bytes) -> bytearray:
    """Wrap data in the RF frame: header, reversed address, data, CRC."""
    data_offset = 0x12
    inverse_offset = 0x0F
    result_size = data_offset + len(addr) + len(data)
    buf = bytearray(result_size + 2)

    buf[0x0F] = 0x71
    buf[0x10] = 0x0F
    buf[0x11] = 0x55

    for i, byte in enumerate(addr):
        buf[data_offset + len(addr) - i - 1] = byte

    buf[data_offset + len(addr) : result_size] = data

    for i in range(inverse_offset, inverse_offset + len(addr) + 3):
        buf[i] = reverse_8(buf[i])

    crc = crc16(addr, data)
    buf[result_size] = crc & 0xFF
    buf[result_size + 1] = (crc >> 8) & 0xFF
    return buf


def package_body(
    cmd_type: int,
    i2: int,
    sequence: int,
    safe_key: int,
    forward: bool,
    data: bytes,
    key: bytes | None,
) -> bytearray:
    """Build and encrypt the Fastcon body (control byte, seq, safe key, checksum, data)."""
    body = bytearray(len(data) + 4)
    body[0] = (i2 & 0b1111) | ((cmd_type & 0b111) << 4) | (int(forward) << 7)
    body[1] = sequence & 0xFF
    body[2] = safe_key & 0xFF
    body[4:] = data
    body[3] = sum(b for i, b in enumerate(body) if i != 3) & 0xFF

    for i in range(4):
        body[i] ^= DEFAULT_ENCRYPT_KEY[i & 3]

    real_key = key if key is not None else DEFAULT_ENCRYPT_KEY
    for i in range(len(data)):
        body[4 + i] ^= real_key[i & 3]
    return body


class CommandBuilder:
    """Builds advertisement payloads, tracking the send sequence number."""

    def __init__(self, sequence: int | None = None) -> None:
        # Start at a random sequence so lights don't ignore our first commands
        # as repeats after a restart.
        self._sequence = sequence if sequence is not None else random.randint(1, 254)

    def _next_sequence(self) -> int:
        self._sequence += 1
        if self._sequence >= 256:
            self._sequence = 1
        return self._sequence

    @property
    def last_sequence(self) -> int:
        """Sequence number of the most recently built command."""
        return self._sequence

    def generate(
        self,
        cmd_type: int,
        data: bytes,
        key: bytes | None,
        forward: bool,
        i2: int = 0,
    ) -> bytes:
        """Return the manufacturer data payload (after the 0xFFF0 company ID)."""
        safe_key = key[3] if key is not None else 0xFF
        body = package_body(
            cmd_type, i2, self._next_sequence(), safe_key, forward, data, key
        )
        payload = get_rf_payload(FASTCON_ADDRESS, bytes(body))
        whiten(payload)
        return bytes(payload[0x0F:])

    def scan(self, forward: bool = False) -> bytes:
        """Ask devices in discovery mode to announce themselves.

        With `forward`, lights relay the request through the mesh.
        """
        return self.generate(CMD_SCAN, bytes(12), None, forward=forward)

    def bind(
        self, did: bytes, mesh_address: int, phone_key: bytes, device_key: bytes
    ) -> bytes:
        """Discovery response: give a device its mesh address and the phone key."""
        data = bytes(did[:6]) + bytes((mesh_address & 0xFF, 0x01)) + bytes(phone_key)
        return self.generate(CMD_DISCOVERY_RESPONSE, data, device_key, forward=False)

    def light(self, mesh_address: int, phone_key: bytes, command: bytes) -> bytes:
        """Single control command for one light."""
        data = bytearray(12)
        data[0] = (2 | ((len(command) + 1) << 4)) & 0xFF
        data[1] = mesh_address & 0xFF
        data[2 : 2 + len(command)] = command
        return self.generate(
            CMD_SINGLE_CONTROL, bytes(data), phone_key, forward=True,
            i2=mesh_address // 256,
        )


def light_off() -> bytes:
    """Turn a light off."""
    return bytes((0,))


def light_on(level: int) -> bytes:
    """Turn a light on at brightness level 0-127."""
    return bytes((0x80 | (level & 0x7F),))


def light_rgb(r: int, g: int, b: int, level: int) -> bytes:
    """Set RGB colour (normalised to full scale) at brightness level 0-127."""
    total = r + g + b
    norm = 255.0 / total if total else 0.0
    return bytes(
        (
            0x80 | (level & 0x7F),
            min(255, int(b * norm)),
            min(255, int(r * norm)),
            min(255, int(g * norm)),
            0,
            0,
        )
    )


def light_white(level: int) -> bytes:
    """Switch to the white channel at brightness level 0-127."""
    return bytes((0x80 | (level & 0x7F), 0, 0, 0, 127, 127))


@dataclass(frozen=True)
class DiscoveredDevice:
    """Device announced in a discovery broadcast."""

    did: bytes
    device_type: int
    key: bytes
    # Mesh address the device currently has (0 if unbound). Header byte 2 of
    # every broadcast carries the sender's address.
    mesh_address: int = 0

    @property
    def name(self) -> str:
        """Short name the BRMesh app shows (last 2 bytes of the DID)."""
        return self.did[4:6].hex().upper()


def parse_broadcast(payload: bytes) -> DiscoveredDevice | None:
    """Parse BRMesh manufacturer data (the bytes after the 0xFFF0 company ID).

    Layout of a discovery broadcast (16 bytes):
      header(4, encrypted) | DID(6, last 2 = name) | type(2, little endian) | key(4)

    Decrypted header byte 2 is the device's current mesh address.
    """
    if len(payload) < 16:
        return None
    header0 = payload[0] ^ DEFAULT_ENCRYPT_KEY[0]
    if (header0 >> 4) & 7 != 1:
        return None
    return DiscoveredDevice(
        did=bytes(payload[4:10]),
        device_type=payload[10] | (payload[11] << 8),
        key=bytes(payload[12:16]),
        mesh_address=payload[2] ^ DEFAULT_ENCRYPT_KEY[2],
    )


@dataclass(frozen=True)
class Heartbeat:
    """Periodic broadcast from a bound device."""

    mesh_address: int
    group_address: int


def parse_heartbeat(payload: bytes, phone_key: bytes) -> Heartbeat | None:
    """Parse a heartbeat broadcast (the bytes after the 0xFFF0 company ID).

    Same body layout as our commands: header(4) encrypted with the default key,
    then data encrypted with the phone key. Header type is 3 and the low nibble
    of byte 0 holds the high bits of the mesh address; data byte 0 has subtype
    4, byte 1 the mesh address and byte 2 the group address. The checksum
    (header byte 3) confirms the phone key is right.
    """
    payload = unwrap_rf_frame(payload) or payload
    if len(payload) < 16:
        return None
    header = bytes(b ^ DEFAULT_ENCRYPT_KEY[i] for i, b in enumerate(payload[:4]))
    if (header[0] >> 4) & 7 != 3:
        return None
    content = bytes(b ^ phone_key[i & 3] for i, b in enumerate(payload[4:]))
    if (sum(header[:3]) + sum(content)) & 0xFF != header[3]:
        return None
    if content[0] & 0x0F != 4:
        return None
    return Heartbeat(
        mesh_address=content[1] | ((header[0] & 0x0F) << 8),
        group_address=content[2],
    )


def unwrap_rf_frame(payload: bytes) -> bytes | None:
    """Return the Fastcon body of a whitened RF frame, or None if it isn't one.

    Lights relay commands in the same 24-byte form we send them: header
    71 0F 55, the Fastcon address, a 16-byte body and a CRC, all whitened.
    """
    if len(payload) != 24:
        return None
    buf = bytearray(0x0F) + bytearray(payload)
    whiten(buf)
    frame = buf[0x0F:]
    if bytes(reverse_8(b) for b in frame[:3]) != b"\x71\x0f\x55":
        return None
    return bytes(frame[6:22])


def describe_broadcast(payload: bytes, phone_key: bytes) -> dict:
    """Decode the generic body fields of any BRMesh broadcast, for logging."""
    body = unwrap_rf_frame(payload)
    frame = "rf" if body is not None else "plain"
    payload = body or payload
    if len(payload) < 4:
        return {"kind": "too short", "frame": frame}
    header = bytes(b ^ DEFAULT_ENCRYPT_KEY[i] for i, b in enumerate(payload[:4]))
    content = bytes(b ^ phone_key[i & 3] for i, b in enumerate(payload[4:]))
    header_type = (header[0] >> 4) & 7
    info = {
        "kind": {1: "discovery", 2: "bind", 3: "status", 5: "control"}.get(
            header_type, "unknown"
        ),
        "frame": frame,
        "header_type": header_type,
        "forward": bool(header[0] & 0x80),
        "address_high": header[0] & 0x0F,
        "sequence": header[1],
        "safe_key": header[2],
        "checksum_ok": (sum(header[:3]) + sum(content)) & 0xFF == header[3],
        "data": content.hex(),
    }
    if header_type == 1 and len(payload) >= 16:
        info["discovered_light"] = payload[8:10].hex().upper()
        info["reported_address"] = header[2]
    if header_type == 3 and content:
        info["subtype"] = content[0] & 0x0F
        if info["subtype"] == 4:
            info["kind"] = "heartbeat"
    if header_type == 5 and info["checksum_ok"] and len(content) >= 2:
        # Single control: data[0] = 2 | (len + 1) << 4, data[1] = mesh address
        length = (content[0] >> 4) - 1
        info["mesh_address"] = content[1] | (info["address_high"] << 8)
        info["command"] = content[2 : 2 + max(length, 0)].hex()
        info["control_type"] = content[0] & 0x0F
    return info


def _percent(level: int) -> int:
    return round((level & 0x7F) * 100 / 127)


def describe_command(command: bytes) -> str:
    """Human-readable meaning of a single control command's bytes."""
    if not command:
        return "empty command"
    first = command[0]
    on = bool(first & 0x80)
    if len(command) == 1:
        if first == 0:
            return "light off"
        if on:
            level = first & 0x7F
            return f"light on, brightness {_percent(level)}%" if level else "light on"
        return f"brightness {_percent(first)}%"
    if len(command) >= 6:
        blue, red, green, warm, cold = command[1:6]
        brightness = f"brightness {_percent(first)}%"
        if not on and not first:
            return "light off"
        if (red or green or blue) and not (warm or cold):
            return f"color RGB({red}, {green}, {blue}), {brightness}"
        if (warm or cold) and not (red or green or blue):
            return f"white, {brightness}"
        if not (red or green or blue or warm or cold):
            return f"light on, {brightness}"
        return f"color RGB({red}, {green}, {blue}) + white ({warm}, {cold}), {brightness}"
    return f"command {command.hex()}"


def describe_action(info: dict) -> str:
    """Best guess at what a decoded broadcast means, for logs and diagnostics."""
    kind = info.get("kind")
    if kind == "discovery":
        return (
            f"discovery: {info.get('discovered_light', '?')} announces itself "
            f"(reports mesh address {info.get('reported_address', '?')})"
        )
    if kind == "heartbeat":
        if info.get("checksum_ok"):
            return f"heartbeat from mesh address {info.get('header_mesh', '?')}"
        return "heartbeat (other key, can't decode)"
    if kind == "status":
        if not info.get("checksum_ok"):
            return "status (other key, can't decode)"
        return f"status, subtype {info.get('subtype')}"
    if kind == "bind":
        return "bind (discovery response)"
    if kind == "control":
        if not info.get("checksum_ok"):
            return "control command (other key, can't decode)"
        if info.get("control_type") == 2:
            return describe_command(bytes.fromhex(info.get("command", "")))
        return f"control type {info.get('control_type')}: {info.get('data')}"
    if info.get("header_type") == 0:
        return "scan request"
    return f"unknown broadcast (type {info.get('header_type')})"
