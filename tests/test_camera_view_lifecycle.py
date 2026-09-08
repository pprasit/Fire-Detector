from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DESKTOP_SCRIPT = PROJECT_ROOT / "web" / "static" / "desktop" / "js" / "dashboard.js"
DESKTOP_TEMPLATE = PROJECT_ROOT / "web" / "templates" / "desktop" / "index.html"
WEB_SERVER = PROJECT_ROOT / "src" / "fire_detector" / "web_server.py"


class CameraViewLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = DESKTOP_SCRIPT.read_text(encoding="utf-8")
        cls.template = DESKTOP_TEMPLATE.read_text(encoding="utf-8")
        cls.web_server = WEB_SERVER.read_text(encoding="utf-8")

    def test_viewer_uses_one_mjpeg_transport_per_camera(self):
        self.assertIn("/api/camera-mjpeg/${cameraSourceMode}/${camera}", self.script)
        self.assertNotIn("new WebSocket(cameraStreamWebSocketUrl())", self.script)

    def test_releasing_camera_view_removes_every_image_source(self):
        release_start = self.script.index("function releaseCameraStreams(")
        release_end = self.script.index("function updateCameraStreamReadyStatus(", release_start)
        release_body = self.script[release_start:release_end]
        self.assertIn("cameraStreamsWanted = false", release_body)
        self.assertIn("cameraStreamSession += 1", release_body)
        self.assertIn('image.removeAttribute("src")', release_body)

    def test_camera_view_has_connecting_feedback_for_both_streams(self):
        self.assertIn('data-camera-loader="thermal"', self.template)
        self.assertIn('data-camera-loader="visible"', self.template)
        self.assertIn("Establishing JPEG stream", self.template)

    def test_hidden_page_pauses_camera_streams(self):
        visibility_start = self.script.index('document.addEventListener("visibilitychange"')
        visibility_body = self.script[visibility_start:visibility_start + 900]
        self.assertIn("releaseCameraStreams", visibility_body)
        self.assertIn("startCameraStreams", visibility_body)

    def test_right_click_opens_metadata_panel_for_both_cameras(self):
        self.assertIn('id="cameraMetadataPanel"', self.template)
        self.assertIn('querySelector(".thermal-feed .camera-viewport")', self.script)
        self.assertIn('querySelector(".visible-feed .camera-viewport")', self.script)
        self.assertIn('addEventListener("contextmenu"', self.script)
        self.assertIn("new EventSource", self.script)
        self.assertIn("/api/camera-stream/metadata-stream/${cameraSourceMode}/${camera}", self.script)
        self.assertIn("cameraMetadataEventSource?.close()", self.script)

    def test_backend_exposes_and_preserves_frame_metadata(self):
        self.assertIn('@app.get("/api/camera-stream/metadata/<source>/<camera>")', self.web_server)
        self.assertIn('@app.get("/api/camera-stream/metadata-stream/<source>/<camera>")', self.web_server)
        self.assertIn('b"\\r\\nX-Camera-Metadata: "', self.web_server)

    def test_ffmpeg_preview_pipe_does_not_batch_small_thermal_frames(self):
        self.assertIn("stdout=subprocess.PIPE", self.web_server)
        self.assertIn("bufsize=0", self.web_server)

    def test_live_pointing_preview_uses_latest_frame_without_transcoding_queue(self):
        self.assertIn('@app.get("/api/camera-frame/latest/<source>/<camera>")', self.web_server)
        self.assertIn('"latest-frame-request"', self.web_server)
        self.assertIn('X-Camera-Transport', self.web_server)
        self.assertIn('"direct-latest-frame"', self.web_server)
        self.assertNotIn('source_url = f"http://127.0.0.1:{server_port}/api/camera-mjpeg/live/{camera}"', self.web_server)


if __name__ == "__main__":
    unittest.main()
