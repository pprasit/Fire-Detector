from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class CameraPairControlTests(unittest.TestCase):
    def test_shared_control_enforces_native_ratios_without_cropping(self):
        css = (ROOT / "web/static/shared/camera_pair_control.css").read_text()
        self.assertIn("aspect-ratio:5 / 4", css)
        self.assertIn("aspect-ratio:16 / 9", css)
        self.assertIn("object-fit:contain!important", css)

    def test_shared_control_supports_both_layouts(self):
        css = (ROOT / "web/static/shared/camera_pair_control.css").read_text()
        self.assertIn('data-layout="horizontal"', css)
        self.assertIn('data-layout="vertical"', css)

    def test_all_camera_pages_load_the_shared_control(self):
        paths = [
            ROOT / "web/templates/desktop/index.html",
            ROOT / "web/templates/mobile/index.html",
            ROOT / "web/templates/index.html",
            ROOT / "web/templates/camera_monitor.html",
            ROOT / "web/static/desktop/mission-design.html",
        ]
        for path in paths:
            with self.subTest(path=path.name):
                page = path.read_text()
                self.assertIn("camera_pair_control.css", page)
                self.assertIn("camera_pair_control.js", page)
                self.assertNotIn("1920 × 1080", page)


if __name__ == "__main__":
    unittest.main()
