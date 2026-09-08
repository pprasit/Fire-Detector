from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TERRAIN_SCRIPT = PROJECT_ROOT / "web" / "static" / "desktop" / "js" / "pointing_terrain_3d.js"
DASHBOARD_SCRIPT = PROJECT_ROOT / "web" / "static" / "desktop" / "js" / "dashboard.js"
DESKTOP_TEMPLATE = PROJECT_ROOT / "web" / "templates" / "desktop" / "index.html"
MISSION_CSS = PROJECT_ROOT / "web" / "static" / "desktop" / "css" / "mission_control.css"
DASHBOARD_CSS = PROJECT_ROOT / "web" / "static" / "desktop" / "css" / "dashboard.css"


class PointingAlignmentMarkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.terrain = TERRAIN_SCRIPT.read_text(encoding="utf-8")
        cls.dashboard = DASHBOARD_SCRIPT.read_text(encoding="utf-8")
        cls.template = DESKTOP_TEMPLATE.read_text(encoding="utf-8")
        cls.mission_css = MISSION_CSS.read_text(encoding="utf-8")
        cls.dashboard_css = DASHBOARD_CSS.read_text(encoding="utf-8")

    def test_saved_alignment_points_are_passed_to_the_terrain(self):
        self.assertIn("appSettings.pointing_alignment?.points || []", self.dashboard)
        self.assertIn("window.pointingTerrain3D?.setAlignmentPoints(points)", self.dashboard)
        self.assertIn("setAlignmentPoints(points = [])", self.terrain)
        self.assertIn("this.localPositionForSample(point)", self.terrain)

    def test_markers_are_purple_map_pins_and_scale_with_zoom(self):
        self.assertIn("const purple = 0xa855f7", self.terrain)
        self.assertIn("new THREE.ConeGeometry", self.terrain)
        self.assertIn("new THREE.SphereGeometry", self.terrain)
        self.assertIn("new THREE.RingGeometry", self.terrain)
        self.assertIn("distance * 0.004", self.terrain)
        self.assertIn("this.updateAlignmentMarkerPresentation()", self.terrain)

    def test_editor_lists_saved_points_in_a_floating_table(self):
        for element_id in (
            "pointingModelEditor",
            "pointingModelEditorBody",
            "pointingModelEditorClose",
        ):
            self.assertIn(f'id="{element_id}"', self.template)
        self.assertIn('data-floating-window="pointingModelEditor"', self.template)
        self.assertIn('editPointingModel.id = "pointingModelEditorOpen"', self.dashboard)
        self.assertIn("function renderPointingModelEditor()", self.dashboard)
        self.assertIn(".pointing-model-editor-table", self.dashboard_css)
        self.assertIn(".pointing-model-editor-open", self.mission_css)
        self.assertIn("<th>Delete Point</th>", self.template)
        self.assertIn('remove.textContent = "Delete Point"', self.dashboard)

    def test_editor_uses_the_main_system_palette(self):
        self.assertIn("border-color: #58d68d", self.mission_css)
        self.assertIn("box-shadow: inset 3px 0 #58d68d", self.dashboard_css)
        self.assertIn("color: #79d6f3", self.dashboard_css)

    def test_clicking_a_row_only_focuses_the_3d_map(self):
        focus_start = self.dashboard.index("function focusPointingModelPoint")
        focus_body = self.dashboard[focus_start:focus_start + 900]
        self.assertIn("focusAlignmentPoint(point)", focus_body)
        self.assertNotIn("sendMotorCommand", focus_body)
        self.assertNotIn("/api/motors", focus_body)
        self.assertIn("focusAlignmentPoint(point)", self.terrain)
        self.assertIn("durationMs: 720", self.terrain)


if __name__ == "__main__":
    unittest.main()
