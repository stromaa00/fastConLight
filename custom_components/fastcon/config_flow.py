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
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    selector,
)

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
    group_device_id,
    TRANSMITTER_ACTION_SUFFIX,
)
from .hub import FastconDevice
from .protocol import EFFECT_COLORS, device_type_name, is_light

CONF_GROUP_ID = "group_id"
CONF_LIGHTS = "lights"
CONF_DELETE = "delete"
CONF_BACK = "back"
# Menu entry leading back to the main menu (HA flows have no back button)
BACK_TO_MENU = {"init": "← Back"}
CONF_AREA = "area"
# Colour slots in the effect form; matches the protocol's 9 colours
EFFECT_SLOTS = 9
NO_COLOR = "none"

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
            step_id="init",
            menu_options=["overview", "settings", "groups", "effects", "add_device"],
        )

    def _light_name(self, device) -> str:
        """The light's name in Home Assistant (as renamed there), else BRMesh <id>."""
        entry = dr.async_get(self.hass).async_get_device(identifiers={(DOMAIN, device.did)})
        name = (entry and (entry.name_by_user or entry.name)) or f"BRMesh {device.name}"
        return name if name.endswith(device.name) else f"{name} ({device.name})"

    async def async_step_overview(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Table of all lights with their mesh address and group."""
        if self.config_entry.state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="not_loaded")
        if user_input is not None:
            return self.async_create_entry(data=dict(self.config_entry.options))
        hub = self.config_entry.runtime_data
        rows = []
        for device in sorted(
            hub.devices.values(), key=lambda d: (d.mesh_address, d.group, d.did)
        ):
            name = self._light_name(device)
            address = str(device.mesh_address)
            if device.new_address is not None and device.new_address != device.mesh_address:
                address += f" → {device.new_address}" + (
                    " (waiting for heartbeat)" if device.bind_sent else " (not bound)"
                )
            group = (
                f"{hub.groups.get(device.group, '?')} ({device.group})"
                if device.group
                else "–"
            )
            rows.append(
                f"| {name} | {address} | {group} | "
                f"{device_type_name(device.device_type)} | {device.did} |"
            )
        table = (
            "| Light | Mesh address | Group | Type | DID |\n|---|---|---|---|---|\n"
            + "\n".join(rows)
            if rows
            else "No lights yet."
        )
        return self.async_show_form(
            step_id="overview",
            data_schema=vol.Schema({}),
            description_placeholders={"table": table, "count": str(len(rows))},
        )

    async def async_step_effects(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Menu: a new effect, or one entry per effect to change it."""
        if self.config_entry.state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="not_loaded")
        hub = self.config_entry.runtime_data
        return self.async_show_menu(
            step_id="effects",
            menu_options={
                **BACK_TO_MENU,
                "effect_new": "+ New effect",
                "effect_builtin": "+ Add the BRMesh app's built-in effects",
                **{
                    f"effect_{i}": f"{e['name']} ({e['mode']}, speed {e['speed']}: "
                    f"{', '.join(e['colors'])})"
                    for i, e in enumerate(hub.effects)
                },
            },
        )

    async def async_step_effect_builtin(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add the app's predefined effects that are missing; keeps your own."""
        self.config_entry.runtime_data.async_add_builtin_effects()
        return self.async_create_entry(data=dict(self.config_entry.options))

    async def async_step_effect_new(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Start a new effect."""
        self._effect_index = None
        return await self.async_step_effect_edit()

    async def async_step_effect_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Name, mode, speed and colours of an effect."""
        hub = self.config_entry.runtime_data
        index = getattr(self, "_effect_index", None)
        current = hub.effects[index] if index is not None else None
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input.get(CONF_BACK):
                return await self.async_step_effects()
            if current and user_input.get(CONF_DELETE):
                hub.async_delete_effect(current["name"])
                return self.async_create_entry(data=dict(self.config_entry.options))
            name = user_input[CONF_NAME].strip()
            colors = [
                user_input[f"color_{i}"]
                for i in range(1, EFFECT_SLOTS + 1)
                if user_input.get(f"color_{i}", NO_COLOR) != NO_COLOR
            ]
            if not name:
                errors[CONF_NAME] = "name_required"
            elif any(
                e["name"] == name for e in hub.effects if current is None or e is not current
            ):
                errors[CONF_NAME] = "effect_name_in_use"
            elif not colors:
                errors["base"] = "colors_required"
            else:
                hub.async_save_effect(
                    current["name"] if current else None,
                    {
                        "name": name,
                        "mode": user_input["mode"],
                        "speed": int(user_input["speed"]),
                        "colors": colors,
                    },
                )
                return self.async_create_entry(data=dict(self.config_entry.options))

        values = user_input or current or {"name": "", "mode": "fade", "speed": 50, "colors": []}
        colors = values.get("colors") or [
            values.get(f"color_{i}", NO_COLOR) for i in range(1, EFFECT_SLOTS + 1)
        ]
        color_selector = selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[NO_COLOR, *EFFECT_COLORS],
                mode=selector.SelectSelectorMode.DROPDOWN,
                translation_key="effect_color",
            )
        )
        schema: dict = {
            vol.Required(CONF_NAME, default=values.get(CONF_NAME, "")): str,
            vol.Required("mode", default=values.get("mode", "fade")): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=["fade", "jump"],
                    mode=selector.SelectSelectorMode.LIST,
                    translation_key="effect_mode",
                )
            ),
            vol.Required("speed", default=values.get("speed", 50)): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1, max=100, step=1, mode=selector.NumberSelectorMode.SLIDER
                )
            ),
        }
        for i in range(1, EFFECT_SLOTS + 1):
            default = colors[i - 1] if i <= len(colors) else NO_COLOR
            schema[vol.Optional(f"color_{i}", default=default)] = color_selector
        if current is not None:
            schema[vol.Optional(CONF_DELETE, default=False)] = bool
        schema[vol.Optional(CONF_BACK, default=False)] = bool
        return self.async_show_form(
            step_id="effect_edit", data_schema=vol.Schema(schema), errors=errors
        )

    async def async_step_groups(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Menu: a new group, or one entry per group to change it."""
        if self.config_entry.state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="not_loaded")
        hub = self.config_entry.runtime_data
        if not hub.groups:
            return await self.async_step_group_new()
        return self.async_show_menu(
            step_id="groups",
            menu_options={
                **BACK_TO_MENU,
                "group_new": "+ New group",
                **{
                    f"group_{gid}": f"{name} (id {gid}, "
                    f"{len(hub.group_members(gid))} lights)"
                    for gid, name in sorted(hub.groups.items())
                },
            },
        )

    async def async_step_group_new(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Start a new group."""
        self._group_id = None
        return await self.async_step_group_edit()

    def __getattr__(self, name: str) -> Any:
        """Menu entries group_<id> and effect_<index> open that item's form."""
        for prefix, attr, target in (
            ("async_step_group_", "_group_id", "async_step_group_edit"),
            ("async_step_effect_", "_effect_index", "async_step_effect_edit"),
        ):
            if name.startswith(prefix) and name[len(prefix) :].isdigit():
                value = int(name[len(prefix) :])

                async def _step(
                    user_input: dict[str, Any] | None = None,
                    attr: str = attr,
                    value: int = value,
                    target: str = target,
                ) -> ConfigFlowResult:
                    setattr(self, attr, value)
                    return await getattr(self, target)()

                return _step
        raise AttributeError(name)

    async def async_step_group_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Name, id and lights of a group; saving sends the memberships."""
        hub = self.config_entry.runtime_data
        group_id = getattr(self, "_group_id", None)
        errors: dict[str, str] = {}
        placeholders = {"group_id": str(group_id or ""), "lights": ""}
        if user_input is not None:
            if user_input.get(CONF_BACK):
                if hub.groups:
                    return await self.async_step_groups()
                return await self.async_step_init()
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
                area = user_input.get(CONF_AREA) or None
                selected = user_input.get(CONF_LIGHTS, [])
                in_area = self._lights_in_area(area, selected)
                # Warn once: area control would switch these lights one by one too
                if in_area and getattr(self, "_area_warned", None) != (area, tuple(selected)):
                    self._area_warned = (area, tuple(selected))
                    errors[CONF_AREA] = "lights_in_area"
                    placeholders["lights"] = ", ".join(in_area)
                else:
                    hub.async_save_group(new_id, name, selected)
                    self._async_set_group_area(new_id, area)
                    return self.async_create_entry(data=dict(self.config_entry.options))

        lights = sorted(
            (d for d in hub.devices.values() if is_light(d.device_type)),
            key=lambda d: d.mesh_address,
        )
        light_options = [
            selector.SelectOptionDict(
                value=d.did,
                label=f"{self._light_name(d)} (address {d.mesh_address})"
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
            schema[vol.Required(CONF_GROUP_ID, default=hub.next_free_group())] = (
                selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=255, step=1, mode=selector.NumberSelectorMode.BOX
                    )
                )
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
        area = (
            user_input.get(CONF_AREA)
            if user_input is not None
            else self._group_area(group_id) if group_id is not None else None
        )
        schema[
            vol.Optional(CONF_AREA, description={"suggested_value": area})
        ] = selector.AreaSelector()
        if group_id is not None:
            schema[vol.Optional(CONF_DELETE, default=False)] = bool
        schema[vol.Optional(CONF_BACK, default=False)] = bool
        return self.async_show_form(
            step_id="group_edit",
            data_schema=vol.Schema(schema),
            errors=errors,
            description_placeholders=placeholders,
        )

    def _group_device(self, group_id: int) -> dr.DeviceEntry | None:
        return dr.async_get(self.hass).async_get_device(
            identifiers={(DOMAIN, group_device_id(self.config_entry.entry_id, group_id))}
        )

    def _group_entity(self, group_id: int) -> er.RegistryEntry | None:
        entities = er.async_get(self.hass)
        entity_id = entities.async_get_entity_id(
            "light", DOMAIN, f"{self.config_entry.entry_id}_group_{group_id}"
        )
        return entities.async_get(entity_id) if entity_id else None

    def _group_area(self, group_id: int) -> str | None:
        """The group's area: its light's own area if set, else its device's."""
        entity = self._group_entity(group_id)
        if entity and entity.area_id:
            return entity.area_id
        device = self._group_device(group_id)
        return device.area_id if device else None

    def _async_set_group_area(self, group_id: int, area: str | None) -> None:
        """Put the group's device into an area; its light follows the device."""
        if (device := self._group_device(group_id)) is not None:
            dr.async_get(self.hass).async_update_device(device.id, area_id=area)
        if (entity := self._group_entity(group_id)) is not None and entity.area_id:
            er.async_get(self.hass).async_update_entity(entity.entity_id, area_id=None)

    def _lights_in_area(self, area: str | None, dids: list[str]) -> list[str]:
        """Selected lights that are in the area themselves (entity or device)."""
        if not area:
            return []
        entities = er.async_get(self.hass)
        devices = dr.async_get(self.hass)
        hub = self.config_entry.runtime_data
        found = []
        for did in dids:
            entity_id = entities.async_get_entity_id("light", DOMAIN, did)
            entity = entities.async_get(entity_id) if entity_id else None
            device = devices.async_get_device(identifiers={(DOMAIN, did)})
            light_area = (entity.area_id if entity and entity.area_id else None) or (
                device.area_id if device else None
            )
            if light_area == area and did in hub.devices:
                found.append(f"BRMesh {hub.devices[did].name}")
        return found

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
