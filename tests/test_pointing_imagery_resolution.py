from pathlib import Path
import math
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import fire_detector.web_server as web_server


PROJECT_ROOT = Path(__file__).resolve().parents[1]
POINTING_SCRIPT = PROJECT_ROOT / "web" / "static" / "desktop" / "js" / "pointing_terrain_3d.js"
DASHBOARD_SCRIPT = PROJECT_ROOT / "web" / "static" / "desktop" / "js" / "dashboard.js"


class FakeImageryResponse:
    status = 200
    headers = {"Content-Type": "image/jpeg"}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return b"\xff\xd8\xffhigh-resolution-imagery"


class PointingImageryResolutionTests(unittest.TestCase):
    def test_arcgis_export_requests_4096_pixel_jpeg(self):
        with tempfile.TemporaryDirectory() as directory, (
            patch.object(web_server, "POINTING_CACHE_DIR", Path(directory))
        ), patch.object(
            web_server.urllib.request,
            "urlopen",
            return_value=FakeImageryResponse(),
        ) as urlopen:
            source = web_server._arcgis_imagery_src(
                {"latitude": 18.4839, "longitude": 98.0152},
                1334,
                30.0,
                "test-digest",
            )

        request_url = urlopen.call_args.args[0].full_url
        query = parse_qs(urlparse(request_url).query)
        self.assertEqual(query["size"], ["4096,4096"])
        self.assertEqual(query["format"], ["jpg"])
        self.assertEqual(query["compressionQuality"], ["88"])
        self.assertTrue(source.endswith("_satellite.jpg"))

    def test_3d_view_prefers_4k_texture_and_allows_closer_zoom(self):
        script = POINTING_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("satellite_high_resolution_src", script)
        self.assertIn("satellite_detail_src", script)
        self.assertIn("satellite_precision_src", script)
        self.assertIn('name: "station-detail-imagery"', script)
        self.assertIn('name: "station-precision-imagery"', script)
        self.assertIn("maxTextureSize >= 4096", script)
        self.assertIn("this.controls.minDistance = 8", script)
        self.assertIn("this.controls.maxDistance = 120000", script)
        self.assertIn("this.controls.zoomToCursor = true", script)

    def test_terrain_uses_true_scale_and_preserves_imagery_detail(self):
        script = POINTING_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("const verticalExaggeration = 1.0", script)
        self.assertIn("texture.generateMipmaps = !preserveDetail", script)
        self.assertIn("this.loadFirstAvailableTexture(satelliteDetailSources, true)", script)
        self.assertIn("this.loadFirstAvailableTexture(satellitePrecisionSources, true)", script)

    def test_google_earth_navigation_and_adaptive_focus_imagery(self):
        script = POINTING_SCRIPT.read_text(encoding="utf-8")
        dashboard = DASHBOARD_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("this.controls.mouseButtons.LEFT = THREE.MOUSE.PAN", script)
        self.assertIn("this.controls.mouseButtons.MIDDLE = THREE.MOUSE.ROTATE", script)
        self.assertIn("this.controls.mouseButtons.RIGHT = THREE.MOUSE.PAN", script)
        self.assertIn("this.controls.zoomToCursor = true", script)
        self.assertIn("this.controls.screenSpacePanning = false", script)
        self.assertIn('name: "adaptive-focus-imagery"', script)
        self.assertIn('size: "2048,2048"', script)
        self.assertIn("distance < 700 ? 180 : distance < 1700 ? 400 : 750", script)
        self.assertIn("consumeNavigationClick", dashboard)

    def test_nested_imagery_meshes_share_an_aligned_grid(self):
        script = POINTING_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("const widthSegments = 480", script)
        self.assertIn("const heightSegments = 480", script)

    def test_local_detail_covers_five_ground_kilometers_from_station(self):
        latitude = 18.4839
        west, _south, east, _north = web_server._web_mercator_bbox(latitude, 98.0152, 5000.0)
        projected_radius = (east - west) / 2.0
        ground_radius = projected_radius * math.cos(math.radians(latitude))
        self.assertAlmostEqual(ground_radius, 5000.0, places=6)
        self.assertEqual(web_server.POINTING_DETAIL_IMAGERY_RADIUS_M, 5000.0)
        self.assertAlmostEqual(
            web_server.POINTING_DETAIL_IMAGERY_RADIUS_M * 2
            / web_server.POINTING_IMAGERY_TEXTURE_SIZE,
            2.44140625,
        )
        self.assertEqual(web_server.POINTING_PRECISION_IMAGERY_RADIUS_M, 1000.0)
        self.assertAlmostEqual(
            web_server.POINTING_PRECISION_IMAGERY_RADIUS_M * 2
            / web_server.POINTING_PRECISION_IMAGERY_TEXTURE_SIZE,
            0.9765625,
        )


if __name__ == "__main__":
    unittest.main()
