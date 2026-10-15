from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fire_detector import web_server


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = (PROJECT_ROOT / "web/static/desktop/js/dashboard.js").read_text(encoding="utf-8")
TERRAIN = (PROJECT_ROOT / "web/static/desktop/js/pointing_terrain_3d.js").read_text(encoding="utf-8")
TEMPLATE = (PROJECT_ROOT / "web/templates/desktop/index.html").read_text(encoding="utf-8")
CSS = (PROJECT_ROOT / "web/static/desktop/css/dashboard.css").read_text(encoding="utf-8")


class PointingFavoriteTests(unittest.TestCase):
    def test_favorite_is_upserted_by_grid_cell_in_device_database(self):
        sample = {
            "grid_cell": {"id": "R0001C0002"},
            "latitude": 18.4,
            "longitude": 98.0,
            "elevation_m": 812.5,
        }
        with TemporaryDirectory() as directory:
            database = Path(directory) / "favorites.sqlite3"
            with patch.object(web_server, "POINTING_FAVORITES_DATABASE_PATH", database):
                first = web_server._save_pointing_favorite(sample)
                sample["elevation_m"] = 813.0
                second = web_server._save_pointing_favorite(sample)
                favorites = web_server._load_pointing_favorites()
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(favorites), 1)
        self.assertEqual(favorites[0]["elevation_m"], 813.0)

    def test_favorite_can_be_deleted_by_id(self):
        sample = {
            "grid_cell": {"id": "R0003C0004"},
            "latitude": 18.5,
            "longitude": 98.1,
            "elevation_m": 900.0,
        }
        with TemporaryDirectory() as directory:
            database = Path(directory) / "favorites.sqlite3"
            with patch.object(web_server, "POINTING_FAVORITES_DATABASE_PATH", database):
                favorite = web_server._save_pointing_favorite(sample)
                deleted = web_server._delete_pointing_favorite(favorite["id"])
                deleted_again = web_server._delete_pointing_favorite(favorite["id"])
                favorites = web_server._load_pointing_favorites()
        self.assertTrue(deleted)
        self.assertFalse(deleted_again)
        self.assertEqual(favorites, [])

    def test_right_click_popup_and_saved_marker_workflow_is_wired(self):
        self.assertIn('new CustomEvent("pointing-map-favorite-request"', TERRAIN)
        self.assertIn('pointingHoverSaveFavorite', TERRAIN)
        self.assertIn('saveFavoriteButton.textContent = "ADD FAVORITE POINT"', TERRAIN)
        self.assertIn('coordinateRow("ELEV", "pointingHoverElevation")', TERRAIN)
        self.assertIn('id="pointingHoverElevation"', TEMPLATE)
        self.assertIn('id="pointingHoverSaveFavorite"', TEMPLATE)
        self.assertIn("ADD FAVORITE POINT", TEMPLATE)
        self.assertIn('fetch("/api/pointing/favorites"', DASHBOARD)
        self.assertIn('setFavoritePoints(pointingFavorites)', DASHBOARD)
        self.assertIn('pickFavorite(event)', DASHBOARD)
        self.assertIn("const cyan = 0x38bdf8", TERRAIN)

    def test_favorite_table_window_and_live_compensated_goto_are_wired(self):
        for identifier in (
            "pointingFavoriteOpen",
            "pointingFavoriteWindow",
            "pointingFavoriteBody",
            "pointingFavoriteClose",
        ):
            self.assertIn(identifier, DASHBOARD if identifier == "pointingFavoriteOpen" else TEMPLATE + DASHBOARD)
        self.assertIn('favoritePoints.innerHTML', DASHBOARD)
        self.assertIn('<span>Favorite Point</span>', DASHBOARD)
        self.assertIn('const sample = await fetchPointingSample(favorite)', DASHBOARD)
        self.assertIn('sendMotorCommand("goto", { Azimuth: String(azimuth), Altitude: String(altitude) })', DASHBOARD)
        self.assertIn(".pointing-favorite-window", CSS)
        self.assertIn(".favorite-point-goto", CSS)
        self.assertIn(".favorite-point-delete", CSS)
        self.assertIn("deleteFavoritePoint", DASHBOARD)
        self.assertIn('method: "DELETE"', DASHBOARD)

    def test_point_layers_and_high_resolution_jpeg_export_are_wired(self):
        self.assertIn("pointingLayerPointing", TEMPLATE)
        self.assertIn("pointingLayerPointing", DASHBOARD)
        self.assertIn("pointingLayerTrackingArea", TEMPLATE)
        self.assertIn("pointingLayerTrackingArea", DASHBOARD)
        self.assertIn("directionOverlay: fields.pointingLayerTrackingArea", DASHBOARD)
        self.assertNotIn('id="pointingLayerTerrain"', TEMPLATE)
        self.assertNotIn('id="pointingLayerGrid"', TEMPLATE)
        self.assertNotIn('id="pointingLayerFavoritePoints"', TEMPLATE)
        self.assertNotIn('id="pointingLayerDirectionOverlay"', TEMPLATE)
        self.assertIn("this.alignmentMarkers.visible = this.modelPointsEnabled", TERRAIN)
        self.assertIn("this.scanCoverage.visible = this.directionOverlayEnabled", TERRAIN)
        self.assertIn("this.northIndicator.visible = this.directionOverlayEnabled", TERRAIN)
        self.assertIn("async captureJpeg", TERRAIN)
        self.assertIn('"image/jpeg"', TERRAIN)
        self.assertIn("3840 / baseWidth", TERRAIN)
        self.assertIn("visiblePointingScreenshotOverlays", DASHBOARD)
        self.assertIn("paintPointingSelectionOverlay", TERRAIN)
        self.assertIn("paintScreenshotButton", TERRAIN)
        self.assertNotIn("new XMLSerializer()", TERRAIN)
        self.assertNotIn("<foreignObject", TERRAIN)
        self.assertIn("pointingSaveScreenshot", DASHBOARD)

    def test_visibility_mask_is_black_only_and_uses_station_installation_height(self):
        from PIL import Image

        self.assertEqual(
            web_server._station_device_elevation(812.5, {"elevation_above_ground_m": 10.0}),
            822.5,
        )
        with TemporaryDirectory() as directory, patch.object(
            web_server,
            "POINTING_CACHE_DIR",
            Path(directory),
        ):
            sources = web_server._write_pointing_raster_pngs(
                [812.5, 813.0],
                [True, False],
                2,
                812.5,
                813.0,
                "visibility-test",
            )
            image_name = sources["visibility"].rsplit("/", 1)[-1]
            mask = Image.open(Path(directory) / image_name).convert("RGBA")
        self.assertEqual(mask.getpixel((0, 0)), (0, 0, 0, 0))
        self.assertEqual(mask.getpixel((1, 0)), (0, 0, 0, 190))
        self.assertIn("configureVisibilityMask(material)", TERRAIN)
        self.assertIn("vGlobalVisibilityUv", TERRAIN)
        self.assertIn("diffuseColor.rgb *= 1.0 - visibilityShadow", TERRAIN)
        self.assertIn("this.visibilityOpacity = layers.visibility === false ? 0 : 0.96", TERRAIN)


if __name__ == "__main__":
    unittest.main()
