import hashlib
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import urllib.error


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "configuration_worker.py"
SPEC = importlib.util.spec_from_file_location("configuration_worker", SCRIPT)
configuration_worker = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(configuration_worker)


class ConfigurationWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        secret = root / "secret"
        secret.write_bytes(b"x" * 32)
        ca = root / "ca.crt"
        ca.write_text("test")
        settings = {
            "mount_agent": {"remote": {
                "device_id": "iriv-production", "media_upload_url": "https://server/api/v1/media/upload",
                "secret_file": str(secret), "ca_file": str(ca),
            }},
            "motion_limits": {
                "azimuth_ccw_limit_deg": -300, "azimuth_cw_limit_deg": 300,
                "altitude_lower_limit_deg": -45, "altitude_upper_limit_deg": 120,
                "slew_rate_deg_per_sec": 100,
            },
        }
        settings_path = root / "AppSetting.JSON"
        settings_path.write_text(json.dumps(settings))
        patches = [
            patch.object(configuration_worker, "SETTINGS_PATH", settings_path),
            patch.object(configuration_worker, "STATE_PATH", root / "state.json"),
            patch.object(configuration_worker, "ACTIVE_PATH", root / "active.json"),
            patch("ssl.create_default_context", return_value=object()),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        self.worker = configuration_worker.ConfigurationWorker()
        self.worker.drive_limits = lambda: {
            "Azimuth": {"speed": 50, "acceleration": 80},
            "Altitude": {"speed": 40, "acceleration": 60},
        }

    def candidate(self, revision=3):
        return {"device_id": "iriv-production", "revision": revision, "station_name": "NARIT#1",
                "location": {"latitude": 18.853, "longitude": 98.958},
                "motion_limits": {"azimuth_min_deg": -180.0, "azimuth_max_deg": 180.0,
                                  "altitude_min_deg": -20.0, "altitude_max_deg": 90.0,
                                  "azimuth_speed_max_deg_s": 20.0, "altitude_speed_max_deg_s": 15.0,
                                  "azimuth_acceleration_deg_s2": 8.0, "altitude_acceleration_deg_s2": 6.0},
                "updated_at": "2026-08-04T07:00:00Z"}

    def test_duplicate_and_old_revisions_are_skipped(self):
        self.worker.state["applied_revision"] = 3
        self.worker.state["acked_revision"] = 3
        self.worker.signed_request = lambda *args: (200, {"configuration": self.candidate(3)})
        with patch.object(self.worker, "validate") as validate:
            self.worker.run_once()
            self.worker.signed_request = lambda *args: (200, {"configuration": self.candidate(2)})
            self.worker.run_once()
        validate.assert_not_called()

    def test_duplicate_revision_retries_missing_ack(self):
        self.worker.state.update({"applied_revision": 3, "acked_revision": None})
        calls = []
        def request(method, path, body=b""):
            calls.append((method, path, body))
            return (200, {"configuration": self.candidate(3)}) if method == "GET" else (200, {})
        self.worker.signed_request = request
        self.worker.run_once()
        self.assertEqual([item[0] for item in calls], ["GET", "POST"])
        self.assertEqual(self.worker.state["acked_revision"], 3)

    def test_invalid_json_is_rejected_without_replacing_active(self):
        active = configuration_worker.ACTIVE_PATH
        configuration_worker.atomic_json_write(active, self.candidate(1))
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return b"{broken"
        with patch("urllib.request.urlopen", return_value=Response()):
            with self.assertRaisesRegex(RuntimeError, "invalid JSON"):
                self.worker.signed_request("GET", self.worker.configuration_path)
        self.assertEqual(json.loads(active.read_text())["revision"], 1)

    def test_authentication_failure_retains_last_known_good(self):
        error = urllib.error.HTTPError("url", 401, "bad signature", {}, None)
        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaisesRegex(RuntimeError, "HTTP 401"):
                self.worker.signed_request("GET", self.worker.configuration_path)
        self.assertFalse(configuration_worker.ACTIVE_PATH.exists())

    def test_value_over_local_limit_rejects_whole_revision(self):
        candidate = self.candidate()
        candidate["motion_limits"]["azimuth_max_deg"] = 301
        with self.assertRaisesRegex(ValueError, "absolute encoder"):
            self.worker.validate(candidate)

    def test_atomic_write_failure_does_not_change_active_or_revision(self):
        configuration_worker.atomic_json_write(configuration_worker.ACTIVE_PATH, self.candidate(1))
        self.worker.signed_request = lambda *args: (200, {"configuration": self.candidate(3)})
        original = configuration_worker.atomic_json_write
        def fail_active(path, payload):
            if path == configuration_worker.ACTIVE_PATH:
                raise OSError("disk full")
            return original(path, payload)
        with patch.object(configuration_worker, "atomic_json_write", side_effect=fail_active):
            self.worker.run_once()
        self.assertEqual(json.loads(configuration_worker.ACTIVE_PATH.read_text())["revision"], 1)
        self.assertIsNone(self.worker.state["applied_revision"])

    def test_restart_recovers_applied_revision_from_active_file(self):
        configuration_worker.atomic_json_write(configuration_worker.ACTIVE_PATH, self.candidate(7))
        restarted = configuration_worker.ConfigurationWorker()
        self.assertEqual(restarted.state["applied_revision"], 7)

    def test_post_hash_is_over_exact_json_bytes(self):
        captured = {}
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return b"{}"
        def open_request(request, **kwargs):
            captured["request"] = request
            return Response()
        with patch("urllib.request.urlopen", side_effect=open_request):
            self.worker.acknowledge(3, "applied", "configuration applied successfully")
        request = captured["request"]
        self.assertEqual(request.headers["X-narit-body-sha256"], hashlib.sha256(request.data).hexdigest())


if __name__ == "__main__":
    unittest.main()
