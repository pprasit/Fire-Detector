from types import SimpleNamespace
import unittest

from fire_detector.odrive_connection import _read_axis_status, read_dual_drive_status


class ODriveTelemetryCacheTests(unittest.TestCase):
    @staticmethod
    def drive(voltage, current):
        return SimpleNamespace(
            serial_number=1,
            vbus_voltage=voltage,
            ibus=current,
            axis0=SimpleNamespace(
                current_state=8,
                active_errors=0,
                disarm_reason=0,
                is_armed=True,
                motor=SimpleNamespace(foc=SimpleNamespace(Iq_measured=1.0, Iq_setpoint=1.0)),
                controller=SimpleNamespace(trajectory_done=False),
            ),
        )

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

    def test_power_telemetry_can_refresh_without_reloading_configuration(self):
        devices = (self.drive(48.0, 1.0), self.drive(49.0, 2.0))
        previous = read_dual_drive_status(devices)
        devices[0].vbus_voltage = 47.0
        devices[0].ibus = 3.0

        cached = read_dual_drive_status(devices, telemetry_only=True, previous=previous)
        refreshed = read_dual_drive_status(
            devices,
            telemetry_only=True,
            previous=previous,
            refresh_power=True,
        )

        self.assertEqual(cached.axes[0].drive_vbus_voltage, 48.0)
        self.assertEqual(cached.axes[0].drive_ibus, 1.0)
        self.assertEqual(refreshed.axes[0].drive_vbus_voltage, 47.0)
        self.assertEqual(refreshed.axes[0].drive_ibus, 3.0)
        self.assertEqual(refreshed.ibus, 5.0)


if __name__ == "__main__":
    unittest.main()
