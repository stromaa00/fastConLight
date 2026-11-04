"""BRMesh hub: discovers devices and broadcasts commands."""

from __future__ import annotations

import asyncio
from collections import deque
import copy
from collections.abc import Callable
from contextlib import suppress
from dataclasses import asdict, dataclass, field
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

from .advertiser import Advertiser
from .const import (
    ADVERTISE_SLOT,
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
    INTERVAL_SAVE_CHANGE,
    MIN_HEARTBEAT_SAMPLES,
    MISSED_HEARTBEATS,
    REPORTED_ADDRESS_WINDOW,
    SCAN_ADOPT_WINDOW,
    DEFAULT_EFFECTS,
    UNAVAILABLE_AFTER,
    group_device_id,
    group_device_name,
    signal_effects_changed,
    signal_availability,
    signal_device_updated,
    signal_groups_changed,
    signal_new_device,
)
from .protocol import (
    ALL_LIGHTS_ADDRESS,
    EFFECT_COLORS,
    EFFECT_MODE_FADE,
    EFFECT_MODE_JUMP,
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
# A command counts as fully sent once it is this close to its duration (seconds)
AIR_TIME_TOLERANCE = 0.05


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


@dataclass(eq=False)
class _Command:
    """A command in the send queue, built when it first goes on air."""

    key: str
    build: Callable[[], bytes]
    action: Callable[[], str]
    device: FastconDevice | None
    # DIDs of the lights it reaches: commands sharing one keep their order
    targets: frozenset[str]
    payload: bytes | None = None
    sequence: int | None = None
    aired: float = 0.0  # seconds on air so far
    errors: list[str] = field(default_factory=list)


def _brightness_key(device: FastconDevice) -> str:
    """Send queue key of the brightness command that follows an effect.

    Not the light's own key, which would replace the effect itself. Newer
    commands for the light drop it, or it would switch the light back on.
    """
    return f"light:brightness:{device.did}"


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
        # Commands not fully sent yet, oldest first and keyed by target, so a
        # newer command for the same light replaces its older one (e.g. slider
        # drags), even while that one is on air.
        self._pending: dict[str, _Command] = {}
        self._wakeup = asyncio.Event()
        # Monotonic time of the last heartbeat per DID, and DIDs considered offline
        self._last_heartbeat: dict[str, float] = {}
        # Mesh address -> last heartbeat from it (decoded with our phone key)
        self._address_heartbeat: dict[int, float] = {}
        # DID -> (address the light reported when it announced itself, time),
        # waiting for a heartbeat from that address to confirm it
        self._reported_address: dict[str, tuple[int, float]] = {}
        self._unavailable: set[str] = set()
        self._last_heartbeat_time: dict[str, str] = {}
        self._heartbeat_intervals: dict[str, deque[float]] = {}
        # Learned intervals kept across restarts, so a light that is off when
        # Home Assistant starts still goes unavailable
        self._saved_intervals: dict[str, float] = {}
        self._started = time.monotonic()
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
        # Colour effects offered by every light entity (Configure -> Effects)
        self.effects: list[dict] = copy.deepcopy(DEFAULT_EFFECTS)
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
        if "effects" in stored:
            self.effects = stored["effects"]
        for data in stored.get("devices", []):
            device = FastconDevice(**data)
            self.devices[device.did] = device
        for did, interval in stored.get("heartbeat_intervals", {}).items():
            if did in self.devices:
                self._saved_intervals[did] = interval
                self._heartbeat_intervals[did] = deque(
                    [interval] * MIN_HEARTBEAT_SAMPLES, maxlen=20
                )

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
            # app) if it's free, so nothing else in the mesh has to change,
            # or if a heartbeat shows it really has it in this mesh.
            address = (
                found.mesh_address
                if found.mesh_address
                and (found.mesh_address not in used or self._heartbeat_from(found.mesh_address))
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
        else:
            self._async_check_reported_address(device, found.mesh_address)
        # A discovered light waits for a bind (discovery response) to join
        # the mesh, so answer it with the address Home Assistant manages.
        self._async_auto_bind(device, found.mesh_address)

    def _heartbeat_from(self, mesh_address: int) -> bool:
        """Whether a heartbeat with our phone key came from this address lately."""
        last = self._address_heartbeat.get(mesh_address)
        return last is not None and time.monotonic() - last < REPORTED_ADDRESS_WINDOW

    @callback
    def _async_check_reported_address(self, device: FastconDevice, reported: int) -> None:
        """Take the address a known light reports if it is really in this mesh.

        The announcement isn't encrypted, so the address only counts once a
        heartbeat decoded with this mesh's phone key comes from it; until then
        it is kept as a candidate.
        """
        if not reported or reported == device.mesh_address:
            self._reported_address.pop(device.did, None)
            return
        if self._heartbeat_from(reported):
            self._async_adopt_reported_address(device, reported)
        else:
            self._reported_address[device.did] = (reported, time.monotonic())

    @callback
    def _async_adopt_reported_address(self, device: FastconDevice, reported: int) -> None:
        _LOGGER.info(
            "BRMesh %s reports mesh address %d and a heartbeat with this mesh's key "
            "comes from it; updating it (was %d)",
            device.name, reported, device.mesh_address,
        )
        self._reported_address.pop(device.did, None)
        device.mesh_address = reported
        if device.new_address == reported:
            device.new_address = None
            device.bind_sent = False
        self._async_save()
        async_dispatcher_send(self.hass, signal_device_updated(self.entry.entry_id))

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
        now = time.monotonic()
        self._address_heartbeat[beat.mesh_address] = now
        for did, (reported, when) in list(self._reported_address.items()):
            if now - when > REPORTED_ADDRESS_WINDOW:
                del self._reported_address[did]
            elif reported == beat.mesh_address and (device := self.devices.get(did)):
                self._async_adopt_reported_address(device, reported)
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
                self._async_remember_interval(device.did)
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
            # The light is bound now; make sure it has its group again
            if device.group in self.groups:
                self._async_assign_group(device, device.group)
        if changed:
            self._async_save()
            async_dispatcher_send(self.hass, signal_device_updated(self.entry.entry_id))

    @callback
    def _async_check_availability(self, _now=None) -> None:
        now = time.monotonic()
        changed = False
        for did, device in self.devices.items():
            if did in self._unavailable or (timeout := self._heartbeat_timeout(did)) is None:
                continue
            # No heartbeat since the start: the wait counts from the start
            last = self._last_heartbeat.get(did, self._started)
            if now - last > timeout:
                self._unavailable.add(did)
                changed = True
                _LOGGER.info(
                    "No heartbeat from BRMesh %s for %.0f s; marking it unavailable",
                    device.name, now - last,
                )
        if changed:
            self._async_availability_changed()

    @callback
    def _async_remember_interval(self, did: str) -> None:
        """Store a light's learned heartbeat interval once it is known or has changed."""
        intervals = self._heartbeat_intervals[did]
        if len(intervals) < MIN_HEARTBEAT_SAMPLES:
            return
        interval = statistics.median(intervals)
        saved = self._saved_intervals.get(did)
        if saved is None or abs(interval - saved) > saved * INTERVAL_SAVE_CHANGE:
            self._saved_intervals[did] = round(interval)
            self._async_save()

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
            self._last_heartbeat_time.pop(did, None)
            self._heartbeat_intervals.pop(did, None)
            self._saved_intervals.pop(did, None)
            self._last_auto_bind.pop(did, None)
            self._pending_bind.discard(did)
            self._reported_address.pop(did, None)
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
            "effects": self.effects,
            "heartbeat_intervals": self._saved_intervals,
        }

    def effect(self, name: str) -> dict | None:
        """An effect by name."""
        return next((e for e in self.effects if e["name"] == name), None)

    @callback
    def async_save_effect(self, old_name: str | None, effect: dict) -> None:
        """Add an effect, or replace the one called old_name."""
        index = next(
            (i for i, e in enumerate(self.effects) if e["name"] == old_name), None
        )
        if index is None:
            self.effects.append(effect)
        else:
            self.effects[index] = effect
        self._async_save()
        async_dispatcher_send(self.hass, signal_effects_changed(self.entry.entry_id))

    @callback
    def async_add_builtin_effects(self) -> int:
        """Add the app's predefined effects that are missing (by name)."""
        names = {e["name"] for e in self.effects}
        missing = [copy.deepcopy(e) for e in DEFAULT_EFFECTS if e["name"] not in names]
        if missing:
            self.effects.extend(missing)
            self._async_save()
            async_dispatcher_send(self.hass, signal_effects_changed(self.entry.entry_id))
        return len(missing)

    @callback
    def async_delete_effect(self, name: str) -> None:
        """Delete an effect."""
        self.effects = [e for e in self.effects if e["name"] != name]
        self._async_save()
        async_dispatcher_send(self.hass, signal_effects_changed(self.entry.entry_id))

    @callback
    def async_send_effect(
        self, devices: list[FastconDevice], effect: dict, brightness: bytes | None = None
    ) -> None:
        """Start a colour effect on these lights, one command each.

        Effects go to a single mesh address, so groups and all lights get one
        per light. Replaces unsent commands for those lights. An effect command
        has no brightness; a `brightness` command follows it on each light.
        """
        mode = EFFECT_MODE_FADE if effect.get("mode") == "fade" else EFFECT_MODE_JUMP
        colors = [EFFECT_COLORS[c] for c in effect["colors"] if c in EFFECT_COLORS]
        speed = int(effect.get("speed", 50))
        for device in devices:
            if not is_light(device.device_type):
                continue
            self._queue(
                f"light:{device.did}",
                lambda d=device: self._builder.scene(
                    d.mesh_address, self.phone_key, speed, mode, colors
                ),
                lambda: f"effect {effect['name']}",
                device,
            )
            self._drop(_brightness_key(device))
            if brightness is not None:
                self._queue(
                    _brightness_key(device),
                    lambda d=device: self._builder.light(d.mesh_address, self.phone_key, brightness),
                    lambda: describe_command(brightness),
                    device,
                )

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
        Selected lights get their membership sent again even if Home Assistant
        already has them in the group, e.g. after a bind made them forget it.
        """
        if not 1 <= group_id <= 255:
            raise ServiceValidationError(f"Group id {group_id} is not between 1 and 255")
        self.groups[group_id] = name
        for device in self.devices.values():
            if not is_light(device.device_type):
                continue
            if device.did in dids:
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
        for group_id, group_name in self.groups.items():
            name = group_device_name(group_name)
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
            # bind_address: right after a bind to a new address the light is there
            lambda: self._builder.assign_group(device.bind_address, self.phone_key, device.group),
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
            self._drop(f"light:{device.did}")
            self._drop(_brightness_key(device))
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
                targets=frozenset(d.did for d in members if d.device_type == device_type),
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
        # A bind clears the light's group, so send its group again after it
        if device.group in self.groups:
            self._async_assign_group(device, device.group)

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
        self._drop(_brightness_key(device))
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
            self._drop(key)
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
                targets=frozenset(
                    d.did
                    for d in self.devices.values()
                    if d.device_type == device_type
                ),
            )

    def _queue(
        self,
        key: str,
        build: Callable[[], bytes],
        action: Callable[[], str],
        device: FastconDevice | None = None,
        targets: frozenset[str] = frozenset(),
    ) -> None:
        self._drop(key)
        self._pending[key] = _Command(
            key, build, action, device, frozenset((device.did,)) if device else targets
        )
        self._wakeup.set()

    def _drop(self, key: str) -> None:
        """Forget a command, logging it if it already went on air."""
        command = self._pending.pop(key, None)
        if command is not None and command.payload is not None:
            self._record_sent(command)

    def _ready_commands(self) -> list[_Command]:
        """Commands that may go on air: no older one reaches the same lights."""
        ready = []
        busy: set[str] = set()
        for command in self._pending.values():
            if not command.targets & busy:
                ready.append(command)
            busy |= command.targets
        return ready

    async def _async_broadcast(self, command: _Command, duration: float) -> None:
        """Send from the local adapter and every ESP32 transmitter at once.

        Collects errors on the command; waits `duration` either way so the next
        command doesn't cut this one short on the transmitters, and a failing
        adapter isn't retried at full speed.
        """
        payload = command.payload

        def failed(sender: str, err: Exception) -> None:
            if (error := f"{sender}: {err}") not in command.errors:
                command.errors.append(error)

        async def local() -> None:
            try:
                await self._advertiser.advertise(MANUFACTURER_ID, payload, duration)
            except Exception as err:  # noqa: BLE001 - report any adapter failure
                failed(self.adapter, err)

        async def remote(action: str) -> None:
            try:
                await self.hass.services.async_call(
                    "esphome",
                    action,
                    {"payload": payload.hex(), "duration_ms": int(duration * 1000)},
                    blocking=True,
                )
            except Exception as err:  # noqa: BLE001 - report any transmitter failure
                failed(f"esphome.{action}", err)

        tasks = [remote(action) for action in self.transmitters]
        if self.use_local_adapter or not self.transmitters:
            tasks.append(local())
        tasks.append(asyncio.sleep(duration))
        await asyncio.gather(*tasks)

    def _via(self) -> list[str]:
        via = [f"esphome.{action}" for action in self.transmitters]
        if self.use_local_adapter or not self.transmitters:
            via.insert(0, self.adapter)
        return via

    def _record_sent(self, command: _Command) -> None:
        """Log a command we sent; lights don't relay binds and scans, so we never hear them."""
        device = command.device
        action = command.action()
        error = "; ".join(command.errors) or None
        if error:
            _LOGGER.error("Could not send %s (%s): %s", command.key, action, error)
        record = {
            "time": dt_util.utcnow().isoformat(),
            "direction": "sent",
            "action": action,
            "light": device.name if device else None,
            "mesh_address": device.mesh_address if device else None,
            "sequence": command.sequence,
            "via": self._via(),
            "result": error or "ok",
            "raw": command.payload.hex(),
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
                ready = self._ready_commands()
                # Least air time first: a new command goes next, then they take turns
                command = min(ready, key=lambda c: c.aired)
                try:
                    await self._async_air(command, take_turns=len(ready) > 1)
                except Exception:  # noqa: BLE001 - one bad command must not stop later ones
                    _LOGGER.exception("Could not send %s", command.key)
                    self._pending.pop(command.key, None)
                    continue
                if (
                    self._pending.get(command.key) is command
                    and command.aired >= self.duration - AIR_TIME_TOLERANCE
                ):
                    self._drop(command.key)

    async def _async_air(self, command: _Command, take_turns: bool) -> None:
        """Put a command on air for one turn.

        Alone it gets all its remaining time, cut short after a slot if another
        command comes in. Other meshes can't announce theirs, so with several
        meshes commands always take turns.
        """
        if command.payload is None:
            command.payload = command.build()
            command.sequence = self._builder.last_sequence
            self._sent_sequences.append(command.sequence)
            self._sent_payloads.append(command.payload)
            _LOGGER.debug("Sending %s: %s", command.key, command.payload.hex())
        take_turns = take_turns or len(self._hubs()) > 1
        remaining = max(self.duration - command.aired, 0)
        duration = min(ADVERTISE_SLOT, remaining) if take_turns else remaining
        async with _send_lock(self.hass):
            start = time.monotonic()
            broadcast = asyncio.create_task(self._async_broadcast(command, duration))
            try:
                if take_turns:
                    await broadcast
                else:
                    await self._async_wait_for_new_command(broadcast, start)
            finally:
                if not broadcast.done():
                    broadcast.cancel()
                    with suppress(asyncio.CancelledError):
                        await broadcast
                command.aired += time.monotonic() - start

    async def _async_wait_for_new_command(self, broadcast: asyncio.Task, start: float) -> None:
        """Wait until a broadcast ends, or a new command came and it had a slot."""
        self._wakeup.clear()
        wakeup = asyncio.create_task(self._wakeup.wait())
        try:
            await asyncio.wait({broadcast, wakeup}, return_when=asyncio.FIRST_COMPLETED)
            if not broadcast.done():
                left = ADVERTISE_SLOT - (time.monotonic() - start)
                if left > 0:
                    await asyncio.wait({broadcast}, timeout=left)
        finally:
            wakeup.cancel()
