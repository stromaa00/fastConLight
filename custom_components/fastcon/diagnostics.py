"""Diagnostics download: devices, heartbeat state and recent broadcasts."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import FastconConfigEntry
from .const import CONF_PHONE_KEY

TO_REDACT = {CONF_PHONE_KEY, "key"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: FastconConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for the hub."""
    hub = entry.runtime_data
    return {
        "config": async_redact_data({**entry.data, **entry.options}, TO_REDACT),
        "devices": [
            {
                **async_redact_data(asdict(device), TO_REDACT),
                "name": device.name,
                "available": hub.is_available(device.did),
                "last_heartbeat": hub.last_heartbeat_time(device.did),
            }
            for device in hub.devices.values()
        ],
        "recent_broadcasts": list(hub.recent_broadcasts),
    }
