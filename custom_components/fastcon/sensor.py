"""Per-light mesh address in use, read-only on the device page."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import FastconConfigEntry
from .const import signal_device_updated, signal_new_device
from .entity import light_device_info
from .hub import FastconDevice, FastconHub
from .protocol import is_light


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FastconConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add a bound mesh address sensor for every light, now and when discovered."""
    hub = entry.runtime_data
    async_add_entities(
        FastconBoundAddress(hub, device)
        for device in hub.devices.values()
        if is_light(device.device_type)
    )

    @callback
    def _async_new_device(device: FastconDevice) -> None:
        if is_light(device.device_type):
            async_add_entities([FastconBoundAddress(hub, device)])

    entry.async_on_unload(
        async_dispatcher_connect(hass, signal_new_device(entry.entry_id), _async_new_device)
    )


class FastconBoundAddress(SensorEntity):
    """Mesh address commands go to.

    Changes only through Mesh address plus Bind, once a heartbeat from the
    new address confirms the light took it.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "bound_mesh_address"
    _attr_icon = "mdi:identifier"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = False

    def __init__(self, hub: FastconHub, device: FastconDevice) -> None:
        self._hub = hub
        self._device = device
        self._attr_unique_id = f"{device.did}_bound_mesh_address"
        self._attr_device_info = light_device_info(hub, device)

    @property
    def native_value(self) -> int:
        """Mesh address the light was last bound to."""
        return self._device.mesh_address

    @property
    def extra_state_attributes(self) -> dict[str, int | bool | None]:
        """A chosen new address, and whether its bind awaits a heartbeat."""
        return {
            "pending_address": self._device.new_address,
            "waiting_for_heartbeat": self._device.bind_sent,
        }

    async def async_added_to_hass(self) -> None:
        """Follow address changes."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_device_updated(self._hub.entry.entry_id),
                self.async_write_ha_state,
            )
        )
