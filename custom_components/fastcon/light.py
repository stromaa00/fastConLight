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
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import FastconConfigEntry
from .const import signal_availability, signal_new_device
from .entity import light_device_info
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
    async_add_entities(
        FastconLight(hub, device)
        for device in hub.devices.values()
        if is_light(device.device_type)
    )

    @callback
    def _async_new_device(device: FastconDevice) -> None:
        if is_light(device.device_type):
            async_add_entities([FastconLight(hub, device)])

    entry.async_on_unload(
        async_dispatcher_connect(hass, signal_new_device(entry.entry_id), _async_new_device)
    )


class FastconLight(LightEntity, RestoreEntity):
    """A BRMesh light. Lights don't report state, so it is assumed."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_assumed_state = True
    _attr_should_poll = False

    def __init__(self, hub: FastconHub, device: FastconDevice) -> None:
        self._hub = hub
        self._device = device
        self._attr_unique_id = device.did
        self._attr_device_info = light_device_info(hub, device)
        self._attr_supported_color_modes = _color_modes(device.device_type)
        self._attr_color_mode = next(iter(self._attr_supported_color_modes))
        if ColorMode.RGB in self._attr_supported_color_modes:
            self._attr_color_mode = ColorMode.RGB
            self._attr_rgb_color = (255, 255, 255)
        self._attr_is_on = False
        self._attr_brightness = 255

    @property
    def available(self) -> bool:
        """Unavailable once the light's heartbeats stop (e.g. switched off at the wall)."""
        return self._hub.is_available(self._device.did)

    async def async_added_to_hass(self) -> None:
        """Restore the last assumed state and follow availability changes."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_availability(self._hub.entry.entry_id),
                self.async_write_ha_state,
            )
        )
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

        level = _level(self._attr_brightness or 255)
        if self._attr_color_mode == ColorMode.WHITE:
            command = light_white(level)
        elif self._attr_color_mode == ColorMode.RGB and any(self._attr_rgb_color):
            command = light_rgb(*self._attr_rgb_color, level)
        elif self._attr_color_mode == ColorMode.ONOFF:
            command = light_on(127)
        else:
            command = light_on(level)

        self._hub.async_send_light(self._device, command)
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off."""
        self._hub.async_send_light(self._device, light_off())
        self._attr_is_on = False
        self.async_write_ha_state()
