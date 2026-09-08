import unittest
from unittest.mock import patch

from fire_detector import web_server


class AzimuthSensorBridgeTests(unittest.TestCase):
    def setUp(self):
        with web_server._AZIMUTH_SENSOR_BRIDGE_LOCK:
            web_server._AZIMUTH_SENSOR_BRIDGE_STATE.clear()
        self.settings = {
            "source": "node_red",
            "ccw_pin": 17,
            "cw_pin": 13,
            "ccw_active_high": True,
            "cw_active_high": True,
            "ccw_pull": "down",
            "cw_pull": "down",
        }

    def test_bridge_preserves_raw_levels_and_active_high_logic(self):
        web_server._update_azimuth_sensor_bridge({
            "ccw_raw_level": 1,
            "cw_raw_level": 0,
        })

        status = web_server._read_azimuth_sensor_bridge(self.settings)

        self.assertTrue(status["ccw_sensor"])
        self.assertFalse(status["cw_sensor"])
        self.assertIsNone(status["ccw_error"])
        self.assertEqual(status["source"], "node_red")

    def test_bridge_applies_active_low_logic(self):
        settings = {**self.settings, "cw_active_high": False}
        web_server._update_azimuth_sensor_bridge({
            "ccw_raw_level": False,
            "cw_raw_level": False,
        })

        status = web_server._read_azimuth_sensor_bridge(settings)

        self.assertFalse(status["ccw_sensor"])
        self.assertTrue(status["cw_sensor"])

    def test_missing_bridge_update_is_reported_without_claiming_gpio(self):
        status = web_server._read_azimuth_sensor_bridge(self.settings)

        self.assertIsNone(status["ccw_raw_level"])
        self.assertIn("No sensor update", status["ccw_error"])

    def test_stale_bridge_update_is_rejected(self):
        web_server._update_azimuth_sensor_bridge({
            "ccw_raw_level": True,
            "cw_raw_level": False,
        })
        with web_server._AZIMUTH_SENSOR_BRIDGE_LOCK:
            received = web_server._AZIMUTH_SENSOR_BRIDGE_STATE["received_monotonic"]
        with patch.object(web_server, "monotonic", return_value=received + 10.0):
            status = web_server._read_azimuth_sensor_bridge(self.settings)

        self.assertIsNone(status["ccw_raw_level"])
        self.assertIn("stale", status["ccw_error"])

    def test_invalid_payload_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "cw_raw_level"):
            web_server._update_azimuth_sensor_bridge({
                "ccw_raw_level": True,
                "cw_raw_level": "high",
            })


if __name__ == "__main__":
    unittest.main()
