"""Scan and bind buttons on the hub."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import FastconConfigEntry
from .const import signal_new_device
from .entity import hub_device_info, light_device_info
from .hub import FastconDevice, FastconHub
from .protocol import is_light


@dataclass(frozen=True, kw_only=True)
class FastconButtonDescription(ButtonEntityDescription):
    """Describes a hub button."""

    press_fn: Callable[[FastconHub], None]


BUTTONS = (
    FastconButtonDescription(
        key="scan",
        translation_key="scan",
        icon="mdi:magnify-scan",
        entity_category=EntityCategory.CONFIG,
        press_fn=lambda hub: hub.async_scan(),
    ),
    FastconButtonDescription(
        key="bind_all",
        translation_key="bind_all",
        icon="mdi:link-variant",
        entity_category=EntityCategory.CONFIG,
        press_fn=lambda hub: hub.async_bind_all(),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FastconConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add the hub buttons and a bind button per light."""
    hub = entry.runtime_data
    async_add_entities(FastconButton(hub, desc) for desc in BUTTONS)
    async_add_entities(
        FastconBindButton(hub, device)
        for device in hub.devices.values()
        if is_light(device.device_type)
    )

    @callback
    def _async_new_device(device: FastconDevice) -> None:
        if is_light(device.device_type):
            async_add_entities([FastconBindButton(hub, device)])

    entry.async_on_unload(
        async_dispatcher_connect(hass, signal_new_device(entry.entry_id), _async_new_device)
    )


class FastconButton(ButtonEntity):
    """Button that triggers a hub action."""

    _attr_has_entity_name = True
    entity_description: FastconButtonDescription

    def __init__(self, hub: FastconHub, description: FastconButtonDescription) -> None:
        self._hub = hub
        self.entity_description = description
        self._attr_unique_id = f"{hub.entry.entry_id}_{description.key}"
        self._attr_device_info = hub_device_info(hub)

    async def async_press(self) -> None:
        """Run the action."""
        self.entity_description.press_fn(self._hub)


class FastconBindButton(ButtonEntity):
    """Bind just this light (send it its mesh address and the phone key)."""

    _attr_has_entity_name = True
    _attr_translation_key = "bind"
    _attr_icon = "mdi:link-variant"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hub: FastconHub, device: FastconDevice) -> None:
        self._hub = hub
        self._device = device
        self._attr_unique_id = f"{device.did}_bind"
        self._attr_device_info = light_device_info(hub, device)

    async def async_press(self) -> None:
        """Bind the light."""
        self._hub.async_bind(self._device)
