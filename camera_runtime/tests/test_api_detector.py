import unittest
import json
import time
from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app import app, classic_detector, state
import config


class TestDetectorConfigAPI(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.client.testing = True

    def test_get_detector_config(self):
        res = self.client.get('/api/detector/config')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "ok")
        self.assertFalse(data["saved_to_disk"])
        self.assertIn("hotspot_threshold", data["detector_config"])
        self.assertIn("use_adaptive", data["detector_config"])

    def test_post_detector_config_runtime_only(self):
        # Read json file mtime before call
        json_path = BASE_DIR / "system_settings.json"
        mtime_before = json_path.stat().st_mtime if json_path.exists() else 0

        # Change in-memory threshold and toggle adaptive saliency
        payload = {
            "hotspot_threshold": 215,
            "use_adaptive": False,
            "adaptive_k": 3.5,
            "adaptive_min_threshold": 160
        }
        res = self.client.post('/api/detector/config', json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "ok")
        self.assertFalse(data["saved_to_disk"])
        self.assertEqual(data["detector_config"]["hotspot_threshold"], 215)
        self.assertEqual(data["detector_config"]["use_adaptive"], False)
        self.assertEqual(data["detector_config"]["adaptive_k"], 3.5)
        self.assertEqual(data["detector_config"]["adaptive_min_threshold"], 160)

        # Verify in-memory classic_detector is updated
        self.assertEqual(classic_detector.threshold, 215)
        self.assertEqual(classic_detector.use_adaptive, False)
        self.assertEqual(state["hotspot_threshold"], 215)
        self.assertEqual(state["use_adaptive"], False)

        # Verify json file was NOT modified
        mtime_after = json_path.stat().st_mtime if json_path.exists() else 0
        self.assertEqual(mtime_before, mtime_after)

    def test_sweep_control_accepts_detector_parameters(self):
        payload = {
            "action": "status",
            "hotspot_threshold": 220,
            "use_adaptive": True
        }
        res = self.client.post('/api/sweep/control', json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["active_parameters"]["hotspot_threshold"], 220)
        self.assertEqual(data["active_parameters"]["use_adaptive"], True)


if __name__ == '__main__':
    unittest.main()
