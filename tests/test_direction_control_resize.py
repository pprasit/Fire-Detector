from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = PROJECT_ROOT / "web" / "templates" / "desktop" / "index.html"
SCRIPT = PROJECT_ROOT / "web" / "static" / "desktop" / "js" / "dashboard.js"
STYLES = PROJECT_ROOT / "web" / "static" / "desktop" / "css" / "mission_control.css"


class DirectionControlResizeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = TEMPLATE.read_text(encoding="utf-8")
        cls.script = SCRIPT.read_text(encoding="utf-8")
        cls.styles = STYLES.read_text(encoding="utf-8")

    def test_direction_panel_has_all_edge_and_corner_resize_handles(self):
        for edge in ("n", "e", "s", "w", "ne", "nw", "se", "sw"):
            self.assertIn(f'data-resize-edge="{edge}"', self.template)
        self.assertIn('cursor: ns-resize', self.styles)
        self.assertIn('cursor: ew-resize', self.styles)
        self.assertIn('cursor: nwse-resize', self.styles)
        self.assertIn('cursor: nesw-resize', self.styles)

    def test_panel_resize_preserves_usable_controls_and_scales_pad(self):
        self.assertIn("min-width: min(330px", self.styles)
        self.assertIn("min-height: min(500px", self.styles)
        self.assertIn("grid-template-rows: auto auto minmax(180px, 1fr) auto auto", self.styles)
        self.assertIn("width: clamp(17px, 5.8cqw, 25px)", self.styles)

    def test_resize_is_initialized_and_size_is_persisted(self):
        self.assertIn("function initializeResizableFloatingWindows()", self.script)
        self.assertIn("initializeResizableFloatingWindows();", self.script)
        self.assertIn('state.width = Math.round(rect.width)', self.script)
        self.assertIn('state.height = Math.round(rect.height)', self.script)
        self.assertIn('panel.style.width = `${width}px`', self.script)
        self.assertIn('panel.style.height = `${height}px`', self.script)


if __name__ == "__main__":
    unittest.main()
