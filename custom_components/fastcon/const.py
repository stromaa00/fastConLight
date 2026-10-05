"""Constants for the BRMesh / Fastcon integration."""

DOMAIN = "fastcon"

CONF_ADAPTER = "adapter"
CONF_PHONE_KEY = "phone_key"
CONF_ADVERTISE_DURATION = "advertise_duration"
CONF_DEVICE_ID = "device_id"
CONF_DEVICE_TYPE = "device_type"
CONF_DEVICE_KEY = "device_key"
CONF_MESH_ADDRESS = "mesh_address"

DEFAULT_PHONE_KEY = "A1A2A3A4"
# The firmware advertises each command for 3 s; lights usually react much sooner.
DEFAULT_ADVERTISE_DURATION = 3.0

# BRMesh lights broadcast from addresses starting with 11:22
DEVICE_ADDRESS_PREFIX = "11:22:"


def signal_new_device(entry_id: str) -> str:
    """Dispatcher signal sent when a device is added to a hub."""
    return f"{DOMAIN}_new_device_{entry_id}"
