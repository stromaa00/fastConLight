"""Tests for the MGMT packet helpers.

Run with: python -m unittest discover -s tests/python
"""

import importlib.util
from pathlib import Path
import struct
import sys
import unittest

_PATH = Path(__file__).parents[2] / "custom_components" / "fastcon" / "mgmt.py"
_spec = importlib.util.spec_from_file_location("fastcon_mgmt", _PATH)
mgmt = importlib.util.module_from_spec(_spec)
sys.modules["fastcon_mgmt"] = mgmt
_spec.loader.exec_module(mgmt)


class MgmtTest(unittest.TestCase):
    def test_advertising_data_matches_firmware_layout(self):
        payload = bytes(range(24))
        adv = mgmt.advertising_data(0xFFF0, payload)
        # BLE_PREDATA from the firmware, then the payload
        self.assertEqual(adv[:7], bytes((0x02, 0x01, 0x02, 0x1B, 0xFF, 0xF0, 0xFF)))
        self.assertEqual(adv[7:], payload)
        self.assertEqual(len(adv), 31)

    def test_ext_adv_params_layout(self):
        params = mgmt.ext_adv_params(5, connectable=False, interval_ms=100)
        self.assertEqual(len(params), 18)
        instance, flags, duration, timeout, min_i, max_i, tx = struct.unpack("<BIHHIIb", params)
        self.assertEqual(instance, 5)
        self.assertEqual(flags, mgmt.MGMT_ADV_PARAM_INTERVALS)
        self.assertEqual((duration, timeout, tx), (0, 0, 0))
        self.assertEqual((min_i, max_i), (160, 160))  # 100 ms in 0.625 ms units

    def test_ext_adv_params_connectable(self):
        params = mgmt.ext_adv_params(1, connectable=True, interval_ms=100)
        flags = struct.unpack_from("<I", params, 1)[0]
        self.assertTrue(flags & mgmt.MGMT_ADV_FLAG_CONNECTABLE)

    def test_ext_adv_data_layout(self):
        adv = bytes(31)
        params = mgmt.ext_adv_data(3, adv)
        self.assertEqual(params[:3], bytes((3, 31, 0)))
        self.assertEqual(params[3:], adv)

    def test_own_instance_is_highest_supported(self):
        features = struct.pack("<IBBBB", 0, 31, 31, 5, 2) + bytes((5, 1))
        self.assertEqual(mgmt.own_instance(features), 5)

    def test_own_instance_requires_support(self):
        features = struct.pack("<IBBBB", 0, 31, 31, 0, 0)
        with self.assertRaises(mgmt.MgmtError):
            mgmt.own_instance(features)

if __name__ == "__main__":
    unittest.main()
