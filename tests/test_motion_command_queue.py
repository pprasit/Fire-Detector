import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fire_detector import web_server
from fire_detector.motion_algorithm import PositionMotionAlgorithm, PositionStepInput
from fire_detector.motion_commands import (
    ManagedMotionController,
    MotionCommandManager,
    MotionCommandSuperseded,
)


class BlockingMonitor:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = []

    def goto_positions(self, positions, speed=None):
        self.calls.append(("start", positions, speed))
        if len([call for call in self.calls if call[0] == "start"]) == 1:
            self.started.set()
            self.release.wait(2.0)
        self.calls.append(("finish", positions, speed))
        return positions

    def stop_motors(self):
        self.calls.append(("stop",))
        return {"stopped": True}

    def command_velocities(self, velocities):
        self.calls.append(("velocities", velocities))
        return {"accepted": velocities}


class MotionCommandManagerTests(unittest.TestCase):
    def setUp(self):
        self.monitor = BlockingMonitor()
        self.manager = MotionCommandManager(self.monitor)
        self.proxy = ManagedMotionController(self.monitor, self.manager, "test-api")

    def tearDown(self):
        self.monitor.release.set()
        self.manager.close()

    def test_concurrent_api_commands_execute_in_arrival_order(self):
        results = []
        first = threading.Thread(
            target=lambda: results.append(self.proxy.goto_positions({"Azimuth": 10.0}, 5.0))
        )
        second = threading.Thread(
            target=lambda: results.append(self.proxy.goto_positions({"Azimuth": 20.0}, 5.0))
        )

        first.start()
        self.assertTrue(self.monitor.started.wait(1.0))
        second.start()
        time.sleep(0.05)

        self.assertEqual(self.monitor.calls, [("start", {"Azimuth": 10.0}, 5.0)])
        self.monitor.release.set()
        first.join(1.0)
        second.join(1.0)

        self.assertEqual(
            self.monitor.calls,
            [
                ("start", {"Azimuth": 10.0}, 5.0),
                ("finish", {"Azimuth": 10.0}, 5.0),
                ("start", {"Azimuth": 20.0}, 5.0),
                ("finish", {"Azimuth": 20.0}, 5.0),
            ],
        )
        self.assertCountEqual(results, [{"Azimuth": 10.0}, {"Azimuth": 20.0}])

    def test_stop_bypasses_pending_commands_and_invalidates_them(self):
        errors = []
        first = threading.Thread(
            target=lambda: self.proxy.goto_positions({"Azimuth": 10.0}, 5.0)
        )

        def pending_command():
            try:
                self.proxy.goto_positions({"Azimuth": 20.0}, 5.0)
            except Exception as exc:
                errors.append(exc)

        second = threading.Thread(target=pending_command)
        stop_result = []
        stop = threading.Thread(target=lambda: stop_result.append(self.proxy.stop_motors()))

        first.start()
        self.assertTrue(self.monitor.started.wait(1.0))
        second.start()
        time.sleep(0.02)
        stop.start()
        time.sleep(0.02)

        # The current atomic controller call may finish, but the pending Goto
        # must never enter the controller ahead of, or after, this safety stop.
        self.monitor.release.set()
        first.join(1.0)
        second.join(1.0)
        stop.join(1.0)

        self.assertEqual(
            self.monitor.calls,
            [
                ("start", {"Azimuth": 10.0}, 5.0),
                ("finish", {"Azimuth": 10.0}, 5.0),
                ("stop",),
            ],
        )
        self.assertEqual(stop_result, [{"stopped": True}])
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], MotionCommandSuperseded)

    def test_zero_velocity_is_safety_priority(self):
        first = threading.Thread(
            target=lambda: self.proxy.goto_positions({"Azimuth": 10.0}, 5.0)
        )
        zero_result = []
        zero = threading.Thread(
            target=lambda: zero_result.append(self.proxy.command_velocities({"Azimuth": 0.0}))
        )

        first.start()
        self.assertTrue(self.monitor.started.wait(1.0))
        zero.start()
        time.sleep(0.02)
        self.monitor.release.set()
        first.join(1.0)
        zero.join(1.0)

        self.assertEqual(
            self.monitor.calls,
            [
                ("start", {"Azimuth": 10.0}, 5.0),
                ("finish", {"Azimuth": 10.0}, 5.0),
                ("velocities", {"Azimuth": 0.0}),
            ],
        )
        self.assertEqual(zero_result, [{"accepted": {"Azimuth": 0.0}}])


class MotionGenerationTests(unittest.TestCase):
    @staticmethod
    def device_with_velocity(velocity):
        controller = SimpleNamespace(
            input_vel=velocity,
            config=SimpleNamespace(control_mode=web_server.CONTROL_MODE_VELOCITY_CONTROL,
                                   input_mode=web_server.INPUT_MODE_VEL_RAMP),
        )
        return SimpleNamespace(axis0=SimpleNamespace(controller=controller))

    def test_stale_motion_cannot_zero_new_motion(self):
        monitor = web_server.ODriveMonitor()
        monitor._software_position_generation = 2

        with patch.object(monitor, "_write_velocity_commands_hardware") as writer:
            monitor._stop_software_position_axes_if_current(
                {"Azimuth": 10.0}, generation=1,
            )

        writer.assert_not_called()

    def test_stale_or_stopped_position_task_cannot_write(self):
        monitor = web_server.ODriveMonitor()
        monitor._software_position_generation = 2
        active = threading.Event()
        stopped = threading.Event()
        stopped.set()

        self.assertFalse(monitor._software_position_is_current(active, generation=1))
        self.assertFalse(monitor._software_position_is_current(stopped, generation=2))
        self.assertTrue(monitor._software_position_is_current(active, generation=2))

    def test_current_motion_still_stops_itself_on_completion(self):
        monitor = web_server.ODriveMonitor()
        monitor._software_position_generation = 2

        with patch.object(monitor, "_write_velocity_commands_hardware") as writer:
            monitor._stop_software_position_axes_if_current(
                {"Azimuth": 10.0}, generation=2,
            )

        writer.assert_called_once_with({"Azimuth": 0.0}, require_enabled=False)

    def test_stale_motion_cannot_overwrite_new_state(self):
        monitor = web_server.ODriveMonitor()
        monitor._software_position_generation = 2
        monitor._software_position_state = {"Azimuth": {"phase": "moving"}}

        monitor._update_software_position_state(
            {"Azimuth": {"phase": "cancelled"}}, generation=1,
        )

        self.assertEqual(monitor._software_position_state["Azimuth"]["phase"], "moving")

    def test_stale_sine_loop_cannot_zero_new_motion(self):
        monitor = web_server.ODriveMonitor()
        monitor._sine_velocity_generations["Azimuth"] = 2

        with patch.object(monitor, "_write_velocity_commands_hardware") as writer:
            monitor._stop_sine_velocity_axis_if_current(
                "Azimuth", generation=1,
            )

        writer.assert_not_called()

    def test_retarget_preserves_existing_velocity_command(self):
        monitor = web_server.ODriveMonitor()
        monitor._software_position_generation = 7
        device = self.device_with_velocity(5.0 / 360.0)
        status = SimpleNamespace(axes=[SimpleNamespace(
            label="Azimuth",
            control_mode=web_server.CONTROL_MODE_VELOCITY_CONTROL,
            input_vel=5.0,
            position_deg=0.0,
        )])
        thread = MagicMock()
        shared_snapshot = {
            "axes": [{
                "label": "Azimuth",
                "control_mode": web_server.CONTROL_MODE_VELOCITY_CONTROL,
                "input_vel": 5.0,
                "position_deg": 0.0,
                "is_armed": True,
            }]
        }

        with (
            patch.object(monitor, "_cancel_software_position_move", return_value=7),
            patch.object(monitor, "_connected_devices", return_value=(device,)),
            patch.object(monitor, "snapshot", return_value=shared_snapshot),
            patch.object(monitor, "_hardware_call", side_effect=lambda callback, **_: callback()),
            patch.object(web_server.MotionCommandGuard, "require_enabled"),
            patch.object(web_server, "_apply_slew_rate"),
            patch.object(web_server, "_configure_velocity_control"),
            patch.object(web_server, "_set_if_present") as setter,
            patch.object(web_server, "_read_azimuth_sensors", return_value={}),
            patch.object(web_server, "_load_app_settings", return_value={"motion_limits": {}}),
            patch.object(web_server, "_software_position_gain", return_value=0.5),
            patch.object(web_server, "Thread", return_value=thread),
        ):
            monitor._start_software_position_move({"Azimuth": 20.0}, 10.0)

        self.assertNotIn(
            ((device.axis0, "controller.input_vel", 0.0), {}),
            [(call.args, call.kwargs) for call in setter.call_args_list],
        )
        self.assertEqual(
            monitor._software_position_state["Azimuth"]["command_velocity_deg_per_sec"],
            5.0,
        )
        thread.start.assert_called_once_with()


class PositionMotionAlgorithmTests(unittest.TestCase):
    def setUp(self):
        self.algorithm = PositionMotionAlgorithm()

    def step(self, **overrides):
        values = {
            "error_deg": 10.0,
            "actual_velocity_deg_per_sec": 0.0,
            "previous_command_deg_per_sec": 0.0,
            "max_speed_deg_per_sec": 20.0,
            "gain_per_sec": 0.5,
            "acceleration_deg_per_sec2": 40.0,
            "interval_sec": 0.025,
            "position_tolerance_deg": 0.08,
            "settle_velocity_deg_per_sec": 0.25,
        }
        values.update(overrides)
        return self.algorithm.step(PositionStepInput(**values))

    def test_position_step_applies_acceleration_limit(self):
        result = self.step()
        self.assertFalse(result.settled)
        self.assertEqual(result.command_velocity_deg_per_sec, 1.0)

    def test_position_step_preserves_retarget_velocity_continuity(self):
        result = self.step(previous_command_deg_per_sec=5.0)
        self.assertEqual(result.command_velocity_deg_per_sec, 5.0)

    def test_position_step_stops_only_after_position_and_velocity_settle(self):
        moving = self.step(error_deg=0.01, actual_velocity_deg_per_sec=1.0)
        settled = self.step(error_deg=0.01, actual_velocity_deg_per_sec=0.1)
        self.assertFalse(moving.settled)
        self.assertTrue(settled.settled)
        self.assertEqual(settled.command_velocity_deg_per_sec, 0.0)

    def test_precise_offset_does_not_settle_inside_default_goto_tolerance(self):
        result = self.step(
            error_deg=0.01,
            actual_velocity_deg_per_sec=0.0,
            position_tolerance_deg=0.0025,
        )

        self.assertFalse(result.settled)
        self.assertGreater(result.command_velocity_deg_per_sec, 0.0)


if __name__ == "__main__":
    unittest.main()
