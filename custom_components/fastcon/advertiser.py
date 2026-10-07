"""Send raw BLE advertisements through BlueZ.

Home Assistant's Bluetooth integration can only scan, so commands are broadcast
by registering a short-lived LE advertisement on the same adapter via D-Bus.
"""

# No "from __future__ import annotations": dbus-fast reads the D-Bus signatures
# from the annotations below and needs them unquoted.

import asyncio
from dataclasses import dataclass
import logging

from dbus_fast import BusType, Message, MessageType, Variant
from dbus_fast.aio import MessageBus
from dbus_fast.constants import PropertyAccess
from dbus_fast.service import ServiceInterface, dbus_property, method

from .mgmt import (
    MGMT_STATUS_PERMISSION_DENIED,
    MgmtAdvertiser,
    MgmtError,
    MgmtStatusError,
)

_LOGGER = logging.getLogger(__name__)

BLUEZ_SERVICE = "org.bluez"
ADVERTISING_MANAGER = "org.bluez.LEAdvertisingManager1"
ADVERTISEMENT_PATH = "/org/homeassistant/fastcon/advertisement0"

# Bluetooth 4.x controllers reject non-connectable advertising faster than
# 100 ms, so the firmware's 43 ms interval can't be used here.
DEFAULT_INTERVAL_MS = 100


class AdvertiseError(Exception):
    """Raised when BlueZ refuses an advertising request."""


@dataclass(frozen=True)
class _Variant:
    """One way of asking BlueZ to advertise; controllers differ in what they accept."""

    adv_type: str
    interval_ms: int | None

    def __str__(self) -> str:
        interval = f"{self.interval_ms} ms" if self.interval_ms else "default interval"
        return f"{self.adv_type}, {interval}"


class _Advertisement(ServiceInterface):
    """org.bluez.LEAdvertisement1 carrying one manufacturer data payload."""

    def __init__(self, manufacturer_id: int, data: bytes, adv_type: str) -> None:
        super().__init__("org.bluez.LEAdvertisement1")
        self._manufacturer_id = manufacturer_id
        self._data = data
        self._adv_type = adv_type

    @method()
    def Release(self):  # noqa: N802
        _LOGGER.debug("BlueZ released the advertisement")

    @dbus_property(access=PropertyAccess.READ)
    def Type(self) -> "s":  # noqa: N802, F821
        return self._adv_type

    @dbus_property(access=PropertyAccess.READ)
    def ManufacturerData(self) -> "a{qv}":  # noqa: N802, F722
        return {self._manufacturer_id: Variant("ay", self._data)}


class _TimedAdvertisement(_Advertisement):
    """Advertisement that also asks for a fixed advertising interval."""

    def __init__(
        self, manufacturer_id: int, data: bytes, adv_type: str, interval_ms: int
    ) -> None:
        super().__init__(manufacturer_id, data, adv_type)
        self._interval_ms = interval_ms

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


def _plain(value):
    """Unwrap dbus-fast Variants for readable logging."""
    if isinstance(value, Variant):
        return _plain(value.value)
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


class BlueZAdvertiser:
    """Broadcasts payloads on one BlueZ adapter, one at a time."""

    def __init__(self, adapter: str, interval_ms: int = DEFAULT_INTERVAL_MS) -> None:
        self._adapter = adapter
        self._adapter_path = f"/org/bluez/{adapter}"
        # Tried in order until one is accepted; the working one is kept.
        self._variants = [
            _Variant("broadcast", interval_ms),
            _Variant("broadcast", None),
            _Variant("peripheral", None),
        ]
        self._bus: MessageBus | None = None

    async def _get_bus(self) -> MessageBus:
        if self._bus is None or not self._bus.connected:
            self._bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        return self._bus

    async def advertise(self, manufacturer_id: int, data: bytes, duration: float) -> None:
        """Advertise the payload for `duration` seconds."""
        bus = await self._get_bus()
        await self._register_first_accepted(bus, manufacturer_id, data)
        try:
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

    async def _register_first_accepted(
        self, bus: MessageBus, manufacturer_id: int, data: bytes
    ) -> None:
        errors: list[str] = []
        for index, variant in enumerate(self._variants):
            try:
                await self._register(bus, variant, manufacturer_id, data)
            except AdvertiseError as err:
                errors.append(f"[{variant}] {err}")
                continue
            if index:
                _LOGGER.warning(
                    "%s accepted advertising only as: %s (refused: %s)",
                    self._adapter, variant, "; ".join(errors),
                )
                # Keep using the variant that works.
                self._variants = self._variants[index:]
            return

        diagnostics = await self._diagnostics(bus)
        raise AdvertiseError(
            f"{'; '.join(errors)}. Adapter state: {diagnostics}. "
            "The bluetoothd log has the exact reason "
            "(Home Assistant OS: ha host logs --identifier bluetoothd)"
        )

    async def _register(
        self, bus: MessageBus, variant: _Variant, manufacturer_id: int, data: bytes
    ) -> None:
        advertisement = (
            _TimedAdvertisement(manufacturer_id, data, variant.adv_type, variant.interval_ms)
            if variant.interval_ms
            else _Advertisement(manufacturer_id, data, variant.adv_type)
        )
        bus.export(ADVERTISEMENT_PATH, advertisement)
        try:
            await _call(
                bus, self._adapter_path, ADVERTISING_MANAGER,
                "RegisterAdvertisement", "oa{sv}", [ADVERTISEMENT_PATH, {}],
            )
        except AdvertiseError:
            bus.unexport(ADVERTISEMENT_PATH)
            raise

    async def _diagnostics(self, bus: MessageBus) -> dict:
        """Read what the adapter reports about itself and its advertising support."""
        result: dict = {}
        for interface, keys in (
            ("org.bluez.Adapter1", ("Powered", "Discovering", "Roles")),
            (ADVERTISING_MANAGER, None),
        ):
            try:
                reply = await _call(
                    bus, self._adapter_path, "org.freedesktop.DBus.Properties",
                    "GetAll", "s", [interface],
                )
            except AdvertiseError as err:
                result[interface] = str(err)
                continue
            props = _plain(reply.body[0])
            result.update(
                {k: v for k, v in props.items() if keys is None or k in keys}
            )
        return result

    def close(self) -> None:
        """Disconnect from D-Bus."""
        if self._bus is not None:
            self._bus.disconnect()
            self._bus = None


class Advertiser:
    """Sends through MGMT, falling back to BlueZ D-Bus if MGMT isn't usable.

    MGMT is preferred because it accepts the full 31-byte packet; BlueZ only
    works where the kernel leaves enough room next to its own flags.
    """

    def __init__(self, adapter: str, interval_ms: int = DEFAULT_INTERVAL_MS) -> None:
        self._adapter = adapter
        self._mgmt: MgmtAdvertiser | None = MgmtAdvertiser(adapter, interval_ms)
        self._bluez = BlueZAdvertiser(adapter, max(interval_ms, DEFAULT_INTERVAL_MS))
        # Once MGMT has worked, later errors are treated as transient.
        self._mgmt_worked = False

    async def advertise(self, manufacturer_id: int, data: bytes, duration: float) -> None:
        """Advertise the payload for `duration` seconds."""
        if self._mgmt is not None:
            try:
                await self._mgmt.advertise(manufacturer_id, data, duration)
            except TimeoutError as err:
                raise AdvertiseError("kernel management API timed out") from err
            except MgmtError as err:
                if not (
                    isinstance(err, MgmtStatusError)
                    and err.status == MGMT_STATUS_PERMISSION_DENIED
                ):
                    # The kernel was reached but refused; BlueZ can't do better.
                    raise AdvertiseError(f"kernel management API: {err}") from err
                self._disable_mgmt(err)
            except OSError as err:
                if self._mgmt_worked:
                    # Reopen the socket on the next command instead of giving up.
                    self._mgmt.close()
                    raise AdvertiseError(f"kernel management API: {err!r}") from err
                self._disable_mgmt(err)
            else:
                self._mgmt_worked = True
                return
        await self._bluez.advertise(manufacturer_id, data, duration)

    def _disable_mgmt(self, err: Exception) -> None:
        """MGMT isn't usable here (e.g. no CAP_NET_ADMIN); use BlueZ from now on."""
        _LOGGER.warning(
            "Can't use the kernel management API on %s (%r); using BlueZ D-Bus instead, "
            "which can't send full BRMesh packets on most systems",
            self._adapter, err,
        )
        if self._mgmt is not None:
            self._mgmt.close()
        self._mgmt = None

    def close(self) -> None:
        """Release sockets and D-Bus connections."""
        if self._mgmt is not None:
            self._mgmt.close()
        self._bluez.close()
