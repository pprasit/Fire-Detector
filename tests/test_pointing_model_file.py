import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import fire_detector.web_server as web_server


class PointingModelFileTests(unittest.TestCase):
    def test_model_is_written_as_an_independent_atomic_json_document(self):
        with tempfile.TemporaryDirectory() as directory:
            model_path = Path(directory) / "pointing_model.json"
            alignment = {"latest": None, "points": []}
            settings = {
                "station": {
                    "name": "NARIT#1",
                    "latitude": 18.48389,
                    "longitude": 98.01517,
                    "elevation_above_ground_m": 10.0,
                    "azimuth_north_offset_deg": 90.0,
                }
            }
            with patch.object(web_server, "POINTING_MODEL_PATH", model_path):
                web_server._write_pointing_model_file(alignment, settings)
                loaded = web_server._load_pointing_model_file()

            document = json.loads(model_path.read_text(encoding="utf-8"))
            self.assertEqual(document["schema_version"], 1)
            self.assertEqual(document["station"]["name"], "NARIT#1")
            self.assertEqual(document["pointing_alignment"]["points"], [])
            self.assertEqual(loaded["points"], [])
            self.assertEqual(loaded["model"]["point_count"], 0)

    def test_settings_omit_alignment_after_the_dedicated_file_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            model_path = Path(directory) / "pointing_model.json"
            model_path.write_text("{}\n", encoding="utf-8")
            settings = {
                "station": {"name": "NARIT#1"},
                "pointing_alignment": {"latest": None, "points": []},
            }
            with patch.object(web_server, "POINTING_MODEL_PATH", model_path):
                document = web_server._settings_document_without_pointing_model(settings)
            self.assertNotIn("pointing_alignment", document)
            self.assertEqual(document["station"]["name"], "NARIT#1")

    def test_legacy_alignment_is_preserved_until_first_model_file_is_created(self):
        with tempfile.TemporaryDirectory() as directory:
            model_path = Path(directory) / "pointing_model.json"
            settings = {"pointing_alignment": {"latest": None, "points": []}}
            with patch.object(web_server, "POINTING_MODEL_PATH", model_path):
                document = web_server._settings_document_without_pointing_model(settings)
            self.assertIn("pointing_alignment", document)


if __name__ == "__main__":
    unittest.main()
