"""BRMesh hub: discovers devices and broadcasts commands."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import asdict, dataclass
import logging

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store

from .advertiser import AdvertiseError, BlueZAdvertiser
from .const import (
    CONF_ADAPTER,
    CONF_ADVERTISE_DURATION,
    CONF_PHONE_KEY,
    DEFAULT_ADVERTISE_DURATION,
    DEFAULT_PHONE_KEY,
    DEVICE_ADDRESS_PREFIX,
    DOMAIN,
    signal_new_device,
)
from .protocol import MANUFACTURER_ID, CommandBuilder, parse_broadcast

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1


@dataclass
class FastconDevice:
    """A BRMesh device known to the hub."""

    did: str  # 12 hex chars
    device_type: int
    key: str  # 8 hex chars
    mesh_address: int

    @property
    def name(self) -> str:
        """Short name the BRMesh app uses (last 4 hex chars of the DID)."""
        return self.did[-4:]

    @property
    def unique_id(self) -> str:
        """Identifier in the firmware's NAME-DID-TYPE-KEY format."""
        return f"{self.name}-{self.did}-{self.device_type:04X}-{self.key}"


class FastconHub:
    """Owns the device list, the Bluetooth listener and the send queue."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        config = {**entry.data, **entry.options}
        self.adapter: str = config[CONF_ADAPTER]
        self.phone_key = bytes.fromhex(config.get(CONF_PHONE_KEY, DEFAULT_PHONE_KEY))
        self.duration: float = config.get(
            CONF_ADVERTISE_DURATION, DEFAULT_ADVERTISE_DURATION
        )
        self.devices: dict[str, FastconDevice] = {}
        self._store: Store[dict] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self._advertiser = BlueZAdvertiser(self.adapter)
        self._builder = CommandBuilder()
        # Pending commands keyed by target, so a newer command for the same
        # light replaces one that hasn't been sent yet (e.g. slider drags).
        self._pending: dict[str, Callable[[], bytes]] = {}
        self._wakeup = asyncio.Event()

    async def async_setup(self) -> None:
        """Load stored devices and start listening and sending."""
        stored = await self._store.async_load() or {}
        for data in stored.get("devices", []):
            device = FastconDevice(**data)
            self.devices[device.did] = device

        self.entry.async_on_unload(
            bluetooth.async_register_callback(
                self.hass,
                self._async_on_advertisement,
                bluetooth.BluetoothCallbackMatcher(
                    manufacturer_id=MANUFACTURER_ID, connectable=False
                ),
                bluetooth.BluetoothScanningMode.ACTIVE,
            )
        )
        self.entry.async_create_background_task(
            self.hass, self._async_send_loop(), f"{DOMAIN} sender"
        )

    def close(self) -> None:
        """Release the D-Bus connection."""
        self._advertiser.close()

    @callback
    def _async_on_advertisement(
        self,
        service_info: bluetooth.BluetoothServiceInfoBleak,
        change: bluetooth.BluetoothChange,
    ) -> None:
        if not service_info.address.upper().startswith(DEVICE_ADDRESS_PREFIX):
            return
        payload = service_info.manufacturer_data.get(MANUFACTURER_ID)
        if payload is None or (found := parse_broadcast(payload)) is None:
            return
        did = found.did.hex().upper()
        if did in self.devices:
            return
        _LOGGER.info("Discovered BRMesh device %s (type %04X)", did, found.device_type)
        self.async_add_device(
            FastconDevice(
                did=did,
                device_type=found.device_type,
                key=found.key.hex().upper(),
                mesh_address=self.next_free_address(),
            )
        )

    def next_free_address(self) -> int:
        """Lowest mesh address (1-255) not used by a known device."""
        used = {device.mesh_address for device in self.devices.values()}
        return next((addr for addr in range(1, 256) if addr not in used), 255)

    @callback
    def async_add_device(self, device: FastconDevice) -> None:
        """Add or replace a device, persist it and create its entities."""
        self.devices[device.did] = device
        self._async_save()
        async_dispatcher_send(self.hass, signal_new_device(self.entry.entry_id), device)

    @callback
    def async_remove_device(self, did: str) -> None:
        """Forget a device."""
        if self.devices.pop(did, None) is not None:
            self._async_save()

    @callback
    def _async_save(self) -> None:
        self._store.async_delay_save(
            lambda: {"devices": [asdict(d) for d in self.devices.values()]}, 1
        )

    @callback
    def async_scan(self) -> None:
        """Ask unbound lights to announce themselves."""
        self._queue("scan", self._builder.scan)

    @callback
    def async_bind(self, device: FastconDevice) -> None:
        """Give a device its mesh address and the phone key."""
        self._queue(
            f"bind:{device.did}",
            lambda: self._builder.bind(
                bytes.fromhex(device.did),
                device.mesh_address,
                self.phone_key,
                bytes.fromhex(device.key),
            ),
        )

    @callback
    def async_bind_all(self) -> None:
        """Bind every known device."""
        for device in self.devices.values():
            self.async_bind(device)

    @callback
    def async_send_light(self, device: FastconDevice, command: bytes) -> None:
        """Queue a light command, replacing any unsent one for the same light."""
        self._queue(
            f"light:{device.did}",
            lambda: self._builder.light(device.mesh_address, self.phone_key, command),
        )

    def _queue(self, key: str, build: Callable[[], bytes]) -> None:
        self._pending[key] = build
        self._wakeup.set()

    async def _async_send_loop(self) -> None:
        while True:
            await self._wakeup.wait()
            self._wakeup.clear()
            while self._pending:
                key = next(iter(self._pending))
                payload = self._pending.pop(key)()
                _LOGGER.debug("Sending %s: %s", key, payload.hex())
                try:
                    await self._advertiser.advertise(
                        MANUFACTURER_ID, payload, self.duration
                    )
                except (AdvertiseError, OSError) as err:
                    _LOGGER.error(
                        "Could not advertise on %s (%s): %s", self.adapter, key, err
                    )
