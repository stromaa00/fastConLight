"""Scan and bind buttons on the hub."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import FastconConfigEntry
from .entity import hub_device_info
from .hub import FastconHub


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
    """Add the hub buttons."""
    async_add_entities(FastconButton(entry.runtime_data, desc) for desc in BUTTONS)


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
