from types import SimpleNamespace
import unittest

from fire_detector.odrive_connection import _read_axis_status


class ODriveTelemetryCacheTests(unittest.TestCase):
    def test_runtime_axis_state_is_refreshed_in_telemetry_only_mode(self):
        axis = SimpleNamespace(
            current_state=8,
            active_errors=0,
            disarm_reason=0,
            is_armed=True,
            controller=SimpleNamespace(trajectory_done=False),
        )
        previous = _read_axis_status(axis, "axis0", "Azimuth")

        axis.current_state = 1
        axis.disarm_reason = 0x20
        axis.is_armed = False
        axis.controller.trajectory_done = True
        latest = _read_axis_status(
            axis,
            "axis0",
            "Azimuth",
            telemetry_only=True,
            previous=previous,
        )

        self.assertEqual(latest.current_state, 1)
        self.assertEqual(latest.disarm_reason, 0x20)
        self.assertFalse(latest.is_armed)
        self.assertTrue(latest.trajectory_done)

    def test_idle_axis_does_not_report_latched_foc_current(self):
        axis = SimpleNamespace(
            current_state=1,
            active_errors=0,
            disarm_reason=0,
            is_armed=False,
            motor=SimpleNamespace(
                foc=SimpleNamespace(Iq_measured=7.5, Iq_setpoint=6.0),
            ),
            controller=SimpleNamespace(trajectory_done=True),
        )

        status = _read_axis_status(axis, "axis0", "Altitude")

        self.assertEqual(status.current, 0.0)
        self.assertEqual(status.current_setpoint, 0.0)

    def test_armed_axis_reports_live_foc_current(self):
        axis = SimpleNamespace(
            current_state=8,
            active_errors=0,
            disarm_reason=0,
            is_armed=True,
            motor=SimpleNamespace(
                foc=SimpleNamespace(Iq_measured=3.25, Iq_setpoint=3.0),
            ),
            controller=SimpleNamespace(trajectory_done=False),
        )

        status = _read_axis_status(axis, "axis0", "Altitude")

        self.assertEqual(status.current, 3.25)
        self.assertEqual(status.current_setpoint, 3.0)


if __name__ == "__main__":
    unittest.main()
