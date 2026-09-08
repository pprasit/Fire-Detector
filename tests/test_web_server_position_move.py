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


class GotoPayloadPrecisionTests(unittest.TestCase):
    def test_accepts_precise_position_tolerance_for_small_offsets(self):
        positions, speed, tolerance = web_server._parse_goto_payload({
            "Altitude": "-3.773",
            "position_tolerance_deg": "0.0025",
        })

        self.assertEqual(positions, {"Altitude": -3.773})
        self.assertIsNone(speed)
        self.assertEqual(tolerance, 0.0025)

    def test_rejects_tolerance_looser_than_normal_goto(self):
        with self.assertRaisesRegex(ValueError, "Position tolerance"):
            web_server._parse_goto_payload({
                "Azimuth": "10",
                "position_tolerance_deg": "0.1",
            })


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


class AzimuthStartupRegionTests(unittest.TestCase):
    def test_late_ccw_sample_corrects_provisional_startup_branch(self):
        state = {}
        provisional = web_server._axis_unwrapped_display_position_deg(
            "Azimuth", 242.0, 125.0, state, {},
        )
        confirmed = web_server._axis_unwrapped_display_position_deg(
            "Azimuth",
            242.0,
            125.0,
            state,
            {"ccw_sensor": True, "cw_sensor": False},
        )

        self.assertEqual(provisional, 117.0)
        self.assertEqual(confirmed, -243.0)
        self.assertTrue(state["Azimuth"]["region_confirmed"])

    def test_late_cw_sample_keeps_positive_startup_branch(self):
        state = {}
        web_server._axis_unwrapped_display_position_deg(
            "Azimuth", 242.0, 125.0, state, None,
        )

        confirmed = web_server._axis_unwrapped_display_position_deg(
            "Azimuth",
            242.0,
            125.0,
            state,
            {"ccw_sensor": False, "cw_sensor": True},
        )

        self.assertEqual(confirmed, 117.0)
        self.assertTrue(state["Azimuth"]["region_confirmed"])

    def test_late_region_confirmation_during_motion_keeps_provisional_continuity(self):
        state = {}
        provisional = web_server._axis_unwrapped_display_position_deg(
            "Azimuth", 242.0, 125.0, state, {},
        )
        confirmed = web_server._axis_unwrapped_display_position_deg(
            "Azimuth",
            241.0,
            125.0,
            state,
            {"ccw_sensor": True, "cw_sensor": False},
            allow_region_reconcile=False,
        )

        self.assertEqual(provisional, 117.0)
        self.assertEqual(confirmed, 116.0)
        self.assertTrue(state["Azimuth"]["region_confirmed"])

    def test_confirmed_branch_stays_continuous_when_region_sensor_changes(self):
        state = {}
        start = web_server._axis_unwrapped_display_position_deg(
            "Azimuth",
            242.0,
            125.0,
            state,
            {"ccw_sensor": True, "cw_sensor": False},
        )
        moved = web_server._axis_unwrapped_display_position_deg(
            "Azimuth",
            241.0,
            125.0,
            state,
            {"ccw_sensor": False, "cw_sensor": True},
        )

        self.assertEqual(start, -243.0)
        self.assertEqual(moved, -244.0)

    def test_first_sensor_sample_after_reconnect_does_not_rewrite_confirmed_branch(self):
        state = {
            "Azimuth": {
                "absolute": 4.486970901489258,
                "unwrapped": -18.394440098510742,
                "region_confirmed": True,
            }
        }
        corrected = web_server._axis_unwrapped_display_position_deg(
            "Azimuth",
            -355.51302909851074,
            22.881411,
            state,
            {"ccw_sensor": False, "cw_sensor": True},
        )

        self.assertAlmostEqual(corrected, -18.394440098510742)
        self.assertTrue(state["Azimuth"]["region_confirmed"])

    def test_region_switch_does_not_hide_position_outside_new_software_limit(self):
        state = {
            "Azimuth": {
                "absolute": 112.7656888961792,
                "unwrapped": -270.1157221038208,
                "region_confirmed": True,
            }
        }
        corrected = web_server._axis_unwrapped_display_position_deg(
            "Azimuth",
            -247.2343111038208,
            22.881411,
            state,
            {"ccw_sensor": True, "cw_sensor": False},
            -190.0,
            440.0,
        )

        self.assertAlmostEqual(corrected, -270.1157221038208)
        self.assertLess(corrected, -190.0)

    def test_sensor_bounce_cannot_toggle_between_opposite_branches(self):
        state = {}
        start = web_server._axis_unwrapped_display_position_deg(
            "Azimuth",
            -116.0,
            22.0,
            state,
            {"ccw_sensor": False, "cw_sensor": True},
            -300.0,
            330.0,
        )
        ccw_bounce = web_server._axis_unwrapped_display_position_deg(
            "Azimuth",
            -116.1,
            22.0,
            state,
            {"ccw_sensor": True, "cw_sensor": False},
            -300.0,
            330.0,
        )
        cw_bounce = web_server._axis_unwrapped_display_position_deg(
            "Azimuth",
            -116.2,
            22.0,
            state,
            {"ccw_sensor": False, "cw_sensor": True},
            -300.0,
            330.0,
        )

        self.assertAlmostEqual(start, 222.0)
        self.assertAlmostEqual(ccw_bounce, 221.9)
        self.assertAlmostEqual(cw_bounce, 221.8)

    def test_ccw_switch_still_selects_negative_branch_when_limit_allows_it(self):
        selected = web_server._azimuth_initial_unwrapped_position(
            89.8842778961792,
            {"ccw_sensor": True, "cw_sensor": False},
            -300.0,
            440.0,
        )

        self.assertAlmostEqual(selected, -270.1157221038208)

    def test_ccw_limit_overshoot_stays_continuous_for_runtime_stop(self):
        state = {
            "Azimuth": {
                "absolute": 170.1,
                "unwrapped": -189.9,
                "region_confirmed": True,
                "sensor_region": "ccw",
            }
        }
        just_past_limit = web_server._axis_unwrapped_display_position_deg(
            "Azimuth",
            169.9,
            0.0,
            state,
            {"ccw_sensor": True, "cw_sensor": False},
            -190.0,
            440.0,
        )

        self.assertAlmostEqual(just_past_limit, -190.1)
        self.assertTrue(
            web_server._axis_velocity_hits_runtime_limit(
                just_past_limit,
                -10.0,
                -190.0,
                440.0,
            )
        )


if __name__ == "__main__":
    unittest.main()
