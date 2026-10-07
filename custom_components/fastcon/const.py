"""Constants for the BRMesh / Fastcon integration."""

DOMAIN = "fastcon"

CONF_ADAPTER = "adapter"
CONF_PHONE_KEY = "phone_key"
CONF_ADVERTISE_DURATION = "advertise_duration"
CONF_ADVERTISE_INTERVAL = "advertise_interval"
CONF_RELAY_SCAN = "relay_scan"
CONF_TRANSMITTERS = "transmitters"
CONF_USE_LOCAL_ADAPTER = "use_local_adapter"
CONF_DEVICE_ID = "device_id"
CONF_DEVICE_TYPE = "device_type"
CONF_DEVICE_KEY = "device_key"
CONF_MESH_ADDRESS = "mesh_address"

DEFAULT_PHONE_KEY = "A1A2A3A4"
# The firmware advertises each command for 3 s; lights usually react much sooner.
DEFAULT_ADVERTISE_DURATION = 3.0
# Time between advertising packets. Connectable advertising (used first)
# allows down to 20 ms; more packets give weak lights more chances.
DEFAULT_ADVERTISE_INTERVAL = 100  # ms
# Send scan requests with the forward bit so lights relay them to lights
# out of the adapter's range. Untested, off by default.
DEFAULT_RELAY_SCAN = False
# ESPHome devices running the brmesh_tx component expose this action;
# Home Assistant names it esphome.<device>_send_brmesh.
TRANSMITTER_ACTION_SUFFIX = "send_brmesh"

# BRMesh lights broadcast from addresses starting with 11:22
DEVICE_ADDRESS_PREFIX = "11:22:"


# A light is marked unavailable after missing several heartbeats. The interval
# is learned per light; until enough heartbeats were seen, it stays available.
UNAVAILABLE_AFTER = 300  # seconds, minimum
MISSED_HEARTBEATS = 4
MIN_HEARTBEAT_SAMPLES = 3
# Lights send heartbeats in bursts (several within a second, after activity).
# Gaps shorter than this belong to one burst and don't count as an interval.
HEARTBEAT_BURST_GAP = 60  # seconds

# A light repeats its discovery broadcast many times a second after a scan;
# bind it at most once per this many seconds.
AUTO_BIND_COOLDOWN = 60  # seconds
AVAILABILITY_CHECK_INTERVAL = 30  # seconds


def signal_availability(entry_id: str) -> str:
    """Dispatcher signal sent when a device's availability changes."""
    return f"{DOMAIN}_availability_{entry_id}"


def signal_device_updated(entry_id: str) -> str:
    """Dispatcher signal sent when a device's settings (e.g. mesh address) change."""
    return f"{DOMAIN}_device_updated_{entry_id}"


def signal_new_device(entry_id: str) -> str:
    """Dispatcher signal sent when a device is added to a hub."""
    return f"{DOMAIN}_new_device_{entry_id}"
