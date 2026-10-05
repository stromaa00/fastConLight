"""Send raw BLE advertisements through BlueZ.

Home Assistant's Bluetooth integration can only scan, so commands are broadcast
by registering a short-lived LE advertisement on the same adapter via D-Bus.
"""

# No "from __future__ import annotations": dbus-fast reads the D-Bus signatures
# from the annotations below and needs them unquoted.

import asyncio
import logging

from dbus_fast import BusType, Message, MessageType, Variant
from dbus_fast.aio import MessageBus
from dbus_fast.constants import PropertyAccess
from dbus_fast.service import ServiceInterface, dbus_property, method

_LOGGER = logging.getLogger(__name__)

BLUEZ_SERVICE = "org.bluez"
ADVERTISING_MANAGER = "org.bluez.LEAdvertisingManager1"
ADVERTISEMENT_PATH = "/org/homeassistant/fastcon/advertisement0"


class AdvertiseError(Exception):
    """Raised when BlueZ refuses an advertising request."""


class _Advertisement(ServiceInterface):
    """org.bluez.LEAdvertisement1 carrying one manufacturer data payload."""

    def __init__(self, manufacturer_id: int, data: bytes, interval_ms: int) -> None:
        super().__init__("org.bluez.LEAdvertisement1")
        self._manufacturer_id = manufacturer_id
        self._data = data
        self._interval_ms = interval_ms

    @method()
    def Release(self):  # noqa: N802
        _LOGGER.debug("BlueZ released the advertisement")

    @dbus_property(access=PropertyAccess.READ)
    def Type(self) -> "s":  # noqa: N802, F821
        return "broadcast"

    @dbus_property(access=PropertyAccess.READ)
    def ManufacturerData(self) -> "a{qv}":  # noqa: N802, F722
        return {self._manufacturer_id: Variant("ay", self._data)}

    @dbus_property(access=PropertyAccess.READ)
    def MinInterval(self) -> "u":  # noqa: N802, F821
        return self._interval_ms

    @dbus_property(access=PropertyAccess.READ)
    def MaxInterval(self) -> "u":  # noqa: N802, F821
        return self._interval_ms


async def _call(bus: MessageBus, path: str, interface: str, member: str,
                signature: str = "", body: list | None = None) -> Message:
    reply = await bus.call(
        Message(
            destination=BLUEZ_SERVICE,
            path=path,
            interface=interface,
            member=member,
            signature=signature,
            body=body or [],
        )
    )
    if reply.message_type == MessageType.ERROR:
        raise AdvertiseError(f"{reply.error_name}: {' '.join(map(str, reply.body))}")
    return reply


async def async_list_adapters() -> list[str]:
    """Return the BlueZ adapters (e.g. "hci0") that support LE advertising."""
    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
    try:
        reply = await _call(
            bus, "/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects"
        )
    finally:
        bus.disconnect()
    return sorted(
        path.rsplit("/", 1)[-1]
        for path, interfaces in reply.body[0].items()
        if ADVERTISING_MANAGER in interfaces
    )


class BlueZAdvertiser:
    """Broadcasts payloads on one BlueZ adapter, one at a time."""

    def __init__(self, adapter: str, interval_ms: int = 43) -> None:
        self._adapter_path = f"/org/bluez/{adapter}"
        self._interval_ms = interval_ms
        self._bus: MessageBus | None = None

    async def _get_bus(self) -> MessageBus:
        if self._bus is None or not self._bus.connected:
            self._bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        return self._bus

    async def advertise(self, manufacturer_id: int, data: bytes, duration: float) -> None:
        """Advertise the payload for `duration` seconds."""
        bus = await self._get_bus()
        bus.export(
            ADVERTISEMENT_PATH,
            _Advertisement(manufacturer_id, data, self._interval_ms),
        )
        try:
            await _call(
                bus, self._adapter_path, ADVERTISING_MANAGER,
                "RegisterAdvertisement", "oa{sv}", [ADVERTISEMENT_PATH, {}],
            )
            try:
                await asyncio.sleep(duration)
            finally:
                try:
                    await _call(
                        bus, self._adapter_path, ADVERTISING_MANAGER,
                        "UnregisterAdvertisement", "o", [ADVERTISEMENT_PATH],
                    )
                except AdvertiseError as err:
                    _LOGGER.debug("Unregistering advertisement failed: %s", err)
        finally:
            bus.unexport(ADVERTISEMENT_PATH)

    def close(self) -> None:
        """Disconnect from D-Bus."""
        if self._bus is not None:
            self._bus.disconnect()
            self._bus = None
