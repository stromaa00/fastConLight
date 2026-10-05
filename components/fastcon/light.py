"""ESPHome Fastcon Light platform."""
import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.components import light
from esphome.const import (
    CONF_OUTPUT_ID,
    CONF_NAME,
)
from . import fastcon_ns, FastconComponent, CONF_FASTCON_ID, CONF_DEVICE_ID, CONF_DEVICE_TYPE, CONF_DEVICE_KEY, CONF_MESH_ADDRESS

FastconLight = fastcon_ns.class_("FastconLight", light.LightOutput)

# Light configuration schema
CONFIG_SCHEMA = light.RGB_LIGHT_SCHEMA.extend({
    cv.GenerateID(CONF_OUTPUT_ID): cv.declare_id(FastconLight),
    cv.GenerateID(CONF_FASTCON_ID): cv.use_id(FastconComponent),
    cv.Required(CONF_DEVICE_ID): cv.string,  # 6-byte hex string (12 chars)
    cv.Required(CONF_DEVICE_TYPE): cv.string,  # 2-byte hex string (4 chars)
    cv.Required(CONF_DEVICE_KEY): cv.string,  # 4-byte hex string (8 chars)
    cv.Optional(CONF_MESH_ADDRESS, default=0): cv.int_range(min=0, max=255),
})


async def to_code(config):
    """Generate code for a Fastcon light."""
    var = cg.new_Pvariable(config[CONF_OUTPUT_ID])
    await light.register_light(var, config)
    
    # Get parent Fastcon component
    parent = await cg.get_variable(config[CONF_FASTCON_ID])
    cg.add(var.set_fastcon_parent(parent))
    
    # Parse and set device ID (6 bytes)
    device_id = config[CONF_DEVICE_ID]
    if len(device_id) == 12:  # 6 bytes = 12 hex chars
        did_bytes = [int(device_id[i:i+2], 16) for i in range(0, 12, 2)]
        cg.add(var.set_device_id(did_bytes))
    
    # Parse and set device type (2 bytes)
    device_type = config[CONF_DEVICE_TYPE]
    if len(device_type) == 4:  # 2 bytes = 4 hex chars
        type_bytes = [int(device_type[i:i+2], 16) for i in range(0, 4, 2)]
        cg.add(var.set_device_type(type_bytes))
    
    # Parse and set device key (4 bytes)
    device_key = config[CONF_DEVICE_KEY]
    if len(device_key) == 8:  # 4 bytes = 8 hex chars
        key_bytes = [int(device_key[i:i+2], 16) for i in range(0, 8, 2)]
        cg.add(var.set_device_key(key_bytes))
    
    # Set mesh address
    cg.add(var.set_mesh_address(config[CONF_MESH_ADDRESS]))
    
    # Register light with parent component
    cg.add(parent.register_light(var))
