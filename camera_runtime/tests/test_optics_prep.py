import unittest
from unittest import mock
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from mission_controller import MissionController, MissionState
from camera_manager import CameraDevice


class MockCamera:
    def __init__(self, cam_id, min_focal, max_focal, wide_fov):
        self.cam_id = cam_id
        self.min_focal_mm = min_focal
        self.max_focal_mm = max_focal
        self.wide_fov_deg = wide_fov
        self.wide_h_fov = wide_fov
        self.current_focal_mm = min_focal
        self.af_triggered = False
        self.sharpness = 85.0
        self.latest_bgr = None

    def set_focal_length_mm(self, focal_mm):
        self.current_focal_mm = float(focal_mm)
        return True

    def trigger_auto_focus(self):
        self.af_triggered = True
        return True

    def compute_sharpness(self):
        return self.sharpness

    def _calculate_fov(self, focal_mm, min_focal_mm=None, wide_fov_deg=None):
        return CameraDevice._calculate_fov(
            focal_mm,
            min_focal_mm if min_focal_mm is not None else self.min_focal_mm,
            wide_fov_deg if wide_fov_deg is not None else self.wide_fov_deg
        )

    def calculate_focal_for_fov(self, target_fov_deg):
        return CameraDevice._calculate_focal_from_fov(target_fov_deg, self.min_focal_mm, self.wide_fov_deg)


class MockPTZ:
    def __init__(self):
        self.az = 0.0
        self.alt = 0.0
        self.stopped = False
        self._abort_slew = False

    def get_position(self):
        return self.az, self.alt

    def goto_position(self, az, alt, speed=10.0, wait=False, tolerance=0.5):
        self.az = az
        self.alt = alt
        return True

    def stop(self):
        self.stopped = True

    def set_velocity(self, az_vel, alt_vel):
        pass


class TestOpticsPrep(unittest.TestCase):
    def setUp(self):
        self.th_cam = MockCamera("thermal", 31.0, 155.0, 14.2)
        self.vis_cam = MockCamera("visible", 5.1, 102.0, 51.69)
        self.cam_mgr = mock.MagicMock()
        self.cam_mgr.get_thermal_camera.return_value = self.th_cam
        self.cam_mgr.get_visible_camera.return_value = self.vis_cam

        self.ptz = MockPTZ()
        self.verifier = mock.MagicMock()
        self.verifier.tracks = []

        self.cfg = {
            "auto_sentry_enabled": False,
            "scan_az_start": 90.0,
            "scan_az_end": 180.0,
            "scan_alt_start": -10.0,
            "scan_alt_end": 0.0,
            "scan_focal_length_mm": 60.0,
            "visible_sync_scan_zoom": True,
            "visible_fov_multiplier": 2.0,
            "zoom_settle_wait_sec": 0.1,
            "focus_settle_sec": 0.1,
            "max_goto_speed": 10.0,
            "sweep_speed_deg_s": 1.0,
        }

        with mock.patch("threading.Thread"):
            self.mission = MissionController(self.cam_mgr, self.ptz, self.verifier, self.cfg)

    def test_start_sentry_initiates_preparing_optics(self):
        self.mission.start_sentry(
            az_start=90.0,
            az_end=180.0,
            focal_length_mm=60.0,
            visible_sync_scan_zoom=True,
            visible_fov_multiplier=2.0
        )
        self.assertEqual(self.mission.state, MissionState.PREPARING_OPTICS)
        self.assertTrue(self.mission._needs_optics_prep)
        self.assertTrue(self.mission.is_ai_paused)

    def test_prepare_scan_optics_adjusts_zoom_and_focus(self):
        self.mission.start_sentry(
            az_start=90.0,
            az_end=180.0,
            alt_start=-10.0,
            focal_length_mm=60.0,
            visible_sync_scan_zoom=True,
            visible_fov_multiplier=2.0
        )

        self.mission._prepare_scan_optics()

        self.assertAlmostEqual(self.th_cam.current_focal_mm, 60.0, places=1)
        self.assertAlmostEqual(self.vis_cam.current_focal_mm, 19.11, places=1)

        self.assertTrue(self.th_cam.af_triggered)
        self.assertTrue(self.vis_cam.af_triggered)

        self.assertAlmostEqual(self.ptz.az, 90.0, places=1)
        self.assertAlmostEqual(self.ptz.alt, -10.0, places=1)
        self.assertTrue(self.ptz.stopped)

        self.assertEqual(self.mission.state, MissionState.SEARCH_SWEEP)
        self.assertFalse(self.mission.is_ai_paused)
        self.assertFalse(self.mission._needs_optics_prep)

    def test_abort_during_prep_does_not_advance_to_search_sweep(self):
        self.mission.start_sentry(
            az_start=90.0,
            az_end=180.0,
            focal_length_mm=60.0
        )
        self.mission.stop_sentry()
        self.assertEqual(self.mission.state, MissionState.IDLE)
        self.assertFalse(self.mission._needs_optics_prep)

        self.mission._prepare_scan_optics()
        self.assertEqual(self.mission.state, MissionState.IDLE)


if __name__ == "__main__":
    unittest.main()

    def test_step_sweep_optics_prep(self):
        self.mission.start_sentry(
            scan_mode="STEP_SWEEP",
            az_start=90.0,
            az_end=180.0,
            alt_start=-10.0,
            focal_length_mm=60.0
        )
        self.mission._prepare_scan_optics()
        self.assertEqual(self.mission.state, MissionState.SEARCH_SWEEP)
        self.assertAlmostEqual(self.th_cam.current_focal_mm, 60.0, places=1)
        self.assertTrue(self.th_cam.af_triggered)
        self.assertFalse(self.mission.is_ai_paused)
