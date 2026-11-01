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
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
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
    CONF_TRANSMITTERS,
    CONF_USE_LOCAL_ADAPTER,
    DEFAULT_ADVERTISE_DURATION,
    DEFAULT_ADVERTISE_INTERVAL,
    DEFAULT_PHONE_KEY,
    DEFAULT_RELAY_SCAN,
    DEVICE_ADDRESS_PREFIX,
    DOMAIN,
    TRANSMITTER_ACTION_SUFFIX,
)
from .hub import FastconDevice
from .protocol import is_light

CONF_GROUP = "group"
CONF_GROUP_ID = "group_id"
CONF_LIGHTS = "lights"
CONF_DELETE = "delete"
NEW_GROUP = "new"

_LOGGER = logging.getLogger(__name__)


def _is_hex(value: str, length: int) -> bool:
    return re.fullmatch(f"[0-9A-Fa-f]{{{length}}}", value) is not None


def _phone_key_in_use(
    hass: HomeAssistant, phone_key: str, own_entry_id: str | None = None
) -> bool:
    """Whether another mesh (config entry) already uses this phone key."""
    return any(
        entry.entry_id != own_entry_id
        and {**entry.data, **entry.options}.get(CONF_PHONE_KEY, "").upper()
        == phone_key.upper()
        for entry in hass.config_entries.async_entries(DOMAIN)
    )


class FastconConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up a BRMesh hub (one mesh, i.e. one phone key) on a local adapter."""

    VERSION = 1

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """A BRMesh light was seen; offer to set up the first hub."""
        if not discovery_info.address.upper().startswith(DEVICE_ADDRESS_PREFIX):
            return self.async_abort(reason="not_supported")
        # Further meshes are added by hand; a light's broadcast can't tell them apart.
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        return await self.async_step_user()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick the name, adapter and phone key."""
        errors: dict[str, str] = {}
        if user_input is not None:
            phone_key = user_input[CONF_PHONE_KEY].strip()
            if not _is_hex(phone_key, 8):
                errors[CONF_PHONE_KEY] = "invalid_key"
            elif _phone_key_in_use(self.hass, phone_key):
                errors[CONF_PHONE_KEY] = "key_in_use"
            else:
                name = user_input.get(CONF_NAME, "").strip() or "BRMesh"
                return self.async_create_entry(
                    title=f"{name} ({user_input[CONF_ADAPTER]})",
                    data={
                        CONF_ADAPTER: user_input[CONF_ADAPTER],
                        CONF_PHONE_KEY: phone_key.upper(),
                    },
                )

        try:
            adapters = await async_list_adapters()
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Could not list BlueZ adapters")
            return self.async_abort(reason="bluez_unavailable")
        if not adapters:
            return self.async_abort(reason="no_adapters")

        first = not self._async_current_entries()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default="BRMesh"): str,
                    vol.Required(CONF_ADAPTER, default=adapters[0]): vol.In(adapters),
                    # The default key only for the first mesh; the next needs its own.
                    vol.Required(
                        CONF_PHONE_KEY, default=DEFAULT_PHONE_KEY if first else ""
                    ): str,
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
        return self.async_show_menu(
            step_id="init", menu_options=["settings", "groups", "add_device"]
        )

    async def async_step_groups(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick a group to change, or start a new one."""
        if self.config_entry.state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="not_loaded")
        hub = self.config_entry.runtime_data
        if user_input is not None or not hub.groups:
            choice = (user_input or {}).get(CONF_GROUP, NEW_GROUP)
            self._group_id = None if choice == NEW_GROUP else int(choice)
            return await self.async_step_group_edit()
        options = [selector.SelectOptionDict(value=NEW_GROUP, label="+")] + [
            selector.SelectOptionDict(value=str(gid), label=f"{name} ({gid})")
            for gid, name in sorted(hub.groups.items())
        ]
        return self.async_show_form(
            step_id="groups",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_GROUP, default=NEW_GROUP): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=options,
                            mode=selector.SelectSelectorMode.LIST,
                            translation_key="group_choice",
                        )
                    )
                }
            ),
        )

    async def async_step_group_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Name, id and lights of a group; saving sends the memberships."""
        hub = self.config_entry.runtime_data
        group_id = getattr(self, "_group_id", None)
        errors: dict[str, str] = {}
        if user_input is not None:
            if group_id is not None and user_input.get(CONF_DELETE):
                hub.async_delete_group(group_id)
                return self.async_create_entry(data=dict(self.config_entry.options))
            name = user_input[CONF_NAME].strip()
            new_id = group_id if group_id is not None else int(user_input[CONF_GROUP_ID])
            if not name:
                errors[CONF_NAME] = "name_required"
            elif group_id is None and new_id in hub.groups:
                errors[CONF_GROUP_ID] = "group_id_in_use"
            else:
                hub.async_save_group(new_id, name, user_input.get(CONF_LIGHTS, []))
                return self.async_create_entry(data=dict(self.config_entry.options))

        lights = sorted(
            (d for d in hub.devices.values() if is_light(d.device_type)),
            key=lambda d: d.mesh_address,
        )
        light_options = [
            selector.SelectOptionDict(
                value=d.did,
                label=f"BRMesh {d.name} (address {d.mesh_address})"
                + (
                    f" - now in {hub.groups.get(d.group, d.group)}"
                    if d.group and d.group != group_id
                    else ""
                ),
            )
            for d in lights
        ]
        schema: dict = {
            vol.Required(
                CONF_NAME, default=hub.groups.get(group_id, "") if group_id else ""
            ): str,
        }
        if group_id is None:
            schema[vol.Required(CONF_GROUP_ID, default=hub.next_free_group())] = vol.All(
                vol.Coerce(int), vol.Range(min=1, max=255)
            )
        schema[
            vol.Optional(
                CONF_LIGHTS,
                default=[d.did for d in lights if group_id and d.group == group_id],
            )
        ] = selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=light_options,
                multiple=True,
                mode=selector.SelectSelectorMode.LIST,
            )
        )
        if group_id is not None:
            schema[vol.Optional(CONF_DELETE, default=False)] = bool
        return self.async_show_form(
            step_id="group_edit",
            data_schema=vol.Schema(schema),
            errors=errors,
            description_placeholders={"group_id": str(group_id or "")},
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Phone key and advertising duration."""
        config = {**self.config_entry.data, **self.config_entry.options}
        errors: dict[str, str] = {}
        transmitter_options = sorted(
            set(config.get(CONF_TRANSMITTERS, []))
            | {
                action
                for action in self.hass.services.async_services_for_domain("esphome")
                if action.endswith(TRANSMITTER_ACTION_SUFFIX) or "brmesh" in action
            }
        )
        if user_input is not None:
            phone_key = user_input[CONF_PHONE_KEY].strip()
            if not _is_hex(phone_key, 8):
                errors[CONF_PHONE_KEY] = "invalid_key"
            elif _phone_key_in_use(self.hass, phone_key, self.config_entry.entry_id):
                errors[CONF_PHONE_KEY] = "key_in_use"
            else:
                return self.async_create_entry(
                    data={**user_input, CONF_PHONE_KEY: phone_key.upper()}
                )

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
                    vol.Optional(
                        CONF_TRANSMITTERS,
                        default=config.get(CONF_TRANSMITTERS, []),
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=transmitter_options,
                            multiple=True,
                            custom_value=True,
                            # Dropdown allows typing an action that isn't listed
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Required(
                        CONF_USE_LOCAL_ADAPTER,
                        default=config.get(CONF_USE_LOCAL_ADAPTER, True),
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
            elif hub.other_hub_with(did.upper()) is not None:
                errors[CONF_DEVICE_ID] = "device_in_other_mesh"
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
