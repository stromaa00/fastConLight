"""ESPHome custom component for Fastcon BLE mesh lighting control."""
import esphome.codegen as cg
import esphome.config_validation as cv
from esphome import automation
from esphome.components import light
from esphome.const import (
    CONF_ID,
    CONF_OUTPUT_ID,
)

DEPENDENCIES = ["esp32"]
CODEOWNERS = ["@stromaa00"]
AUTO_LOAD = ["light"]

# Component namespace
fastcon_ns = cg.esphome_ns.namespace("fastcon")
FastconComponent = fastcon_ns.class_("FastconComponent", cg.Component)
FastconLight = fastcon_ns.class_("FastconLight", light.LightOutput)

# Configuration constants
CONF_PHONE_KEY = "phone_key"
CONF_DEVICE_ID = "device_id"
CONF_DEVICE_TYPE = "device_type"
CONF_DEVICE_KEY = "device_key"
CONF_MESH_ADDRESS = "mesh_address"
CONF_FASTCON_ID = "fastcon_id"
CONF_AUTO_DISCOVER = "auto_discover"

# Component configuration schema
CONFIG_SCHEMA = cv.Schema({
    cv.GenerateID(): cv.declare_id(FastconComponent),
    cv.Optional(CONF_PHONE_KEY, default="A1A2A3A4"): cv.string,
    cv.Optional(CONF_AUTO_DISCOVER, default=True): cv.boolean,
}).extend(cv.COMPONENT_SCHEMA)


async def to_code(config):
    """Generate code for the Fastcon component."""
    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)
    
    # Set phone key
    phone_key = config[CONF_PHONE_KEY]
    if len(phone_key) == 8:  # Hex string format (4 bytes = 8 hex chars)
        key_bytes = [int(phone_key[i:i+2], 16) for i in range(0, 8, 2)]
        cg.add(var.set_phone_key(key_bytes))
    
    # Set auto discover
    cg.add(var.set_auto_discover(config[CONF_AUTO_DISCOVER]))


# Actions
ScanAction = fastcon_ns.class_("ScanAction", automation.Action)
BindAllAction = fastcon_ns.class_("BindAllAction", automation.Action)

@automation.register_action(
    "fastcon.scan",
    ScanAction,
    cv.Schema({
        cv.GenerateID(): cv.use_id(FastconComponent),
    })
)
async def fastcon_scan_to_code(config, action_id, template_arg, args):
    """Code generation for scan action."""
    parent = await cg.get_variable(config[CONF_ID])
    return cg.new_Pvariable(action_id, template_arg, parent)


@automation.register_action(
    "fastcon.bind_all",
    BindAllAction,
    cv.Schema({
        cv.GenerateID(): cv.use_id(FastconComponent),
    })
)
async def fastcon_bind_all_to_code(config, action_id, template_arg, args):
    """Code generation for bind all action."""
    parent = await cg.get_variable(config[CONF_ID])
    return cg.new_Pvariable(action_id, template_arg, parent)
