"""
Unit and Integration Tests for Thermal 360 Panorama System
Tests:
1. Optical calculations (FOV from focal length)
2. Hardware constraints (Azimuth >= 95.0 deg)
3. Snake / Zigzag grid generation and overlap consistency
4. Positional spherical stitcher with synthetic thermal frames
5. API endpoints (calculate, status, sessions)
"""

import os
import json
import shutil
import tempfile
import unittest
from unittest import mock
from pathlib import Path
import cv2
import numpy as np

import sys
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from thermal_panorama_engine import ThermalPanoramaEngine
from panorama_stitcher import ThermalPanoramaStitcher


class DummyCameraDevice:
    def __init__(self):
        self.focal_mm = 31.0
        self.latest_frame = np.full((480, 640, 3), 40, dtype=np.uint8)

    def set_focal_length_mm(self, target_mm: float):
        self.focal_mm = target_mm
        return True

    def get_latest_frame(self):
        # Generate synthetic thermal gradient with hot target
        frame = self.latest_frame.copy()
        cv2.circle(frame, (320, 240), 40, (200, 200, 255), -1)
        return frame, b"jpeg_bytes"


class DummyCameraManager:
    def __init__(self):
        self.cam = DummyCameraDevice()

    def get_thermal_camera(self):
        return self.cam

    def get_visible_camera(self):
        return None


class DummyPTZController:
    def __init__(self):
        self.az = 95.0
        self.alt = 0.0

    def goto_position(self, az, alt, **kwargs):
        self.az = az
        self.alt = alt
        return True

    def get_position(self):
        return self.az, self.alt

    def stop(self):
        pass


class StuckPTZController(DummyPTZController):
    def __init__(self):
        super().__init__()
        self.stop_called = False
        self.goto_calls = 0

    def goto_position(self, az, alt, **kwargs):
        self.goto_calls += 1
        return False

    def stop(self):
        self.stop_called = True


class TestThermalPanorama(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.cam_mgr = DummyCameraManager()
        self.ptz = DummyPTZController()
        self.engine = ThermalPanoramaEngine(self.cam_mgr, self.ptz, self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_optical_fov_calculation(self):
        self.assertEqual(self.engine.POSITION_TOLERANCE_DEG, 0.35)
        self.assertEqual(self.engine.MAX_POSITION_ATTEMPTS, 5)
        # At wide (31mm): should match baseline 14.2 x 11.4
        h31, v31 = self.engine.calculate_fov(31.0)
        self.assertAlmostEqual(h31, 14.2, delta=0.2)
        self.assertAlmostEqual(v31, 11.4, delta=0.2)

        # At 60mm: should be narrower (~7.36 x 5.90)
        h60, v60 = self.engine.calculate_fov(60.0)
        self.assertTrue(h60 < h31)
        self.assertTrue(v60 < v31)
        self.assertAlmostEqual(h60, 7.36, delta=0.3)

    def test_hardware_constraint_azimuth(self):
        # Requesting Azimuth -90° to +90° should be fully accepted without clamping
        plan = self.engine.calculate_grid_plan(
            az_min=-90.0,
            az_max=90.0,
            alt_min=-20.0,
            alt_max=0.0,
            focal_mm=60.0,
            overlap_pct=25.0
        )
        self.assertEqual(plan["az_min"], -90.0)
        self.assertEqual(plan["az_max"], 90.0)
        self.assertEqual(len(plan["warnings"]), 0)

        # Azimuth exceeding mount limit (-300 to 300) should be clamped
        plan_clamp = self.engine.calculate_grid_plan(
            az_min=-350.0,
            az_max=350.0,
            alt_min=-20.0,
            alt_max=0.0,
            focal_mm=31.0
        )
        self.assertEqual(plan_clamp["az_min"], -300.0)
        self.assertEqual(plan_clamp["az_max"], 300.0)

    def test_snake_grid_pattern(self):
        plan = self.engine.calculate_grid_plan(
            az_min=95.0,
            az_max=125.0,
            alt_min=-20.0,
            alt_max=0.0,
            focal_mm=31.0,
            overlap_pct=25.0
        )
        self.assertGreater(len(plan["waypoints"]), 0)
        # Check even row goes forward, odd row goes backward
        row0_wps = [w for w in plan["waypoints"] if w["row"] == 0]
        row1_wps = [w for w in plan["waypoints"] if w["row"] == 1]
        if len(row0_wps) >= 2 and len(row1_wps) >= 2:
            self.assertLess(row0_wps[0]["az"], row0_wps[-1]["az"])
            self.assertGreater(row1_wps[0]["az"], row1_wps[-1]["az"])

    def test_full_dome_uses_continuous_branch_inside_mount_limits(self):
        plan = self.engine.calculate_grid_plan(-180, 180, -15, 15, 43.4, 30)
        row_sizes = []
        for row in range(plan["rows_count"]):
            points = [p for p in plan["waypoints"] if p["row"] == row]
            row_sizes.append(len(points))
            physical = [p["az"] for p in points]
            self.assertTrue(all(self.engine.MIN_HARDWARE_AZIMUTH <= az <= self.engine.MAX_HARDWARE_AZIMUTH for az in physical))
            self.assertTrue(all(abs(b - a) < 15 for a, b in zip(physical, physical[1:])))
        self.assertEqual(len(set(row_sizes)), 1)

    def test_stitcher_positional_projection(self):
        stitcher = ThermalPanoramaStitcher()
        frames_dir = self.temp_dir / "test_frames"
        frames_dir.mkdir()

        frames_meta = []
        # Create 4 small test frames in 2x2 grid
        coords = [(95.0, -10.0), (105.0, -10.0), (105.0, 0.0), (95.0, 0.0)]
        for i, (az, alt) in enumerate(coords):
            img = np.full((120, 160, 3), 50 + i * 40, dtype=np.uint8)
            cv2.circle(img, (80, 60), 20, (255, 255, 255), -1)
            p = frames_dir / f"test_{i}.jpg"
            cv2.imwrite(str(p), img)
            frames_meta.append({
                "filepath": str(p),
                "az": az,
                "alt": alt
            })

        stitched, stats = stitcher.stitch_positional(
            frames_metadata=frames_meta,
            h_fov_deg=14.2,
            v_fov_deg=11.4,
            pixels_per_deg=20.0
        )
        self.assertIsNotNone(stitched)
        self.assertGreater(stitched.shape[0], 0)
        self.assertGreater(stitched.shape[1], 0)
        self.assertEqual(stats["placed_frames"], 4)
        self.assertEqual(
            stats["photometric_normalization"],
            "center_median+column_flat_field+overlap_gain_bias_edge_compensation+cosine_feather+panorama_column_equalization",
        )

    def test_save_session_writes_overwritable_grid_cells_and_manifest(self):
        session_dir = self.temp_dir / "panoramas" / "session_save_test"
        raw_dir = session_dir / "raw_frames"
        raw_dir.mkdir(parents=True)
        source = raw_dir / "frame_r00_c01_latest.jpg"
        cv2.imwrite(str(source), np.full((24, 32, 3), 71, dtype=np.uint8))
        plan = {
            "waypoints": [{"step_index": 1, "row": 0, "col": 1, "az": 10.0, "alt": -15.0}],
            "h_fov_deg": 14.2,
            "v_fov_deg": 11.4,
            "overlap_pct": 30.0,
            "step_alt_deg": 8.0,
        }
        metadata = {
            "frames": [{
                "step_index": 1,
                "row": 0,
                "col": 1,
                "az": 10.0,
                "alt": -15.0,
                "filepath": str(source),
            }]
        }
        (session_dir / "partial_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
        self.engine.session_state.update({
            "session_id": session_dir.name,
            "session_dir": str(session_dir),
            "plan": plan,
        })

        with mock.patch.object(self.engine, "_schedule_live_mosaic") as schedule:
            result = self.engine.save_current_session()

        self.assertTrue(result["success"])
        self.assertEqual(result["saved_frames"], 1)
        self.assertTrue((session_dir / "saved_grid" / "cell_r00_c01.jpg").is_file())
        self.assertTrue((session_dir / "saved_manifest.json").is_file())
        schedule.assert_called_once()

    def test_motion_failure_blocks_capture_and_preserves_cell(self):
        stuck_ptz = StuckPTZController()
        engine = ThermalPanoramaEngine(self.cam_mgr, stuck_ptz, self.temp_dir)
        session_dir = self.temp_dir / "session_motion_failure"
        (session_dir / "raw_frames").mkdir(parents=True)
        plan = {
            "waypoints": [{"step_index": 0, "row": 0, "col": 0, "az": 120.0, "alt": -15.0}],
            "h_fov_deg": 14.2,
            "v_fov_deg": 11.4,
            "overlap_pct": 30.0,
            "az_min": 0.0,
            "az_max": 360.0,
            "alt_min": -15.0,
            "alt_max": 15.0,
        }
        engine.session_state.update({"is_running": True, "start_time": 1.0, "total_steps": 1})

        with mock.patch("thermal_panorama_engine.time.sleep", return_value=None):
            engine._worker_capture(session_dir, plan, 31.0, 0.0, "test")

        self.assertEqual(engine.session_state["status"], "MOTION_ERROR")
        self.assertFalse(engine.session_state["is_running"])
        self.assertTrue(stuck_ptz.stop_called)
        self.assertEqual(stuck_ptz.goto_calls, 5)
        self.assertEqual(list((session_dir / "raw_frames").glob("*.jpg")), [])


if __name__ == "__main__":
    unittest.main()
