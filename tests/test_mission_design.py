from pathlib import Path
import re
import unittest

import numpy as np

from fire_detector.dem_panorama import _mount_row_to_geographic


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MISSION_PAGE = PROJECT_ROOT / "web" / "static" / "desktop" / "mission-design.html"
DASHBOARD_SCRIPT = PROJECT_ROOT / "web" / "static" / "desktop" / "js" / "dashboard.js"
WEB_SERVER = PROJECT_ROOT / "src" / "fire_detector" / "web_server.py"


class MissionDesignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = MISSION_PAGE.read_text(encoding="utf-8")
        cls.dashboard = DASHBOARD_SCRIPT.read_text(encoding="utf-8")
        cls.web_server = WEB_SERVER.read_text(encoding="utf-8")

    def test_desktop_navigation_exposes_mission_design_as_item_07(self):
        self.assertIn('data-view-mode="mission"', self.dashboard)
        self.assertIn("<span>Mission Design</span><kbd>07</kbd>", self.dashboard)

    def test_mission_interface_is_english_only(self):
        self.assertIn('<html lang="en">', self.page)
        self.assertIsNone(re.search(r"[\u0e00-\u0e7f]", self.page))

    def test_dem_panorama_and_vertical_camera_column_replace_position_list(self):
        self.assertIn('class="workspace"', self.page)
        self.assertIn('class="panel path-panel"', self.page)
        self.assertIn('class="panel camera-panel"', self.page)
        self.assertIn("grid-template-rows:1fr 1fr", self.page)
        self.assertNotIn('id="points"', self.page)
        self.assertIn('<h2>DEM panorama', self.page)
        self.assertIn('aria-label="DEM and satellite panorama for mission design"', self.page)

    def test_scan_pattern_controls_and_export_column_are_removed(self):
        self.assertNotIn('id="mode"', self.page)
        self.assertNotIn('id="pattern"', self.page)
        self.assertNotIn("'pattern'", self.page)

    def test_editors_are_draggable_and_panorama_has_preview_before_apply(self):
        self.assertIn('id="positionEditor"', self.page)
        self.assertIn('id="panoramaBuilder"', self.page)
        self.assertIn("installDrag($('positionEditor'))", self.page)
        self.assertIn("panoramaPreview", self.page)
        self.assertIn("Start Thermal Panorama Capture", self.page)

    def test_panorama_maps_from_horizon_using_thermal_fov_and_overlap(self):
        self.assertIn("Azimuth 0–360° · Altitude −15–+10°", self.page)
        self.assertIn('id="panoHFov"', self.page)
        self.assertIn('id="panoVFov"', self.page)
        self.assertIn('id="panoOverlap"', self.page)
        self.assertIn('id="panoLowerAlt"', self.page)
        self.assertIn('id="panoUpperAlt"', self.page)
        self.assertIn("effectiveFov", self.page)
        self.assertIn("row%2===0", self.page)
        self.assertIn("/api/settings", self.page)
        self.assertIn("panorama:panoramaSettings()", self.page)
        self.assertIn("MAX_WAYPOINTS=6000", self.page)
        self.assertNotIn("Capture time", self.page)

    def test_scan_grid_uses_zoom_dependent_thermal_fov_and_real_progress(self):
        self.assertIn('id="scanZoomPct"', self.page)
        self.assertIn('value="10"', self.page)
        self.assertIn("function rebuildScanGrid(){", self.page)
        self.assertIn("thermalFocalFromPct", self.page)
        self.assertIn("scan-grid-cell", self.page)
        self.assertIn("/api/camera-control/panorama/status", self.page)
        self.assertIn("/api/camera-control/panorama/calculate", self.page)
        self.assertIn("/api/camera-control/panorama/${sequenceAction", self.page)
        self.assertIn("applyHardwarePanoramaPlan", self.page)
        self.assertIn("scanCapturedSteps", self.page)

    def test_export_is_csv_and_preview_remains_a_local_simulation(self):
        self.assertIn("scan-mission.csv", self.page)
        self.assertIn("text/csv", self.page)
        self.assertIn("$('preview').onclick=()=>play()", self.page)
        self.assertIn("$('goto').onclick=()=>play(true)", self.page)

    def test_start_stop_toggle_controls_and_tracks_camera_sweep_module(self):
        button = self.page.index('id="missionRunToggle"')
        panorama = self.page.index('id="panoramaOpen"')
        self.assertLess(button, panorama)
        self.assertIn("mission-run-toggle is-pending is-unavailable", self.page)
        self.assertIn("missionActive?'Stop':'Start'", self.page)
        self.assertIn("content:'Start Mission'", self.page)
        self.assertIn("content:'Stop Mission'", self.page)
        self.assertIn("fetch('/api/camera-control/sweep'", self.page)
        self.assertIn("body:JSON.stringify({action})", self.page)
        self.assertIn("setInterval(refreshMissionControl,2000)", self.page)
        self.assertIn("mission_state", self.page)
        self.assertIn("mission-control-event", self.page)
        self.assertIn('event.data?.type !== "mission-control-event"', self.dashboard)

    def test_header_actions_share_one_size_and_icon_language(self):
        self.assertIn(".action-button{width:138px;height:38px", self.page)
        for button_id in ["missionRunToggle", "add", "save", "preview"]:
            pattern = rf'<button class="[^"]*action-button[^"]*" id="{button_id}"[^>]*><svg '
            self.assertRegex(self.page, pattern)
        self.assertIn('class="panorama-inline" id="panoramaOpen"', self.page)

    def test_inline_save_persists_panorama_grid_and_centered_altitude_marker(self):
        self.assertIn('id="panoramaOpen" type="button">▣ Save</button>', self.page)
        self.assertIn("/api/camera-control/panorama/save", self.page)
        self.assertIn("function markerAltitudeY(", self.page)
        self.assertIn("visualMin=(rowValues[0]??b.altMin)-rowStep/2", self.page)

    def test_compact_summary_editable_range_and_capture_control(self):
        self.assertIn('id="rangeValue"', self.page)
        self.assertIn('id="rangeEditor" hidden', self.page)
        self.assertIn("$('rangeEditor').addEventListener('focusout'", self.page)
        self.assertIn("localStorage.setItem(scanRangeKey", self.page)
        self.assertIn('id="captureToggle"', self.page)
        self.assertIn("$('captureToggle').onclick", self.page)
        self.assertNotIn('<div class="eyebrow">Mission</div>', self.page)

    def test_panorama_confirmation_uses_themed_dialog(self):
        self.assertIn('id="themeConfirm"', self.page)
        self.assertIn("function themedConfirm", self.page)
        self.assertIn("await themedConfirm", self.page)
        self.assertNotIn("if(!confirm(", self.page)
        self.assertIn('id="confirmResume"', self.page)
        self.assertIn("function themedSequenceChoice", self.page)
        self.assertIn("'Start New Sequence'", self.page)
        self.assertIn("Resume Sequence", self.page)
        self.assertIn("?'resume':'start'", self.page)

    def test_panorama_altitude_defaults_to_minus_fifteen_through_plus_ten(self):
        self.assertIn('id="scanAltMin" type="number" min="-15" max="10" value="-15"', self.page)
        self.assertIn('id="scanAltMax" type="number" min="-15" max="10" value="10"', self.page)
        self.assertIn("saved.altMin>=-15&&saved.altMax<=10", self.page)

    def test_dem_panorama_is_created_on_demand_beside_capture(self):
        capture = self.page.index('id="captureToggle"')
        create = self.page.index('id="createDemPanorama"')
        self.assertLess(capture, create)
        self.assertIn("Create DEM Panorama", self.page)
        self.assertIn("/api/mission-design/dem-panorama", self.page)
        self.assertIn("method:'POST'", self.page)
        self.assertIn("altitude_min_deg:-15,altitude_max_deg:10", self.page)
        self.assertIn("dem-panorama-layer", self.page)
        self.assertIn("map.innerHTML=", self.page)
        self.assertIn("async function demPanoramaApi(response)", self.page)
        self.assertIn("contentType.includes('application/json')", self.page)
        self.assertIn("loadDemPanorama()", self.page)
        self.assertIn('@app.route("/api/mission-design/dem-panorama", methods=["GET", "POST"])', self.web_server)
        self.assertIn("def _mission_design_dem_panorama(*, create: bool = False, force: bool = False)", self.web_server)
        self.assertIn("render_dem_panorama(", self.web_server)
        self.assertIn("pointing_model=pointing_model", self.web_server)
        self.assertIn("azimuth_north_offset_deg=float", self.web_server)
        self.assertIn("panorama_digest", self.web_server)
        self.assertIn("force:true", self.page)
        self.assertIn("Regenerate DEM Panorama", self.page)
        self.assertNotIn("button.hidden=true;$('map').dataset.demPanorama='ready'", self.page)

    def test_dem_panorama_pixels_are_reprojected_into_mount_coordinates(self):
        true_azimuth, true_altitude = _mount_row_to_geographic(
            np.array([0.0, 90.0]),
            0.0,
            pointing_model={"active": False},
            azimuth_north_offset_deg=90.0,
        )
        np.testing.assert_allclose(true_azimuth, [270.0, 0.0], atol=1e-9)
        np.testing.assert_allclose(true_altitude, [0.0, 0.0], atol=1e-9)

        true_azimuth, true_altitude = _mount_row_to_geographic(
            np.array([10.0]),
            2.0,
            pointing_model={
                "active": True,
                "mode": "single_point_offset",
                "azimuth_offset_deg": 1.0,
                "altitude_offset_deg": -3.0,
            },
            azimuth_north_offset_deg=90.0,
        )
        np.testing.assert_allclose(true_azimuth, [279.0], atol=1e-9)
        np.testing.assert_allclose(true_altitude, [5.0], atol=1e-9)

    def test_dem_panorama_keeps_source_aspect_ratio_with_horizontal_scroll(self):
        self.assertIn("overflow-x:scroll", self.page)
        self.assertIn("function sizeDemPanorama()", self.page)
        self.assertIn("sourceAspect=(7200*azSpan/360)/(500*altSpan/25)", self.page)
        self.assertIn("viewport.clientHeight*requiredMapAspect", self.page)
        self.assertIn("new ResizeObserver(sizeDemPanorama)", self.page)

    def test_scan_grid_shows_live_mount_position_and_velocity(self):
        for field_id in ["actualAz", "actualAlt", "actualAzVel", "actualAltVel", "actualTarget"]:
            self.assertIn(f'id="{field_id}"', self.page)
        self.assertIn("fetch('/api/status'", self.page)
        self.assertIn("setInterval(refreshMountTelemetry,100)", self.page)
        self.assertIn("actual-mount-marker", self.page)
        self.assertIn("locator-ring", self.page)
        self.assertIn("actualTelemetryBusy", self.page)
        self.assertIn("new MutationObserver(()=>drawActualMarker())", self.page)
        self.assertNotIn("new MutationObserver(drawActualMarker)", self.page)
        self.assertNotIn("viewport.scrollLeft", self.page)

    def test_captured_panorama_frames_are_rendered_inside_grid_cells(self):
        self.assertIn("scanCellImages=new Map()", self.page)
        self.assertIn("state?.latest_thumbnail", self.page)
        self.assertIn("/api/camera-control/panorama/image/", self.page)
        self.assertIn('<image href=', self.page)
        self.assertIn("state?.captured_thumbnails", self.page)
        self.assertIn("state?.latest_thumbnail_step", self.page)
        self.assertIn("scanCellImages.set(step", self.page)
        self.assertNotIn("scanCellImages.set(Math.max(0,current-1)", self.page)
        self.assertIn("cropW=sourceW*(1-overlap)", self.page)
        self.assertIn("cropH=sourceH*(1-overlap)", self.page)
        self.assertIn("applyHardwarePanoramaPlan(state.plan)", self.page)
        self.assertIn("openGridNeighborhood(selected)", self.page)
        self.assertIn("neighbor-grid", self.page)
        self.assertIn('data-grid-index="${neighborIndex}"', self.page)
        self.assertIn("openGridNeighborhood(Number(cell.dataset.gridIndex),true)", self.page)
        self.assertIn("if(!preserveZoom)viewerScale=1", self.page)
        self.assertIn("state?.live_mosaic", self.page)
        self.assertIn("View live mosaic", self.page)

    def test_thermal_and_visible_scan_tabs_are_removed(self):
        self.assertNotIn('id="scanThermalTab"', self.page)
        self.assertNotIn('id="scanVisibleTab"', self.page)
        self.assertNotIn("function setScanCameraMode", self.page)
        self.assertNotIn("const scanCameraTabs=", self.page)

    def test_panorama_has_horizontal_scroll_and_image_inspector(self):
        self.assertIn("overflow-x:scroll", self.page)
        self.assertIn("function sizeDemPanorama()", self.page)
        self.assertIn("sourceAspect=(7200*azSpan/360)/(500*altSpan/25)", self.page)
        self.assertIn("String(yScale/xScale)", self.page)
        self.assertIn("new ResizeObserver(sizeDemPanorama)", self.page)
        self.assertIn(".scan-grid-axis-y{transform:translateX(9px)", self.page)
        self.assertIn("function normalizeYAxisLabels()", self.page)
        self.assertIn("padStart(4", self.page)
        self.assertIn('viewBox="0 -55 1000 700"', self.page)
        self.assertIn('id="gridImageViewer"', self.page)
        self.assertIn("$('viewerStage').addEventListener('wheel'", self.page)
        self.assertIn('id="viewMosaic"', self.page)
        self.assertIn("state?.stitched_image", self.page)
        self.assertIn(".scan-grid-cell.is-captured{fill:transparent;stroke:transparent", self.page)
        self.assertIn("scanGrid.findIndex((cell,index)=>", self.page)
        self.assertIn("if(!scanCellImages.has(index))return false", self.page)
        self.assertNotIn("best=Infinity", self.page)

    def test_run_toggle_waits_for_real_status_before_enabling(self):
        self.assertIn("missionCommandPending=true,missionControlAvailable=false", self.page)
        self.assertIn("button.disabled=missionCommandPending||!missionControlAvailable", self.page)
        self.assertIn("missionActive=sweepIsActive(result.sweep)", self.page)
        self.assertIn('missionCommandPending?\'Working…\':missionActive?\'Stop\':\'Start\'', self.page)

    def test_camera_panels_use_the_same_live_mjpeg_transport_as_camera_view(self):
        self.assertIn("/api/camera-mjpeg/live/${camera}?mission=", self.page)
        self.assertIn("function startMissionCameraStreams()", self.page)
        self.assertIn("function stopMissionCameraStreams()", self.page)
        self.assertIn("img.removeAttribute('src')", self.page)
        self.assertIn("document.addEventListener('visibilitychange'", self.page)
        self.assertNotIn("setTimeout(()=>refreshCamera(camera),1000)", self.page)


if __name__ == "__main__":
    unittest.main()
