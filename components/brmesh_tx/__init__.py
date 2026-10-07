"""BRMesh transmitter: broadcasts BRMesh packets sent by Home Assistant.

A Bluetooth proxy can only listen. This component lets the fastcon Home
Assistant integration send commands from an ESP32 placed near lights that
the Home Assistant host can't reach. Any ESP32 works: the packets fit a
legacy (Bluetooth 4.x) advertisement.
"""

import esphome.codegen as cg
from esphome.components import esp32_ble
import esphome.config_validation as cv
from esphome.const import CONF_ID

CODEOWNERS = ["@stromaa00"]
DEPENDENCIES = ["esp32"]
AUTO_LOAD = ["esp32_ble"]

CONF_INTERVAL = "interval"

brmesh_tx_ns = cg.esphome_ns.namespace("brmesh_tx")
BrmeshTx = brmesh_tx_ns.class_("BrmeshTx", cg.Component)

CONFIG_SCHEMA = cv.Schema(
    {
        cv.GenerateID(): cv.declare_id(BrmeshTx),
        cv.GenerateID(esp32_ble.CONF_BLE_ID): cv.use_id(esp32_ble.ESP32BLE),
        # Non-connectable advertising: Bluetooth 4.x chips (original ESP32)
        # need at least 100 ms; ESP32-C3/S3/C6 accept down to 20 ms.
        cv.Optional(CONF_INTERVAL, default="100ms"): cv.All(
            cv.positive_time_period_milliseconds,
            cv.Range(
                min=cv.TimePeriod(milliseconds=20), max=cv.TimePeriod(milliseconds=10240)
            ),
        ),
    }
).extend(cv.COMPONENT_SCHEMA)


async def to_code(config):
    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)
    await cg.get_variable(config[esp32_ble.CONF_BLE_ID])
    cg.add(var.set_interval(config[CONF_INTERVAL]))
