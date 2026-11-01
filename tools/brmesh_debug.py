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
from datetime import datetime
import importlib.util
import os
from collections.abc import Callable
from pathlib import Path
import shlex
import sys

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


def _now() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


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
        self.verbose = False
        self.sniffing = False
        self.discovered: dict[str, protocol.DiscoveredDevice] = {}
        # Mesh address -> (group address, rssi, time) of the last heartbeat
        self.heartbeats: dict[int, tuple[int, int, str]] = {}
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
                payload = _manufacturer_data(adv.data, protocol.MANUFACTURER_ID)
                if payload is not None:
                    self._on_brmesh(_mac(adv.address), adv.rssi, payload)

        self._unsub.append(self.client.subscribe_bluetooth_le_raw_advertisements(on_advertisements))

    def _on_brmesh(self, address: str, rssi: int, payload: bytes) -> None:
        own = payload in self._own
        found = (
            protocol.parse_broadcast(payload) if address.startswith(DEVICE_ADDRESS_PREFIX) else None
        )
        if found is not None:
            did = found.did.hex().upper()
            new = did not in self.discovered
            self.discovered[did] = found
            if new or self.show_all:
                kind = protocol.LIGHT_TYPE_NAMES.get(found.device_type, f"type {found.device_type:04X}")
                self.emit(
                    "found",
                    f"{_now()} FOUND {found.name}  did={did} {kind} key={found.key.hex().upper()} "
                    f"address={found.mesh_address} rssi={rssi}\n"
                    f"         identity {found.name}-{did}-{found.device_type:04X}-{found.key.hex().upper()}"
                )
            return
        if (beat := protocol.parse_heartbeat(payload, self.phone_key)) is not None:
            self.heartbeats[beat.mesh_address] = (beat.group_address, rssi, _now()[:8])
            if self.show_all:
                self.emit(
                    "beat",
                    f"{_now()} BEAT address={beat.mesh_address} group={beat.group_address} "
                    f"from={address} rssi={rssi}"
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

    def print_discovered(self) -> None:
        if not self.discovered:
            self.emit("info", "No lights discovered yet.")
        for did, found in self.discovered.items():
            kind = protocol.LIGHT_TYPE_NAMES.get(found.device_type, f"type {found.device_type:04X}")
            self.emit(
                "info",
                f"  {found.name}  did={did}  {kind}  key={found.key.hex().upper()}  "
                f"address={found.mesh_address}"
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
        return protocol.light_on(_level(values[0]))
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
  found                              list discovered lights
  bind <did> <key> <address>         bind a light (also: bind <identity> <address>)
  bind found <address>               bind the only discovered light
  on <address|all> [percent]         turn on
  off <address|all>                  turn off
  brightness <address|all> <percent>
  rgb <address|all> <r> <g> <b> [percent]
  white <address|all> [percent]
  raw <hex>                          send a 24-byte payload as is
  duration <ms>                      advertising time per command
  interval <ms>                      time between packets (needs set_brmesh_interval)
  key <hex>                          phone key (8 hex chars)
  all on|off                         also show heartbeats, status and our own packets
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
        await dbg.light(_address(rest[0]), _light_command(cmd, rest[1:]))
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
