"""Per-light mesh address for the next bind, editable on the device page."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
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
    """Add a mesh address entity for every light, now and when discovered."""
    hub = entry.runtime_data
    async_add_entities(
        FastconMeshAddress(hub, device)
        for device in hub.devices.values()
        if is_light(device.device_type)
    )

    @callback
    def _async_new_device(device: FastconDevice) -> None:
        if is_light(device.device_type):
            async_add_entities([FastconMeshAddress(hub, device)])

    entry.async_on_unload(
        async_dispatcher_connect(hass, signal_new_device(entry.entry_id), _async_new_device)
    )


class FastconMeshAddress(NumberEntity):
    """Mesh address the light gets at its next bind.

    Changing it sends nothing; the Bind button applies it. The address in use
    is shown read-only by the bound mesh address sensor.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "mesh_address"
    _attr_icon = "mdi:identifier"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 1
    _attr_native_max_value = 255
    _attr_native_step = 1

    def __init__(self, hub: FastconHub, device: FastconDevice) -> None:
        self._hub = hub
        self._device = device
        self._attr_unique_id = f"{device.did}_mesh_address"
        self._attr_device_info = light_device_info(hub, device)

    @property
    def native_value(self) -> int:
        """The chosen new address, or the current one if none is chosen."""
        if self._device.new_address is not None:
            return self._device.new_address
        return self._device.mesh_address

    async def async_added_to_hass(self) -> None:
        """Follow changes made elsewhere (e.g. options flow)."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_device_updated(self._hub.entry.entry_id),
                self.async_write_ha_state,
            )
        )

    async def async_set_native_value(self, value: float) -> None:
        """Remember the address for the next bind."""
        self._hub.async_set_new_address(self._device, int(value))
        self.async_write_ha_state()
