import unittest
from unittest.mock import patch

from fire_detector import web_server


class SoftwarePositionTimeoutTests(unittest.TestCase):
    def test_timeout_includes_proportional_slowdown_near_target(self):
        with patch.object(web_server, "_software_position_gain", return_value=0.5):
            timeout = web_server._software_position_timeout_sec(
                {"Azimuth": 49.38},
                {"Azimuth": -5.438},
                10.0,
            )

        # The old distance/speed timeout was about 11 seconds after its safety
        # multiplier, which is shorter than the roughly 14.5 second P-control
        # move. The new deadline includes that deceleration phase plus margin.
        self.assertGreater(timeout, 20.0)

    def test_timeout_keeps_minimum_for_tiny_moves(self):
        with patch.object(web_server, "_software_position_gain", return_value=0.5):
            timeout = web_server._software_position_timeout_sec(
                {"Altitude": 5.01},
                {"Altitude": 5.0},
                10.0,
            )

        self.assertEqual(timeout, web_server.SOFTWARE_POSITION_MIN_TIMEOUT_SEC)


class AzimuthTargetPathTests(unittest.TestCase):
    def test_selects_cw_equivalent_in_current_region(self):
        target = web_server._resolve_azimuth_target_deg(-100.0, 250.0, -300.0, 300.0)
        self.assertEqual(target, 260.0)

    def test_selects_ccw_equivalent_in_current_region(self):
        target = web_server._resolve_azimuth_target_deg(100.0, -250.0, -300.0, 300.0)
        self.assertEqual(target, -260.0)

    def test_does_not_choose_short_path_that_crosses_software_limit(self):
        target = web_server._resolve_azimuth_target_deg(0.0, 290.0, -300.0, 300.0)
        self.assertEqual(target, 0.0)

    def test_keeps_requested_branch_when_it_is_already_shortest(self):
        target = web_server._resolve_azimuth_target_deg(49.38, -5.438, -300.0, 300.0)
        self.assertEqual(target, 49.38)


if __name__ == "__main__":
    unittest.main()
