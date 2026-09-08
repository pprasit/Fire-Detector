import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import fire_detector.web_server as web_server


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = PROJECT_ROOT / "web" / "templates" / "desktop" / "index.html"
SCRIPT = PROJECT_ROOT / "web" / "static" / "desktop" / "js" / "dashboard.js"
SERVER = PROJECT_ROOT / "src" / "fire_detector" / "web_server.py"


class RuntimeSettingsApplyTests(unittest.TestCase):
    def test_runtime_apply_changes_cache_without_writing_settings_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            settings_path = Path(temporary) / "AppSetting.JSON"
            remote_path = Path(temporary) / "active-station-configuration.json"
            original = web_server._default_app_settings()
            settings_path.write_text(json.dumps(original), encoding="utf-8")
            original_bytes = settings_path.read_bytes()

            with patch.multiple(
                web_server,
                APP_SETTINGS_PATH=settings_path,
                ACTIVE_STATION_CONFIGURATION_PATH=remote_path,
                _SETTINGS_CACHE=None,
                _SETTINGS_MTIME=None,
                _REMOTE_SETTINGS_MTIME=None,
            ):
                applied = web_server._merge_app_settings(
                    {"motion_limits": {"azimuth_position_offset_deg": 17.25}},
                    persist=False,
                )
                effective = web_server._load_app_settings()

            self.assertEqual(settings_path.read_bytes(), original_bytes)
            self.assertEqual(applied["motion_limits"]["azimuth_position_offset_deg"], 17.25)
            self.assertEqual(effective["motion_limits"]["azimuth_position_offset_deg"], 17.25)

    def test_invalid_runtime_apply_does_not_mutate_active_cache(self):
        baseline = web_server._default_app_settings()
        with patch.object(web_server, "_load_app_settings", return_value=baseline):
            with self.assertRaises(ValueError):
                web_server._merge_app_settings(
                    {"motion_limits": {"azimuth_position_offset_deg": "invalid"}},
                    persist=False,
                )
        self.assertEqual(baseline, web_server._default_app_settings())

    def test_ui_and_endpoint_keep_apply_separate_from_save(self):
        template = TEMPLATE.read_text(encoding="utf-8")
        script = SCRIPT.read_text(encoding="utf-8")
        server = SERVER.read_text(encoding="utf-8")

        self.assertIn('id="settingsApply">Apply Settings</button>', template)
        self.assertIn('fetchWithTimeout("/api/settings/apply"', script)
        self.assertIn('fields.settingsApply?.addEventListener("click", applySystemSettings)', script)
        self.assertIn("Paint cached values immediately", script)
        self.assertIn("Promise.allSettled([", script)
        self.assertIn("if (!statusStreamConnected) void refreshStatus()", script)

        apply_route = server.split('@app.post("/api/settings/apply")', 1)[1].split(
            '@app.post("/api/settings")', 1
        )[0]
        self.assertIn("persist=False", apply_route)
        self.assertNotIn("flash_motion_limits", apply_route)
        self.assertNotIn("reload_configuration", apply_route)
        self.assertNotIn("station_configuration_saved", apply_route)
        self.assertIn("if position_conversion_changed:", apply_route)


if __name__ == "__main__":
    unittest.main()
