"""Config flow for BRMesh / Fastcon."""

from __future__ import annotations

import logging
import re
from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

from .advertiser import async_list_adapters
from .const import (
    CONF_ADAPTER,
    CONF_ADVERTISE_DURATION,
    CONF_ADVERTISE_INTERVAL,
    CONF_DEVICE_ID,
    CONF_DEVICE_KEY,
    CONF_DEVICE_TYPE,
    CONF_MESH_ADDRESS,
    CONF_PHONE_KEY,
    CONF_RELAY_SCAN,
    DEFAULT_ADVERTISE_DURATION,
    DEFAULT_ADVERTISE_INTERVAL,
    DEFAULT_PHONE_KEY,
    DEFAULT_RELAY_SCAN,
    DEVICE_ADDRESS_PREFIX,
    DOMAIN,
)
from .hub import FastconDevice

_LOGGER = logging.getLogger(__name__)


def _is_hex(value: str, length: int) -> bool:
    return re.fullmatch(f"[0-9A-Fa-f]{{{length}}}", value) is not None


class FastconConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up a BRMesh hub on a local Bluetooth adapter."""

    VERSION = 1

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """A BRMesh light was seen; offer to set up the hub."""
        if not discovery_info.address.upper().startswith(DEVICE_ADDRESS_PREFIX):
            return self.async_abort(reason="not_supported")
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        return await self.async_step_user()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick the adapter and phone key."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        errors: dict[str, str] = {}
        if user_input is not None:
            phone_key = user_input[CONF_PHONE_KEY].strip()
            if _is_hex(phone_key, 8):
                return self.async_create_entry(
                    title=f"BRMesh ({user_input[CONF_ADAPTER]})",
                    data={
                        CONF_ADAPTER: user_input[CONF_ADAPTER],
                        CONF_PHONE_KEY: phone_key.upper(),
                    },
                )
            errors[CONF_PHONE_KEY] = "invalid_key"

        try:
            adapters = await async_list_adapters()
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Could not list BlueZ adapters")
            return self.async_abort(reason="bluez_unavailable")
        if not adapters:
            return self.async_abort(reason="no_adapters")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADAPTER, default=adapters[0]): vol.In(adapters),
                    vol.Required(CONF_PHONE_KEY, default=DEFAULT_PHONE_KEY): str,
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Options: settings and manually adding a light."""
        return FastconOptionsFlow()


class FastconOptionsFlow(OptionsFlow):
    """Change settings or add a light by hand (e.g. from an ESPHome YAML)."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the menu."""
        return self.async_show_menu(step_id="init", menu_options=["settings", "add_device"])

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Phone key and advertising duration."""
        config = {**self.config_entry.data, **self.config_entry.options}
        errors: dict[str, str] = {}
        if user_input is not None:
            phone_key = user_input[CONF_PHONE_KEY].strip()
            if _is_hex(phone_key, 8):
                return self.async_create_entry(
                    data={**user_input, CONF_PHONE_KEY: phone_key.upper()}
                )
            errors[CONF_PHONE_KEY] = "invalid_key"

        return self.async_show_form(
            step_id="settings",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_PHONE_KEY, default=config.get(CONF_PHONE_KEY, DEFAULT_PHONE_KEY)
                    ): str,
                    vol.Required(
                        CONF_ADVERTISE_DURATION,
                        default=config.get(
                            CONF_ADVERTISE_DURATION, DEFAULT_ADVERTISE_DURATION
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0.3, max=10, step=0.1, unit_of_measurement="s",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Required(
                        CONF_ADVERTISE_INTERVAL,
                        default=config.get(
                            CONF_ADVERTISE_INTERVAL, DEFAULT_ADVERTISE_INTERVAL
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=20, max=1000, step=10, unit_of_measurement="ms",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Required(
                        CONF_RELAY_SCAN,
                        default=config.get(CONF_RELAY_SCAN, DEFAULT_RELAY_SCAN),
                    ): bool,
                }
            ),
            errors=errors,
        )

    async def async_step_add_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add a light whose ID, type and key you already know."""
        if self.config_entry.state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="not_loaded")
        hub = self.config_entry.runtime_data

        errors: dict[str, str] = {}
        if user_input is not None:
            did = user_input[CONF_DEVICE_ID].strip()
            dtype = user_input[CONF_DEVICE_TYPE].strip()
            key = user_input[CONF_DEVICE_KEY].strip()
            if not _is_hex(did, 12):
                errors[CONF_DEVICE_ID] = "invalid_device_id"
            if not _is_hex(dtype, 4):
                errors[CONF_DEVICE_TYPE] = "invalid_device_type"
            if not _is_hex(key, 8):
                errors[CONF_DEVICE_KEY] = "invalid_key"
            if not errors:
                hub.async_add_device(
                    FastconDevice(
                        did=did.upper(),
                        device_type=int(dtype, 16),
                        key=key.upper(),
                        mesh_address=int(user_input[CONF_MESH_ADDRESS]),
                    )
                )
                return self.async_create_entry(data=dict(self.config_entry.options))

        return self.async_show_form(
            step_id="add_device",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DEVICE_ID): str,
                    vol.Required(CONF_DEVICE_TYPE, default="A8A1"): str,
                    vol.Required(CONF_DEVICE_KEY): str,
                    vol.Required(
                        CONF_MESH_ADDRESS, default=hub.next_free_address()
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=255)),
                }
            ),
            errors=errors,
        )
