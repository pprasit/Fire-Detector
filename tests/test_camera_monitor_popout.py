from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = PROJECT_ROOT / "web" / "templates" / "camera_monitor.html"
SCRIPT = PROJECT_ROOT / "web" / "static" / "desktop" / "js" / "camera_monitor.js"
CSS = PROJECT_ROOT / "web" / "static" / "desktop" / "css" / "camera_monitor.css"
SERVER = PROJECT_ROOT / "src" / "fire_detector" / "web_server.py"


class CameraMonitorPopoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = TEMPLATE.read_text(encoding="utf-8")
        cls.script = SCRIPT.read_text(encoding="utf-8")
        cls.css = CSS.read_text(encoding="utf-8")
        cls.server = SERVER.read_text(encoding="utf-8")

    def test_standalone_route_and_two_live_feeds_exist(self):
        self.assertIn('@app.get("/camera-monitor")', self.server)
        self.assertIn('id="thermalImage"', self.template)
        self.assertIn('id="visibleImage"', self.template)
        self.assertIn("/api/camera-frame/latest-pair/live", self.script)
        self.assertNotIn("/api/camera-mjpeg/live/", self.script)
        self.assertNotIn("new EventSource", self.script)
        self.assertIn('response.headers.get("X-Camera-Pair-Metadata")', self.script)
        self.assertIn("setTimeout(() => controller.abort(), 3000)", self.script)
        self.assertIn("Promise.allSettled", self.script)
        self.assertIn('displayCameraBlob("thermal"', self.script)
        self.assertIn('displayCameraBlob("visible"', self.script)
        self.assertIn("NCP1", self.server)
        self.assertIn("X-Camera-Pair-Metadata", self.server)

    def test_standalone_monitor_has_jog_and_offset_direction_controls(self):
        self.assertIn('id="directionMode"', self.template)
        self.assertIn('value="jog"', self.template)
        self.assertIn('value="offset"', self.template)
        self.assertIn('/api/motors/velocity-command', self.script)
        self.assertIn('/api/motors/goto', self.script)
        self.assertIn('X-Motion-Client-ID', self.script)
        self.assertIn("Math.hypot(azimuthSign, altitudeSign)", self.script)

    def test_monitor_stops_jog_when_tab_loses_control(self):
        self.assertIn('window.addEventListener("blur", stop)', self.script)
        self.assertIn('document.addEventListener("visibilitychange"', self.script)
        self.assertIn('window.addEventListener("pagehide"', self.script)
        self.assertIn('keepalive: azimuth === 0 && altitude === 0', self.script)

    def test_second_display_layout_is_responsive(self):
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr))", self.css)
        self.assertIn("@media (max-width: 820px)", self.css)


if __name__ == "__main__":
    unittest.main()
