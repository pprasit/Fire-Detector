from pathlib import Path
import unittest

from fire_detector.web_server import (
    _apply_pointing_alignment_model,
    _calculate_alignment_position_offsets,
    _clean_pointing_alignment,
    _earth_curvature_drop_m,
    _fit_pointing_alignment_model,
    _mount_direction_through_pointing_model,
    _sightline_geometry,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVER = (PROJECT_ROOT / "src" / "fire_detector" / "web_server.py").read_text(encoding="utf-8")


class PointingAlignmentOffsetTests(unittest.TestCase):
    def test_hardware_offset_formulas_rebase_both_displayed_axes(self):
        result = _calculate_alignment_position_offsets(
            target_azimuth_deg=280.906,
            target_altitude_deg=-3.764,
            telemetry_azimuth_deg=175.773,
            telemetry_altitude_deg=0.302,
            previous_azimuth_offset_deg=125.0,
            previous_altitude_offset_deg=178.0,
            azimuth_scale=-1.0,
            altitude_scale=1.0,
        )
        self.assertAlmostEqual(result["residual_azimuth_deg"], 105.133)
        self.assertAlmostEqual(result["calculated_azimuth_position_offset_deg"], 19.867)
        self.assertAlmostEqual(result["residual_altitude_deg"], -4.066)
        self.assertAlmostEqual(result["calculated_altitude_position_offset_deg"], 173.934)

    def test_reversed_altitude_axis_applies_residual_with_inverse_sign(self):
        result = _calculate_alignment_position_offsets(
            target_azimuth_deg=10.0,
            target_altitude_deg=-5.0,
            telemetry_azimuth_deg=8.0,
            telemetry_altitude_deg=-2.0,
            previous_azimuth_offset_deg=20.0,
            previous_altitude_offset_deg=30.0,
            azimuth_scale=1.0,
            altitude_scale=-1.0,
        )
        self.assertEqual(result["calculated_azimuth_position_offset_deg"], 18.0)
        self.assertEqual(result["calculated_altitude_position_offset_deg"], 33.0)

    def test_invalid_axis_scale_is_rejected(self):
        with self.assertRaises(ValueError):
            _calculate_alignment_position_offsets(
                target_azimuth_deg=0.0,
                target_altitude_deg=0.0,
                telemetry_azimuth_deg=0.0,
                telemetry_altitude_deg=0.0,
                previous_azimuth_offset_deg=0.0,
                previous_altitude_offset_deg=0.0,
                azimuth_scale=0.0,
                altitude_scale=1.0,
            )

    def test_calculation_audit_fields_are_preserved(self):
        latest = {
            "grid_cell": "R0792C0643",
            "latitude": 18.449925,
            "longitude": 98.008562,
            "dem_azimuth_deg": 280.456,
            "dem_altitude_deg": -3.964,
            "camera_offset_azimuth_deg": 0.45,
            "camera_offset_altitude_deg": 0.2,
            "expected_mount_azimuth_deg": 280.906,
            "expected_mount_altitude_deg": -3.764,
            "telemetry_azimuth_deg": 175.773,
            "telemetry_altitude_deg": 0.302,
            "residual_azimuth_deg": 105.133,
            "residual_altitude_deg": -4.066,
            "previous_azimuth_position_offset_deg": 125.0,
            "previous_altitude_position_offset_deg": 178.0,
            "calculated_azimuth_position_offset_deg": 19.867,
            "calculated_altitude_position_offset_deg": 173.934,
            "azimuth_position_scale": -1.0,
            "altitude_position_scale": 1.0,
            "raw_azimuth_encoder_deg": -300.773,
            "raw_altitude_encoder_deg": -177.698,
            "saved_at": "2026-09-02T14:00:00Z",
        }
        cleaned = _clean_pointing_alignment({"latest": latest})["latest"]
        self.assertEqual(cleaned["calculated_azimuth_position_offset_deg"], 19.867)
        self.assertEqual(cleaned["calculated_altitude_position_offset_deg"], 173.934)
        self.assertEqual(cleaned["azimuth_position_scale"], -1.0)

    def test_endpoint_builds_model_without_rebasing_encoder_coordinates(self):
        endpoint_start = SERVER.index('def api_pointing_alignment_point()')
        endpoint = SERVER[endpoint_start:endpoint_start + 7000]
        self.assertIn('"points": points', endpoint)
        self.assertNotIn("monitor.rebase_position_offsets()", endpoint)
        self.assertNotIn("goto_positions", endpoint)
        self.assertNotIn("set_velocities", endpoint)

    def test_multi_point_model_recovers_known_mount_yaw(self):
        points = []
        for index, (reference_azimuth, reference_altitude) in enumerate(((20, 2), (120, 10), (250, -4))):
            points.append({
                "id": f"point-{index}",
                "grid_cell": f"R{index:04d}C0000",
                "latitude": 18.4,
                "longitude": 98.0,
                "elevation_m": 500.0,
                "distance_m": 5000.0,
                "curvature_drop_m": 1.7,
                "slant_range_m": 5000.0,
                "reference_azimuth_deg": reference_azimuth,
                "reference_altitude_deg": reference_altitude,
                "telemetry_azimuth_deg": reference_azimuth + 7.0,
                "telemetry_altitude_deg": reference_altitude,
                "camera_offset_azimuth_deg": 0.0,
                "camera_offset_altitude_deg": 0.0,
                "saved_at": "2026-09-02T12:00:00Z",
            })
        model = _fit_pointing_alignment_model(points)
        self.assertTrue(model["active"])
        self.assertAlmostEqual(model["rms_error_deg"], 0.0, places=4)
        command_azimuth, command_altitude, applied = _apply_pointing_alignment_model(80.0, 5.0, model)
        self.assertTrue(applied)
        self.assertAlmostEqual(command_azimuth, 87.0, places=4)
        self.assertAlmostEqual(command_altitude, 5.0, places=4)
        pointing_azimuth, pointing_altitude, inverse_applied = _mount_direction_through_pointing_model(
            command_azimuth,
            command_altitude,
            model,
        )
        self.assertTrue(inverse_applied)
        self.assertAlmostEqual(pointing_azimuth, 80.0, places=4)
        self.assertAlmostEqual(pointing_altitude, 5.0, places=4)

    def test_first_point_activates_live_offset_compensation(self):
        template = {
            "reference_altitude_deg": -8.0,
            "telemetry_altitude_deg": -11.0,
        }
        one = [{**template, "reference_azimuth_deg": 10.0, "telemetry_azimuth_deg": 11.0}]
        model = _fit_pointing_alignment_model(one)
        self.assertTrue(model["active"])
        self.assertEqual(model["mode"], "single_point_offset")
        command_azimuth, command_altitude, applied = _apply_pointing_alignment_model(80.0, 5.0, model)
        self.assertTrue(applied)
        self.assertAlmostEqual(command_azimuth, 81.0)
        self.assertAlmostEqual(command_altitude, 2.0)
        pointing_azimuth, pointing_altitude, inverse_applied = _mount_direction_through_pointing_model(
            command_azimuth,
            command_altitude,
            model,
        )
        self.assertTrue(inverse_applied)
        self.assertAlmostEqual(pointing_azimuth, 80.0)
        self.assertAlmostEqual(pointing_altitude, 5.0)

    def test_status_payload_keeps_raw_mount_and_pointing_coordinates_separate(self):
        self.assertIn('axis["mount_position_deg"] = axis.get("position_deg")', SERVER)
        self.assertIn('axis["pointing_position_deg"] = axis.get("position_deg")', SERVER)
        self.assertIn("_mount_direction_through_pointing_model(", SERVER)

    def test_single_point_altitude_offset_maps_reference_to_observed_mount(self):
        model = _fit_pointing_alignment_model([{
            "reference_azimuth_deg": 93.538,
            "telemetry_azimuth_deg": 93.247382,
            "reference_altitude_deg": -8.669,
            "telemetry_altitude_deg": -11.268715,
        }])
        self.assertAlmostEqual(model["altitude_offset_deg"], -2.599715)
        _, command_altitude, applied = _apply_pointing_alignment_model(-8.0, -8.669, model)
        self.assertTrue(applied)
        self.assertAlmostEqual(command_altitude, -11.268715)

    def test_two_close_points_wait_for_better_rigid_fit(self):
        template = {
            "reference_altitude_deg": 0.0,
            "telemetry_altitude_deg": 0.0,
        }
        one = [{**template, "reference_azimuth_deg": 10.0, "telemetry_azimuth_deg": 11.0}]
        close = one + [{**template, "reference_azimuth_deg": 12.0, "telemetry_azimuth_deg": 13.0}]
        model = _fit_pointing_alignment_model(close)
        self.assertFalse(model["active"])
        self.assertIn("too close", model["status"])

    def test_sightline_geometry_reports_curvature_and_slant_range(self):
        geometry = _sightline_geometry(1000.0, 1000.0, 20000.0)
        self.assertAlmostEqual(geometry["curvature_drop_m"], _earth_curvature_drop_m(20000.0))
        self.assertLess(geometry["altitude_deg"], 0.0)
        self.assertGreater(geometry["slant_range_m"], 20000.0)


if __name__ == "__main__":
    unittest.main()
