"""Test and debug BRMesh lights through an ESP32 running brmesh-transmitter.yaml.

Talks to the ESP32 directly over the ESPHome native API, without Home
Assistant: sends scans, binds and light commands through its send_brmesh
action and decodes the BRMesh broadcasts its Bluetooth proxy hears.

    pip install aioesphomeapi
    python tools/brmesh_debug.py --host 192.168.1.50 --key <api key> info
    python tools/brmesh_debug.py --host ... --key ... scan
    python tools/brmesh_debug.py --host ... --key ... shell

Host, key and phone key can also come from BRMESH_HOST, BRMESH_KEY and
BRMESH_PHONE_KEY.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
from datetime import datetime
import importlib.util
import json
import os
from collections.abc import Callable
from pathlib import Path
import shlex
import sys
import time

from aioesphomeapi import APIClient, LogLevel, UserService

_PROTOCOL = Path(__file__).resolve().parents[1] / "custom_components" / "fastcon" / "protocol.py"
_spec = importlib.util.spec_from_file_location("fastcon_protocol", _PROTOCOL)
protocol = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = protocol  # dataclasses look the module up by name
_spec.loader.exec_module(protocol)

MANUFACTURER_DATA = 0xFF
DEVICE_ADDRESS_PREFIX = "11:22:"


def _mac(address: int) -> str:
    raw = f"{address:012X}"
    return ":".join(raw[i : i + 2] for i in range(0, 12, 2))


def _manufacturer_data(adv: bytes, company_id: int) -> bytes | None:
    """Payload after the company ID in a raw advertisement, if present."""
    i = 0
    while i < len(adv):
        length = adv[i]
        if length == 0 or i + 1 + length > len(adv):
            return None
        if adv[i + 1] == MANUFACTURER_DATA and length >= 3:
            if adv[i + 2] | (adv[i + 3] << 8) == company_id:
                return bytes(adv[i + 4 : i + 1 + length])
        i += 1 + length
    return None


AD_TYPES = {
    0x01: "flags",
    0x02: "uuid16 (part)",
    0x03: "uuid16",
    0x08: "short name",
    0x09: "name",
    0x0A: "tx power",
    0x16: "service data",
    0xFF: "manufacturer",
}


def _ad_structures(adv: bytes) -> list[str]:
    """Readable list of the AD structures in a raw advertisement."""
    parts = []
    i = 0
    while i < len(adv):
        length = adv[i]
        if length == 0 or i + 1 + length > len(adv):
            parts.append(f"trailing {adv[i:].hex()}")
            break
        kind, data = adv[i + 1], adv[i + 2 : i + 1 + length]
        name = AD_TYPES.get(kind, f"type 0x{kind:02X}")
        if kind in (0x08, 0x09):
            parts.append(f"{name} '{data.decode(errors='replace')}'")
        elif kind == 0xFF and len(data) >= 2:
            parts.append(f"{name} 0x{data[0] | (data[1] << 8):04X}: {data[2:].hex(' ')}")
        else:
            parts.append(f"{name}: {data.hex(' ')}")
        i += 1 + length
    return parts


def _xor_frame(body: bytes, phone_key: bytes) -> tuple[bytes, bytes, bool]:
    """Header decrypted with the default key, data with the phone key, checksum ok."""
    header = bytes(b ^ protocol.DEFAULT_ENCRYPT_KEY[i] for i, b in enumerate(body[:4]))
    data = bytes(b ^ phone_key[i & 3] for i, b in enumerate(body[4:]))
    checksum_ok = len(header) == 4 and (sum(header[:3]) + sum(data)) & 0xFF == header[3]
    return header, data, checksum_ok


def _decode_new_protocol(payload: bytes, phone_key: bytes) -> str:
    """Newer devices' a5 5a frames: layout unknown, so show every plausible reading.

    The BRMesh app builds them natively (bl_get_ble_payload). Shown: the bytes
    as sent, decrypted like an old-protocol body, and the same after removing
    the whitening the old RF frames use.
    """
    body = payload[2:]
    buf = bytearray(0x0F) + bytearray(body)
    protocol.whiten(buf)
    dewhitened = bytes(buf[0x0F:])
    lines = [f"           = new protocol frame ({len(body)} bytes after a5 5a, layout unknown)"]
    for label, candidate in (("as sent   ", body), ("dewhitened", dewhitened)):
        header, data, ok = _xor_frame(candidate, phone_key)
        lines.append(
            f"           {label} raw {candidate.hex(' ')}\n"
            f"                      header {header.hex(' ')}  data {data.hex(' ')}"
            f"  checksum {'OK' if ok else '-'}"
        )
    return "\n".join(lines)


# Phone keys of other meshes found so far, to decode their frames that have
# no zero padding (e.g. effects, which use all 12 data bytes)
_known_keys: list[bytes] = []


def _guess_phone_key(payload: bytes) -> bytes | None:
    """The phone key of a frame from another mesh.

    Data bytes 8-11 are usually zero, so there the encrypted bytes are the key
    itself; otherwise keys found in earlier frames are tried. Accepted only if
    header byte 2 (last key byte) and the checksum agree.
    """
    body = protocol.unwrap_rf_frame(payload) or payload
    if len(body) < 16:
        return None
    for candidate in [bytes(body[12:16]), *_known_keys]:
        header, _, ok = _xor_frame(body, candidate)
        if ok and header[2] == candidate[3]:
            if candidate not in _known_keys:
                _known_keys.append(candidate)
            return candidate
    return None


def _decode_brmesh(payload: bytes, phone_key: bytes) -> str:
    """All fields of a BRMesh frame, decrypted with the phone key."""
    if payload[:2] == protocol.NEW_PROTOCOL_MAGIC:
        return _decode_new_protocol(payload, phone_key)
    info = protocol.describe_broadcast(payload, phone_key)
    if info.get("key") == "phone key" and info.get("checksum_ok") is False:
        if (guess := _guess_phone_key(payload)) is not None and guess != phone_key:
            return (
                f"           ! other mesh: phone key is probably {guess.hex().upper()} "
                f"(from zero padding or an earlier frame, checksum ok)\n"
                + _decode_brmesh(payload, guess)
            )
    beat = protocol.parse_heartbeat(payload, phone_key)
    mesh = beat.mesh_address if beat else info.get("mesh_address")
    body = protocol.unwrap_rf_frame(payload) or payload
    header = bytes(b ^ protocol.DEFAULT_ENCRYPT_KEY[i] for i, b in enumerate(body[:4]))
    lines = [
        f"           = {protocol.describe_action({**info, 'header_mesh': mesh})}",
        f"           header {header.hex(' ')}  (type {info.get('header_type')} {info.get('kind')}, "
        f"forward={info.get('forward')}, seq={info.get('sequence')}, byte2={info.get('safe_key')}, "
        f"data {info.get('key')}, checksum "
        + {True: "ok", False: "wrong" + (" (other phone key?)" if info.get("key") == "phone key" else ""),
           None: "not checkable"}[info.get("checksum_ok")] + ")",
        f"           data   {bytes.fromhex(info['data']).hex(' ') if 'data' in info else '-'}",
    ]
    if beat:
        lines.append(f"           heartbeat: mesh address {beat.mesh_address}, group {beat.group_address}")
    if info.get("kind") == "control" and info.get("checksum_ok") and info.get("control_type") == 3:
        # By device type in a group, as the app switches all (group 0) and groups
        device_type = info["target_device_type"]
        group = info.get("group", 0)
        lines.append(
            f"           control type 3: {protocol.device_type_name(device_type)} "
            f"(0x{device_type:04X}) in group {group}{' (all)' if not group else ''}, "
            f"command {info.get('command')}"
        )
    elif info.get("kind") == "control" and info.get("checksum_ok") and "mesh_address" in info:
        target = info["mesh_address"]
        meaning = {0: " (all lights)", 253: " (temporary group)", 254: " (music group)", 255: " (gateway)"}
        group = " (room/scene group)" if 240 <= target <= 243 else ""
        lines.append(
            f"           control: to mesh address {target}{meaning.get(target, group)}, "
            f"control type {info.get('control_type')}, command {info.get('command')}"
        )
    if "device_type" in info:
        lines.append(
            f"           device: {info['device_type_name']} (type {info['device_type']} = "
            f"0x{info['device_type']:04X}), DID {info['did']}, key {info['device_key']}, "
            f"identity {info['did'][-4:]}-{info['did']}-{info['device_type']:04X}-{info['device_key']}"
        )
    return "\n".join(lines)


def _now() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


# Discovered lights are kept here between sessions (they include each light's key)
LIGHTS_FILE = Path(os.environ.get("BRMESH_LIGHTS_FILE") or Path.home() / ".brmesh_debug_lights.json")


def load_lights() -> dict[str, protocol.DiscoveredDevice]:
    """Lights discovered in earlier sessions, by DID."""
    try:
        data = json.loads(LIGHTS_FILE.read_text(encoding="utf-8"))
        return {
            d["did"]: protocol.DiscoveredDevice(
                bytes.fromhex(d["did"]), int(d["type"]), bytes.fromhex(d["key"]), int(d["address"])
            )
            for d in data
        }
    except FileNotFoundError:
        return {}
    except (ValueError, KeyError, TypeError) as err:
        print(f"Ignoring {LIGHTS_FILE}: {err}")
        return {}


def save_lights(lights: dict[str, protocol.DiscoveredDevice]) -> None:
    data = [
        {"did": did, "type": f.device_type, "key": f.key.hex().upper(), "address": f.mesh_address}
        for did, f in lights.items()
    ]
    LIGHTS_FILE.write_text(json.dumps(data, indent=1), encoding="utf-8")


class Debugger:
    """One connection to the ESP32 and the state of a debugging session."""

    def __init__(self, args: argparse.Namespace, emit: Callable[[str, str], None] | None = None) -> None:
        """`emit(kind, text)` gets every event; kinds: send, recv, found, beat, esp, info, error."""
        self.emit = emit or (lambda kind, text: print(text))
        self.args = args
        self.phone_key = bytes.fromhex(args.phone_key)
        self.duration_ms: int = args.duration
        self.builder = protocol.CommandBuilder()
        self.client = APIClient(args.host, args.port, None, noise_psk=args.key)
        self.action: UserService | None = None
        self.interval_action: UserService | None = None
        # Packet interval set through set_brmesh_interval; None = firmware setting
        self.interval_ms: int | None = None
        self.show_all = False
        # Show every advertisement (any content) from addresses starting with this
        self.watch: str | None = None
        self._watch_last: dict[tuple[str, bytes], float] = {}
        self.verbose = False
        self.sniffing = False
        # Lights from discovery, including those saved in earlier sessions
        self.discovered: dict[str, protocol.DiscoveredDevice] = load_lights()
        # DIDs that announced themselves in this session
        self.seen: set[str] = set()
        # Mesh address -> (group address, rssi, time) of the last heartbeat
        self.heartbeats: dict[int, tuple[int, int, str]] = {}
        # DID -> address a bind was sent for; adopted when a heartbeat comes from it
        self.pending_binds: dict[str, int] = {}
        self._own: set[bytes] = set()
        self._unsub: list = []

    # Connection

    async def connect(self) -> None:
        await self.client.connect(login=True)
        info, _, services = await self.client.device_info_and_list_entities()
        self.info = info
        self.services = services
        name = self.args.action
        self.action = next(
            (s for s in services if s.name == name or s.name.endswith(name)), None
        )
        self.interval_action = next(
            (s for s in services if s.name.endswith("set_brmesh_interval")), None
        )
        self.emit("info", f"Connected to {info.name} ({info.model}, ESPHome {info.esphome_version})")
        if self.action is None:
            self.emit("error", f"No '{name}' action; found: {', '.join(s.name for s in services) or 'none'}")

    async def close(self) -> None:
        for unsub in self._unsub:
            unsub()
        await self.client.disconnect()

    # Sending

    async def send(self, payload: bytes, what: str) -> None:
        if self.action is None:
            raise RuntimeError("the ESP32 has no send_brmesh action")
        self._own.add(payload)
        self.emit("send", f"{_now()} SEND {what}  seq={self.builder.last_sequence} raw={payload.hex()}")
        await self.client.execute_service(
            self.action, {"payload": payload.hex(), "duration_ms": self.duration_ms}
        )
        # The ESP32 advertises asynchronously; wait so commands don't overlap.
        await asyncio.sleep(self.duration_ms / 1000)

    async def set_interval(self, interval_ms: int) -> None:
        """Time between packets on the ESP32, from its next broadcast on."""
        if self.interval_action is None:
            raise RuntimeError(
                "the ESP32 has no set_brmesh_interval action; add it from brmesh-transmitter.yaml"
            )
        await self.client.execute_service(self.interval_action, {"interval_ms": interval_ms})
        self.interval_ms = interval_ms
        self.emit("info", f"Packet interval {interval_ms} ms.")

    async def scan(self, relay: bool = False) -> None:
        await self.send(self.builder.scan(forward=relay), "scan request")

    async def bind(self, did: str, key: str, address: int) -> None:
        payload = self.builder.bind(
            bytes.fromhex(did), address, self.phone_key, bytes.fromhex(key)
        )
        await self.send(payload, f"bind {did[-4:].upper()} to mesh address {address}")
        self.pending_binds[did.upper()] = address

    async def light_by_type(self, device_type: int, command: bytes, group: int = 0) -> None:
        payload = self.builder.light_by_type(device_type, self.phone_key, command, group)
        target = "all" if not group else f"group {group}"
        await self.send(
            payload,
            f"{target} {protocol.device_type_name(device_type)} lights: "
            f"{protocol.describe_command(command)}",
        )

    async def effect(self, address: int, speed: int, code: bytes) -> None:
        payload = self.builder.effect(address, self.phone_key, speed, code)
        await self.send(payload, f"effect {code.hex(' ')} at speed {speed} on mesh address {address}")

    async def assign_group(self, address: int, group: int) -> None:
        payload = self.builder.assign_group(address, self.phone_key, group)
        await self.send(payload, f"put mesh address {address} into group {group}")

    async def light(self, address: int, command: bytes) -> None:
        payload = self.builder.light(address, self.phone_key, command)
        target = "all lights" if address == protocol.ALL_LIGHTS_ADDRESS else f"address {address}"
        await self.send(payload, f"{target}: {protocol.describe_command(command)}")

    # Receiving

    def start_logs(self) -> None:
        level = LogLevel.LOG_LEVEL_VERBOSE if self.verbose else LogLevel.LOG_LEVEL_DEBUG

        def on_log(msg) -> None:
            text = msg.message.decode(errors="replace").strip()
            self.emit("esp", f"{_now()} ESP  {text}")

        self._unsub.append(self.client.subscribe_logs(on_log, log_level=level))

    def start_sniffing(self) -> None:
        """Decode BRMesh broadcasts heard by the ESP32's Bluetooth proxy.

        ESPHome passes advertisements to one API client only, so Home
        Assistant stops receiving them from this ESP32 until it reconnects.
        """
        if self.sniffing:
            return
        self.sniffing = True

        def on_advertisements(msg) -> None:
            for adv in msg.advertisements:
                if self.watch and (
                    # "ANY": every BRMesh frame from any sender (e.g. the phone app)
                    _manufacturer_data(adv.data, protocol.MANUFACTURER_ID) is not None
                    if self.watch == "ANY"
                    else _mac(adv.address).startswith(self.watch)
                ):
                    self._on_watch(_mac(adv.address), adv.rssi, bytes(adv.data))
                payload = _manufacturer_data(adv.data, protocol.MANUFACTURER_ID)
                if payload is not None:
                    self._on_brmesh(_mac(adv.address), adv.rssi, payload)

        self._unsub.append(self.client.subscribe_bluetooth_le_raw_advertisements(on_advertisements))

    def _on_watch(self, address: str, rssi: int, adv: bytes) -> None:
        """Everything a watched address sends; repeats within 2 s are skipped."""
        now = time.monotonic()
        key = (address, adv)
        if now - self._watch_last.get(key, -10) < 2:
            self._watch_last[key] = now
            return
        self._watch_last[key] = now
        if len(self._watch_last) > 500:
            self._watch_last = {k: t for k, t in self._watch_last.items() if now - t < 2}
        text = f"{_now()} WATCH {address} rssi={rssi}  adv={adv.hex(' ')}\n           " + (
            "\n           ".join(_ad_structures(adv))
        )
        if (payload := _manufacturer_data(adv, protocol.MANUFACTURER_ID)) is not None:
            text += "\n" + _decode_brmesh(payload, self.phone_key)
        self.emit("watch", text)

    def _on_brmesh(self, address: str, rssi: int, payload: bytes) -> None:
        own = payload in self._own
        found = (
            protocol.parse_broadcast(payload) if address.startswith(DEVICE_ADDRESS_PREFIX) else None
        )
        if found is not None:
            did = found.did.hex().upper()
            new = did not in self.seen
            self.seen.add(did)
            if self.discovered.get(did) != found:
                self.discovered[did] = found
                save_lights(self.discovered)
            if new or self.show_all:
                kind = protocol.device_type_name(found.device_type)
                self.emit(
                    "found",
                    f"{_now()} FOUND {found.name}  did={did} {kind} key={found.key.hex().upper()} "
                    f"address={found.mesh_address} rssi={rssi}\n"
                    f"         identity {found.name}-{did}-{found.device_type:04X}-{found.key.hex().upper()}"
                )
            return
        if (beat := protocol.parse_heartbeat(payload, self.phone_key)) is not None:
            self.heartbeats[beat.mesh_address] = (beat.group_address, rssi, _now()[:8])
            self._confirm_binds(beat.mesh_address)
            if self.show_all:
                self.emit(
                    "beat",
                    f"{_now()} BEAT address={beat.mesh_address} group={beat.group_address} "
                    f"from={address} rssi={rssi} raw={payload.hex()}"
                )
            return
        if own and not self.show_all:
            return
        info = protocol.describe_broadcast(payload, self.phone_key)
        if not self.show_all and info.get("kind") in ("heartbeat", "status"):
            return
        echo = " (our packet)" if own else ""
        self.emit(
            "recv",
            f"{_now()} RECV {protocol.describe_action(info)}{echo}  from={address} "
            f"rssi={rssi} raw={payload.hex()}"
        )

    def _confirm_binds(self, mesh_address: int) -> None:
        """Adopt the address of lights whose bind to it a heartbeat now confirms.

        Heartbeats carry no DID, so every light with a bind sent to this
        address counts as confirmed.
        """
        for did, address in list(self.pending_binds.items()):
            if address != mesh_address:
                continue
            del self.pending_binds[did]
            if (found := self.discovered.get(did)) is not None:
                self.discovered[did] = dataclasses.replace(found, mesh_address=address)
                save_lights(self.discovered)
            self.emit(
                "found",
                f"{_now()} BOUND {did[-4:]} confirmed by heartbeat: mesh address {address}",
            )

    def forget(self, did: str) -> None:
        """Remove a light (or "all") from the discovered list and its saved copy."""
        dids = list(self.discovered) if did.lower() == "all" else [did.upper()]
        for d in dids:
            if self.discovered.pop(d, None) is None:
                self.emit("info", f"No discovered light {d}.")
                continue
            self.pending_binds.pop(d, None)
            self.seen.discard(d)
            self.emit("info", f"Forgot {d[-4:]} ({d}).")
        save_lights(self.discovered)

    def print_discovered(self) -> None:
        if not self.discovered:
            self.emit("info", "No lights discovered yet.")
        for did, found in self.discovered.items():
            kind = protocol.device_type_name(found.device_type)
            self.emit(
                "info",
                f"  {found.name}  did={did}  {kind}  key={found.key.hex().upper()}  "
                f"address={found.mesh_address}"
                + ("" if did in self.seen else "  (saved, not seen this session)")
            )

    def print_info(self) -> None:
        info = self.info
        self.emit("info", f"  name:        {info.name} ({info.friendly_name})")
        self.emit("info", f"  model:       {info.model}  mac={info.mac_address}")
        self.emit("info", f"  esphome:     {info.esphome_version}  compiled {info.compilation_time}")
        self.emit("info", f"  bt proxy:    flags {info.bluetooth_proxy_feature_flags}")
        interval = f"{self.interval_ms} ms" if self.interval_ms else "firmware setting"
        self.emit("info", f"  phone key:   {self.phone_key.hex().upper()}  duration {self.duration_ms} ms  interval {interval}")
        for service in self.services:
            args = ", ".join(f"{a.name}:{a.type.name.lower()}" for a in service.args)
            marker = " <- used" if service is self.action else ""
            self.emit("info", f"  action:      {service.name}({args}){marker}")


# Command line

def _level(percent: str) -> int:
    return max(0, min(127, round(int(percent) * 127 / 100)))


def _address(value: str) -> int:
    return protocol.ALL_LIGHTS_ADDRESS if value == "all" else int(value)


def _light_command(name: str, values: list[str]) -> bytes:
    if name == "on":
        return protocol.light_on(_level(values[0]) if values else 127)
    if name == "off":
        return protocol.light_off()
    if name == "brightness":
        return protocol.light_brightness(_level(values[0]))
    if name == "rgb":
        r, g, b = (int(v) for v in values[:3])
        return protocol.light_rgb(r, g, b, _level(values[3]) if len(values) > 3 else 127)
    if name == "white":
        return protocol.light_white(_level(values[0]) if values else 127)
    raise ValueError(name)


def _parse_bind(values: list[str]) -> tuple[str, str, int]:
    """DID KEY ADDRESS, or IDENTITY ADDRESS with IDENTITY = NAME-DID-TYPE-KEY."""
    if len(values) == 2 and values[0].count("-") == 3:
        _, did, _, key = values[0].split("-")
        return did, key, int(values[1])
    did, key, address = values
    return did, key, int(address)


SHELL_HELP = """\
  scan [relay]                       ask lights in discovery mode to announce themselves
  found                              list discovered lights (kept between sessions)
  forget <did>|all                   remove a light from the discovered list
  bind <did> <key> <address>         bind a light (also: bind <identity> <address>)
  bind found <address>               bind the only discovered light
  on <address|all|type:XXXX|types> [pct]
                                     turn on; type:A82A = every light of that device type (as
                                     the app switches "all"); types = every light type (those
                                     seen in discovery, else all 9 known); all = mesh address 0
  off <address|all>                  turn off
  brightness <address|all> <percent>  brightness only (no on bit, min 5); "on <addr> <percent>" = on + brightness
  rgb <address|all> <r> <g> <b> [percent]
  white <address|all> [percent]
  group add <id> <address> [...]     put lights into a group (a light is in at most one)
  group remove <address> [...]       take lights out of their group (= group 0)
  <light command> group:<id> ...     switch a group, e.g. off group:1, brightness group:1 30
  scene <address> <speed> <fade|jump> <colours...>
                                     colour effect, e.g. scene 16 50 fade magenta red blue
                                     (colours: red green blue yellow magenta cyan white off)
  effect <address> <speed> <hex>     raw control type 8 bytes after the speed
  cmd <address|all> <hex>            send any command bytes as a control command, e.g. cmd all 80
  raw <hex>                          send a 24-byte payload as is
  duration <ms>                      advertising time per command
  interval <ms>                      time between packets (needs set_brmesh_interval)
  key <hex>                          phone key (8 hex chars)
  all on|off                         also show heartbeats, status and our own packets
  watch <address|prefix>|any|off     show everything from an address, decoded (e.g. watch 11:22);
                                     any = every BRMesh frame from any sender (phone app too)
  decode <hex>                       decode a BRMesh payload (bytes after FFF0)
  info                               device info and actions
  quit
"""


async def run_line(dbg: Debugger, line: str) -> bool:
    """Run one shell command; False ends the shell."""
    words = shlex.split(line)
    if not words:
        return True
    cmd, rest = words[0].lower(), words[1:]
    if cmd in ("quit", "exit", "q"):
        return False
    if cmd in ("help", "?"):
        dbg.emit("info", SHELL_HELP)
    elif cmd == "scan":
        await dbg.scan(relay=bool(rest and rest[0] == "relay"))
    elif cmd == "found":
        dbg.print_discovered()
    elif cmd == "forget":
        dbg.forget(rest[0])
    elif cmd == "bind":
        if rest and rest[0] == "found":
            if len(dbg.discovered) != 1:
                dbg.emit("info", f"{len(dbg.discovered)} lights discovered; give the DID and key instead.")
                return True
            found = next(iter(dbg.discovered.values()))
            await dbg.bind(found.did.hex(), found.key.hex(), int(rest[1]))
        else:
            await dbg.bind(*_parse_bind(rest))
    elif cmd in ("on", "off", "brightness", "rgb", "white"):
        command = _light_command(cmd, rest[1:])
        target = rest[0].lower()
        if target == "types" or target.startswith("group:"):
            # Every light type (those seen in discovery, else all known light
            # types), optionally only in one group: group:<id>
            group = int(target[6:]) if target.startswith("group:") else 0
            types = sorted(
                {f.device_type for f in dbg.discovered.values() if protocol.is_light(f.device_type)}
            ) or sorted(protocol.LIGHT_TYPE_NAMES)
            for device_type in types:
                await dbg.light_by_type(device_type, command, group)
        elif rest[0].lower().startswith("type:"):
            # type:<hex> = every light of that device type, like the app's all on/off
            await dbg.light_by_type(int(rest[0][5:], 16), command)
        else:
            await dbg.light(_address(rest[0]), command)
    elif cmd == "group":
        # group add <id> <address> [...] / group remove <address> [...] (= group 0)
        action = rest[0].lower() if rest else ""
        if action == "add" and len(rest) >= 3:
            for address in rest[2:]:
                await dbg.assign_group(int(address), int(rest[1]))
        elif action == "remove" and len(rest) >= 2:
            for address in rest[1:]:
                await dbg.assign_group(int(address), 0)
        else:
            raise ValueError("group add <group id> <mesh address> [...] | group remove <mesh address> [...]")
    elif cmd == "scene":
        # scene <address> <speed> <fade|jump> <colour> [...], e.g. scene 16 50 fade magenta red blue
        mode = {"jump": protocol.EFFECT_MODE_JUMP, "fade": protocol.EFFECT_MODE_FADE}[rest[2].lower()]
        colors = [protocol.EFFECT_COLORS[name.lower()] for name in rest[3:]]
        payload = dbg.builder.scene(int(rest[0]), dbg.phone_key, int(rest[1]), mode, colors)
        info = protocol.describe_broadcast(payload, dbg.phone_key)
        await dbg.send(payload, protocol.describe_action(info))
    elif cmd == "effect":
        # effect <address> <speed 1-100> <code hex...>, e.g. effect 16 50 43 02
        code = bytes.fromhex("".join(rest[2:]))
        if not 1 <= len(code) <= 9:
            raise ValueError("effect <address> <speed 1-100> <1-9 code bytes>")
        await dbg.effect(int(rest[0]), int(rest[1]), code)
    elif cmd == "cmd":
        command = bytes.fromhex("".join(rest[1:]))
        if not 1 <= len(command) <= 10:
            raise ValueError("1 to 10 command bytes")
        await dbg.light(_address(rest[0]), command)
    elif cmd == "raw":
        await dbg.send(bytes.fromhex(rest[0]), "raw payload")
    elif cmd == "duration":
        dbg.duration_ms = int(rest[0])
        dbg.emit("info", f"Advertising {dbg.duration_ms} ms per command.")
    elif cmd == "interval":
        await dbg.set_interval(int(rest[0]))
    elif cmd == "key":
        dbg.phone_key = bytes.fromhex(rest[0])
        dbg.emit("info", f"Phone key {dbg.phone_key.hex().upper()}.")
    elif cmd == "watch":
        target = rest[0].upper() if rest else "OFF"
        dbg.watch = None if target == "OFF" else target
        dbg._watch_last.clear()
        if dbg.watch == "ANY":
            dbg.emit("info", "Watching every BRMesh frame from any sender.")
        else:
            dbg.emit("info", f"Watching {dbg.watch}." if dbg.watch else "Watch off.")
    elif cmd == "decode":
        payload = bytes.fromhex("".join(rest))
        dbg.emit("info", f"{payload.hex(' ')}\n" + _decode_brmesh(payload, dbg.phone_key))
    elif cmd == "all":
        dbg.show_all = not rest or rest[0] == "on"
        dbg.emit("info", f"Showing all broadcasts: {'on' if dbg.show_all else 'off'}.")
    elif cmd == "info":
        dbg.print_info()
    else:
        dbg.emit("info", f"Unknown command '{cmd}'. Type help.")
    return True


async def shell(dbg: Debugger) -> None:
    print("BRMesh debug shell. Type help for commands.")
    loop = asyncio.get_running_loop()
    while True:
        try:
            line = await loop.run_in_executor(None, input, "brmesh> ")
        except EOFError:
            break
        try:
            if not await run_line(dbg, line):
                break
        except (ValueError, IndexError) as err:
            print(f"Invalid arguments: {err}. Type help.")
        except Exception as err:  # noqa: BLE001 - keep the shell running
            print(f"Error: {err}")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--host", default=os.environ.get("BRMESH_HOST"), help="ESP32 IP or name")
    parser.add_argument("--key", default=os.environ.get("BRMESH_KEY"), help="API encryption key")
    parser.add_argument("--port", type=int, default=6053)
    parser.add_argument("--action", default="send_brmesh", help="name of the ESPHome action")
    parser.add_argument("--phone-key", default=os.environ.get("BRMESH_PHONE_KEY", "A1A2A3A4"), help="mesh key, 8 hex chars")
    parser.add_argument("--duration", type=int, default=1000, help="advertising time per command in ms")
    parser.add_argument("--interval", type=int, help="time between packets in ms (set on connect)")
    parser.add_argument("--all", action="store_true", help="show every BRMesh broadcast")
    parser.add_argument("--watch", help="show everything from addresses starting with this, e.g. 11:22")
    parser.add_argument("--no-logs", action="store_true", help="don't show the ESP32's log")
    parser.add_argument("-v", "--verbose", action="store_true", help="ESP32 log at verbose level")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("info", help="device info and actions")
    sub.add_parser("shell", help="interactive session (default)")
    p = sub.add_parser("sniff", help="show BRMesh broadcasts")
    p.add_argument("seconds", nargs="?", type=float, default=0, help="0 = until Ctrl+C")
    p = sub.add_parser("scan", help="scan and list lights in discovery mode")
    p.add_argument("--listen", type=float, default=15, help="seconds to listen after the scan")
    p.add_argument("--relay", action="store_true", help="let lights relay the scan")
    p = sub.add_parser("bind", help="bind: DID KEY ADDRESS or IDENTITY ADDRESS")
    p.add_argument("values", nargs="+")
    for name in ("on", "off", "brightness", "rgb", "white"):
        p = sub.add_parser(name, help="light command; address 'all' = every light")
        p.add_argument("address")
        p.add_argument("values", nargs="*")
    p = sub.add_parser("raw", help="send a payload as is")
    p.add_argument("payload")
    args = parser.parse_args()
    if not args.host:
        parser.error("--host (or BRMESH_HOST) is required")

    dbg = Debugger(args)
    dbg.show_all = args.all
    dbg.watch = args.watch.upper() if args.watch else None
    dbg.verbose = args.verbose
    await dbg.connect()
    try:
        if args.interval:
            await dbg.set_interval(args.interval)
        command = args.command or "shell"
        if command == "info":
            dbg.print_info()
            return
        if not args.no_logs:
            dbg.start_logs()
        dbg.start_sniffing()
        if command == "shell":
            await shell(dbg)
        elif command == "sniff":
            await asyncio.sleep(args.seconds or float("inf"))
        elif command == "scan":
            await dbg.scan(relay=args.relay)
            await asyncio.sleep(args.listen)
            print("Discovered:")
            dbg.print_discovered()
        elif command == "bind":
            await dbg.bind(*_parse_bind(args.values))
        elif command == "raw":
            await dbg.send(bytes.fromhex(args.payload), "raw payload")
        else:
            await dbg.light(_address(args.address), _light_command(command, args.values))
        # Give the ESP32 log and replies a moment to arrive.
        if command not in ("shell", "sniff", "scan"):
            await asyncio.sleep(1)
    finally:
        await dbg.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
