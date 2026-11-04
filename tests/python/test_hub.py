"""Tests for the hub and lights, with Home Assistant replaced by small stubs.

Run with: python -m unittest discover -s tests/python
"""

import asyncio
from collections import deque
from enum import Enum
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).parents[2]))


class _ColorMode(str, Enum):
    ONOFF = "onoff"
    BRIGHTNESS = "brightness"
    RGB = "rgb"
    WHITE = "white"


class _Entity:
    def async_write_ha_state(self):
        pass


def _stub_modules() -> tuple[MagicMock, type]:
    """Put stubs of Home Assistant and the advertiser into sys.modules."""
    for name in (
        "homeassistant",
        "homeassistant.components",
        "homeassistant.components.bluetooth",
        "homeassistant.config_entries",
        "homeassistant.const",
        "homeassistant.helpers",
        "homeassistant.helpers.device_registry",
        "homeassistant.helpers.entity_registry",
        "homeassistant.helpers.dispatcher",
        "homeassistant.helpers.entity_platform",
        "homeassistant.helpers.event",
        "homeassistant.helpers.storage",
        "homeassistant.util",
    ):
        sys.modules[name] = MagicMock(name=name)

    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = object
    core.callback = lambda func: func
    sys.modules["homeassistant.core"] = core

    exceptions = types.ModuleType("homeassistant.exceptions")
    exceptions.ServiceValidationError = type("ServiceValidationError", (Exception,), {})
    sys.modules["homeassistant.exceptions"] = exceptions

    light = types.ModuleType("homeassistant.components.light")
    light.ATTR_BRIGHTNESS = "brightness"
    light.ATTR_EFFECT = "effect"
    light.ATTR_RGB_COLOR = "rgb_color"
    light.ATTR_WHITE = "white"
    light.EFFECT_OFF = "off"
    light.ColorMode = _ColorMode
    light.LightEntity = _Entity
    light.LightEntityFeature = MagicMock()
    sys.modules["homeassistant.components.light"] = light

    restore = types.ModuleType("homeassistant.helpers.restore_state")
    restore.RestoreEntity = type("RestoreEntity", (), {})
    sys.modules["homeassistant.helpers.restore_state"] = restore

    # The real advertiser needs dbus_fast and a Bluetooth adapter
    store = MagicMock()
    store.async_load = AsyncMock(return_value=None)
    sys.modules["homeassistant.helpers.storage"].Store = MagicMock(return_value=store)
    advertiser = types.ModuleType("custom_components.fastcon.advertiser")
    advertiser_class = type(
        "Advertiser",
        (),
        {"__init__": lambda self, *args: None, "advertise": AsyncMock(), "close": lambda self: None},
    )
    advertiser.Advertiser = advertiser_class
    sys.modules["custom_components.fastcon.advertiser"] = advertiser
    return store, advertiser_class


_STORE, _ADVERTISER = _stub_modules()

from custom_components.fastcon.const import DEFAULT_EFFECTS  # noqa: E402
from custom_components.fastcon.hub import FastconDevice, FastconHub  # noqa: E402
from custom_components.fastcon.light import FastconLight  # noqa: E402
from custom_components.fastcon.protocol import (  # noqa: E402
    LIGHT_RGBCW,
    light_on,
    light_rgb,
)

DID = "AABBCCDDEEFF"


def _device(did: str = DID) -> FastconDevice:
    return FastconDevice(did=did, device_type=LIGHT_RGBCW, key="01020304", mesh_address=5)


def _hub(stored: dict | None = None) -> FastconHub:
    _STORE.reset_mock()
    _STORE.async_load = AsyncMock(return_value=stored)
    entry = MagicMock(entry_id="entry", data={"adapter": "hci0"}, options={})
    # The tests run the send loop themselves
    entry.async_create_background_task = lambda _hass, coro, _name: coro.close()
    hass = MagicMock(data={})
    return FastconHub(hass, entry)


class SendLoopTest(unittest.IsolatedAsyncioTestCase):
    async def _run_until_empty(self, hub: FastconHub) -> None:
        hub.duration = 0
        task = asyncio.create_task(hub._async_send_loop())
        # Long enough for the loop to send everything with no advertising time
        await asyncio.sleep(0.05)
        self.assertFalse(task.done(), "send loop ended by itself")
        task.cancel()

    async def test_unexpected_adapter_error_is_reported_and_loop_goes_on(self):
        hub = _hub()
        device = _device()
        hub._advertiser.advertise = AsyncMock(side_effect=[ValueError("short packet"), None])
        hub.async_send_light(device, light_on(10))
        hub._queue("second", lambda: b"\x01", lambda: "second")
        await self._run_until_empty(hub)
        results = [record["result"] for record in hub.recent_broadcasts]
        self.assertEqual(len(results), 2)
        self.assertIn("short packet", results[0])
        self.assertEqual(results[1], "ok")

    async def test_command_that_cannot_be_built_does_not_stop_later_ones(self):
        hub = _hub()
        hub._advertiser.advertise = AsyncMock()

        def broken() -> bytes:
            raise ValueError("broken")

        hub._queue("broken", broken, lambda: "broken")
        hub._queue("second", lambda: b"\x01", lambda: "second")
        await self._run_until_empty(hub)
        self.assertEqual([r["action"] for r in hub.recent_broadcasts], ["second"])


class AvailabilityTest(unittest.IsolatedAsyncioTestCase):
    async def _setup(self, stored: dict) -> FastconHub:
        hub = _hub(stored)
        await hub.async_setup()
        return hub

    async def test_light_silent_since_start_goes_unavailable_with_stored_interval(self):
        hub = await self._setup(
            {"devices": [vars(_device())], "heartbeat_intervals": {DID: 100}}
        )
        hub._async_check_availability()
        self.assertTrue(hub.is_available(DID))
        hub._started -= 500  # 4 x 100 s, at least 300 s
        hub._async_check_availability()
        self.assertFalse(hub.is_available(DID))

    async def test_light_without_learned_interval_stays_available(self):
        hub = await self._setup({"devices": [vars(_device())]})
        hub._started -= 100000
        hub._async_check_availability()
        self.assertTrue(hub.is_available(DID))

    async def test_interval_of_removed_light_is_ignored(self):
        hub = await self._setup({"devices": [], "heartbeat_intervals": {DID: 100}})
        self.assertEqual(hub._saved_intervals, {})

    async def test_interval_is_stored_once_learned_and_only_when_it_changes(self):
        hub = await self._setup({"devices": [vars(_device())]})
        beats = hub._heartbeat_intervals.setdefault(DID, deque(maxlen=20))
        beats.extend([100, 100])
        hub._async_remember_interval(DID)
        self.assertEqual(hub._saved_intervals, {})
        beats.append(100)
        hub._async_remember_interval(DID)
        self.assertEqual(hub._saved_intervals, {DID: 100})
        self.assertEqual(hub._data_to_save()["heartbeat_intervals"], {DID: 100})
        hub._store.async_delay_save.reset_mock()
        beats.extend([105, 105])
        hub._async_remember_interval(DID)
        hub._store.async_delay_save.assert_not_called()
        beats.extend([300] * 20)
        hub._async_remember_interval(DID)
        self.assertEqual(hub._saved_intervals, {DID: 300})
        hub._store.async_delay_save.assert_called_once()

    async def test_removing_a_light_forgets_its_interval(self):
        hub = await self._setup(
            {"devices": [vars(_device())], "heartbeat_intervals": {DID: 100}}
        )
        hub.async_remove_device(DID)
        self.assertEqual(hub._data_to_save()["heartbeat_intervals"], {})


class EffectTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.hub = _hub()
        self.device = _device()
        self.hub.devices[DID] = self.device
        self.light = FastconLight(self.hub, self.device)
        self.name = DEFAULT_EFFECTS[0]["name"]

    def _pending_keys(self) -> list[str]:
        return list(self.hub._pending)

    async def test_effect_with_brightness_sends_both_in_order(self):
        await self.light.async_turn_on(effect=self.name, brightness=255)
        self.assertEqual(self._pending_keys(), [f"light:{DID}", f"light:brightness:{DID}"])
        self.assertEqual(self.light._attr_effect, self.name)
        self.assertEqual(self.light._attr_brightness, 255)

    async def test_effect_without_brightness_sends_only_the_effect(self):
        await self.light.async_turn_on(effect=self.name)
        self.assertEqual(self._pending_keys(), [f"light:{DID}"])

    async def test_turning_off_drops_the_unsent_brightness(self):
        await self.light.async_turn_on(effect=self.name, brightness=255)
        await self.light.async_turn_off()
        self.assertEqual(self._pending_keys(), [f"light:{DID}"])

    async def test_new_effect_without_brightness_drops_the_unsent_brightness(self):
        await self.light.async_turn_on(effect=self.name, brightness=255)
        await self.light.async_turn_on(effect=DEFAULT_EFFECTS[1]["name"])
        self.assertEqual(self._pending_keys(), [f"light:{DID}"])

    async def test_all_lights_drops_the_unsent_brightness(self):
        await self.light.async_turn_on(effect=self.name, brightness=255)
        self.hub.async_send_all(light_on(10))
        self.assertNotIn(f"light:brightness:{DID}", self._pending_keys())

    async def test_group_drops_the_unsent_brightness(self):
        self.device.group = 1
        self.hub.groups[1] = "Flur"
        await self.light.async_turn_on(effect=self.name, brightness=255)
        self.hub.async_send_group(1, light_on(10))
        self.assertNotIn(f"light:brightness:{DID}", self._pending_keys())

    async def test_effect_off_ends_the_effect_with_a_colour_command(self):
        await self.light.async_turn_on(effect=self.name)
        sent = []
        self.light._send = sent.append
        await self.light.async_turn_on(effect="off")
        self.assertIsNone(self.light._attr_effect)
        self.assertEqual(sent, [light_rgb(255, 255, 255, 127)])

    async def test_plain_on_keeps_the_effect(self):
        await self.light.async_turn_on(effect=self.name)
        sent = []
        self.light._send = sent.append
        await self.light.async_turn_on()
        self.assertEqual(self.light._attr_effect, self.name)
        self.assertEqual(sent, [light_on(127)])


if __name__ == "__main__":
    unittest.main()
