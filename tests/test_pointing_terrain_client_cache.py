from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (PROJECT_ROOT / "web/static/desktop/js/dashboard.js").read_text(encoding="utf-8")
SERVER = (PROJECT_ROOT / "src/fire_detector/web_server.py").read_text(encoding="utf-8")


class PointingTerrainClientCacheTests(unittest.TestCase):
    def test_browser_cache_uses_one_overwritten_indexeddb_record(self):
        self.assertIn('const POINTING_TERRAIN_DB = "narit-terrain-cache-v1"', SCRIPT)
        self.assertIn('.get("active")', SCRIPT)
        self.assertIn('}, "active")', SCRIPT)
        self.assertIn("readPointingTerrainCache(keyData.cache_key)", SCRIPT)
        self.assertIn("writePointingTerrainCache(keyData.cache_key, data)", SCRIPT)

    def test_build_button_forces_server_and_client_refresh(self):
        self.assertIn('buildTerrain.id = "pointingTerrainBuild"', SCRIPT)
        self.assertIn("loadPointingModel({ force: true, rebuild: true })", SCRIPT)
        self.assertIn('"?resolution_m=30&rebuild=1"', SCRIPT)
        self.assertIn('@app.get("/api/pointing/cache-key")', SERVER)
        self.assertIn("force_rebuild=rebuild", SERVER)

    def test_cache_key_tracks_terrain_inputs_not_unrelated_settings_mtime(self):
        start = SERVER.index("def _pointing_cache_key")
        implementation = SERVER[start:start + 1400]
        self.assertIn('"station": {', implementation)
        self.assertIn('"dem_mtime"', implementation)
        self.assertNotIn('"settings_mtime"', implementation)


if __name__ == "__main__":
    unittest.main()
