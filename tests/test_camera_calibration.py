import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import fire_detector.web_server as web_server


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DESKTOP_TEMPLATE = PROJECT_ROOT / "web" / "templates" / "desktop" / "index.html"
DESKTOP_SCRIPT = PROJECT_ROOT / "web" / "static" / "desktop" / "js" / "dashboard.js"


class CameraCalibrationTests(unittest.TestCase):
    def test_default_calibration_uses_centered_visible_image_and_ten_pixel_step(self):
        self.assertEqual(
            web_server._default_app_settings()["camera_calibration"],
            {
                "visible_offset_x_px": 0,
                "visible_offset_y_px": 0,
                "step_px": 10,
                "visible_crop_width_px": 640,
                "visible_crop_height_px": 512,
            },
        )

    def test_calibration_values_are_validated_as_bounded_whole_pixels(self):
        self.assertEqual(
            web_server._clean_camera_calibration(
                {
                    "visible_offset_x_px": -18,
                    "visible_offset_y_px": 27,
                    "step_px": 5,
                    "visible_crop_width_px": 640,
                    "visible_crop_height_px": 512,
                }
            ),
            {
                "visible_offset_x_px": -18,
                "visible_offset_y_px": 27,
                "step_px": 5,
                "visible_crop_width_px": 640,
                "visible_crop_height_px": 512,
            },
        )
        with self.assertRaisesRegex(ValueError, "whole number"):
            web_server._clean_camera_calibration({"visible_offset_x_px": 1.5})
        with self.assertRaisesRegex(ValueError, "between 1 and 1000"):
            web_server._clean_camera_calibration({"step_px": 0})
        with self.assertRaisesRegex(ValueError, "between 1 and 32768"):
            web_server._clean_camera_calibration({"visible_crop_width_px": 0})

    def test_calibration_is_persisted_in_app_settings(self):
        with tempfile.TemporaryDirectory() as temporary:
            settings_path = Path(temporary) / "AppSetting.JSON"
            remote_path = Path(temporary) / "active-station-configuration.json"
            with patch.multiple(
                web_server,
                APP_SETTINGS_PATH=settings_path,
                ACTIVE_STATION_CONFIGURATION_PATH=remote_path,
                _SETTINGS_CACHE=None,
                _SETTINGS_MTIME=None,
                _REMOTE_SETTINGS_MTIME=None,
            ):
                settings = web_server._merge_app_settings(
                    {
                        "camera_calibration": {
                            "visible_offset_x_px": 40,
                            "visible_offset_y_px": -20,
                            "step_px": 10,
                            "visible_crop_width_px": 800,
                            "visible_crop_height_px": 600,
                        }
                    }
                )
                saved = json.loads(settings_path.read_text(encoding="utf-8"))

            self.assertEqual(settings["camera_calibration"], saved["camera_calibration"])
            self.assertEqual(saved["camera_calibration"]["visible_offset_x_px"], 40)
            self.assertEqual(saved["camera_calibration"]["visible_offset_y_px"], -20)
            self.assertEqual(saved["camera_calibration"]["visible_crop_width_px"], 800)
            self.assertEqual(saved["camera_calibration"]["visible_crop_height_px"], 600)

    def test_desktop_ui_has_calibration_controls_and_one_shared_preview_clock(self):
        template = DESKTOP_TEMPLATE.read_text(encoding="utf-8")
        script = DESKTOP_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("Cameras Calibration", template)
        self.assertIn('data-calibration-nudge="up"', template)
        self.assertIn('data-calibration-nudge="down"', template)
        self.assertIn('data-calibration-nudge="left"', template)
        self.assertIn('data-calibration-nudge="right"', template)
        self.assertIn('id="cameraCalibrationCropWidth"', template)
        self.assertIn('id="cameraCalibrationCropHeight"', template)
        self.assertIn('id="cameraCalibrationReset"', template)
        self.assertIn("drawCameraCalibrationPreview", script)
        self.assertIn("drawCalibrationCropBox", script)
        self.assertIn("resetCameraCalibrationCrop", script)
        self.assertIn("configureCameraCalibrationPreviewGeometry", script)
        self.assertIn("sharedHeight * visible.width / visible.height", script)
        self.assertIn("Math.max(width / sourceWidth, height / sourceHeight)", script)
        self.assertIn("renderAt - cameraCalibrationLastRenderAt >= 100", script)
        self.assertIn("camera_calibration: values, flash_drives: false", script)


if __name__ == "__main__":
    unittest.main()
