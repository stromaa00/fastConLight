"""BRMesh lights."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_RGB_COLOR,
    ATTR_WHITE,
    ColorMode,
    LightEntity,
)
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import FastconConfigEntry
from .const import (
    signal_all_lights,
    signal_availability,
    signal_groups_changed,
    signal_new_device,
)
from .entity import hub_device_info, light_device_info
from .hub import FastconDevice, FastconHub
from .protocol import (
    LIGHT_PWR,
    LIGHT_RGB,
    LIGHT_RGBCW,
    LIGHT_RGBW,
    is_light,
    light_off,
    light_on,
    light_rgb,
    light_white,
)


def _color_modes(device_type: int) -> set[ColorMode]:
    # Colour temperature isn't mapped yet: the CCT command format is unknown,
    # so CCT-style lights get brightness only.
    if device_type == LIGHT_RGB:
        return {ColorMode.RGB}
    if device_type in (LIGHT_RGBW, LIGHT_RGBCW):
        return {ColorMode.RGB, ColorMode.WHITE}
    if device_type == LIGHT_PWR:
        return {ColorMode.ONOFF}
    return {ColorMode.BRIGHTNESS}


def _level(brightness: int) -> int:
    """Map Home Assistant brightness 1-255 to the protocol's 1-127."""
    return max(1, round(brightness * 127 / 255))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FastconConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add lights for known devices and for ones discovered later."""
    hub = entry.runtime_data
    async_add_entities([FastconAllLights(hub)])
    async_add_entities(
        FastconLight(hub, device)
        for device in hub.devices.values()
        if is_light(device.device_type)
    )
    added_groups = set(hub.groups)
    async_add_entities(FastconGroupLight(hub, gid) for gid in hub.groups)

    @callback
    def _async_groups_changed() -> None:
        # New groups get an entity; deleted ones remove their own
        new = set(hub.groups) - added_groups
        added_groups.update(new)
        added_groups.intersection_update(hub.groups)
        if new:
            async_add_entities(FastconGroupLight(hub, gid) for gid in sorted(new))

    entry.async_on_unload(
        async_dispatcher_connect(hass, signal_groups_changed(entry.entry_id), _async_groups_changed)
    )

    @callback
    def _async_new_device(device: FastconDevice) -> None:
        if is_light(device.device_type):
            async_add_entities([FastconLight(hub, device)])

    entry.async_on_unload(
        async_dispatcher_connect(hass, signal_new_device(entry.entry_id), _async_new_device)
    )


class _FastconLightBase(LightEntity, RestoreEntity):
    """Common state and commands. Lights don't report state, so it is assumed."""

    _attr_has_entity_name = True
    _attr_assumed_state = True
    _attr_should_poll = False

    def __init__(self, hub: FastconHub, color_modes: set[ColorMode]) -> None:
        self._hub = hub
        self._attr_supported_color_modes = color_modes
        self._attr_color_mode = next(iter(color_modes))
        if ColorMode.RGB in color_modes:
            self._attr_color_mode = ColorMode.RGB
            self._attr_rgb_color = (255, 255, 255)
        self._attr_is_on = False
        self._attr_brightness = 255

    async def async_added_to_hass(self) -> None:
        """Restore the last assumed state."""
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is None:
            return
        self._attr_is_on = last.state == STATE_ON
        if (brightness := last.attributes.get(ATTR_BRIGHTNESS)) is not None:
            self._attr_brightness = brightness
        if (rgb := last.attributes.get(ATTR_RGB_COLOR)) is not None:
            self._attr_rgb_color = tuple(rgb)
        if (mode := last.attributes.get("color_mode")) in self._attr_supported_color_modes:
            self._attr_color_mode = ColorMode(mode)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on, optionally changing brightness, colour or white."""
        modes = self._attr_supported_color_modes
        if ATTR_WHITE in kwargs and ColorMode.WHITE in modes:
            self._attr_color_mode = ColorMode.WHITE
            self._attr_brightness = kwargs[ATTR_WHITE]
        else:
            if ATTR_BRIGHTNESS in kwargs:
                self._attr_brightness = kwargs[ATTR_BRIGHTNESS]
            if ATTR_RGB_COLOR in kwargs and ColorMode.RGB in modes:
                self._attr_color_mode = ColorMode.RGB
                self._attr_rgb_color = kwargs[ATTR_RGB_COLOR]

        self._send(self._on_command())
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off."""
        self._send(light_off())
        self._attr_is_on = False
        self.async_write_ha_state()

    def _on_command(self) -> bytes:
        level = _level(self._attr_brightness or 255)
        if self._attr_color_mode == ColorMode.WHITE:
            command = light_white(level)
        elif self._attr_color_mode == ColorMode.RGB and any(self._attr_rgb_color):
            command = light_rgb(*self._attr_rgb_color, level)
        elif self._attr_color_mode == ColorMode.ONOFF:
            command = light_on(127)
        else:
            command = light_on(level)
        return command

    def _send(self, command: bytes) -> None:
        raise NotImplementedError


class FastconLight(_FastconLightBase):
    """A single BRMesh light."""

    _attr_name = None

    def __init__(self, hub: FastconHub, device: FastconDevice) -> None:
        super().__init__(hub, _color_modes(device.device_type))
        self._device = device
        self._attr_unique_id = device.did
        self._attr_device_info = light_device_info(hub, device)

    @property
    def available(self) -> bool:
        """Unavailable once the light's heartbeats stop (e.g. switched off at the wall)."""
        return self._hub.is_available(self._device.did)

    async def async_added_to_hass(self) -> None:
        """Also follow availability changes and commands to all lights."""
        await super().async_added_to_hass()
        entry_id = self._hub.entry.entry_id
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, signal_availability(entry_id), self.async_write_ha_state
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, signal_all_lights(entry_id), self._async_follow_all
            )
        )

    @callback
    def _async_follow_all(self, all_lights: _FastconLightBase, group: int | None = None) -> None:
        """Take over the state sent to all lights or this light's group."""
        if group is not None and self._device.group != group:
            return
        self._attr_is_on = all_lights.is_on
        if all_lights.is_on:
            self._attr_brightness = all_lights.brightness
            if all_lights.color_mode in self._attr_supported_color_modes:
                self._attr_color_mode = all_lights.color_mode
            if ColorMode.RGB in self._attr_supported_color_modes:
                self._attr_rgb_color = all_lights.rgb_color
        self.async_write_ha_state()

    def _send(self, command: bytes) -> None:
        self._hub.async_send_light(self._device, command)


class FastconAllLights(_FastconLightBase):
    """Every light of the mesh, switched with one command to mesh address 0."""

    _attr_translation_key = "all_lights"

    def __init__(self, hub: FastconHub) -> None:
        super().__init__(hub, {ColorMode.RGB, ColorMode.WHITE})
        self._attr_unique_id = f"{hub.entry.entry_id}_all_lights"
        self._attr_device_info = hub_device_info(hub)

    def _send(self, command: bytes) -> None:
        self._hub.async_send_all(command)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn all lights on; the single lights take over the state."""
        await super().async_turn_on(**kwargs)
        async_dispatcher_send(self.hass, signal_all_lights(self._hub.entry.entry_id), self)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn all lights off; the single lights take over the state."""
        await super().async_turn_off(**kwargs)
        async_dispatcher_send(self.hass, signal_all_lights(self._hub.entry.entry_id), self)


class FastconGroupLight(_FastconLightBase):
    """A group of lights (set up under Configure -> Groups).

    Switched like the BRMesh app does: one command per device type of its
    lights, addressed to the group id. Its lights take over the state.
    """

    def __init__(self, hub: FastconHub, group_id: int) -> None:
        super().__init__(hub, {ColorMode.RGB, ColorMode.WHITE})
        self._group_id = group_id
        self._attr_unique_id = f"{hub.entry.entry_id}_group_{group_id}"
        self._attr_device_info = hub_device_info(hub)

    @property
    def name(self) -> str:
        """The group's name as set in the options."""
        return self._hub.groups.get(self._group_id, f"Group {self._group_id}")

    @property
    def extra_state_attributes(self) -> dict:
        """Group id and the lights in it."""
        return {
            "group_id": self._group_id,
            "lights": [d.name for d in self._hub.group_members(self._group_id)],
        }

    async def async_added_to_hass(self) -> None:
        """Follow renames and remove itself when the group is deleted."""
        await super().async_added_to_hass()
        # Area picked in the options before this entity existed
        if (area := self._hub.pending_group_areas.pop(self._group_id, None)) is not None:
            er.async_get(self.hass).async_update_entity(self.entity_id, area_id=area)
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, signal_groups_changed(self._hub.entry.entry_id), self._async_groups_changed
            )
        )

    @callback
    def _async_groups_changed(self) -> None:
        if self._group_id in self._hub.groups:
            self.async_write_ha_state()
            return
        registry = er.async_get(self.hass)
        if registry.async_get(self.entity_id):
            registry.async_remove(self.entity_id)
        else:
            self.hass.async_create_task(self.async_remove())

    def _send(self, command: bytes) -> None:
        self._hub.async_send_group(self._group_id, command)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the group on; its lights take over the state."""
        await super().async_turn_on(**kwargs)
        async_dispatcher_send(
            self.hass, signal_all_lights(self._hub.entry.entry_id), self, self._group_id
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the group off; its lights take over the state."""
        await super().async_turn_off(**kwargs)
        async_dispatcher_send(
            self.hass, signal_all_lights(self._hub.entry.entry_id), self, self._group_id
        )
