"""BRMesh / Fastcon lights through Home Assistant's own Bluetooth adapter."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN
from .hub import FastconHub

PLATFORMS = [Platform.BUTTON, Platform.LIGHT, Platform.SWITCH]

type FastconConfigEntry = ConfigEntry[FastconHub]


async def async_setup_entry(hass: HomeAssistant, entry: FastconConfigEntry) -> bool:
    """Set up the BRMesh hub."""
    hub = FastconHub(hass, entry)
    await hub.async_setup()
    entry.runtime_data = hub

    # Register the hub device first so lights can point at it with via_device.
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="fastConLight",
        model="BRMesh gateway (BlueZ)",
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: FastconConfigEntry) -> bool:
    """Unload the hub."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        entry.runtime_data.close()
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: FastconConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: FastconConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Allow deleting a light from the device page."""
    hub = entry.runtime_data
    for domain, identifier in device_entry.identifiers:
        if domain == DOMAIN and identifier in hub.devices:
            hub.async_remove_device(identifier)
            return True
    return False
