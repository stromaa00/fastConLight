"""Hub switch: bind discovered lights automatically."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import FastconConfigEntry
from .entity import hub_device_info
from .hub import FastconHub


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FastconConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add the auto-bind switch."""
    async_add_entities([FastconAutoBindSwitch(entry.runtime_data)])


class FastconAutoBindSwitch(SwitchEntity):
    """When on, every light found by a scan is bound right away."""

    _attr_has_entity_name = True
    _attr_translation_key = "auto_bind"
    _attr_icon = "mdi:link-variant-plus"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hub: FastconHub) -> None:
        self._hub = hub
        self._attr_unique_id = f"{hub.entry.entry_id}_auto_bind"
        self._attr_device_info = hub_device_info(hub)

    @property
    def is_on(self) -> bool:
        """Whether discovered lights are bound automatically."""
        return self._hub.auto_bind

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Bind discovered lights automatically."""
        self._hub.async_set_auto_bind(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Only bind when 'Bind all devices' is pressed."""
        self._hub.async_set_auto_bind(False)
        self.async_write_ha_state()
