from pathlib import Path
import unittest

from fire_detector.camera_frame_pool import (
    CAMERA_POOL_PROFILES,
    CameraFramePool,
    CameraSourceValidationError,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class CameraFramePoolTests(unittest.TestCase):
    def test_pool_discards_superseded_frames_instead_of_queueing(self):
        pool = CameraFramePool()
        with pool.updated:
            first = pool.store_locked("live", "thermal", b"first", "image/jpeg", {"zoom_pct": 1, "simulated": False, "source_verified": True})
            second = pool.store_locked("live", "thermal", b"second", "image/jpeg", {"zoom_pct": 2, "simulated": False, "source_verified": True})

        latest = pool.latest("live", "thermal")
        self.assertIsNotNone(latest)
        self.assertEqual(latest["data"], b"second")
        self.assertGreater(second["sequence"], first["sequence"])
        with pool.lock:
            status = pool.status_locked()
        self.assertEqual(status["architecture"]["queue_depth_per_camera"], 1)
        self.assertEqual(status["sources"]["live"]["cameras"]["thermal"]["retained_frames"], 1)

    def test_production_pool_rejects_simulation_and_unverified_live_frames(self):
        pool = CameraFramePool(simulation_enabled=False)
        with pool.updated:
            with self.assertRaisesRegex(CameraSourceValidationError, "Simulation frames are disabled"):
                pool.store_locked("simulation", "thermal", b"fake", "image/jpeg", {"simulated": True})
            with self.assertRaisesRegex(CameraSourceValidationError, "must explicitly declare"):
                pool.store_locked("live", "thermal", b"fake", "image/jpeg", {"simulated": True})
            with self.assertRaisesRegex(CameraSourceValidationError, "must explicitly declare"):
                pool.store_locked("live", "thermal", b"unknown", "image/jpeg", {})
            with self.assertRaisesRegex(CameraSourceValidationError, "source_verified=true"):
                pool.store_locked("live", "thermal", b"unverified", "image/jpeg", {"simulated": False})

    def test_simulation_pool_accepts_explicit_simulation_frames(self):
        pool = CameraFramePool(simulation_enabled=True)
        with pool.updated:
            pool.store_locked("simulation", "thermal", b"simulation", "image/jpeg", {"simulated": True})
        self.assertEqual(pool.latest("simulation", "thermal")["data"], b"simulation")

    def test_pointing_policy_is_owned_by_the_central_pool(self):
        self.assertEqual(CAMERA_POOL_PROFILES["pointing"]["max_fps"], 10)
        self.assertEqual(CAMERA_POOL_PROFILES["pointing"]["dimensions"]["thermal"], (400, 320))
        self.assertEqual(CAMERA_POOL_PROFILES["pointing"]["dimensions"]["visible"], (480, 270))

    def test_dashboard_variants_do_not_open_a_second_frame_websocket(self):
        scripts = (
            PROJECT_ROOT / "web" / "static" / "js" / "dashboard.js",
            PROJECT_ROOT / "web" / "static" / "mobile" / "js" / "dashboard.js",
            PROJECT_ROOT / "web" / "static" / "desktop" / "js" / "dashboard.js",
        )
        for script in scripts:
            source = script.read_text(encoding="utf-8")
            self.assertNotIn("role=viewer", source, script.as_posix())
            self.assertNotIn("cameraStreamWebSocketUrl", source, script.as_posix())
            self.assertNotIn("rtsp://", source, script.as_posix())


if __name__ == "__main__":
    unittest.main()
