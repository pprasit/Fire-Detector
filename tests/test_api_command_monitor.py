import time
import unittest

from fire_detector.api_command_monitor import ApiCommandMonitor
from fire_detector.motion_commands import MotionCommandManager
from fire_detector.mount_agent import MountAgent


class ApiCommandMonitorTests(unittest.TestCase):
    def test_trace_contains_timestamps_parameters_and_redacts_credentials(self):
        monitor = ApiCommandMonitor()
        handle = monitor.begin({
            "message_id": "trace-1",
            "action": "axis.goto",
            "params": {
                "axis": "altitude",
                "position_deg": 12.5,
                "lease_id": "do-not-store",
                "nested": {"secret": "do-not-store"},
            },
        }, {"source": "test-client"})
        monitor.mark_dispatch_started(handle)
        monitor.finish(handle, {"ok": True})

        snapshot = monitor.snapshot()
        event = snapshot["events"][0]
        self.assertEqual(event["action"], "axis.goto")
        self.assertEqual(event["params"]["position_deg"], 12.5)
        self.assertEqual(event["params"]["lease_id"], "<redacted>")
        self.assertEqual(event["params"]["nested"]["secret"], "<redacted>")
        self.assertEqual(event["state"], "ok")
        self.assertIsNotNone(event["received_at"])
        self.assertIsNotNone(event["completed_at"])
        self.assertIsNotNone(event["total_ms"])

    def test_rejected_protocol_command_is_visible(self):
        monitor = ApiCommandMonitor()
        agent = MountAgent(
            lambda action, params, context: {"action": action},
            lambda: {},
            lambda: {"mount_agent": {"local": {"enabled": False}, "remote": {"enabled": False}}},
            command_monitor=monitor,
        )
        response = agent.dispatch_for_session({
            "version": "1.0",
            "type": "command",
            "message_id": "denied-1",
            "action": "mount.enable",
            "params": {},
        }, source="test", owner="test-owner")

        self.assertFalse(response["ok"])
        event = monitor.snapshot()["events"][0]
        self.assertEqual(event["state"], "error")
        self.assertEqual(event["error_code"], "CONTROL_LEASE_REQUIRED")

    def test_motion_manager_adds_queue_and_execution_timing(self):
        class Controller:
            @staticmethod
            def goto_positions(positions, speed=None):
                time.sleep(0.01)
                return {"positions": positions, "speed": speed}

        monitor = ApiCommandMonitor()
        manager = MotionCommandManager(Controller(), monitor)
        handle = monitor.begin({
            "message_id": "motion-1",
            "action": "mount.goto",
            "params": {"azimuth_deg": 15},
        }, {"source": "test"})
        monitor.mark_dispatch_started(handle)
        try:
            result = manager.submit("mount-agent", "goto_positions", {"Azimuth": 15}, 2)
            self.assertEqual(result["positions"], {"Azimuth": 15})
            monitor.finish(handle, {"ok": True})
        finally:
            manager.close()

        event = monitor.snapshot()["events"][0]
        self.assertEqual(event["manager_action"], "goto_positions")
        self.assertIsNotNone(event["manager_sequence"])
        self.assertGreaterEqual(event["queue_wait_ms"], 0)
        self.assertGreaterEqual(event["execution_ms"], 8)

    def test_revision_avoids_resending_unchanged_history(self):
        monitor = ApiCommandMonitor()
        handle = monitor.begin({"action": "system.ping", "params": {}}, {"source": "test"})
        monitor.finish(handle, {"ok": True})
        first = monitor.snapshot()
        unchanged = monitor.snapshot(after_revision=first["revision"])
        self.assertFalse(unchanged["changed"])
        self.assertEqual(unchanged["events"], [])

    def test_automatic_console_status_poll_can_be_filtered_server_side(self):
        monitor = ApiCommandMonitor()
        poll = monitor.begin({
            "message_id": "poll-123",
            "action": "mount.get_status",
            "params": {},
        }, {"source": "web-api-console"})
        monitor.finish(poll, {"ok": True})
        command = monitor.begin({
            "message_id": "goto-123",
            "action": "axis.goto",
            "params": {"axis": "azimuth", "position_deg": 3},
        }, {"source": "local"})
        monitor.finish(command, {"ok": True})

        filtered = monitor.snapshot(include_automatic=False)
        self.assertEqual([event["action"] for event in filtered["events"]], ["axis.goto"])
        complete = monitor.snapshot(include_automatic=True)
        self.assertEqual(len(complete["events"]), 2)


if __name__ == "__main__":
    unittest.main()
