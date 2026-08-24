import json
from pathlib import Path
import socket
import tempfile
import time
import unittest

from fire_detector.mount_agent import MountAgent, _capabilities


class MountAgentProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.socket_path = Path(self.temp_dir.name) / "mount-agent.sock"
        self.calls = []
        self.snapshot = {
            "connected": True,
            "health": "ready",
            "timestamp": "2026-08-04T00:00:00Z",
            "axes": [{"label": "Azimuth", "position_deg": 12.5}],
        }
        settings = {
            "mount_agent": {
                "local": {"enabled": True, "socket_path": str(self.socket_path), "mode": "660"},
                "remote": {"enabled": False},
            }
        }

        def handler(action, params, context):
            self.calls.append((action, params, context))
            if action == "mount.get_status":
                return self.snapshot
            return {"action": action}

        self.agent = MountAgent(handler, lambda: self.snapshot, lambda: settings)
        self.agent.start()
        deadline = time.monotonic() + 2.0
        while not self.socket_path.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(self.socket_path.exists(), "local socket did not become ready")
        self.client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.client.settimeout(2.0)
        self.client.connect(str(self.socket_path))
        self.stream = self.client.makefile("rwb")

    def tearDown(self):
        self.stream.close()
        self.client.close()
        self.agent.stop()
        self.temp_dir.cleanup()

    def call(self, action, params=None, message_id="test-message", **fields):
        message = {
            "version": "1.0",
            "type": "command",
            "message_id": message_id,
            "action": action,
            "params": params or {},
            **fields,
        }
        self.stream.write(json.dumps(message).encode("utf-8") + b"\n")
        self.stream.flush()
        return json.loads(self.stream.readline())

    def test_status_round_trip_over_real_unix_socket(self):
        response = self.call("mount.get_status")
        self.assertTrue(response["ok"])
        self.assertEqual(response["correlation_id"], "test-message")
        self.assertEqual(response["result"]["health"], "ready")

    def test_mutating_command_requires_same_session_lease(self):
        denied = self.call("mount.enable", message_id="enable-denied")
        self.assertFalse(denied["ok"])
        self.assertEqual(denied["error"]["code"], "CONTROL_LEASE_REQUIRED")

        lease = self.call("control.acquire", {"lease_ms": 1000}, message_id="lease")
        lease_id = lease["result"]["lease_id"]
        allowed = self.call("mount.enable", message_id="enable-ok", control_lease_id=lease_id)
        self.assertTrue(allowed["ok"])

    def test_duplicate_message_is_not_dispatched_twice(self):
        first = self.call("mount.get_status", message_id="same-id")
        second = self.call("mount.get_status", message_id="same-id")
        self.assertTrue(first["ok"])
        self.assertEqual(second["result"], {"duplicate": True})
        self.assertEqual([call[0] for call in self.calls], ["mount.get_status"])

    def test_subscription_streams_telemetry_on_same_connection(self):
        response = self.call(
            "subscribe",
            {"topics": ["axis.telemetry"], "interval_ms": 100},
            message_id="subscribe",
        )
        self.assertTrue(response["ok"])
        event = json.loads(self.stream.readline())
        self.assertEqual(event["type"], "telemetry")
        self.assertEqual(event["payload"]["topic"], "axis.telemetry")
        self.assertEqual(event["payload"]["data"]["axes"][0]["position_deg"], 12.5)

    def test_capabilities_match_current_command_surface(self):
        capabilities = set(_capabilities())
        self.assertTrue({
            "system.ping", "system.get_capabilities", "pointing.goto_altaz",
            "calibration.get_status", "tuning.apply", "tuning.save",
        }.issubset(capabilities))


if __name__ == "__main__":
    unittest.main()
