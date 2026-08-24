import time
import unittest
from unittest.mock import patch

from fire_detector import web_server


class SimulationMonitorTests(unittest.TestCase):
    def setUp(self):
        self.settings = {
            "motion_limits": {
                "azimuth_ccw_limit_deg": -180.0, "azimuth_cw_limit_deg": 180.0,
                "altitude_lower_limit_deg": -20.0, "altitude_upper_limit_deg": 90.0,
                "slew_rate_deg_per_sec": 20.0,
                "azimuth_remote_acceleration_deg_s2": 50.0,
                "altitude_remote_acceleration_deg_s2": 50.0,
            }
        }
        patcher = patch.object(web_server, "_load_app_settings", return_value=self.settings)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.monitor = web_server.SimulationMonitor(poll_interval=0.005)
        self.monitor.start()

    def test_snapshot_is_explicitly_simulated(self):
        status = self.monitor.snapshot()
        self.assertTrue(status["simulation_mode"])
        self.assertEqual(status["run_mode"], "simulation")
        self.assertTrue(status["connected"])
        self.assertEqual([axis["position_source"] for axis in status["axes"]], ["simulation_model_with_noise"] * 2)
        self.assertEqual(status["simulation_noise_percent"], 0.05)

    def test_idle_encoder_has_small_noise_floor(self):
        samples = [self.monitor.snapshot()["axes"][0]["position_deg"] for _ in range(20)]
        self.assertTrue(all(-0.0005 <= value <= 0.0005 for value in samples))
        self.assertGreater(len({round(value, 8) for value in samples}), 1)

    def test_hardware_monitor_status_identifies_hardware_mode(self):
        with patch.object(web_server, "_read_azimuth_sensors", return_value={}):
            status = web_server.ODriveMonitor().snapshot()
        self.assertEqual(status["run_mode"], "hardware")
        self.assertFalse(status["simulation_mode"])

    def test_measurement_noise_stays_within_point_zero_five_percent(self):
        self.monitor._stop.set()
        time.sleep(0.01)
        with self.monitor._lock:
            self.monitor._axes["Azimuth"].update(position=100.0, velocity=10.0)
        samples = [
            next(axis for axis in self.monitor.snapshot()["axes"] if axis["label"] == "Azimuth")
            for _ in range(30)
        ]
        self.assertTrue(all(99.95 <= axis["position_deg"] <= 100.05 for axis in samples))
        self.assertTrue(all(9.995 <= axis["velocity_deg_per_sec"] <= 10.005 for axis in samples))
        self.assertGreater(len({round(axis["position_deg"], 7) for axis in samples}), 1)
        with self.monitor._lock:
            self.assertEqual(self.monitor._axes["Azimuth"]["position"], 100.0)

    def test_goto_uses_simulated_state_and_configuration_limits(self):
        self.monitor.enable_motors()
        self.monitor.goto_positions({"Azimuth": 2.0, "Altitude": 1.0}, 10.0)
        time.sleep(0.2)
        status = self.monitor.snapshot()
        positions = {axis["label"]: axis["position_deg"] for axis in status["axes"]}
        self.assertGreater(positions["Azimuth"], 0.0)
        self.assertGreater(positions["Altitude"], 0.0)
        with self.assertRaises(ValueError):
            self.monitor.goto_positions({"Azimuth": 181.0}, 10.0)

    def test_velocity_api_path_never_connects_to_hardware(self):
        router = web_server.MountCommandRouter(self.monitor)
        with patch.object(web_server, "connect_many", side_effect=AssertionError("hardware accessed")):
            router.dispatch("mount.enable", {}, {})
            router.dispatch("axis.set_velocity", {
                "axis": "azimuth", "velocity_deg_per_sec": 5.0, "command_timeout_ms": 200,
            }, {})
            time.sleep(0.05)
        axis = next(axis for axis in self.monitor.snapshot()["axes"] if axis["label"] == "Azimuth")
        self.assertGreater(axis["position_deg"], 0.0)

    def test_disable_stops_all_simulated_motion(self):
        self.monitor.enable_motors()
        self.monitor.set_velocities({"Azimuth": 10.0, "Altitude": 5.0})
        time.sleep(0.04)
        status = self.monitor.disable_motors()
        self.assertTrue(all(
            not axis["is_armed"] and abs(axis["velocity_deg_per_sec"]) <= 0.00005
            for axis in status["axes"]
        ))


if __name__ == "__main__":
    unittest.main()
