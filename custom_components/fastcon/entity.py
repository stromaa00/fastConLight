"""Shared device info helpers."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN
from .hub import FastconDevice, FastconHub
from .protocol import LIGHT_TYPE_NAMES


def hub_device_info(hub: FastconHub) -> DeviceInfo:
    """Device info for the hub itself."""
    return DeviceInfo(identifiers={(DOMAIN, hub.entry.entry_id)})


def light_device_info(hub: FastconHub, device: FastconDevice) -> DeviceInfo:
    """Device info for one BRMesh device."""
    return DeviceInfo(
        identifiers={(DOMAIN, device.did)},
        name=f"BRMesh {device.name}",
        manufacturer="BRMesh",
        model=LIGHT_TYPE_NAMES.get(device.device_type, f"Type {device.device_type:04X}"),
        serial_number=device.did,
        via_device=(DOMAIN, hub.entry.entry_id),
    )
