"""BRMesh hub: discovers devices and broadcasts commands."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import timedelta
import logging
import statistics
import time

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .advertiser import AdvertiseError, Advertiser
from .const import (
    AUTO_BIND_COOLDOWN,
    AVAILABILITY_CHECK_INTERVAL,
    CONF_ADAPTER,
    CONF_ADVERTISE_DURATION,
    CONF_PHONE_KEY,
    DEFAULT_ADVERTISE_DURATION,
    DEFAULT_PHONE_KEY,
    DEVICE_ADDRESS_PREFIX,
    DOMAIN,
    HEARTBEAT_BURST_GAP,
    MIN_HEARTBEAT_SAMPLES,
    MISSED_HEARTBEATS,
    UNAVAILABLE_AFTER,
    signal_availability,
    signal_device_updated,
    signal_new_device,
)
from .protocol import (
    MANUFACTURER_ID,
    CommandBuilder,
    Heartbeat,
    describe_action,
    describe_broadcast,
    describe_command,
    parse_broadcast,
    parse_heartbeat,
)

_LOGGER = logging.getLogger(__name__)
# Every received BRMesh broadcast is logged here at INFO level. Off by default;
# enable with logger.set_level: custom_components.fastcon.broadcasts: info
_BROADCAST_LOGGER = logging.getLogger(f"{__package__}.broadcasts")

RECENT_BROADCASTS = 200  # kept for the diagnostics download

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
        self._advertiser = Advertiser(self.adapter)
        self._builder = CommandBuilder()
        # Pending commands keyed by target, so a newer command for the same
        # light replaces one that hasn't been sent yet (e.g. slider drags).
        # key -> (build payload, describe action, target device)
        self._pending: dict[
            str, tuple[Callable[[], bytes], Callable[[], str], FastconDevice | None]
        ] = {}
        self._wakeup = asyncio.Event()
        # Monotonic time of the last heartbeat per DID, and DIDs considered offline
        self._last_heartbeat: dict[str, float] = {}
        self._unavailable: set[str] = set()
        self._last_heartbeat_time: dict[str, str] = {}
        self._heartbeat_intervals: dict[str, deque[float]] = {}
        # Monotonic time of the last automatic bind per DID
        self._last_auto_bind: dict[str, float] = {}
        # Address a device had before the user changed it, to spot failed binds
        self._previous_address: dict[str, int] = {}
        # Binds the user asked for that the light may not have accepted yet.
        # A light only accepts a bind in discovery mode (after a power cycle),
        # so these are sent again as soon as the light announces itself.
        self._pending_bind: set[str] = set()
        # Bind discovered lights automatically; off unless the user turns it on
        self.auto_bind = False
        self.recent_broadcasts: deque[dict] = deque(maxlen=RECENT_BROADCASTS)
        # Sequence numbers of our own recent commands, to recognise relays of them
        self._sent_sequences: deque[int] = deque(maxlen=50)

    async def async_setup(self) -> None:
        """Load stored devices and start listening and sending."""
        stored = await self._store.async_load() or {}
        self.auto_bind = stored.get("auto_bind", False)
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
        self.entry.async_on_unload(
            async_track_time_interval(
                self.hass,
                self._async_check_availability,
                timedelta(seconds=AVAILABILITY_CHECK_INTERVAL),
            )
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
        if payload is None:
            return
        self._record_broadcast(service_info, payload)
        if (beat := parse_heartbeat(payload, self.phone_key)) is not None:
            self._async_on_heartbeat(service_info.address, beat)
            return
        if (found := parse_broadcast(payload)) is None:
            return
        did = found.did.hex().upper()
        if (device := self.devices.get(did)) is None:
            used = {d.mesh_address for d in self.devices.values()}
            # Keep the address the device already has (e.g. from the BRMesh
            # app) if it's free, so nothing else in the mesh has to change.
            address = (
                found.mesh_address
                if found.mesh_address and found.mesh_address not in used
                else self.next_free_address()
            )
            _LOGGER.info(
                "Discovered BRMesh device %s (type %04X), mesh address %d",
                did, found.device_type, address,
            )
            device = FastconDevice(
                did=did,
                device_type=found.device_type,
                key=found.key.hex().upper(),
                mesh_address=address,
            )
            self.async_add_device(device)
        # A discovered light waits for a bind (discovery response) to join
        # the mesh, so answer it with the address Home Assistant manages.
        self._async_auto_bind(device, found.mesh_address)

    @callback
    def _async_auto_bind(self, device: FastconDevice, reported_address: int) -> None:
        now = time.monotonic()
        if device.did in self._pending_bind:
            self._pending_bind.discard(device.did)
            self._last_auto_bind[device.did] = now
            _LOGGER.info(
                "BRMesh %s is in discovery mode; sending its pending bind to mesh address %d",
                device.name, device.mesh_address,
            )
            self.async_bind(device, pending=False)
            return
        last = self._last_auto_bind.get(device.did)
        if last is not None and now - last < AUTO_BIND_COOLDOWN:
            return
        self._last_auto_bind[device.did] = now
        if not self.auto_bind:
            if reported_address and reported_address != device.mesh_address:
                _LOGGER.info(
                    "BRMesh %s reports mesh address %d but Home Assistant uses %d; "
                    "press its Bind button now or turn on auto-bind",
                    device.name, reported_address, device.mesh_address,
                )
            return
        if reported_address and reported_address != device.mesh_address:
            _LOGGER.info(
                "Binding BRMesh %s to mesh address %d (it reported %d)",
                device.name, device.mesh_address, reported_address,
            )
        else:
            _LOGGER.info(
                "Binding BRMesh %s to mesh address %d", device.name, device.mesh_address
            )
        self.async_bind(device, pending=False)

    def _record_broadcast(
        self, service_info: bluetooth.BluetoothServiceInfoBleak, payload: bytes
    ) -> None:
        info = describe_broadcast(payload, self.phone_key)
        beat = parse_heartbeat(payload, self.phone_key)
        mesh = beat.mesh_address if beat else info.get("mesh_address")
        device = next(
            (d for d in self.devices.values() if mesh is not None and d.mesh_address == mesh),
            None,
        )
        own = info["kind"] == "control" and info.get("sequence") in self._sent_sequences
        action = describe_action({**info, "header_mesh": mesh})
        if info["kind"] == "control" and info.get("checksum_ok"):
            action += " (sent by Home Assistant)" if own else " (from another controller)"
        record = {
            "time": dt_util.utcnow().isoformat(),
            "direction": "received",
            "action": action,
            "address": service_info.address,
            "rssi": service_info.rssi,
            **info,
            "mesh_address": mesh,
            "light": device.name if device else None,
            "own_command": own,
            "raw": payload.hex(),
        }
        self.recent_broadcasts.append(record)
        _BROADCAST_LOGGER.info(
            "%s | light=%s mesh=%s rssi=%s seq=%s raw=%s",
            action, record["light"], mesh, service_info.rssi, info.get("sequence"),
            record["raw"],
        )

    def last_heartbeat_time(self, did: str) -> str | None:
        """ISO time of the last heartbeat from a device, if any."""
        return self._last_heartbeat_time.get(did)

    @callback
    def _async_on_heartbeat(self, address: str, beat: Heartbeat) -> None:
        device = next(
            (d for d in self.devices.values() if d.mesh_address == beat.mesh_address),
            None,
        )
        if device is None:
            if stale := next(
                (
                    d
                    for did, old in self._previous_address.items()
                    if old == beat.mesh_address and (d := self.devices.get(did))
                ),
                None,
            ):
                _LOGGER.warning(
                    "BRMesh %s still reports its old mesh address %d instead of %d; "
                    "switch the light off and on so it accepts the pending bind",
                    stale.name, beat.mesh_address, stale.mesh_address,
                )
            else:
                _LOGGER.debug(
                    "Heartbeat from %s for unknown mesh address %d",
                    address, beat.mesh_address,
                )
            return
        self._previous_address.pop(device.did, None)
        self._pending_bind.discard(device.did)
        now = time.monotonic()
        if (last := self._last_heartbeat.get(device.did)) is not None and (
            now - last >= HEARTBEAT_BURST_GAP
        ):
            self._heartbeat_intervals.setdefault(device.did, deque(maxlen=20)).append(
                now - last
            )
            _LOGGER.debug(
                "Heartbeat from %s (mesh %d) via %s, %.0f s after the previous one",
                device.name, beat.mesh_address, address, now - last,
            )
        self._last_heartbeat[device.did] = now
        self._last_heartbeat_time[device.did] = dt_util.utcnow().isoformat()
        if device.did in self._unavailable:
            self._unavailable.discard(device.did)
            _LOGGER.info("BRMesh %s is reachable again", device.name)
            self._async_availability_changed()

    @callback
    def _async_check_availability(self, _now=None) -> None:
        now = time.monotonic()
        changed = False
        for did, last in self._last_heartbeat.items():
            if did in self._unavailable or (timeout := self._heartbeat_timeout(did)) is None:
                continue
            if now - last > timeout:
                self._unavailable.add(did)
                changed = True
                if device := self.devices.get(did):
                    _LOGGER.info(
                        "No heartbeat from BRMesh %s for %.0f s; marking it unavailable",
                        device.name, now - last,
                    )
        if changed:
            self._async_availability_changed()

    def _heartbeat_timeout(self, did: str) -> float | None:
        """Seconds without a heartbeat before a light counts as offline.

        None until enough heartbeats were seen to know the light's interval.
        """
        intervals = self._heartbeat_intervals.get(did)
        if not intervals or len(intervals) < MIN_HEARTBEAT_SAMPLES:
            return None
        return max(UNAVAILABLE_AFTER, MISSED_HEARTBEATS * statistics.median(intervals))

    def heartbeat_interval(self, did: str) -> float | None:
        """Median seconds between heartbeats, if known."""
        intervals = self._heartbeat_intervals.get(did)
        return statistics.median(intervals) if intervals else None

    @callback
    def _async_availability_changed(self) -> None:
        async_dispatcher_send(self.hass, signal_availability(self.entry.entry_id))

    def is_available(self, did: str) -> bool:
        """False only for devices whose heartbeats stopped."""
        return did not in self._unavailable

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
            self._last_heartbeat.pop(did, None)
            self._heartbeat_intervals.pop(did, None)
            self._last_auto_bind.pop(did, None)
            self._pending_bind.discard(did)
            self._previous_address.pop(did, None)
            self._unavailable.discard(did)
            self._async_save()

    @callback
    def async_set_auto_bind(self, enabled: bool) -> None:
        """Turn automatic binding of discovered lights on or off."""
        self.auto_bind = enabled
        self._last_auto_bind.clear()
        self._async_save()

    @callback
    def _async_save(self) -> None:
        self._store.async_delay_save(
            lambda: {
                "devices": [asdict(d) for d in self.devices.values()],
                "auto_bind": self.auto_bind,
            },
            1,
        )

    @callback
    def async_scan(self) -> None:
        """Ask unbound lights to announce themselves."""
        self._queue("scan", self._builder.scan, lambda: "scan request")

    @callback
    def async_bind(self, device: FastconDevice, pending: bool = True) -> None:
        """Give a device its mesh address and the phone key.

        A light only accepts a bind in discovery mode, which it enters after a
        power cycle. The bind is sent now (in case it is), and with `pending`
        it is sent again when the light next announces itself.
        """
        if pending:
            self._pending_bind.add(device.did)
            _LOGGER.info(
                "Bind for BRMesh %s (mesh address %d) sent; if the light doesn't take "
                "it, switch the light off and on and it is bound when it announces itself",
                device.name, device.mesh_address,
            )
        self._queue(
            f"bind:{device.did}",
            lambda: self._builder.bind(
                bytes.fromhex(device.did),
                device.mesh_address,
                self.phone_key,
                bytes.fromhex(device.key),
            ),
            lambda: f"bind to mesh address {device.mesh_address}",
            device,
        )

    @callback
    def async_set_mesh_address(self, device: FastconDevice, address: int) -> None:
        """Give a device a new mesh address and bind it so the light adopts it."""
        if not 1 <= address <= 255:
            raise ServiceValidationError(f"Mesh address {address} is not between 1 and 255")
        if other := next(
            (
                d
                for d in self.devices.values()
                if d.mesh_address == address and d.did != device.did
            ),
            None,
        ):
            raise ServiceValidationError(
                f"Mesh address {address} is already used by BRMesh {other.name}"
            )
        if address != device.mesh_address:
            _LOGGER.info(
                "BRMesh %s: mesh address %d -> %d", device.name, device.mesh_address, address
            )
            self._previous_address[device.did] = device.mesh_address
            device.mesh_address = address
            self._async_save()
            async_dispatcher_send(self.hass, signal_device_updated(self.entry.entry_id))
        self.async_bind(device)

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
            lambda: describe_command(command),
            device,
        )

    def _queue(
        self,
        key: str,
        build: Callable[[], bytes],
        action: Callable[[], str],
        device: FastconDevice | None = None,
    ) -> None:
        self._pending[key] = (build, action, device)
        self._wakeup.set()

    def _record_sent(
        self, action: str, device: FastconDevice | None, payload: bytes, error: str | None
    ) -> None:
        """Log a command we sent; lights don't relay binds and scans, so we never hear them."""
        record = {
            "time": dt_util.utcnow().isoformat(),
            "direction": "sent",
            "action": action,
            "light": device.name if device else None,
            "mesh_address": device.mesh_address if device else None,
            "sequence": self._builder.last_sequence,
            "result": error or "ok",
            "raw": payload.hex(),
        }
        self.recent_broadcasts.append(record)
        _BROADCAST_LOGGER.info(
            "SENT %s | light=%s mesh=%s seq=%s result=%s raw=%s",
            action, record["light"], record["mesh_address"], record["sequence"],
            record["result"], record["raw"],
        )

    async def _async_send_loop(self) -> None:
        while True:
            await self._wakeup.wait()
            self._wakeup.clear()
            while self._pending:
                key = next(iter(self._pending))
                build, action, device = self._pending.pop(key)
                payload = build()
                self._sent_sequences.append(self._builder.last_sequence)
                _LOGGER.debug("Sending %s: %s", key, payload.hex())
                error = None
                try:
                    await self._advertiser.advertise(
                        MANUFACTURER_ID, payload, self.duration
                    )
                except (AdvertiseError, OSError) as err:
                    error = str(err)
                    _LOGGER.error(
                        "Could not advertise on %s (%s): %s", self.adapter, key, err
                    )
                self._record_sent(action(), device, payload, error)
