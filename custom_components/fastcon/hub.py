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
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
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
    CONF_ADVERTISE_INTERVAL,
    CONF_PHONE_KEY,
    CONF_RELAY_SCAN,
    CONF_TRANSMITTERS,
    CONF_USE_LOCAL_ADAPTER,
    DEFAULT_ADVERTISE_DURATION,
    DEFAULT_ADVERTISE_INTERVAL,
    DEFAULT_PHONE_KEY,
    DEFAULT_RELAY_SCAN,
    DEVICE_ADDRESS_PREFIX,
    DOMAIN,
    HEARTBEAT_BURST_GAP,
    MIN_HEARTBEAT_SAMPLES,
    MISSED_HEARTBEATS,
    SCAN_ADOPT_WINDOW,
    UNAVAILABLE_AFTER,
    group_device_id,
    signal_availability,
    signal_device_updated,
    signal_groups_changed,
    signal_new_device,
)
from .protocol import (
    ALL_LIGHTS_ADDRESS,
    DEFAULT_ENCRYPT_KEY,
    MANUFACTURER_ID,
    CommandBuilder,
    Heartbeat,
    describe_action,
    describe_broadcast,
    describe_command,
    device_type_name,
    is_light,
    parse_broadcast,
    parse_heartbeat,
    unwrap_rf_frame,
)

_LOGGER = logging.getLogger(__name__)
# Every received BRMesh broadcast is logged here at INFO level. Off by default;
# enable with logger.set_level: custom_components.fastcon.broadcasts: info
_BROADCAST_LOGGER = logging.getLogger(f"{__package__}.broadcasts")

RECENT_BROADCASTS = 1000  # kept for the diagnostics download
# All lights broadcast from this address
LIGHT_BROADCAST_ADDRESS = "11:22:33:44:55:66"

STORAGE_VERSION = 1


def _send_lock(hass: HomeAssistant) -> asyncio.Lock:
    """One lock for all hubs: meshes may share an adapter (and its advertising
    instance) and ESP32 transmitters, so only one command is on air at a time."""
    return hass.data.setdefault(f"{DOMAIN}_send_lock", asyncio.Lock())


@dataclass
class FastconDevice:
    """A BRMesh device known to the hub."""

    did: str  # 12 hex chars
    device_type: int
    key: str  # 8 hex chars
    mesh_address: int
    # Address chosen for the next bind; the light keeps mesh_address until then
    new_address: int | None = None
    # A bind to new_address was sent; mesh_address changes once a heartbeat
    # from new_address confirms the light took it
    bind_sent: bool = False
    # Group the light is in (0 = none); a light is in at most one group
    group: int = 0

    @property
    def bind_address(self) -> int:
        """Address a bind gives the light: the new one once Bind was pressed."""
        if self.bind_sent and self.new_address is not None:
            return self.new_address
        return self.mesh_address

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
        self.interval_ms = int(
            config.get(CONF_ADVERTISE_INTERVAL, DEFAULT_ADVERTISE_INTERVAL)
        )
        self.relay_scan: bool = config.get(CONF_RELAY_SCAN, DEFAULT_RELAY_SCAN)
        # ESPHome actions (e.g. "brmesh_transmitter_send_brmesh") that broadcast
        # our packets from ESP32s near lights the adapter can't reach
        self.transmitters: list[str] = [
            action.strip().removeprefix("esphome.")
            for action in config.get(CONF_TRANSMITTERS, [])
            if action.strip()
        ]
        self.use_local_adapter: bool = config.get(CONF_USE_LOCAL_ADAPTER, True)
        self._advertiser = Advertiser(self.adapter, self.interval_ms)
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
        # Binds the user asked for that the light may not have accepted yet.
        # A light only accepts a bind in discovery mode (after a power cycle),
        # so these are sent again as soon as the light announces itself.
        self._pending_bind: set[str] = set()
        # Bind discovered lights automatically; off unless the user turns it on
        self.auto_bind = False
        # Group id -> name; members are the devices whose group is that id
        self.groups: dict[int, str] = {}
        # Monotonic time of this mesh's last scan, to adopt the lights it finds
        self.last_scan: float | None = None
        self.recent_broadcasts: deque[dict] = deque(maxlen=RECENT_BROADCASTS)
        # BRMesh broadcasts received since setup, to tell "nothing received"
        # apart from "received but not understood" in the diagnostics
        self.received_count = 0
        self.setup_time = dt_util.utcnow().isoformat()
        # Sequence numbers of our own recent commands, to recognise relays of them
        self._sent_sequences: deque[int] = deque(maxlen=50)
        # Our own recent packets, to recognise when one of our senders (the
        # adapter, an ESP32 transmitter) hears another one sending them
        self._sent_payloads: deque[bytes] = deque(maxlen=50)

    async def async_setup(self) -> None:
        """Load stored devices and start listening and sending."""
        stored = await self._store.async_load() or {}
        self.auto_bind = stored.get("auto_bind", False)
        self.groups = {int(gid): name for gid, name in stored.get("groups", {}).items()}
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
        # Everything else the lights broadcast (other manufacturer data, names,
        # service data), so the log shows all that comes back from them.
        self.entry.async_on_unload(
            bluetooth.async_register_callback(
                self.hass,
                self._async_on_light_address,
                bluetooth.BluetoothCallbackMatcher(
                    address=LIGHT_BROADCAST_ADDRESS, connectable=False
                ),
                bluetooth.BluetoothScanningMode.ACTIVE,
            )
        )
        # Heartbeat hunting: any advertisement from any address that looks like
        # a type 3 BRMesh frame. Only does work at debug level.
        self.entry.async_on_unload(
            bluetooth.async_register_callback(
                self.hass,
                self._async_on_any_advertisement,
                bluetooth.BluetoothCallbackMatcher(connectable=False),
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
        payload = service_info.manufacturer_data.get(MANUFACTURER_ID)
        if payload is None:
            return
        # Log every BRMesh broadcast, including ones sent directly by a phone
        # app or remote from their own address, but only act on the lights'.
        self.received_count += 1
        self._record_broadcast(service_info, payload)
        # Heartbeats count from any address, like the BRMesh app does; only
        # our own commands can't decode as one (they are type 5).
        if (beat := parse_heartbeat(payload, self.phone_key)) is not None:
            self._async_on_heartbeat(service_info.address, beat)
            return
        if not service_info.address.upper().startswith(DEVICE_ADDRESS_PREFIX):
            return
        if (found := parse_broadcast(payload)) is None:
            return
        did = found.did.hex().upper()
        if (device := self.devices.get(did)) is None:
            # Discovery broadcasts don't say which mesh a light belongs to, so
            # only one hub adopts a new light (see _adopts_new_lights).
            if self.other_hub_with(did) is not None or not self._adopts_new_lights():
                return
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
                device.name, device.bind_address,
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

    @callback
    def _async_on_light_address(
        self,
        service_info: bluetooth.BluetoothServiceInfoBleak,
        change: bluetooth.BluetoothChange,
    ) -> None:
        """Log advertisement content from the lights other than BRMesh frames."""
        other = {
            f"0x{company:04X}": data.hex()
            for company, data in service_info.manufacturer_data.items()
            if company != MANUFACTURER_ID
        }
        if not (other or service_info.service_data or service_info.name not in ("", None, service_info.address)):
            return
        record = {
            "time": dt_util.utcnow().isoformat(),
            "direction": "received",
            "action": "other advertisement content from the lights",
            "address": service_info.address,
            "rssi": service_info.rssi,
            "name": service_info.name,
            "manufacturer_data": other,
            "service_data": {k: v.hex() for k, v in service_info.service_data.items()},
            "service_uuids": list(service_info.service_uuids),
        }
        self.recent_broadcasts.append(record)
        _BROADCAST_LOGGER.info("other advertisement content from %s: %s", service_info.address, record)

    @callback
    def _async_on_any_advertisement(
        self,
        service_info: bluetooth.BluetoothServiceInfoBleak,
        change: bluetooth.BluetoothChange,
    ) -> None:
        """Log anything that looks like a heartbeat, whatever its source.

        Frames with manufacturer ID 0xFFF0 are already logged by
        _record_broadcast; this covers other company IDs, service data and
        any address. Enabled with logger level debug on the broadcasts logger.
        """
        if not _BROADCAST_LOGGER.isEnabledFor(logging.DEBUG):
            return
        candidates = [
            (f"manufacturer 0x{company:04X}", data)
            for company, data in service_info.manufacturer_data.items()
            if company != MANUFACTURER_ID
        ]
        candidates += [
            (f"service data {uuid}", data)
            for uuid, data in service_info.service_data.items()
        ]
        for source, data in candidates:
            for offset in (0, 2):  # the company ID may be part of the data
                body = unwrap_rf_frame(data[offset:]) or data[offset:]
                if len(body) < 16:
                    continue
                header = bytes(b ^ DEFAULT_ENCRYPT_KEY[i] for i, b in enumerate(body[:4]))
                if (header[0] >> 4) & 7 != 3:
                    continue
                beat = parse_heartbeat(data[offset:], self.phone_key)
                _BROADCAST_LOGGER.debug(
                    "possible heartbeat from %s (%s, offset %d) rssi=%s decoded=%s raw=%s",
                    service_info.address, source, offset, service_info.rssi,
                    beat, data.hex(),
                )
                break

    def _record_broadcast(
        self, service_info: bluetooth.BluetoothServiceInfoBleak, payload: bytes
    ) -> None:
        info = describe_broadcast(payload, self.phone_key)
        beat = parse_heartbeat(payload, self.phone_key)
        mesh = beat.mesh_address if beat else info.get("mesh_address")
        # Several lights may share a mesh address
        lights = [
            d.name for d in self.devices.values() if mesh is not None and d.mesh_address == mesh
        ]
        own = info["kind"] == "control" and info.get("sequence") in self._sent_sequences
        # Lights always send from 11:22:..., so our exact packet from any other
        # address is one of our own senders heard by another, not a light.
        echo = (
            not service_info.address.upper().startswith(DEVICE_ADDRESS_PREFIX)
            and payload in self._sent_payloads
        )
        action = describe_action({**info, "header_mesh": mesh})
        if echo:
            action = f"echo of our own broadcast, not from a light: {action}"
        elif info["kind"] == "control" and info.get("checksum_ok"):
            action += " (sent by Home Assistant)" if own else " (from another controller)"
        record = {
            "time": dt_util.utcnow().isoformat(),
            "direction": "echo" if echo else "received",
            "action": action,
            "address": service_info.address,
            "rssi": service_info.rssi,
            **info,
            "mesh_address": mesh,
            "light": ", ".join(lights) or None,
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
        self._async_confirm_binds(beat.mesh_address)
        # Heartbeats carry no DID, so lights sharing a mesh address all count it
        devices = [d for d in self.devices.values() if d.mesh_address == beat.mesh_address]
        if not devices:
            _LOGGER.debug(
                "Heartbeat from %s for unknown mesh address %d", address, beat.mesh_address
            )
            return
        now = time.monotonic()
        changed = False
        for device in devices:
            if device.bind_sent:
                # Still on its old address: the bind to the new one isn't taken yet
                _LOGGER.debug(
                    "BRMesh %s still reports mesh address %d, bind to %s not confirmed yet",
                    device.name, beat.mesh_address, device.new_address,
                )
            else:
                self._pending_bind.discard(device.did)
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
                changed = True
        if changed:
            self._async_availability_changed()

    @callback
    def _async_confirm_binds(self, mesh_address: int) -> None:
        """Adopt a new mesh address once a heartbeat from it shows the bind worked.

        Heartbeats carry no DID, so a heartbeat from the new address confirms
        every light with a bind sent to it.
        """
        changed = False
        for device in self.devices.values():
            if not device.bind_sent or device.new_address != mesh_address:
                continue
            _LOGGER.info(
                "BRMesh %s confirmed mesh address %d (was %d)",
                device.name, mesh_address, device.mesh_address,
            )
            device.mesh_address = mesh_address
            device.new_address = None
            device.bind_sent = False
            self._pending_bind.discard(device.did)
            changed = True
        if changed:
            self._async_save()
            async_dispatcher_send(self.hass, signal_device_updated(self.entry.entry_id))

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

    def _hubs(self) -> list[FastconHub]:
        """All running hubs (one per mesh), in config entry order."""
        hubs: list[FastconHub] = []
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.entry_id == self.entry.entry_id:
                hubs.append(self)
            elif entry.state is ConfigEntryState.LOADED:
                hubs.append(entry.runtime_data)
        return hubs

    def other_hub_with(self, did: str) -> FastconHub | None:
        """Another mesh's hub that already knows this device, if any."""
        return next(
            (hub for hub in self._hubs() if hub is not self and did in hub.devices),
            None,
        )

    def _adopts_new_lights(self) -> bool:
        """Whether a newly discovered light goes to this hub.

        With several meshes, the hub that scanned most recently takes it
        (within SCAN_ADOPT_WINDOW); otherwise the first hub with auto-bind on,
        or the first hub if none has auto-bind on.
        """
        hubs = self._hubs()
        now = time.monotonic()
        scanning = [
            hub
            for hub in hubs
            if hub.last_scan is not None and now - hub.last_scan < SCAN_ADOPT_WINDOW
        ]
        if scanning:
            return max(scanning, key=lambda hub: hub.last_scan) is self
        return next((hub for hub in hubs if hub.auto_bind), hubs[0]) is self

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
            self._unavailable.discard(did)
            self._async_save()

    @callback
    def async_set_auto_bind(self, enabled: bool) -> None:
        """Turn automatic binding of discovered lights on or off."""
        self.auto_bind = enabled
        self._last_auto_bind.clear()
        self._async_save()

    def _data_to_save(self) -> dict:
        return {
            "devices": [asdict(d) for d in self.devices.values()],
            "auto_bind": self.auto_bind,
            "groups": {str(gid): name for gid, name in self.groups.items()},
        }

    @callback
    def _async_save(self) -> None:
        self._store.async_delay_save(self._data_to_save, 1)

    def group_members(self, group_id: int) -> list[FastconDevice]:
        """Lights in a group."""
        return [
            d for d in self.devices.values() if d.group == group_id and is_light(d.device_type)
        ]

    def next_free_group(self) -> int:
        """Lowest group id (1-255) not in use."""
        return next((gid for gid in range(1, 256) if gid not in self.groups), 255)

    @callback
    def async_save_group(self, group_id: int, name: str, dids: list[str]) -> None:
        """Create or change a group and send the new memberships to the lights.

        A light is in at most one group, so adding it here moves it out of
        any other group; lights no longer selected leave the group (group 0).
        """
        if not 1 <= group_id <= 255:
            raise ServiceValidationError(f"Group id {group_id} is not between 1 and 255")
        self.groups[group_id] = name
        for device in self.devices.values():
            if not is_light(device.device_type):
                continue
            if device.did in dids and device.group != group_id:
                self._async_assign_group(device, group_id)
            elif device.did not in dids and device.group == group_id:
                self._async_assign_group(device, 0)
        self._async_save()
        self.async_sync_group_devices()
        async_dispatcher_send(self.hass, signal_groups_changed(self.entry.entry_id))

    @callback
    def async_delete_group(self, group_id: int) -> None:
        """Delete a group and take its lights out of it."""
        for device in self.group_members(group_id):
            self._async_assign_group(device, 0)
        self.groups.pop(group_id, None)
        self._async_save()
        self.async_sync_group_devices()
        async_dispatcher_send(self.hass, signal_groups_changed(self.entry.entry_id))

    @callback
    def async_sync_group_devices(self) -> None:
        """Give each group its own device under the hub, and hang lights under it.

        So the hub's connected devices list the groups and the lights in no
        group, and each group device lists its lights.
        """
        registry = dr.async_get(self.hass)
        entry_id = self.entry.entry_id
        hub_device = registry.async_get_device(identifiers={(DOMAIN, entry_id)})
        group_devices = {}
        for group_id, name in self.groups.items():
            device = registry.async_get_or_create(
                config_entry_id=entry_id,
                identifiers={(DOMAIN, group_device_id(entry_id, group_id))},
                name=name,
                manufacturer="BRMesh",
                model="Light group",
                via_device=(DOMAIN, entry_id),
            )
            if device.name != name:
                device = registry.async_update_device(device.id, name=name) or device
            group_devices[group_id] = device
        for light in self.devices.values():
            device = registry.async_get_device(identifiers={(DOMAIN, light.did)})
            parent = group_devices.get(light.group, hub_device)
            if device and parent and device.via_device_id != parent.id:
                registry.async_update_device(device.id, via_device_id=parent.id)
        wanted = {group_device_id(entry_id, gid) for gid in self.groups}
        prefix = group_device_id(entry_id, 0)[:-1]
        for device in dr.async_entries_for_config_entry(registry, entry_id):
            if any(
                domain == DOMAIN and ident.startswith(prefix) and ident not in wanted
                for domain, ident in device.identifiers
            ):
                registry.async_remove_device(device.id)

    @callback
    def _async_assign_group(self, device: FastconDevice, group_id: int) -> None:
        _LOGGER.info(
            "BRMesh %s (mesh address %d): group %d -> %d",
            device.name, device.mesh_address, device.group, group_id,
        )
        device.group = group_id
        self._queue(
            f"group:{device.did}",
            lambda: self._builder.assign_group(device.mesh_address, self.phone_key, device.group),
            lambda: (
                f"put into group {device.group}" if device.group else "remove from its group"
            ),
            device,
        )

    @callback
    def async_send_group(self, group_id: int, command: bytes) -> None:
        """Queue a light command for a group: one per device type of its lights.

        Unsent commands for its single lights are dropped, as these override them.
        """
        members = self.group_members(group_id)
        for device in members:
            self._pending.pop(f"light:{device.did}", None)
        for device_type in sorted({d.device_type for d in members}):
            self._queue(
                f"light:group:{group_id}:{device_type}",
                lambda t=device_type: self._builder.light_by_type(
                    t, self.phone_key, command, group_id
                ),
                lambda t=device_type: (
                    f"group {self.groups.get(group_id, group_id)} "
                    f"({device_type_name(t)}): {describe_command(command)}"
                ),
            )

    @callback
    def async_scan(self) -> None:
        """Ask unbound lights to announce themselves."""
        self.last_scan = time.monotonic()
        self._queue(
            "scan",
            lambda: self._builder.scan(forward=self.relay_scan),
            lambda: "scan request (relayed by lights)" if self.relay_scan else "scan request",
        )

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
                device.name, device.bind_address,
            )
        self._queue(
            f"bind:{device.did}",
            lambda: self._builder.bind(
                bytes.fromhex(device.did),
                device.bind_address,
                self.phone_key,
                bytes.fromhex(device.key),
            ),
            lambda: f"bind to mesh address {device.bind_address}",
            device,
        )

    @callback
    def async_set_new_address(self, device: FastconDevice, address: int) -> None:
        """Choose the mesh address the light gets when its Bind button is pressed.

        Nothing is sent yet. Several lights may share an address; they then
        all follow commands to it.
        """
        if not 1 <= address <= 255:
            raise ServiceValidationError(f"Mesh address {address} is not between 1 and 255")
        new_address = None if address == device.mesh_address else address
        if new_address != device.new_address:
            device.new_address = new_address
            # A bind sent for another address no longer counts; press Bind again
            device.bind_sent = False
            self._async_save()
            async_dispatcher_send(self.hass, signal_device_updated(self.entry.entry_id))

    @callback
    def async_bind_new_address(self, device: FastconDevice) -> None:
        """Bind the light, to its new mesh address if one was chosen.

        The light keeps its current address (commands still go there) until a
        heartbeat from the new address confirms the bind.
        """
        if device.new_address is not None and not device.bind_sent:
            _LOGGER.info(
                "BRMesh %s: binding to mesh address %d (now %d); adopted once its "
                "heartbeat comes from the new address",
                device.name, device.new_address, device.mesh_address,
            )
            device.bind_sent = True
            self._async_save()
            async_dispatcher_send(self.hass, signal_device_updated(self.entry.entry_id))
        self.async_bind(device)

    @callback
    def async_bind_all(self) -> None:
        """Bind every known device, to its new mesh address where one was chosen."""
        for device in self.devices.values():
            self.async_bind_new_address(device)

    @callback
    def async_send_light(self, device: FastconDevice, command: bytes) -> None:
        """Queue a light command, replacing any unsent one for the same light."""
        self._queue(
            f"light:{device.did}",
            lambda: self._builder.light(device.mesh_address, self.phone_key, command),
            lambda: describe_command(command),
            device,
        )

    @callback
    def async_send_all(self, command: bytes) -> None:
        """Queue a light command for every light in the mesh at once.

        Like the BRMesh app: one command per device type in the mesh (control
        type 3); with no known lights, one to mesh address 0. Unsent commands
        for single lights are dropped, as these override them.
        """
        for key in [key for key in self._pending if key.startswith("light:")]:
            del self._pending[key]
        types = sorted({d.device_type for d in self.devices.values() if is_light(d.device_type)})
        if not types:
            self._queue(
                "light:all",
                lambda: self._builder.light(ALL_LIGHTS_ADDRESS, self.phone_key, command),
                lambda: f"all lights: {describe_command(command)}",
            )
        for device_type in types:
            self._queue(
                f"light:all:{device_type}",
                lambda t=device_type: self._builder.light_by_type(t, self.phone_key, command),
                lambda t=device_type: (
                    f"all {device_type_name(t)} lights: {describe_command(command)}"
                ),
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

    async def _async_broadcast(self, key: str, payload: bytes) -> list[str]:
        """Send from the local adapter and every ESP32 transmitter at once.

        Returns the errors; waits the advertising duration either way so the
        next command doesn't cut this one short on the transmitters.
        """
        errors: list[str] = []

        async def local() -> None:
            try:
                await self._advertiser.advertise(MANUFACTURER_ID, payload, self.duration)
            except (AdvertiseError, OSError) as err:
                errors.append(f"{self.adapter}: {err}")
                _LOGGER.error("Could not advertise on %s (%s): %s", self.adapter, key, err)

        async def remote(action: str) -> None:
            try:
                await self.hass.services.async_call(
                    "esphome",
                    action,
                    {"payload": payload.hex(), "duration_ms": int(self.duration * 1000)},
                    blocking=True,
                )
            except Exception as err:  # noqa: BLE001 - report any transmitter failure
                errors.append(f"esphome.{action}: {err}")
                _LOGGER.error("Could not send through esphome.%s (%s): %s", action, key, err)

        tasks = [remote(action) for action in self.transmitters]
        if self.use_local_adapter or not self.transmitters:
            tasks.append(local())
        else:
            tasks.append(asyncio.sleep(self.duration))
        await asyncio.gather(*tasks)
        return errors

    def _via(self) -> list[str]:
        via = [f"esphome.{action}" for action in self.transmitters]
        if self.use_local_adapter or not self.transmitters:
            via.insert(0, self.adapter)
        return via

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
            "via": self._via(),
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
                self._sent_payloads.append(payload)
                _LOGGER.debug("Sending %s: %s", key, payload.hex())
                async with _send_lock(self.hass):
                    errors = await self._async_broadcast(key, payload)
                self._record_sent(
                    action(), device, payload, "; ".join(errors) if errors else None
                )
