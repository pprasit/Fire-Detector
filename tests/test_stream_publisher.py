import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("publish_live_stream", SCRIPTS / "publish_live_stream.py")
publish_live_stream = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(publish_live_stream)


class FakeProcess:
    def __init__(self):
        self.stderr = []
        self.pid = 123

    def wait(self):
        return 0

    def poll(self):
        return 0


class StreamPublisherTests(unittest.TestCase):
    def test_publisher_fetches_fresh_credentials_on_every_start(self):
        fetches = []
        commands = []

        def fetch():
            fetches.append(True)
            return ({
                "username": "publisher user",
                "password": "publisher/password",
                "paths": {
                    "thermal": "/iriv-production/thermal",
                    "visible": "/iriv-production/visible",
                },
            }, 200)

        def popen(command, **_kwargs):
            commands.append(command)
            return FakeProcess()

        with (
            patch.object(publish_live_stream, "fetch_publisher_credentials", fetch),
            patch.object(publish_live_stream, "measured_upload_capacity", return_value=None),
            patch.object(publish_live_stream.subprocess, "Popen", popen),
            patch.object(sys, "argv", ["publish_live_stream.py", "--camera", "thermal"]),
        ):
            self.assertEqual(publish_live_stream.main(), 0)
            self.assertEqual(publish_live_stream.main(), 0)

        self.assertEqual(len(fetches), 2)
        self.assertEqual(len(commands), 2)
        command = commands[0]
        self.assertEqual(command[command.index("-rtsp_transport") + 1], "tcp")
        self.assertEqual(command[command.index("-b:v") + 1], "400k")
        self.assertEqual(command[command.index("-bufsize") + 1], "200k")
        self.assertEqual(command[command.index("-buffer_size") + 1], str(256 * 1024))
        self.assertEqual(command[command.index("-rw_timeout") + 1], "10000000")
        self.assertEqual(
            command[command.index("-vf") + 1],
            "fps=15,scale=640:512:force_original_aspect_ratio=decrease,"
            "pad=640:512:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
        )
        self.assertEqual(command[-1], (
            "rtsp://publisher%20user:publisher%2Fpassword@100.102.91.123:8554/"
            "iriv-production/thermal"
        ))

    def test_manual_upload_capacity_selects_safe_fps_step(self):
        self.assertEqual(
            publish_live_stream.recommended_frame_rate(1.373968, "relay"),
            10,
        )
        self.assertEqual(publish_live_stream.recommended_frame_rate(10.0, "relay"), 15)
        self.assertEqual(publish_live_stream.recommended_frame_rate(0.2, "relay"), 3)
        self.assertEqual(publish_live_stream.recommended_frame_rate(None, "relay"), 15)

    def test_bitrate_scales_with_selected_frame_rate(self):
        self.assertEqual(publish_live_stream.scaled_bitrate("400k", 10), "267k")
        self.assertEqual(publish_live_stream.scaled_bitrate("2.5M", 12), "2000k")

    def test_runtime_backlog_moves_to_next_lower_fps_step(self):
        self.assertEqual(publish_live_stream.next_lower_frame_rate(15), 12)
        self.assertEqual(publish_live_stream.next_lower_frame_rate(10), 8)
        self.assertEqual(publish_live_stream.next_lower_frame_rate(3), 3)

    def test_runtime_recovery_moves_up_only_one_fps_step(self):
        self.assertEqual(publish_live_stream.next_higher_frame_rate(3), 5)
        self.assertEqual(publish_live_stream.next_higher_frame_rate(10), 12)
        self.assertEqual(publish_live_stream.next_higher_frame_rate(15), 15)

    def test_adaptive_policy_decreases_fast_and_recovers_slowly(self):
        self.assertEqual(
            publish_live_stream.adaptive_transition(15, 15, 200_000, 3, 2.0),
            ("backlog", 12),
        )
        self.assertEqual(
            publish_live_stream.adaptive_transition(12, 8, 0, 0, 1.0),
            ("capacity", 8),
        )
        self.assertIsNone(
            publish_live_stream.adaptive_transition(8, 15, 0, 0, 179.0)
        )
        self.assertEqual(
            publish_live_stream.adaptive_transition(8, 15, 0, 0, 180.0),
            ("recovery", 10),
        )
        self.assertIsNone(
            publish_live_stream.adaptive_transition(8, 15, 40_000, 0, 600.0)
        )

    def test_full_profile_can_be_selected_explicitly(self):
        self.assertEqual(publish_live_stream.selected_profile("full"), "full")
        self.assertEqual(
            publish_live_stream.STREAM_PROFILES["full"]["visible"]["bitrate"],
            "4M",
        )

    def test_unknown_profile_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown NARIT stream profile"):
            publish_live_stream.selected_profile("unbounded")

    def test_send_queue_parser_selects_only_requested_process(self):
        output = (
            'ESTAB 0 1234 100.64.0.1:1 100.102.91.123:8554 users:(("ffmpeg",pid=41,fd=4))\n'
            'ESTAB 0 5678 100.64.0.1:2 100.102.91.123:8554 users:(("ffmpeg",pid=42,fd=4))\n'
        )
        result = type("Result", (), {"stdout": output})()
        with patch.object(publish_live_stream.subprocess, "run", return_value=result):
            self.assertEqual(publish_live_stream.rtsp_send_queue_bytes(42), 5678)

    def test_log_sanitizer_removes_plain_and_url_encoded_secrets(self):
        line = "publisher/password publisher%2Fpassword rtsp://private-url"
        cleaned = publish_live_stream.sanitized(
            line, ("publisher/password", "rtsp://private-url")
        )
        self.assertNotIn("publisher/password", cleaned)
        self.assertNotIn("publisher%2Fpassword", cleaned)
        self.assertNotIn("rtsp://private-url", cleaned)

    def test_effective_stream_policy_is_published_for_camera_producer(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            publish_live_stream,
            "STREAM_POLICY_STATE_DIR",
            Path(directory),
        ):
            publish_live_stream.write_stream_policy_state(
                "thermal", "relay", 10, "steady", 1234
            )
            payload = json.loads(
                (Path(directory) / "stream-policy-thermal.json").read_text()
            )

        self.assertEqual(payload["frame_rate"], 10)
        self.assertEqual(payload["queue_bytes"], 1234)
        self.assertEqual(payload["camera"], "thermal")


if __name__ == "__main__":
    unittest.main()
