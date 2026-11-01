"""Shared device info helpers."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN, group_device_id
from .hub import FastconDevice, FastconHub
from .protocol import device_type_name


def hub_device_info(hub: FastconHub) -> DeviceInfo:
    """Device info for the hub itself."""
    return DeviceInfo(identifiers={(DOMAIN, hub.entry.entry_id)})


def light_device_info(hub: FastconHub, device: FastconDevice) -> DeviceInfo:
    """Device info for one BRMesh device."""
    return DeviceInfo(
        identifiers={(DOMAIN, device.did)},
        name=f"BRMesh {device.name}",
        manufacturer="BRMesh",
        model=device_type_name(device.device_type),
        serial_number=device.did,
        via_device=(DOMAIN, light_parent(hub, device)),
    )


def light_parent(hub: FastconHub, device: FastconDevice) -> str:
    """Identifier of the device a light hangs under: its group, else the hub."""
    if device.group in hub.groups:
        return group_device_id(hub.entry.entry_id, device.group)
    return hub.entry.entry_id


def group_device_info(hub: FastconHub, group_id: int) -> DeviceInfo:
    """Device info for a group (the device itself is created by the hub)."""
    return DeviceInfo(identifiers={(DOMAIN, group_device_id(hub.entry.entry_id, group_id))})
