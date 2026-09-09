import json
import unittest
from unittest.mock import patch

from fire_detector.web_server import (
    _absolute_camera_zoom_target,
    _clean_pointing_alignment,
    _post_camera_zoom,
    _stepped_camera_zoom_target,
)


class _FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.payload


class CameraZoomControlTests(unittest.TestCase):
    def test_one_normalized_percentage_drives_both_camera_lenses(self):
        self.assertEqual(_stepped_camera_zoom_target(18.5, "in", 1), 19.5)
        self.assertEqual(_stepped_camera_zoom_target(18.5, "out", 1), 17.5)

    def test_targets_are_clamped_to_camera_percentage_limits(self):
        self.assertEqual(_stepped_camera_zoom_target(95, "in", 10), 100.0)
        self.assertEqual(_stepped_camera_zoom_target(5, "out", 10), 0.0)

    def test_invalid_direction_step_or_metadata_is_rejected(self):
        with self.assertRaises(ValueError):
            _stepped_camera_zoom_target(50, "left", 10)
        with self.assertRaises(ValueError):
            _stepped_camera_zoom_target(50, "in", 0)
        with self.assertRaises(ValueError):
            _stepped_camera_zoom_target(None, "in", 10)

    def test_absolute_linked_target_accepts_only_zero_to_one_hundred(self):
        self.assertEqual(_absolute_camera_zoom_target("66.4"), 66.4)
        self.assertEqual(_absolute_camera_zoom_target(0), 0.0)
        self.assertEqual(_absolute_camera_zoom_target(100), 100.0)
        with self.assertRaises(ValueError):
            _absolute_camera_zoom_target(100.1)
        with self.assertRaises(ValueError):
            _absolute_camera_zoom_target("")

    def test_upstream_command_uses_documented_absolute_zoom_api(self):
        response = _FakeResponse({"status": "ok", "camera": "all", "target_value": 60})
        with patch("fire_detector.web_server.urllib.request.urlopen", return_value=response) as urlopen:
            result = _post_camera_zoom("all", 60)

        request = urlopen.call_args.args[0]
        self.assertEqual(json.loads(request.data), {"camera": "all", "zoom_pct": 60})
        self.assertEqual(request.method, "POST")
        self.assertEqual(result["status"], "ok")

    def test_pointing_alignment_sample_is_validated_before_settings_save(self):
        latest = {
            "grid_cell": "R0795C0645",
            "latitude": 18.449202,
            "longitude": 98.009282,
            "dem_azimuth_deg": -80.853,
            "dem_altitude_deg": -4.369,
            "camera_offset_azimuth_deg": 0.2,
            "camera_offset_altitude_deg": -0.1,
            "expected_mount_azimuth_deg": -80.653,
            "expected_mount_altitude_deg": -4.469,
            "telemetry_azimuth_deg": -80.65,
            "telemetry_altitude_deg": -4.47,
            "residual_azimuth_deg": -0.003,
            "residual_altitude_deg": 0.001,
            "saved_at": "2026-09-02T12:00:00.000Z",
        }
        cleaned = _clean_pointing_alignment({"latest": latest})
        self.assertEqual(cleaned["latest"]["grid_cell"], "R0795C0645")
        self.assertEqual(cleaned["latest"]["camera_offset_azimuth_deg"], 0.2)
        with self.assertRaises(ValueError):
            _clean_pointing_alignment({"latest": {**latest, "latitude": 91}})


if __name__ == "__main__":
    unittest.main()
