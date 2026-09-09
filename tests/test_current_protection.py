import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fire_detector.current_protection import CurrentEnvelope, CurrentEnvelopeConfig
from fire_detector import web_server


class CurrentEnvelopeTests(unittest.TestCase):
    def setUp(self):
        self.config = CurrentEnvelopeConfig()

    def test_peak_is_available_for_two_accumulated_seconds(self):
        envelope = CurrentEnvelope(self.config, require_startup_recovery=False)

        for _ in range(19):
            result = envelope.step(40.0, 0.1)
            self.assertEqual(result.allowed_current_amp, 40.0)

        result = envelope.step(40.0, 0.1)
        self.assertEqual(result.phase, "derating")
        self.assertEqual(result.allowed_current_amp, 40.0)
        self.assertEqual(result.peak_remaining_sec, 0.0)

    def test_derating_reduces_torque_without_velocity_output(self):
        envelope = CurrentEnvelope(self.config, require_startup_recovery=False)
        envelope.step(40.0, 1.0)
        envelope.step(40.0, 1.0)

        halfway = envelope.step(20.0, 0.375)
        complete = envelope.step(20.0, 0.375)

        self.assertAlmostEqual(halfway.allowed_current_amp, 30.0)
        self.assertAlmostEqual(halfway.torque_limit_nm, 8.7)
        self.assertEqual(complete.phase, "continuous")
        self.assertAlmostEqual(complete.allowed_current_amp, 20.0)
        self.assertAlmostEqual(complete.torque_limit_nm, 5.8)
        self.assertFalse(hasattr(complete, "velocity"))

    def test_peak_budget_requires_full_low_current_recovery(self):
        envelope = CurrentEnvelope(self.config)

        for _ in range(29):
            result = envelope.step(10.0, 1.0)
        self.assertNotEqual(result.phase, "ready")

        result = envelope.step(10.0, 1.0)
        self.assertEqual(result.phase, "ready")
        self.assertEqual(result.peak_remaining_sec, 2.0)

    def test_partial_recovery_does_not_restore_peak_budget(self):
        envelope = CurrentEnvelope(self.config, require_startup_recovery=False)
        envelope.step(30.0, 1.0)
        for _ in range(15):
            envelope.step(10.0, 1.0)
        result = envelope.step(30.0, 0.1)

        self.assertLess(result.peak_remaining_sec, 1.0)

    def test_monitor_derating_writes_only_torque_limits(self):
        monitor = web_server.ODriveMonitor()
        envelope = CurrentEnvelope(self.config, require_startup_recovery=False)
        envelope.step(40.0, 1.0)
        envelope.step(40.0, 1.0)
        monitor._current_envelopes["Azimuth"] = envelope
        monitor._current_envelope_last_step["Azimuth"] = 99.625
        monitor._current_envelope_last_write["Azimuth"] = 0.0
        monitor._current_envelope_applied_amp["Azimuth"] = 40.0

        axis = SimpleNamespace()
        status = SimpleNamespace(
            axes=(
                SimpleNamespace(label="Azimuth", available=True, current=20.0),
                SimpleNamespace(label="Altitude", available=False, current=0.0),
            )
        )
        devices = (SimpleNamespace(axis0=axis), None)

        with (
            patch.object(web_server, "monotonic", return_value=100.0),
            patch.object(web_server, "_set_if_present") as setter,
        ):
            monitor._apply_current_envelopes(status, devices)

        written_paths = [call.args[1] for call in setter.call_args_list]
        self.assertEqual(
            written_paths,
            ["config.torque_soft_max", "config.torque_soft_min"],
        )
        self.assertNotIn("controller.input_vel", written_paths)
        self.assertAlmostEqual(setter.call_args_list[0].args[2], 8.7)
        self.assertAlmostEqual(setter.call_args_list[1].args[2], -8.7)


if __name__ == "__main__":
    unittest.main()
