"""Advertise through the Linux Bluetooth management API (MGMT).

BlueZ's D-Bus advertising API won't accept a full 31-byte BRMesh packet: it
reserves room for flags it manages itself, and the kernel then rejects the
data as too long ("Invalid Parameters"). MGMT lets us send our own flags and
use all 31 bytes, exactly like the ESP32 firmware does.

Needs CAP_NET_ADMIN, which the Home Assistant OS core container has.
No Home Assistant imports, so the packet helpers can be unit tested.
"""

from __future__ import annotations

import asyncio
import ctypes
import ctypes.util
import logging
import os
import socket
import struct

_LOGGER = logging.getLogger(__name__)

AF_BLUETOOTH = 31
BTPROTO_HCI = 1
HCI_DEV_NONE = 0xFFFF
HCI_CHANNEL_CONTROL = 3

MGMT_OP_READ_ADV_FEATURES = 0x003D
MGMT_OP_REMOVE_ADVERTISING = 0x003F
MGMT_OP_ADD_EXT_ADV_PARAMS = 0x0054
MGMT_OP_ADD_EXT_ADV_DATA = 0x0055

MGMT_EV_CMD_COMPLETE = 0x0001
MGMT_EV_CMD_STATUS = 0x0002

MGMT_ADV_FLAG_CONNECTABLE = 1 << 0
MGMT_ADV_PARAM_INTERVALS = 1 << 14

MGMT_STATUS_PERMISSION_DENIED = 0x14

STATUS_NAMES = {
    0x01: "Unknown Command",
    0x03: "Failed",
    0x0A: "Busy",
    0x0B: "Rejected",
    0x0C: "Not Supported",
    0x0D: "Invalid Parameters",
    0x0F: "Not Powered",
    0x11: "Invalid Index",
    0x14: "Permission Denied",
}

AD_FLAGS_LE_GENERAL_DISCOVERABLE = 0x02  # Same flags byte the firmware sends
REQUEST_TIMEOUT = 3.0


class MgmtError(Exception):
    """Advertising through MGMT failed."""


class MgmtStatusError(MgmtError):
    """A MGMT command returned an error status."""

    def __init__(self, opcode: int, status: int) -> None:
        super().__init__(
            f"MGMT command 0x{opcode:04x} failed: "
            f"{STATUS_NAMES.get(status, 'Unknown')} (0x{status:02x})"
        )
        self.status = status


def advertising_data(manufacturer_id: int, payload: bytes) -> bytes:
    """Full legacy advertising data: flags + manufacturer specific data."""
    return bytes((2, 0x01, AD_FLAGS_LE_GENERAL_DISCOVERABLE, len(payload) + 3, 0xFF)) + (
        struct.pack("<H", manufacturer_id) + payload
    )


def ext_adv_params(instance: int, connectable: bool, interval_ms: int) -> bytes:
    """Parameters for MGMT Add Extended Advertising Parameters."""
    flags = MGMT_ADV_PARAM_INTERVALS | (MGMT_ADV_FLAG_CONNECTABLE if connectable else 0)
    interval = round(interval_ms / 0.625)
    # instance, flags, duration, timeout, min interval, max interval, tx power
    return struct.pack("<BIHHIIb", instance, flags, 0, 0, interval, interval, 0)


def ext_adv_data(instance: int, adv_data: bytes) -> bytes:
    """Parameters for MGMT Add Extended Advertising Data (no scan response)."""
    return struct.pack("<BBB", instance, len(adv_data), 0) + adv_data


def pick_instance(adv_features: bytes) -> int:
    """Highest advertising instance not in use, from Read Advertising Features."""
    _flags, _max_adv, _max_scan, max_instances, num = struct.unpack_from("<IBBBB", adv_features)
    used = set(adv_features[8 : 8 + num])
    for instance in range(max_instances, 0, -1):
        if instance not in used:
            return instance
    raise MgmtError("no free advertising instance")


class _SockaddrHci(ctypes.Structure):
    _fields_ = [
        ("hci_family", ctypes.c_ushort),
        ("hci_dev", ctypes.c_ushort),
        ("hci_channel", ctypes.c_ushort),
    ]


def _open_control_socket() -> socket.socket:
    # Python's socket module can't bind to an HCI channel, so use libc.
    libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6", use_errno=True)
    fd = libc.socket(
        AF_BLUETOOTH, socket.SOCK_RAW | socket.SOCK_CLOEXEC | socket.SOCK_NONBLOCK, BTPROTO_HCI
    )
    if fd < 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err))
    addr = _SockaddrHci(AF_BLUETOOTH, HCI_DEV_NONE, HCI_CHANNEL_CONTROL)
    if libc.bind(fd, ctypes.byref(addr), ctypes.sizeof(addr)) < 0:
        err = ctypes.get_errno()
        os.close(fd)
        raise OSError(err, os.strerror(err))
    return socket.socket(AF_BLUETOOTH, socket.SOCK_RAW, BTPROTO_HCI, fileno=fd)


class MgmtAdvertiser:
    """Broadcasts payloads on one controller through MGMT."""

    def __init__(self, adapter: str, interval_ms: int) -> None:
        self._index = int(adapter.removeprefix("hci"))
        self._interval_ms = interval_ms
        self._sock: socket.socket | None = None
        # Connectable first: it uses the adapter's public address. Non-connectable
        # needs a random address, which controllers refuse to set while Home
        # Assistant is scanning ("Opcode 0x2005 failed: -16").
        self._connectable_options = [True, False]

    async def _request(self, opcode: int, params: bytes = b"") -> bytes:
        if self._sock is None:
            self._sock = _open_control_socket()
        loop = asyncio.get_running_loop()
        await loop.sock_sendall(
            self._sock, struct.pack("<HHH", opcode, self._index, len(params)) + params
        )
        async with asyncio.timeout(REQUEST_TIMEOUT):
            while True:
                packet = await loop.sock_recv(self._sock, 512)
                event, index, length = struct.unpack_from("<HHH", packet)
                if event not in (MGMT_EV_CMD_COMPLETE, MGMT_EV_CMD_STATUS) or index != self._index:
                    continue
                body = packet[6 : 6 + length]
                op, status = struct.unpack_from("<HB", body)
                if op != opcode:
                    continue
                if status:
                    raise MgmtStatusError(opcode, status)
                if event == MGMT_EV_CMD_COMPLETE:
                    return body[3:]

    async def advertise(self, manufacturer_id: int, payload: bytes, duration: float) -> None:
        """Advertise the payload for `duration` seconds."""
        adv = advertising_data(manufacturer_id, payload)
        errors: list[str] = []
        for i, connectable in enumerate(self._connectable_options):
            instance = pick_instance(await self._request(MGMT_OP_READ_ADV_FEATURES))
            try:
                await self._request(
                    MGMT_OP_ADD_EXT_ADV_PARAMS,
                    ext_adv_params(instance, connectable, self._interval_ms),
                )
                await self._request(MGMT_OP_ADD_EXT_ADV_DATA, ext_adv_data(instance, adv))
            except (MgmtStatusError, TimeoutError) as err:
                await self._remove(instance)
                if getattr(err, "status", None) == MGMT_STATUS_PERMISSION_DENIED:
                    raise
                reason = str(err) or "timed out"
                kind = "connectable" if connectable else "non-connectable"
                errors.append(f"[{kind}] {reason}")
                continue
            if i:
                _LOGGER.warning(
                    "hci%d advertises only as %s (%s)", self._index,
                    "connectable" if connectable else "non-connectable", "; ".join(errors),
                )
                self._connectable_options = self._connectable_options[i:]
            try:
                await asyncio.sleep(duration)
            finally:
                await self._remove(instance)
            return
        raise MgmtError("; ".join(errors))

    async def _remove(self, instance: int) -> None:
        try:
            await self._request(MGMT_OP_REMOVE_ADVERTISING, bytes((instance,)))
        except (MgmtError, OSError, TimeoutError) as err:
            _LOGGER.debug("Removing advertising instance %d failed: %s", instance, err)

    def close(self) -> None:
        """Close the MGMT socket."""
        if self._sock is not None:
            self._sock.close()
            self._sock = None
