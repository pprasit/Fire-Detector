from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DESKTOP_TEMPLATE = PROJECT_ROOT / "web" / "templates" / "desktop" / "index.html"
DESKTOP_SCRIPT = PROJECT_ROOT / "web" / "static" / "desktop" / "js" / "dashboard.js"
TERRAIN_SCRIPT = PROJECT_ROOT / "web" / "static" / "desktop" / "js" / "pointing_terrain_3d.js"
MISSION_CSS = PROJECT_ROOT / "web" / "static" / "desktop" / "css" / "mission_control.css"
DASHBOARD_CSS = PROJECT_ROOT / "web" / "static" / "desktop" / "css" / "dashboard.css"


class PointingCameraDockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = DESKTOP_TEMPLATE.read_text(encoding="utf-8")
        cls.dashboard = DESKTOP_SCRIPT.read_text(encoding="utf-8")
        cls.terrain = TERRAIN_SCRIPT.read_text(encoding="utf-8")
        cls.css = MISSION_CSS.read_text(encoding="utf-8")
        cls.dashboard_css = DASHBOARD_CSS.read_text(encoding="utf-8")

    def test_pointing_camera_is_installed_as_a_right_dock(self):
        self.assertIn('pointingCameraWindow.classList.add("is-docked")', self.dashboard)
        self.assertIn('monitorShell.append(pointingCameraWindow)', self.dashboard)
        self.assertIn('"is-pointing-camera-docked"', self.dashboard)
        self.assertIn("grid-row: 2 / 4", self.css)

    def test_selected_map_label_contains_angles_and_goto(self):
        for element_id in (
            "pointingHoverAzimuth",
            "pointingHoverAltitude",
            "pointingHoverGoto",
        ):
            self.assertIn(f'id="{element_id}"', self.template)
        self.assertIn('new CustomEvent("pointing-map-goto")', self.terrain)
        self.assertIn('window.addEventListener("pointing-map-goto"', self.dashboard)

    def test_selected_map_label_can_close_without_clearing_line_of_sight(self):
        self.assertIn('id="pointingHoverClose"', self.template)
        self.assertIn('this.selection.userData.showLabel = false', self.terrain)
        self.assertIn('this.selectionLabel.hidden = true', self.terrain)
        close_binding = self.terrain.index('this.selectionLabelClose.addEventListener("click"')
        close_body = self.terrain[close_binding:close_binding + 700]
        self.assertNotIn("clearLineOfSight", close_body)
        self.assertIn(".pointing-hover-close", self.dashboard_css)

    def test_pointing_camera_can_open_the_central_pool_monitor_in_a_new_tab(self):
        self.assertIn('id="pointingCameraPopout"', self.template)
        self.assertIn('window.open("/camera-monitor", "camera-monitor")', self.dashboard)
        self.assertIn("closePointingCameraWindow();", self.dashboard)
        self.assertIn(".pointing-camera-popout", self.dashboard_css)
        self.assertIn("grid-template-columns: minmax(0, 1fr) auto 32px 32px", self.css)
        self.assertIn("#pointingCameraPopout { grid-column: 3; }", self.css)
        self.assertIn("#pointingCameraClose { grid-column: 4; }", self.css)

    def test_map_goto_reuses_the_validated_target_command(self):
        listener_start = self.dashboard.index('window.addEventListener("pointing-map-goto"')
        listener_body = self.dashboard[listener_start:listener_start + 260]
        self.assertIn("fields.pointingTargetGoto?.click()", listener_body)

    def test_camera_feeds_keep_native_ratios_and_fit_without_scrollbars(self):
        self.assertIn('pointingCameraConfiguredRatio(".pointing-camera-feed.is-visible", 1920, 1080)', self.dashboard)
        self.assertIn('pointingCameraConfiguredRatio(".pointing-camera-feed.is-thermal", 640, 512)', self.dashboard)
        self.assertIn("1 / thermalRatio + 1 / visibleRatio", self.dashboard)
        self.assertIn('--pointing-camera-dock-width', self.css)
        self.assertIn("width: 100%", self.css)
        self.assertIn("object-fit: cover", self.css)
        self.assertIn("overflow: hidden", self.css)
        self.assertIn("grid-template-columns: minmax(0, 1fr) 116px", self.css)

    def test_both_camera_headers_show_live_zoom_percentage(self):
        self.assertIn('id="pointingCameraThermalZoomPct"', self.template)
        self.assertIn('id="pointingCameraVisibleZoomPct"', self.template)
        self.assertIn("function subscribePointingCameraMetadata(camera)", self.dashboard)
        self.assertIn("/api/camera-stream/metadata-stream/${cameraSourceMode}/${camera}", self.dashboard)
        self.assertIn("metadata?.zoom_pct", self.dashboard)
        self.assertIn("pointingCameraMetadataStreams.forEach((stream) => stream.close())", self.dashboard)
        self.assertIn(".pointing-camera-zoom-pct", self.css)

    def test_pointing_header_shows_four_live_mount_telemetry_panels(self):
        for element_id in (
            "pointingLiveAzimuthPosition",
            "pointingLiveAltitudePosition",
            "pointingLiveAzimuthVelocity",
            "pointingLiveAltitudeVelocity",
        ):
            self.assertIn(f'id="{element_id}"', self.template)
            self.assertIn(f'getElementById("{element_id}")', self.dashboard)
        self.assertIn("const renderPointingTelemetry = (field, value, unit)", self.dashboard)
        self.assertIn("repeat(6, minmax(64px, 1fr))", self.css)
        self.assertIn(".is-live-telemetry.is-azimuth em", self.css)
        self.assertIn(".is-live-telemetry.is-altitude em", self.css)

    def test_add_to_model_opens_themed_confirmation_and_saves_directly(self):
        self.assertIn('id="pointingHoverAddModel"', self.template)
        self.assertIn('id="pointingModelAddDialog"', self.template)
        for element_id in (
            "pointingModelAddReference",
            "pointingModelAddTelemetry",
            "pointingModelAddDifference",
            "pointingModelAddCancel",
            "pointingModelAddConfirm",
        ):
            self.assertIn(f'id="{element_id}"', self.template)
            self.assertIn(f'getElementById("{element_id}")', self.dashboard)
        self.assertIn('new CustomEvent("pointing-map-add-model")', self.terrain)
        self.assertIn('window.addEventListener("pointing-map-add-model", openPointingModelAddDialog)', self.dashboard)
        self.assertIn('fetch("/api/pointing/alignment-point"', self.dashboard)
        self.assertIn("camera_offset_azimuth_deg: 0", self.dashboard)
        self.assertIn("camera_offset_altitude_deg: 0", self.dashboard)
        self.assertIn(".pointing-model-add-summary", self.dashboard_css)

    def test_model_comparison_controls_both_camera_zoom_levels(self):
        for element_id in (
            "pointingModelLinkedZoomPct",
            "pointingModelZoomStep",
            "pointingModelZoomOut",
            "pointingModelZoomIn",
            "pointingModelZoomMessage",
        ):
            self.assertIn(f'id="{element_id}"', self.template)
            self.assertIn(f'getElementById("{element_id}")', self.dashboard)
        self.assertIn('fetch("/api/camera-control/zoom"', self.dashboard)
        self.assertIn("JSON.stringify({ direction, step_pct: step })", self.dashboard)
        self.assertIn("JSON.stringify({ target_zoom_pct: normalizedTarget })", self.dashboard)
        self.assertIn(
            'addEventListener("blur", () => commitPointingModelLinkedZoom(input))',
            self.dashboard,
        )
        self.assertIn('event.key === "Enter"', self.dashboard)
        self.assertIn('bindPointingModelZoomButton(fields.pointingModelZoomOut, "out")', self.dashboard)
        self.assertIn('bindPointingModelZoomButton(fields.pointingModelZoomIn, "in")', self.dashboard)
        self.assertIn("repeatHeldStep", self.dashboard)
        self.assertIn("pointerdown", self.dashboard)
        self.assertIn(".pointing-model-zoom-controls", self.dashboard_css)
        self.assertIn(".pointing-model-zoom-settings", self.dashboard_css)

    def test_camera_view_footer_has_thermal_referenced_linked_zoom(self):
        for element_id in (
            "cameraLiveZoomControl",
            "cameraLiveLinkedZoomPct",
            "cameraLiveZoomStep",
            "cameraLiveZoomOut",
            "cameraLiveZoomIn",
            "cameraLiveZoomMessage",
        ):
            self.assertIn(f'id="{element_id}"', self.template)
            self.assertIn(f'getElementById("{element_id}")', self.dashboard)
        self.assertIn('min="0" max="10" step="0.1" value="10.0"', self.template)
        self.assertIn(
            'bindPointingModelZoomButton(fields.cameraLiveZoomOut, "out", fields.cameraLiveZoomStep)',
            self.dashboard,
        )
        self.assertIn(
            'bindPointingModelZoomButton(fields.cameraLiveZoomIn, "in", fields.cameraLiveZoomStep)',
            self.dashboard,
        )
        self.assertIn("cameraZoomPollTimer = setInterval(loadPointingModelLinkedZoom, 1500)", self.dashboard)
        self.assertIn(".camera-live-zoom-control", self.dashboard_css)

    def test_add_to_model_does_not_launch_comparison_or_centering_windows(self):
        self.assertNotIn('window.addEventListener("pointing-map-add-model", openPointingModelComparison)', self.dashboard)
        self.assertIn("function openPointingModelAddDialog()", self.dashboard)
        add_start = self.dashboard.index("function openPointingModelAddDialog()")
        add_body = self.dashboard[add_start:add_start + 2200]
        self.assertNotIn("openPointingModelComparison()", add_body)
        self.assertNotIn("openPointingAlignment()", add_body)
        self.assertIn("The mount will not move", add_body)

    def test_alignment_window_minimizes_near_event_log_and_hides_camera_dock_on_open(self):
        for element_id in (
            "pointingAlignmentMinimize",
            "pointingAlignmentMinimized",
            "pointingAlignmentRestore",
            "pointingAlignmentMinimizedStatus",
        ):
            self.assertIn(f'id="{element_id}"', self.template)
            self.assertIn(f'getElementById("{element_id}")', self.dashboard)
        self.assertNotIn('id="pointingAlignmentGotoDem"', self.template)
        self.assertNotIn('id="pointingAlignmentReset"', self.template)
        self.assertNotIn("Mount Calibration Points", self.template)
        self.assertIn("function minimizePointingAlignment()", self.dashboard)
        self.assertIn("function restorePointingAlignment()", self.dashboard)
        self.assertIn("closePointingCameraWindow()", self.dashboard)
        self.assertIn(".pointing-alignment-minimized", self.dashboard_css)
        self.assertIn("bottom: 150px", self.dashboard_css)

    def test_alignment_direction_mode_and_step_navigation(self):
        for element_id in (
            "pointingAlignmentDirectionMode",
            "pointingAlignmentDirectionValueLabel",
            "pointingAlignmentDirectionUnit",
            "pointingAlignmentBack",
            "pointingAlignmentSave",
        ):
            self.assertIn(f'id="{element_id}"', self.template)
            self.assertIn(f'getElementById("{element_id}")', self.dashboard)
        self.assertIn('<option value="jog">Jog</option>', self.template)
        self.assertIn('<option value="offset" selected>Offset</option>', self.template)
        self.assertIn("← Back · Model Comparison", self.template)
        self.assertIn("Next · Add Mount Calibration Point →", self.template)
        self.assertIn("function updatePointingAlignmentDirectionMode()", self.dashboard)
        self.assertIn('if (pointingAlignmentDirectionMode() === "offset")', self.dashboard)
        self.assertIn("else startDirectionJog(button, event, controls)", self.dashboard)
        self.assertIn("closePointingAlignment({ reopenComparison: false })", self.dashboard)
        self.assertIn("openPointingModelEditor()", self.dashboard)
        self.assertIn(".pointing-alignment-direction-settings", self.dashboard_css)

    def test_alignment_header_shows_raw_pre_homing_axis_telemetry(self):
        for element_id in ("pointingAlignmentRawAzimuth", "pointingAlignmentRawAltitude"):
            self.assertIn(f'id="{element_id}"', self.template)
            self.assertIn(f'getElementById("{element_id}")', self.dashboard)
        self.assertIn("RAW TELEMETRY · PRE-HOMING", self.template)
        self.assertIn("toNumber(axes.Azimuth.raw_position_deg)", self.dashboard)
        self.assertIn("toNumber(axes.Altitude.raw_position_deg)", self.dashboard)
        self.assertIn(".pointing-alignment-raw-telemetry", self.dashboard_css)

    def test_alignment_window_has_equal_height_previews_and_linked_zoom(self):
        for element_id in (
            "pointingAlignmentLinkedZoomPct",
            "pointingAlignmentZoomStep",
            "pointingAlignmentZoomOut",
            "pointingAlignmentZoomIn",
        ):
            self.assertIn(f'id="{element_id}"', self.template)
            self.assertIn(f'getElementById("{element_id}")', self.dashboard)
        self.assertNotIn('id="pointingAlignmentMessage"', self.template)
        self.assertIn("grid-template-columns: minmax(0, 640fr) minmax(0, 910fr)", self.dashboard_css)
        self.assertIn("width: min(1320px, calc(100vw - 32px))", self.dashboard_css)
        self.assertIn("bindPointingModelZoomButton(fields.pointingAlignmentZoomOut", self.dashboard)

    def test_live_previews_pull_latest_resized_frame_without_video_backlog(self):
        self.assertIn("function attachPointingLatestFrame(image, camera, session)", self.dashboard)
        self.assertIn("/api/camera-frame/latest/live/${camera}?preview=pointing", self.dashboard)
        self.assertIn("targetIntervalMs = failed ? 500 : pointingCameraFrameIntervalMs", self.dashboard)
        self.assertIn("poolStatus.profiles?.pointing?.max_fps", self.dashboard)
        self.assertIn("pointingCameraFrameSession += 1", self.dashboard)


if __name__ == "__main__":
    unittest.main()
