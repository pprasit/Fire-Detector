"""
Master Mission Controller Module (Autonomous Fire Sentry Workflow)
Executes the state machine:
1. SEARCH_SWEEP (Continuous 360° Pan @ 1°/s, Wide 31mm lens)
2. TARGET_LOCK (Confirmed Fire Detected -> Stop PTZ -> Center Target in Frame)
3. OPTICAL_ZOOM_VERIFY (Zoom In to 100-155mm -> Verify In-Focus/Sharpness -> AI Confirmation)
4. ALARM_ALERT (Record GPS/Angles & Dual Snapshots -> Trigger Alarm)
5. RESUME_SWEEP (Zoom Out to 31mm -> Resume Scan)
"""

import os
import time
import math
import threading
import logging
from typing import Optional, Dict, Any, List, Tuple
import numpy as np
import cv2

from camera_manager import CameraManager, CameraDevice
from ptz_controller import PTZController, normalize_angle_360, shortest_angular_diff
from fire_verifier import ThermalFireVerifier
from incident_manager import FireIncidentManager
from telegram_notifier import TelegramNotifier
from llm_verifier import LLMVerifier

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MissionController")


class MissionState:
    IDLE = "IDLE"
    PAUSED = "PAUSED"
    PREPARING_OPTICS = "PREPARING_OPTICS"
    SEARCH_SWEEP = "SEARCH_SWEEP"
    STEP_MOVING = "STEP_MOVING"
    STEP_DWELLING = "STEP_DWELLING"
    TARGET_CENTERING = "TARGET_CENTERING"
    ZOOMING_IN = "ZOOMING_IN"
    VERIFYING_FOCUS = "VERIFYING_FOCUS"
    DEEP_CONFIRMATION = "DEEP_CONFIRMATION"
    ALARM_ACTIVE = "ALARM_ACTIVE"
    ZOOMING_OUT = "ZOOMING_OUT"


class MissionController:
    """Coordinates Autonomous Sentry (Continuous Sweep & Step Sweep), Fire Verification & Incident Tracking."""

    def __init__(self, camera_mgr: CameraManager, ptz_ctrl: PTZController, fire_verifier: ThermalFireVerifier, cfg: dict):
        self.cam_mgr = camera_mgr
        self.ptz = ptz_ctrl
        self.verifier = fire_verifier
        self.cfg = cfg
        inc_cfg = cfg.get("incident", {})
        self.incident_mgr = FireIncidentManager(
            match_tolerance_deg=float(inc_cfg.get("match_tolerance_deg", 1.0)),
            max_inactive_gap_hours=float(inc_cfg.get("max_inactive_gap_hours", 2.0))
        )
        self.latest_incident = None

        # Telegram Hotspot Notifier
        telegram_cfg = cfg.get("telegram", {})
        self.notifier = TelegramNotifier(
            bot_token=telegram_cfg.get("bot_token", ""),
            chat_id=telegram_cfg.get("chat_id", "7235888789"),
            enabled=telegram_cfg.get("enabled", True),
            send_photos=telegram_cfg.get("send_photos", True),
            cooldown_sec=telegram_cfg.get("cooldown_sec", 30.0),
            suppress_false_alarm=telegram_cfg.get("suppress_false_alarm", True)
        )

        # Multimodal LLM Fire Verifier
        llm_cfg = cfg.get("llm", {})
        self.llm_verifier = LLMVerifier(
            api_key=llm_cfg.get("api_key", ""),
            base_url=llm_cfg.get("base_url", "https://lllm.narit.or.th/v1"),
            model=llm_cfg.get("model", "OpenAI-NARIT-Local-AI-01"),
            enabled=llm_cfg.get("enabled", True),
            max_tokens=llm_cfg.get("max_tokens", 2048),
            temperature=llm_cfg.get("temperature", 0.1),
            timeout_sec=llm_cfg.get("timeout_sec", 45)
        )

        self.state = MissionState.PREPARING_OPTICS if cfg.get("auto_sentry_enabled", False) else MissionState.IDLE
        self._needs_optics_prep = bool(cfg.get("auto_sentry_enabled", False))
        self.current_fire_target = None
        self.locked_azimuth = 0.0
        self.locked_altitude = 0.0
        self.locked_targets_history: List[Dict[str, float]] = []
        self.false_alarm_exclusions: List[Dict[str, Any]] = []
        self.state_timestamp = time.time()
        self.is_ai_paused = bool(cfg.get("auto_sentry_enabled", False))  # Pauses AI inference during lens movement

        self.is_paused = False
        self._abort_cycle = False
        self.paused_az = None
        self.paused_alt = None
        self.resume_target_az = None
        self.resume_direction = None
        self.resume_wp_idx = 0
        self.resume_alt_idx = 0
        self.current_waypoint_idx = 0
        self.total_waypoints_count = 0
        self.current_alt_idx = 0
        self.alt_layers = []
        self.grid_direction = "UP"  # "UP" (bottom-to-top) or "DOWN" (top-to-bottom)
        self.sweep_cycle_count = 0

        # Hotspot Re-check Watchlist
        self.hotspot_watchlist: Dict[str, dict] = {}
        self._init_watchlist_from_history()

        self._running = True
        self._lock = threading.Lock()

        # Start background Sentry State Machine
        self._thread = threading.Thread(target=self._sentry_loop, daemon=True)
        self._thread.start()

    def _init_watchlist_from_history(self):
        """Loads active unextinguished incidents into the hotspot watchlist, deduplicating spatial clusters."""
        try:
            active = self.incident_mgr.get_active_incidents(max_age_hours=24.0)
            active.sort(key=lambda x: x.get("last_epoch", 0), reverse=True)
            for inc in active:
                inc_id = inc["id"]
                az = float(inc.get("current_azimuth", inc["azimuth"]))
                alt = float(inc.get("current_altitude", inc["altitude"]))
                # Check if already covered by an existing watchlist checkpoint within 1.5 degrees
                is_duplicate = False
                for existing_item in self.hotspot_watchlist.values():
                    dist = math.sqrt(shortest_angular_diff(existing_item["azimuth"], az)**2 + (existing_item["altitude"] - alt)**2)
                    if dist <= 1.5:
                        is_duplicate = True
                        break
                if is_duplicate:
                    continue

                zoom_info = inc.get("zoom_info", {})
                focal_mm = float(zoom_info.get("focal_mm", 155.0)) if zoom_info else 155.0
                self.hotspot_watchlist[inc_id] = {
                    "incident_id": inc_id,
                    "azimuth": az,
                    "altitude": alt,
                    "target_focal_mm": focal_mm,
                    "first_detected": inc.get("first_epoch", time.time()),
                    "last_checked_time": inc.get("last_epoch", 0.0),
                    "last_checked_cycle": -1,
                    "consecutive_misses": 0,
                    "status": "ACTIVE"
                }
            if self.hotspot_watchlist:
                logger.info(f"Loaded {len(self.hotspot_watchlist)} unique active hotspots into Re-check Watchlist.")
        except Exception as e:
            logger.warning(f"Error initializing hotspot watchlist: {e}")

    def is_recently_verified(self, az: float, alt: float, cooldown_sec: Optional[float] = None, tol_deg: Optional[float] = None) -> bool:
        """Returns True if this angle was already verified within cooldown period to prevent re-zooming."""
        if cooldown_sec is None:
            cooldown_sec = float(self.cfg.get("alarm_cooldown_sec", 60.0))
        if tol_deg is None:
            # Adaptive tolerance based on current scan FOV (prevents re-triggering while target is in frame)
            th_cam = self.cam_mgr.get_thermal_camera()
            fov_h = float(th_cam.get_zoom_info().get("fov_h", 12.0)) if th_cam else 12.0
            tol_deg = max(3.5, min(12.0, fov_h * 0.85))

        now = time.time()
        # 1. Check temporary false alarm exclusions (e.g. 2-hour suppression on verified rocks/roofs)
        self.false_alarm_exclusions = [
            item for item in self.false_alarm_exclusions
            if now < item.get("expires_at", 0.0)
        ]
        for item in self.false_alarm_exclusions:
            d_az = abs(az - item["az"]) % 360.0
            if d_az > 180.0:
                d_az = 360.0 - d_az
            d_alt = abs(alt - item["alt"])
            if math.sqrt(d_az**2 + d_alt**2) <= tol_deg:
                return True

        # 2. Check general locked targets history
        self.locked_targets_history = [
            item for item in self.locked_targets_history
            if now - item["time"] < 300.0
        ]
        for item in self.locked_targets_history:
            if now - item["time"] < cooldown_sec:
                d_az = abs(az - item["az"]) % 360.0
                if d_az > 180.0:
                    d_az = 360.0 - d_az
                d_alt = abs(alt - item["alt"])
                dist = math.sqrt(d_az**2 + d_alt**2)
                if dist <= tol_deg:
                    return True
        return False

    def _set_state(self, new_state: str):
        with self._lock:
            old_state = self.state
            self.state = new_state
            self.state_timestamp = time.time()
            logger.info(f"[Mission State] {old_state} ---> {new_state}")

    @staticmethod
    def calculate_fov(focal_length_mm: float) -> Tuple[float, float]:
        """Calculates (h_fov_deg, v_fov_deg) for thermal camera at given focal length (31mm - 155mm)."""
        focal = max(10.0, float(focal_length_mm))
        sensor_w = 2.0 * 31.0 * math.tan(math.radians(14.2 / 2.0))
        sensor_h = 2.0 * 31.0 * math.tan(math.radians(11.4 / 2.0))
        h_fov = math.degrees(2.0 * math.atan(sensor_w / (2.0 * focal)))
        v_fov = math.degrees(2.0 * math.atan(sensor_h / (2.0 * focal)))
        return round(h_fov, 2), round(v_fov, 2)

    @staticmethod
    def calculate_step_from_focal_length(
        focal_length_mm: float,
        reference_fov_deg: float = 14.2,
        reference_focal_mm: float = 31.0,
        overlap_ratio: float = 0.2
    ) -> float:
        """Calculates step angle in degrees from focal length and overlap ratio."""
        focal = max(10.0, float(focal_length_mm))
        overlap = max(0.0, min(0.90, float(overlap_ratio)))
        sensor_mm = 2.0 * reference_focal_mm * math.tan(math.radians(reference_fov_deg / 2.0))
        fov_radians = 2.0 * math.atan(sensor_mm / (2.0 * focal))
        fov_degrees = math.degrees(fov_radians)
        return max(0.5, fov_degrees * (1.0 - overlap))

    def calculate_continuous_trajectory(
        self,
        az_start: float,
        az_end: float,
        alt_start: float,
        alt_end: float,
        focal_length_mm: float,
        fov_overlap_pct: float
    ) -> Tuple[List[float], float, float, float, float]:
        """
        Calculates altitude layers, horizontal trigger step, vertical layer step, and FOV.
        Returns: (alt_layers, az_step, alt_step, h_fov, v_fov)
        """
        h_fov, v_fov = self.calculate_fov(focal_length_mm)
        overlap = max(0.0, min(0.85, float(fov_overlap_pct) / 100.0))

        az_step = max(0.5, round(h_fov * (1.0 - overlap), 2))
        alt_step = max(0.5, round(v_fov * (1.0 - overlap), 2))

        rng_alt = abs(alt_end - alt_start)
        if rng_alt < 0.1:
            alt_layers = [round(alt_start, 2)]
        else:
            layers_count = max(2, int(round(rng_alt / alt_step)) + 1)
            actual_alt_step = (alt_end - alt_start) / (layers_count - 1)
            alt_layers = [round(alt_start + (i * actual_alt_step), 2) for i in range(layers_count)]
            alt_layers[-1] = round(alt_end, 2)

        return alt_layers, az_step, alt_step, h_fov, v_fov

    @staticmethod
    def build_axis_values(start: float, end: float, desired_step: float) -> List[float]:
        """Generates evenly spaced coordinates from start to end inclusive."""
        rng = abs(end - start)
        if rng == 0 or desired_step <= 0:
            return [start]
        intervals = rng / desired_step
        point_count = max(2, int(round(intervals)) + 1)
        adjusted_step = (end - start) / (point_count - 1)
        values = [round(start + (i * adjusted_step), 2) for i in range(point_count)]
        values[-1] = round(end, 2)
        return values

    def generate_snake_grid(self, az_start: float, az_end: float, alt_layers: List[float], az_step: float) -> List[Tuple[float, float]]:
        """Generates snake grid waypoints [(az, alt), ...] alternating direction per altitude layer."""
        az_values = self.build_axis_values(az_start, az_end, az_step)
        waypoints = []
        for row_idx, alt in enumerate(alt_layers):
            forward = (row_idx % 2 == 0)
            row_az = az_values if forward else list(reversed(az_values))
            for az in row_az:
                waypoints.append((az, alt))
        return waypoints

    def get_status(self) -> dict:
        with self._lock:
            az, alt = self.ptz.get_position()
            focal_mm = float(self.cfg.get("scan_focal_length_mm", 31.0))
            h_fov, v_fov = self.calculate_fov(focal_mm)
            return {
                "mission_state": self.state,
                "scan_mode": self.cfg.get("scan_mode", "CONTINUOUS"),
                "current_az": az,
                "current_alt": alt,
                "locked_az": self.locked_azimuth,
                "locked_alt": self.locked_altitude,
                "is_ai_paused": self.is_ai_paused,
                "is_paused": self.is_paused,
                "state_elapsed_sec": round(time.time() - self.state_timestamp, 1),
                "current_waypoint": self.current_waypoint_idx,
                "total_waypoints": self.total_waypoints_count,
                "current_layer": self.current_alt_idx + 1 if self.alt_layers else 1,
                "total_layers": len(self.alt_layers) if self.alt_layers else 1,
                "alt_layers": self.alt_layers,
                "focal_length_mm": focal_mm,
                "h_fov_deg": h_fov,
                "v_fov_deg": v_fov,
                "fov_overlap_pct": float(self.cfg.get("scan_fov_overlap_pct", 20.0)),
                "sweep_speed_deg_s": float(self.cfg.get("sweep_speed_deg_s", 1.0)),
                "latest_incident": self.latest_incident or self.incident_mgr.get_latest_incident(),
                "watchlist_count": len([i for i in self.hotspot_watchlist.values() if i.get("status") == "ACTIVE"]),
                "hotspot_watchlist": list(self.hotspot_watchlist.values())
            }

    def get_trajectory_info(self) -> dict:
        """Calculates trajectory details, layers, FOV, and estimated pass time."""
        az_start = float(self.cfg.get("scan_az_start", -90.0))
        az_end = float(self.cfg.get("scan_az_end", 90.0))
        alt_start = float(self.cfg.get("scan_alt_start", -10.0))
        alt_end = float(self.cfg.get("scan_alt_end", 0.0))
        focal_mm = float(self.cfg.get("scan_focal_length_mm", 31.0))
        ov_val = float(self.cfg.get("scan_fov_overlap_pct", 20.0))
        speed = max(0.1, float(self.cfg.get("sweep_speed_deg_s", 1.0)))
        goto_speed = max(1.0, float(self.cfg.get("step_goto_speed", self.cfg.get("max_goto_speed", 10.0))))
        settle_sec = float(self.cfg.get("settle_sec", 0.5))

        alt_layers, az_step, alt_step, h_fov, v_fov = self.calculate_continuous_trajectory(
            az_start=az_start,
            az_end=az_end,
            alt_start=alt_start,
            alt_end=alt_end,
            focal_length_mm=focal_mm,
            fov_overlap_pct=ov_val
        )

        layers_count = len(alt_layers)
        az_range = abs(az_end - az_start)
        total_pan_time = layers_count * (az_range / speed)
        transition_time = (layers_count - 1) * ((alt_step / goto_speed) + settle_sec)
        est_total_sec = int(round(total_pan_time + transition_time))
        est_total_min = round(est_total_sec / 60.0, 1)

        return {
            "layers_count": layers_count,
            "alt_layers": alt_layers,
            "alt_step_deg": alt_step,
            "az_step_deg": az_step,
            "fov": {
                "h_deg": h_fov,
                "v_deg": v_fov
            },
            "est_total_sec": est_total_sec,
            "est_total_min": est_total_min
        }

    def calculate_synchronized_visible_focal(self, thermal_focal_mm: Optional[float] = None) -> float:
        """
        Calculates matching focal length for Visible camera such that:
        Visible Horizontal FOV = visible_fov_multiplier * Thermal Horizontal FOV (default 2.0x).
        """
        th_focal = float(thermal_focal_mm or self.cfg.get("scan_focal_length_mm", 60.0))
        mult = float(self.cfg.get("visible_fov_multiplier", 2.0))
        th_cam = self.cam_mgr.get_thermal_camera()
        vis_cam = self.cam_mgr.get_visible_camera()
        if not th_cam or not vis_cam:
            return 19.1

        wide_h_fov = getattr(th_cam, 'wide_h_fov', getattr(th_cam, 'wide_fov_deg', 14.2))
        th_fov_h = th_cam._calculate_fov(th_focal, getattr(th_cam, 'min_focal_mm', 31.0), wide_h_fov)
        target_vis_fov_h = th_fov_h * mult
        return vis_cam.calculate_focal_for_fov(target_vis_fov_h)

    def start_sentry(
        self,
        az_start: Optional[float] = None,
        az_end: Optional[float] = None,
        speed: Optional[float] = None,
        alt: Optional[float] = None,
        alt_start: Optional[float] = None,
        alt_end: Optional[float] = None,
        alt_step: Optional[float] = None,
        scan_mode: Optional[str] = None,
        focal_length_mm: Optional[float] = None,
        scan_focal_length_mm: Optional[float] = None,
        fov_overlap_pct: Optional[float] = None,
        scan_fov_overlap_pct: Optional[float] = None,
        visible_sync_scan_zoom: Optional[bool] = None,
        visible_fov_multiplier: Optional[float] = None,
        max_goto_speed: Optional[float] = None,
        settle_sec: Optional[float] = None,
        step_calc_mode: Optional[str] = None,
        step_az_deg: Optional[float] = None,
        step_overlap_pct: Optional[float] = None,
        step_dwell_sec: Optional[float] = None,
        step_goto_speed: Optional[float] = None,
        capture_az_step: Optional[float] = None
    ):
        """User command: Start or Resume autonomous scan with focal length and FOV overlap trajectory calculation."""
        if az_start is not None: self.cfg["scan_az_start"] = float(az_start)
        if az_end is not None: self.cfg["scan_az_end"] = float(az_end)
        if speed is not None: self.cfg["sweep_speed_deg_s"] = float(speed)
        if scan_mode is not None: self.cfg["scan_mode"] = str(scan_mode).upper()

        # Focal length & Overlap
        f_len = focal_length_mm if focal_length_mm is not None else scan_focal_length_mm
        if f_len is not None: self.cfg["scan_focal_length_mm"] = max(31.0, min(155.0, float(f_len)))

        f_ov = fov_overlap_pct if fov_overlap_pct is not None else scan_fov_overlap_pct
        if f_ov is not None:
            self.cfg["scan_fov_overlap_pct"] = max(0.0, min(85.0, float(f_ov)))
            self.cfg["step_overlap_pct"] = self.cfg["scan_fov_overlap_pct"]

        if visible_sync_scan_zoom is not None:
            self.cfg["visible_sync_scan_zoom"] = bool(visible_sync_scan_zoom)
        if visible_fov_multiplier is not None:
            self.cfg["visible_fov_multiplier"] = max(1.0, min(5.0, float(visible_fov_multiplier)))

        if max_goto_speed is not None: self.cfg["max_goto_speed"] = float(max_goto_speed)
        if step_goto_speed is not None: self.cfg["step_goto_speed"] = float(step_goto_speed)
        if settle_sec is not None: self.cfg["settle_sec"] = float(settle_sec)

        if step_calc_mode is not None: self.cfg["step_calc_mode"] = str(step_calc_mode).upper()
        if step_az_deg is not None: self.cfg["step_az_deg"] = float(step_az_deg)
        if step_overlap_pct is not None: self.cfg["step_overlap_pct"] = float(step_overlap_pct)
        if step_dwell_sec is not None: self.cfg["step_dwell_sec"] = float(step_dwell_sec)
        if capture_az_step is not None: self.cfg["capture_az_step"] = float(capture_az_step)

        # If currently in PAUSED state, resume seamlessly from current progress
        if self.is_paused or self.state == MissionState.PAUSED:
            logger.info(f" Resuming Sentry from paused state (Layer {self.current_alt_idx + 1}, Waypoint {self.resume_wp_idx + 1})...")
            self._abort_cycle = False
            self.ptz._abort_slew = False
            self.is_paused = False
            self.is_resuming = True
            self.is_ai_paused = False
            self._set_state(MissionState.SEARCH_SWEEP)
            return

        # Alt Range Settings
        if alt_start is not None:
            self.cfg["scan_alt_start"] = float(alt_start)
        elif alt is not None:
            self.cfg["scan_alt_start"] = float(alt)

        if alt_end is not None:
            self.cfg["scan_alt_end"] = float(alt_end)
        elif "scan_alt_end" not in self.cfg:
            self.cfg["scan_alt_end"] = self.cfg.get("scan_alt_start", 5.0)

        a_s = float(self.cfg.get("scan_alt_start", -15.0))
        a_e = float(self.cfg.get("scan_alt_end", 5.0))
        f_val = float(self.cfg.get("scan_focal_length_mm", 31.0))
        ov_val = float(self.cfg.get("scan_fov_overlap_pct", 20.0))

        # Calculate Trajectory Altitude Layers and Step size automatically
        calc_layers, calc_az_step, calc_alt_step, h_fov, v_fov = self.calculate_continuous_trajectory(
            az_start=float(self.cfg.get("scan_az_start", -90.0)),
            az_end=float(self.cfg.get("scan_az_end", 90.0)),
            alt_start=a_s,
            alt_end=a_e,
            focal_length_mm=f_val,
            fov_overlap_pct=ov_val
        )

        self.alt_layers = calc_layers
        self.cfg["capture_az_step"] = calc_az_step
        self.cfg["scan_alt_step"] = calc_alt_step

        # Fresh start: reset all progress counters
        self._abort_cycle = False
        self.is_paused = False
        self.is_resuming = False
        self.resume_wp_idx = 0
        self.resume_alt_idx = 0
        self.current_alt_idx = 0
        self.current_waypoint_idx = 0
        self.current_fire_target = None
        self.is_ai_paused = False
        self.grid_direction = "UP"
        self.sweep_cycle_count = 0
        self.ptz._abort_slew = False

        # Fresh start: optics preparation (zoom & focus) before scan sweep
        self.is_ai_paused = True
        self._needs_optics_prep = True
        self._set_state(MissionState.PREPARING_OPTICS)

        vis_mult = float(self.cfg.get("visible_fov_multiplier", 2.0))
        logger.info(
            f"Sentry start requested [{self.cfg.get('scan_mode', 'CONTINUOUS')}]: "
            f"Az [{self.cfg.get('scan_az_start')}° to {self.cfg.get('scan_az_end')}°], "
            f"Alt layers ({len(self.alt_layers)}) = {self.alt_layers}, "
            f"Thermal Focal Length = {f_val:.1f}mm (FOV: {h_fov}° H x {v_fov}° V, {ov_val}% overlap)"
            + (f", Visible Sync = {vis_mult:.1f}x FOV" if self.cfg.get("visible_sync_scan_zoom", True) else "")
            + " -> Preparing Zoom & Auto-Focus before scan sweep..."
        )

    def pause_sentry(self):
        """User command: Temporarily pause sentry scan (holds current progress/position so Start can resume)."""
        logger.info(f" Pause requested by user. Holding PTZ @ Waypoint {self.current_waypoint_idx}, Layer {self.current_alt_idx + 1}")
        self._abort_cycle = True
        self.is_paused = True
        self.is_resuming = False
        cur_az, cur_alt = self.ptz.get_position()
        self.paused_az = cur_az
        self.paused_alt = cur_alt
        self.resume_target_az = getattr(self, "current_sweep_row_end_az", None)
        self.resume_direction = getattr(self, "current_sweep_direction", None)
        self._set_state(MissionState.PAUSED)
        self.ptz.stop()

    def stop_sentry(self):
        """User command: Fully stop sentry mode and reset progress so next Start begins from beginning."""
        logger.info(" Stop / Reset requested by user. Halting all PTZ movement and resetting scan progress.")
        self._abort_cycle = True
        self._needs_optics_prep = False
        self.is_paused = False
        self.is_resuming = False
        self.paused_az = None
        self.paused_alt = None
        self.resume_target_az = None
        self.resume_direction = None
        self.resume_wp_idx = 0
        self.resume_alt_idx = 0
        self.current_waypoint_idx = 0
        self.current_alt_idx = 0
        self.current_fire_target = None
        self.is_ai_paused = False
        self.grid_direction = "UP"
        self.sweep_cycle_count = 0
        self._set_state(MissionState.IDLE)
        self.ptz.stop()

    def _prepare_scan_optics(self):
        """
        Sequential scan preparation per user specification:
        Step 1: Slew PTZ to initial scan start position (az_start, start_alt) and wait until completely stopped.
        Step 2: ONLY once PTZ is completely stationary at start position, command Thermal & Visible Zoom.
        Step 3: Wait for zoom motors to finish adjusting completely (zoom_settle_wait_sec).
        Step 4: Trigger Auto-Focus on both cameras while PTZ remains completely stationary.
        Step 5: Wait for Auto-Focus to settle and lock onto scene (focus_settle_sec).
        Step 6: Begin autonomous scan sweep!
        """
        if getattr(self, "_abort_cycle", False) or self.state in (MissionState.IDLE, MissionState.PAUSED) or not self._running:
            return

        self._set_state(MissionState.PREPARING_OPTICS)
        self.is_ai_paused = True
        logger.info("🧭 [ScanPrep] Step 1/3: Positioning PTZ to start position before adjusting zoom...")

        f_val = float(self.cfg.get("scan_focal_length_mm", 60.0))
        az_start = float(self.cfg.get("scan_az_start", -90.0))
        start_alt = float(self.alt_layers[0]) if getattr(self, "alt_layers", None) and len(self.alt_layers) > 0 else float(self.cfg.get("scan_alt_start", -15.0))
        goto_speed = max(1.0, float(self.cfg.get("max_goto_speed", 10.0)))
        zoom_wait = max(0.1, float(self.cfg.get("zoom_settle_wait_sec", 2.0)))
        focus_wait = max(0.1, float(self.cfg.get("focus_settle_sec", 3.5)))

        # =========================================================================
        # 1. First move PTZ to start position and ensure it is COMPLETELY stationary
        # =========================================================================
        try:
            cur_az, cur_alt = self.ptz.get_position()
            dist = math.sqrt(shortest_angular_diff(az_start, cur_az)**2 + (start_alt - cur_alt)**2)
            if dist > 0.5:
                logger.info(f"🧭 [ScanPrep] Slew PTZ to start Az={az_start:.1f}°, Alt={start_alt:.1f}° (dist={dist:.1f}°)...")
                self.ptz.goto_position(az_start, start_alt, speed=goto_speed, wait=True, tolerance=0.5)
            self.ptz.stop()
            time.sleep(0.5)  # Let mechanical vibration settle completely
        except Exception as e:
            logger.warning(f"[ScanPrep] Error positioning PTZ to start: {e}")

        if getattr(self, "_abort_cycle", False) or self.state in (MissionState.IDLE, MissionState.PAUSED) or not self._running:
            return

        # =========================================================================
        # 2. PTZ is now stationary at start position. ONLY NOW command Camera Zoom!
        # =========================================================================
        th_cam = self.cam_mgr.get_thermal_camera()
        vis_cam = self.cam_mgr.get_visible_camera()

        logger.info("🔭 [ScanPrep] Step 2/3: PTZ is stationary at start position. Now adjusting zoom lenses...")
        try:
            if th_cam and hasattr(th_cam, 'set_focal_length_mm'):
                logger.info(f"🔭 [ScanPrep] Command Thermal Camera zoom to {f_val:.1f}mm...")
                th_cam.set_focal_length_mm(f_val)

            if bool(self.cfg.get("visible_sync_scan_zoom", True)) and vis_cam and hasattr(vis_cam, 'set_focal_length_mm'):
                target_vis_focal = self.calculate_synchronized_visible_focal(f_val)
                logger.info(
                    f"🔭 [ScanPrep] Command Visible Camera zoom to {target_vis_focal:.1f}mm "
                    f"(Target FOV = {float(self.cfg.get('visible_fov_multiplier', 2.0)):.1f}x Thermal)..."
                )
                vis_cam.set_focal_length_mm(target_vis_focal)
        except Exception as e:
            logger.warning(f"[ScanPrep] Error commanding camera zoom: {e}")

        # Wait for zoom motors to complete travel while PTZ remains completely stationary
        logger.info(f"⏳ [ScanPrep] Waiting {zoom_wait:.1f}s for zoom motors to settle (PTZ stationary)...")
        zoom_end = time.time() + zoom_wait
        while time.time() < zoom_end:
            if getattr(self, "_abort_cycle", False) or self.state in (MissionState.IDLE, MissionState.PAUSED) or not self._running:
                return
            time.sleep(0.2)

        if getattr(self, "_abort_cycle", False) or self.state in (MissionState.IDLE, MissionState.PAUSED) or not self._running:
            return

        # =========================================================================
        # 3. Zoom is settled. Trigger Auto-Focus while PTZ remains stationary!
        # =========================================================================
        logger.info("🎯 [ScanPrep] Step 3/3: Zoom settled. Triggering Auto-Focus on Thermal & Visible cameras...")
        try:
            if th_cam and hasattr(th_cam, 'trigger_auto_focus'):
                th_cam.trigger_auto_focus()
            if vis_cam and hasattr(vis_cam, 'trigger_auto_focus'):
                vis_cam.trigger_auto_focus()
        except Exception as e:
            logger.warning(f"[ScanPrep] Error triggering auto-focus: {e}")

        # Wait for Auto-Focus to settle and lock onto scene
        logger.info(f"⏳ [ScanPrep] Waiting {focus_wait:.1f}s for Auto-Focus to stabilize before scan starts...")
        focus_end = time.time() + focus_wait
        while time.time() < focus_end:
            if getattr(self, "_abort_cycle", False) or self.state in (MissionState.IDLE, MissionState.PAUSED) or not self._running:
                return
            if th_cam:
                sharpness = th_cam.compute_sharpness()
                logger.debug(f"[ScanPrep] Thermal focus sharpness: {sharpness:.1f}")
            time.sleep(0.3)

        # =========================================================================
        # 4. Preparation complete - Ready to scan!
        # =========================================================================
        self.verifier.tracks.clear()
        self.is_ai_paused = False
        self._needs_optics_prep = False
        logger.info("✅ [ScanPrep] PTZ positioned, Zoom & Auto-Focus fully prepared and stabilized. Starting scan sweep now!")
        self._set_state(MissionState.SEARCH_SWEEP)

    def _sentry_loop(self):
        """Autonomous Sentry Loop dispatching between Continuous Sweep and Step Sweep."""
        time.sleep(1.0)

        while self._running:
            try:
                if self.state not in (
                    MissionState.SEARCH_SWEEP,
                    MissionState.STEP_MOVING,
                    MissionState.STEP_DWELLING,
                    MissionState.PREPARING_OPTICS,
                ):
                    time.sleep(0.1)
                    continue

                if self.state == MissionState.PREPARING_OPTICS or getattr(self, "_needs_optics_prep", False):
                    self._prepare_scan_optics()
                    if self.state in (MissionState.IDLE, MissionState.PAUSED) or getattr(self, "_abort_cycle", False):
                        continue

                scan_mode = self.cfg.get("scan_mode", "CONTINUOUS").upper()
                if scan_mode == "STEP_SWEEP":
                    self._run_step_sweep_cycle()
                else:
                    self._run_continuous_sweep_cycle()
            except Exception as e:
                logger.exception(f"Unexpected error in Sentry Loop: {e}")
                time.sleep(1.0)

    def _run_step_sweep_cycle(self):
        """Step-by-Step (Step & Stare) sentry scan over multi-layer snake grid."""
        az_start = float(self.cfg.get("scan_az_start", -180.0))
        az_end = float(self.cfg.get("scan_az_end", 180.0))
        dwell_sec = max(0.5, float(self.cfg.get("step_dwell_sec", 1.5)))
        goto_speed = max(1.0, float(self.cfg.get("step_goto_speed", 10.0)))
        step_calc_mode = self.cfg.get("step_calc_mode", "DEGREE").upper()

        alt_layers = list(getattr(self, "alt_layers", [-15.0, -10.0, -5.0, 0.0, 5.0]))
        if not alt_layers:
            alt_layers = [float(self.cfg.get("scan_alt_start", -15.0))]

        # Determine Azimuth Step Angle
        if step_calc_mode == "FOV_AUTO":
            thermal_cam = self.cam_mgr.get_thermal_camera()
            focal_mm = getattr(thermal_cam, "current_focal_mm", 31.0) if thermal_cam else 31.0
            overlap_ratio = float(self.cfg.get("step_overlap_pct", 20.0)) / 100.0
            az_step = self.calculate_step_from_focal_length(focal_mm, reference_fov_deg=14.2, overlap_ratio=overlap_ratio)
        else:
            az_step = max(1.0, float(self.cfg.get("step_az_deg", 12.0)))

        waypoints = self.generate_snake_grid(az_start, az_end, alt_layers, az_step)
        self.total_waypoints_count = len(waypoints)

        is_resume_cycle = getattr(self, "is_resuming", False)
        self.is_resuming = False
        start_wp = max(0, min(self.resume_wp_idx, len(waypoints) - 1)) if is_resume_cycle else 0
        logger.info(
            f"[StepSweep] Starting Grid Scan ({self.total_waypoints_count} points, from wp {start_wp + 1}, is_resume={is_resume_cycle}, "
            f"Az step={az_step:.2f}°, Dwell={dwell_sec}s, SlewSpeed={goto_speed}°/s)"
        )

        for wp_idx in range(start_wp, len(waypoints)):
            if self.state not in (MissionState.SEARCH_SWEEP, MissionState.STEP_MOVING, MissionState.STEP_DWELLING) or getattr(self, "_abort_cycle", False) or not self._running:
                if self.is_paused:
                    self.resume_wp_idx = wp_idx
                self.ptz.stop()
                break

            self.resume_wp_idx = wp_idx
            wp_az, wp_alt = waypoints[wp_idx]
            self.current_waypoint_idx = wp_idx + 1

            # Update altitude index
            for l_idx, l_alt in enumerate(alt_layers):
                if abs(l_alt - wp_alt) < 0.01:
                    self.current_alt_idx = l_idx
                    break

            # 1. Step Moving Phase (Check if already at waypoint before slewing)
            cur_az, cur_alt = self.ptz.get_position()
            if abs(cur_az - wp_az) > 0.5 or abs(cur_alt - wp_alt) > 0.5:
                self._set_state(MissionState.STEP_MOVING)
                logger.info(f"[StepSweep] Moving to Waypoint {self.current_waypoint_idx}/{self.total_waypoints_count}: Az={wp_az:.2f}°, Alt={wp_alt:.2f}°")
                self.ptz.goto_position(wp_az, wp_alt, speed=goto_speed, wait=True, tolerance=0.5)

            if self.state not in (MissionState.SEARCH_SWEEP, MissionState.STEP_MOVING, MissionState.STEP_DWELLING) or getattr(self, "_abort_cycle", False) or not self._running:
                if self.is_paused:
                    self.resume_wp_idx = wp_idx
                self.ptz.stop()
                break

            # 2. Step Dwelling (Stabilized AI Verification) Phase
            self.ptz.stop()
            self._set_state(MissionState.STEP_DWELLING)
            logger.info(f"[StepSweep] Stare/Dwell @ Waypoint {self.current_waypoint_idx} for {dwell_sec}s...")

            dwell_end = time.time() + dwell_sec
            fire_confirmed = False

            while time.time() < dwell_end and self._running:
                if self.state not in (MissionState.SEARCH_SWEEP, MissionState.STEP_MOVING, MissionState.STEP_DWELLING) or getattr(self, "_abort_cycle", False):
                    break

                # Continuous check for confirmed fire (ignore lingering hold tracks & recently verified targets)
                confirmed_tracks = [
                    t for t in self.verifier.tracks
                    if t.state == "CONFIRMED_FIRE" and t.tracker.time_since_update <= 1 and not getattr(t, "is_held", False)
                ]
                if len(confirmed_tracks) > 0:
                    cur_az, cur_alt = self.ptz.get_position()
                    if not self.is_recently_verified(cur_az, cur_alt):
                        target = confirmed_tracks[0]
                        self.current_fire_target = target
                        self.locked_azimuth = cur_az
                        self.locked_altitude = cur_alt
                        logger.info(f" Fire Confirmed at Step Waypoint {self.current_waypoint_idx} (Az={cur_az:.2f}°, Alt={cur_alt:.2f}°)! Locking Target...")
                        self.ptz.stop()
                        fire_confirmed = True
                        self._handle_fire_verification_cycle()
                        break
                else:
                    cur_az, cur_alt = self.ptz.get_position()
                    h_fov, v_fov = self.calculate_fov(focal_mm if 'focal_mm' in locals() else 31.0)
                    recheck_item = self._find_step_watchlist_item_to_intercept(cur_az, cur_alt, h_fov, v_fov)
                    if recheck_item:
                        self.ptz.stop()
                        fire_confirmed = True
                        self._handle_watchlist_recheck(recheck_item)
                        break

                time.sleep(0.05)

            if fire_confirmed:
                pass

        if self.state in (MissionState.SEARCH_SWEEP, MissionState.STEP_MOVING, MissionState.STEP_DWELLING) and not getattr(self, "_abort_cycle", False):
            self.resume_wp_idx = 0
            self.sweep_cycle_count += 1
            logger.info(f"[StepSweep] Full grid scan complete (Cycle #{self.sweep_cycle_count}). Restarting next cycle in 1s...")
            self._set_state(MissionState.SEARCH_SWEEP)
            time.sleep(1.0)

    def _run_continuous_sweep_cycle(self):
        """Continuous Smooth Sentry Scan with Bidirectional Continuous Serpentine Grid."""
        az_start = float(self.cfg.get("scan_az_start", -180.0))
        az_end = float(self.cfg.get("scan_az_end", 180.0))
        az_speed = abs(float(self.cfg.get("sweep_speed_deg_s", 1.0)))
        goto_speed = max(1.0, float(self.cfg.get("max_goto_speed", 10.0)))
        settle_sec = max(0.1, float(self.cfg.get("settle_sec", 0.5)))
        base_layers = list(getattr(self, "alt_layers", [-15.0, -10.0, -5.0, 0.0, 5.0]))
        if not base_layers:
            base_layers = [float(self.cfg.get("scan_alt_start", -15.0))]

        scan_focal = float(self.cfg.get("scan_focal_length_mm", 31.0))
        h_fov, v_fov = self.calculate_fov(scan_focal)

        # Determine layers for this cycle based on current grid_direction
        # If UP: scan base_layers upwards (e.g. [-15, -10, -5, 0, +5])
        # If DOWN: scan reversed base_layers downwards (e.g. [0, -5, -10, -15])
        if len(base_layers) > 1:
            if self.grid_direction == "DOWN":
                # Downward pass: starts from the layer below the top layer down to the bottom
                active_layers = list(reversed(base_layers[:-1]))
            elif self.sweep_cycle_count > 0:
                # Upward pass after a downward pass: starts from the layer above the bottom layer up to the top
                active_layers = list(base_layers[1:])
            else:
                # First pass (fresh start): all layers from bottom to top
                active_layers = list(base_layers)
        else:
            active_layers = list(base_layers)

        is_resume_cycle = getattr(self, "is_resuming", False)
        self.is_resuming = False
        start_layer = max(0, min(self.resume_alt_idx, len(active_layers) - 1)) if is_resume_cycle else 0

        logger.info(
            f"[ContinuousSweep] Starting Cycle #{self.sweep_cycle_count + 1} ({self.grid_direction}): "
            f"{len(active_layers)} layers {active_layers} (from layer {start_layer + 1}, is_resume={is_resume_cycle}) "
            f"Az: {az_start}° <-> {az_end}° @ {az_speed}°/s"
        )

        # Pre-position to start ONLY at the very first start of the mission (when cycle == 0 and not resuming)
        if not is_resume_cycle and self.sweep_cycle_count == 0 and self.state == MissionState.SEARCH_SWEEP and not getattr(self, "_abort_cycle", False):
            cur_az, cur_alt = self.ptz.get_position()
            dist = math.sqrt(shortest_angular_diff(az_start, cur_az)**2 + (active_layers[0] - cur_alt)**2)
            if dist > 0.5:
                self.ptz.goto_position(az_start, active_layers[0], speed=goto_speed, wait=True, tolerance=0.5)
                time.sleep(settle_sec)

        for row_idx in range(start_layer, len(active_layers)):
            if self.state != MissionState.SEARCH_SWEEP or getattr(self, "_abort_cycle", False) or not self._running:
                if self.is_paused:
                    self.resume_alt_idx = row_idx
                self.ptz.stop()
                break

            self.resume_alt_idx = row_idx
            self.current_alt_idx = row_idx
            row_alt = active_layers[row_idx]

            # Query current PTZ position at the start of each layer
            cur_az, cur_alt = self.ptz.get_position()

            # Check if resuming on the exact paused row
            is_resuming_this_row = (is_resume_cycle and row_idx == start_layer and getattr(self, "paused_az", None) is not None)

            if is_resuming_this_row:
                # 1. Check if user moved PTZ away while paused
                dist_moved = math.sqrt(shortest_angular_diff(self.paused_az, cur_az)**2 + (self.paused_alt - cur_alt)**2)
                if dist_moved > 1.0:
                    logger.info(f"[ContinuousSweep] Resuming: PTZ was moved {dist_moved:.1f}° away while paused. Returning to paused position: Az={self.paused_az:.1f}°, Alt={self.paused_alt:.1f}°...")
                    self.ptz.goto_position(self.paused_az, self.paused_alt, speed=goto_speed, wait=True, tolerance=0.5)
                    time.sleep(settle_sec)
                    cur_az, cur_alt = self.ptz.get_position()
                elif abs(cur_alt - row_alt) > 0.5:
                    self.ptz.goto_position(cur_az, row_alt, speed=goto_speed, wait=True, tolerance=0.5)
                    time.sleep(settle_sec)
                    cur_az, cur_alt = self.ptz.get_position()

                # Restore previous sweep target and direction
                row_end_az = getattr(self, "resume_target_az", None)
                direction = getattr(self, "resume_direction", None)
                if row_end_az is None or direction is None:
                    row_end_az = az_end if shortest_angular_diff(az_end, cur_az) != 0 else az_start
                    direction = 1.0 if shortest_angular_diff(row_end_az, cur_az) >= 0 else -1.0
                row_start_az = az_start if row_end_az == az_end else az_end

                # Clear pause markers
                self.paused_az = None
                self.paused_alt = None
                self.resume_target_az = None
                self.resume_direction = None
                is_resume_cycle = False
            else:
                # In continuous serpentine sweep:
                # Determine sweep direction (towards az_end or towards az_start) based on current PTZ azimuth
                d_to_start = abs(shortest_angular_diff(az_start, cur_az))
                d_to_end = abs(shortest_angular_diff(az_end, cur_az))
                if d_to_end < d_to_start:
                    # Closer to az_end -> sweep from az_end to az_start
                    row_start_az = az_end
                    row_end_az = az_start
                else:
                    # Closer to az_start -> sweep from az_start to az_end
                    row_start_az = az_start
                    row_end_az = az_end

                diff_sweep = shortest_angular_diff(row_end_az, row_start_az)
                direction = 1.0 if diff_sweep >= 0 else -1.0

                # Adjust altitude to row_alt (and azimuth if not near row_start_az)
                needs_goto = False
                if abs(cur_alt - row_alt) > 0.5:
                    needs_goto = True
                if abs(shortest_angular_diff(row_start_az, cur_az)) > 3.0:
                    needs_goto = True

                if needs_goto and not getattr(self, "_abort_cycle", False):
                    logger.info(f"[ContinuousSweep] Layer {row_idx+1}/{len(active_layers)}: Adjust Alt={row_alt}° (Az={row_start_az}°)...")
                    self.ptz.goto_position(row_start_az, row_alt, speed=goto_speed, wait=True, tolerance=0.5)
                    time.sleep(settle_sec)

            self.current_sweep_row_end_az = row_end_az
            self.current_sweep_direction = direction

            if self.state != MissionState.SEARCH_SWEEP or getattr(self, "_abort_cycle", False):
                if self.is_paused:
                    self.resume_alt_idx = row_idx
                self.ptz.stop()
                break

            cur_az, cur_alt = self.ptz.get_position()
            logger.info(f"[ContinuousSweep] Layer {row_idx+1}/{len(active_layers)} (Alt={row_alt}°): Sweeping Azimuth {cur_az:.1f}° to {row_end_az:.1f}°...")
            command_az_vel = direction * az_speed

            # Continuous sweep across row
            while self.state == MissionState.SEARCH_SWEEP and not getattr(self, "_abort_cycle", False) and self._running:
                confirmed_tracks = [
                    t for t in self.verifier.tracks
                    if t.state == "CONFIRMED_FIRE" and t.tracker.time_since_update <= 1 and not getattr(t, "is_held", False)
                ]
                if len(confirmed_tracks) > 0:
                    cur_az, cur_alt = self.ptz.get_position()
                    if not self.is_recently_verified(cur_az, cur_alt):
                        target = confirmed_tracks[0]
                        self.current_fire_target = target
                        self.locked_azimuth = cur_az
                        self.locked_altitude = cur_alt
                        logger.info(f" Hotspot Confirmed at Az={cur_az:.2f}°, Alt={cur_alt:.2f}°! Stopping Sweep & Locking Target...")
                        self.ptz.stop()
                        self._handle_fire_verification_cycle()
                        if self.state != MissionState.SEARCH_SWEEP or getattr(self, "_abort_cycle", False):
                            break
                        # Resume continuous sweep on the current row from the current position towards row_end_az
                        cur_az, cur_alt = self.ptz.get_position()
                        alt_err = row_alt - cur_alt
                        alt_hold_vel = max(-1.0, min(1.0, alt_err / 0.75))
                        self.ptz.set_velocity(command_az_vel, alt_hold_vel)
                        logger.info(f"[ContinuousSweep] Resuming sweep on Layer {row_idx+1} from Az={cur_az:.1f}° towards {row_end_az:.1f}°...")
                        time.sleep(0.3)
                        continue

                cur_az, cur_alt = self.ptz.get_position()

                # Check if we should intercept a remembered hotspot for re-checking in this cycle
                recheck_item = self._find_watchlist_item_to_intercept(cur_az, cur_alt, row_alt, direction, v_fov)
                if recheck_item:
                    logger.info(
                        f"📍 [HotspotWatchlist] Intercepting remembered hotspot {recheck_item['incident_id']} at "
                        f"Az={recheck_item['azimuth']:.2f}°, Alt={recheck_item['altitude']:.2f}° (Cycle #{self.sweep_cycle_count + 1})"
                    )
                    self.ptz.stop()
                    self._handle_watchlist_recheck(recheck_item)
                    if self.state != MissionState.SEARCH_SWEEP or getattr(self, "_abort_cycle", False):
                        break
                    # Resume continuous sweep on the current row from the current position towards row_end_az
                    cur_az, cur_alt = self.ptz.get_position()
                    alt_err = row_alt - cur_alt
                    alt_hold_vel = max(-1.0, min(1.0, alt_err / 0.75))
                    self.ptz.set_velocity(command_az_vel, alt_hold_vel)
                    logger.info(f"[ContinuousSweep] Resuming sweep on Layer {row_idx+1} from Az={cur_az:.1f}° towards {row_end_az:.1f}°...")
                    time.sleep(0.3)
                    continue

                alt_err = row_alt - cur_alt
                alt_hold_vel = max(-1.0, min(1.0, alt_err / 0.75))

                err_to_end = shortest_angular_diff(row_end_az, cur_az)
                reached_end = (err_to_end <= 0.4) if direction > 0 else (err_to_end >= -0.4)
                if reached_end:
                    logger.info(f"[ContinuousSweep] Layer {row_idx+1} reached boundary at Az={cur_az:.2f}°.")
                    self.ptz.stop()
                    time.sleep(settle_sec)
                    break

                self.ptz.set_velocity(command_az_vel, alt_hold_vel)
                time.sleep(0.08)

            self.ptz.stop()

            # If paused during this row, save CURRENT row index and break immediately
            if self.is_paused:
                self.resume_alt_idx = row_idx
                logger.info(f"[ContinuousSweep] Paused at layer {row_idx+1} (Alt={row_alt}°). Saved resume_alt_idx={row_idx}")
                break

        if self.state == MissionState.SEARCH_SWEEP and not getattr(self, "_abort_cycle", False):
            self.resume_alt_idx = 0
            self.sweep_cycle_count += 1
            # Seamlessly toggle direction between UP and DOWN
            self.grid_direction = "DOWN" if self.grid_direction == "UP" else "UP"
            logger.info(f"[ContinuousSweep] Cycle #{self.sweep_cycle_count} complete! Next cycle direction: {self.grid_direction}. Reversing smoothly...")
            time.sleep(0.5)

    def _center_target_in_thermal(self):
        """
        Calculates angular offset of detected target from thermal optical center
        and slews PTZ mount so the target is aligned at dead-center before zooming.
        """
        if not self.current_fire_target:
            return

        try:
            # 1. Extract Target Bounding Box
            bbox = None
            if hasattr(self.current_fire_target, 'tracker'):
                bbox = self.current_fire_target.tracker.get_state()
            elif hasattr(self.current_fire_target, 'bbox'):
                bbox = self.current_fire_target.bbox
            elif hasattr(self.current_fire_target, 'box_history') and self.current_fire_target.box_history:
                bbox = self.current_fire_target.box_history[-1]

            if not bbox or len(bbox) < 4:
                return
            self._target_bbox = [float(b) for b in bbox]

            # 2. Get Thermal Camera Dimensions & Current FOV
            th_cam = self.cam_mgr.get_thermal_camera()
            frame_w = 640.0
            frame_h = 512.0
            if th_cam and th_cam.latest_bgr is not None:
                h, w = th_cam.latest_bgr.shape[:2]
                frame_w, frame_h = float(w), float(h)

            cx = frame_w / 2.0
            cy = frame_h / 2.0

            tx = (float(bbox[0]) + float(bbox[2])) / 2.0
            ty = (float(bbox[1]) + float(bbox[3])) / 2.0

            # Pixel offset normalized to [-0.5, 0.5]
            dx_norm = (tx - cx) / frame_w
            dy_norm = (ty - cy) / frame_h

            zoom_info = th_cam.get_zoom_info() if th_cam else {}
            fov_h = float(zoom_info.get("fov_h", 14.2))
            fov_v = float(zoom_info.get("fov_v", fov_h * (frame_h / frame_w)))

            # Angular offsets in degrees
            # dx > 0 (target is to the right) -> pan right (+Az)
            # dy > 0 (target is below center) -> tilt down (-Alt)
            d_az = dx_norm * fov_h
            d_alt = -dy_norm * fov_v

            cur_az, cur_alt = self.ptz.get_position()
            target_az = normalize_angle_360(cur_az + d_az)
            target_alt = cur_alt + d_alt

            # Check mount limits
            min_alt = float(self.cfg.get("alt_min", -30.0))
            max_alt = float(self.cfg.get("alt_max", 60.0))
            target_alt = max(min_alt, min(max_alt, target_alt))

            # Only slew if angular error is significant (> 0.2 deg)
            if abs(d_az) > 0.2 or abs(d_alt) > 0.2:
                logger.info(
                    f" [Centering] Target Pixel=({tx:.0f}, {ty:.0f}), Center=({cx:.0f}, {cy:.0f}) | "
                    f"Offset: ΔAz={d_az:+.2f}°, ΔAlt={d_alt:+.2f}°  Moving PTZ to Az={target_az:.2f}°, Alt={target_alt:.2f}°"
                )
                self.ptz.goto_position(target_az, target_alt, speed=6.0, wait=True, tolerance=0.3, timeout=8.0)
                final_az, final_alt = self.ptz.get_position()
                self.locked_azimuth = final_az
                self.locked_altitude = final_alt
                logger.info(f" [Centering] Target centered at Az={final_az:.2f}°, Alt={final_alt:.2f}°")
            else:
                logger.info(f" [Centering] Target already centered (ΔAz={d_az:+.2f}°, ΔAlt={d_alt:+.2f}°).")
        except Exception as e:
            logger.error(f"Error during target centering: {e}", exc_info=True)

    def _calculate_adaptive_zoom_focal(
        self,
        bbox: Optional[List[float]],
        frame_w: float = 640.0,
        frame_h: float = 512.0,
        cur_focal: float = 31.0,
        max_focal: float = 155.0,
        safety_margin: float = 0.12,
        is_centered: bool = True
    ) -> float:
        """
        Calculates maximum safe optical focal length to zoom as close as possible to the hotspot
        without allowing the hotspot bounding box to exceed the frame boundaries (including safety margin).
        """
        if not bbox or len(bbox) < 4:
            return max_focal

        cx = frame_w / 2.0
        cy = frame_h / 2.0
        x1, y1, x2, y2 = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
        w = max(1.0, x2 - x1)
        h = max(1.0, y2 - y1)

        # Max optical magnification based on hardware limit
        max_m = (max_focal / cur_focal) if cur_focal > 0 else 5.0
        constraints = [max_m]

        if is_centered:
            # Target was centered by PTZ, so it expands symmetrically around optical center (cx, cy)
            m_w = (frame_w * (1.0 - 2.0 * safety_margin)) / w
            m_h = (frame_h * (1.0 - 2.0 * safety_margin)) / h
            constraints.append(m_w)
            constraints.append(m_h)
        else:
            margin_x = safety_margin * frame_w
            margin_y = safety_margin * frame_h
            if x1 < cx:
                constraints.append((cx - margin_x) / max(1.0, cx - x1))
            if x2 > cx:
                constraints.append((frame_w - margin_x - cx) / max(1.0, x2 - cx))
            if y1 < cy:
                constraints.append((cy - margin_y) / max(1.0, cy - y1))
            if y2 > cy:
                constraints.append((frame_h - margin_y - cy) / max(1.0, y2 - cy))

        safe_m = max(1.0, min(constraints))
        # Must zoom in (target_focal >= cur_focal)
        target_focal = max(cur_focal, min(max_focal, cur_focal * safe_m))
        logger.info(
            f"[AdaptiveZoom] Hotspot size=[{w:.0f}x{h:.0f}] (centered={is_centered}) | "
            f"Frame={frame_w:.0f}x{frame_h:.0f} | Cur Focal={cur_focal:.1f}mm | Safe Zoom={safe_m:.2f}x -> Target Focal={target_focal:.1f}mm"
        )
        return float(target_focal)

    def _evaluate_deep_zoom_hotspot(self, thermal_cam) -> Tuple[bool, Optional[Any], Optional[List[int]]]:
        """
        Evaluates whether a genuine fire hotspot exists in the deep zoom frame.
        Requires either:
        1. Confirmed AI Verifier Track with hits and thermal core pass, OR
        2. Thermal Connected Component with:
           - Brightness >= hotspot_threshold (at least 230-240)
           - Contiguous Area >= min_hotspot_area (at least 15 pixels)
           - Peak core value >= thermal_core_min_val (245)
        Returns: (is_confirmed, best_target_track, bounding_box)
        """
        import config
        ai_cfg = getattr(config, "AI_CONFIG", {})
        th_limit = int(ai_cfg.get("hotspot_threshold", 240))
        min_area = int(ai_cfg.get("min_hotspot_area", 15))
        core_min = int(ai_cfg.get("thermal_core_min_val", 245))

        # 1. Check AI verifier tracks first
        try:
            confirmed_tracks = [
                t for t in self.verifier.tracks
                if (t.state == "CONFIRMED_FIRE" or (hasattr(t, 'tracker') and getattr(t.tracker, 'hits', 0) >= 2) or getattr(t, 'hits', 0) >= 2)
                and getattr(t, 'thermal_core_pass', True)
            ]
            if confirmed_tracks:
                best_track = confirmed_tracks[0]
                bbox = None
                if hasattr(best_track, 'tracker'):
                    bbox = best_track.tracker.get_state()
                elif hasattr(best_track, 'bbox'):
                    bbox = best_track.bbox
                track_hits = getattr(best_track.tracker, 'hits', getattr(best_track, 'hits', 1)) if hasattr(best_track, 'tracker') else getattr(best_track, 'hits', 1)
                logger.info(f"🔥 Deep Zoom AI Track Confirmed: {best_track.state} (Hits={track_hits}, Score={best_track.score:.2f})")
                return True, best_track, bbox
        except Exception as e:
            logger.warning(f"Warning checking AI verifier tracks during deep zoom: {e}")

        # 2. Fallback: inspect raw thermal frame with strict connected components & multi-pixel area filter
        if thermal_cam and thermal_cam.latest_bgr is not None:
            try:
                gray_th = cv2.cvtColor(thermal_cam.latest_bgr, cv2.COLOR_BGR2GRAY)
                # Must have true high heat pixels
                if np.max(gray_th) >= th_limit:
                    _, mask = cv2.threshold(gray_th, th_limit, 255, cv2.THRESH_BINARY)
                    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(mask)
                    best_area = 0
                    best_box = None
                    for i in range(1, num_labels):
                        area = int(stats[i, cv2.CC_STAT_AREA])
                        if area >= min_area:
                            x = int(stats[i, cv2.CC_STAT_LEFT])
                            y = int(stats[i, cv2.CC_STAT_TOP])
                            w = int(stats[i, cv2.CC_STAT_WIDTH])
                            h = int(stats[i, cv2.CC_STAT_HEIGHT])
                            roi = gray_th[y:y+h, x:x+w]
                            if np.max(roi) >= core_min:
                                if area > best_area:
                                    best_area = area
                                    best_box = [x, y, x + w, y + h]
                    if best_box is not None:
                        logger.info(f"🔥 Deep Zoom Direct Hotspot Confirmed: Area={best_area}px (Threshold={th_limit}, MinArea={min_area})")
                        return True, None, best_box
            except Exception as e:
                logger.error(f"Error evaluating deep zoom thermal hotspot: {e}")

        return False, None, None

    def _evaluate_pre_zoom_hotspot(self, thermal_cam) -> Tuple[bool, Optional[Any], Optional[List[int]]]:
        """
        Evaluates whether a candidate hotspot is still present while stationary before zooming in.
        Rejects transient solar glints, foliage reflections, and motion artifacts.
        """
        import config
        ai_cfg = getattr(config, "AI_CONFIG", {})
        th_limit = int(ai_cfg.get("hotspot_threshold", 225))
        min_area = int(ai_cfg.get("min_hotspot_area", 10))
        core_min = int(ai_cfg.get("thermal_core_min_val", 190))

        # 1. Check AI verifier active tracks with recent updates
        confirmed_tracks = [
            t for t in self.verifier.tracks
            if (t.state == "CONFIRMED_FIRE" or (hasattr(t, "tracker") and getattr(t.tracker, "hits", 0) >= 2))
            and hasattr(t, "tracker") and t.tracker.time_since_update <= 1
        ]
        if confirmed_tracks:
            best_track = confirmed_tracks[0]
            bbox = None
            if hasattr(best_track, 'tracker'):
                bbox = best_track.tracker.get_state()
            elif hasattr(best_track, 'bbox'):
                bbox = best_track.bbox
            track_hits = getattr(best_track.tracker, "hits", getattr(best_track, "hits", 1)) if hasattr(best_track, "tracker") else getattr(best_track, "hits", 1)
            age = best_track.tracker.time_since_update if hasattr(best_track, "tracker") else 0
            logger.info(f"🔍 [PreZoom] Active track confirmed while stationary: {best_track.state} (Hits={track_hits}, Age={age})")
            return True, best_track, bbox

        # 2. Check raw thermal frame for hot cluster
        if thermal_cam and thermal_cam.latest_bgr is not None:
            try:
                gray_th = cv2.cvtColor(thermal_cam.latest_bgr, cv2.COLOR_BGR2GRAY)
                if np.max(gray_th) >= th_limit:
                    _, mask = cv2.threshold(gray_th, th_limit, 255, cv2.THRESH_BINARY)
                    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(mask)
                    best_area = 0
                    best_box = None
                    for i in range(1, num_labels):
                        area = int(stats[i, cv2.CC_STAT_AREA])
                        if area >= min_area:
                            x = int(stats[i, cv2.CC_STAT_LEFT])
                            y = int(stats[i, cv2.CC_STAT_TOP])
                            w = int(stats[i, cv2.CC_STAT_WIDTH])
                            h = int(stats[i, cv2.CC_STAT_HEIGHT])
                            roi = gray_th[y:y+h, x:x+w]
                            if np.max(roi) >= core_min:
                                if area > best_area:
                                    best_area = area
                                    best_box = [x, y, x + w, y + h]
                    if best_box is not None:
                        logger.info(f"🔍 [PreZoom] Thermal hotspot persists while stationary: Area={best_area}px (MaxCore={np.max(gray_th)})")
                        return True, None, best_box
            except Exception as e:
                logger.error(f"Error evaluating pre-zoom stationary hotspot: {e}")

        return False, None, None

    def _handle_fire_verification_cycle(self):
        """Runs the deep zoom confirmation state machine when fire is verified."""
        try:
            if getattr(self, "_abort_cycle", False) or self.state in (MissionState.IDLE, MissionState.PAUSED):
                return

            self._set_state(MissionState.TARGET_CENTERING)
            self._center_target_in_thermal()
            time.sleep(0.5)

            if getattr(self, "_abort_cycle", False) or self.state in (MissionState.IDLE, MissionState.PAUSED):
                return

            thermal_cam = self.cam_mgr.get_thermal_camera()
            visible_cam = self.cam_mgr.get_visible_camera()

            # Pre-Zoom Stationary Stare Check: verify hotspot persists while stationary before zooming (currently disabled per user request)
            pre_zoom_enabled = bool(self.cfg.get("pre_zoom_check_enabled", False))
            pre_zoom_stare_sec = float(self.cfg.get("pre_zoom_stare_sec", 0.8))

            if pre_zoom_enabled:
                time.sleep(pre_zoom_stare_sec)

                if getattr(self, "_abort_cycle", False) or self.state in (MissionState.IDLE, MissionState.PAUSED):
                    return

                is_still_hot, stare_target, stare_box = self._evaluate_pre_zoom_hotspot(thermal_cam)
                if not is_still_hot:
                    cur_az, cur_alt = self.ptz.get_position()
                    logger.info(
                        f"💨 [PreZoom] Target at Az={cur_az:.2f}°, Alt={cur_alt:.2f}° disappeared after "
                        f"{pre_zoom_stare_sec:.1f}s stationary stare (Transient/Glint). Aborting optical zoom!"
                    )
                    self.locked_targets_history.append({"az": cur_az, "alt": cur_alt, "time": time.time()})
                    self.verifier.tracks.clear()
                    self.current_fire_target = None
                    self._target_bbox = None
                    return
                else:
                    if stare_box is not None:
                        self._target_bbox = stare_box
                    if stare_target is not None:
                        self.current_fire_target = stare_target

            # Proceed to Optical Zoom
            has_zoom_cam = (thermal_cam and thermal_cam.ptz) or (visible_cam and visible_cam.ptz)

            if has_zoom_cam:
                self.verifier.tracks.clear()
                self.is_ai_paused = True

                # Determine camera frame dimensions & current focal length
                frame_w, frame_h = 640.0, 512.0
                if thermal_cam and thermal_cam.latest_bgr is not None:
                    h, w = thermal_cam.latest_bgr.shape[:2]
                    frame_w, frame_h = float(w), float(h)

                cur_th_focal = float(thermal_cam.get_zoom_info().get("focal_mm", self.cfg.get("scan_focal_length_mm", 31.0))) if thermal_cam else 31.0
                max_th_focal = float(getattr(thermal_cam, 'max_focal_mm', 155.0))

                bbox = getattr(self, '_target_bbox', None)
                if not bbox and self.current_fire_target:
                    if hasattr(self.current_fire_target, 'tracker'):
                        bbox = self.current_fire_target.tracker.get_state()
                    elif hasattr(self.current_fire_target, 'bbox'):
                        bbox = self.current_fire_target.bbox
                    elif hasattr(self.current_fire_target, 'box_history') and self.current_fire_target.box_history:
                        bbox = self.current_fire_target.box_history[-1]

                target_th_focal = self._calculate_adaptive_zoom_focal(
                    bbox=bbox,
                    frame_w=frame_w,
                    frame_h=frame_h,
                    cur_focal=cur_th_focal,
                    max_focal=max_th_focal,
                    safety_margin=0.12,
                    is_centered=True
                )
                self._last_zoom_focal = target_th_focal

                logger.info(f"🔭 Initiating Adaptive Optical Zoom In to {target_th_focal:.1f}mm (Current={cur_th_focal:.1f}mm)...")

                if thermal_cam and hasattr(thermal_cam, 'set_focal_length_mm'):
                    thermal_cam.set_focal_length_mm(target_th_focal)
                    if hasattr(thermal_cam, 'trigger_auto_focus'):
                        thermal_cam.trigger_auto_focus()
                elif thermal_cam and thermal_cam.ptz:
                    thermal_cam.zoom_in(speed=0.9, duration_sec=1.5)

                if visible_cam and visible_cam.ptz:
                    # Zoom visible camera proportionally to provide sharp high-res confirmation
                    zoom_ratio = (target_th_focal - cur_th_focal) / max(1.0, max_th_focal - cur_th_focal)
                    vis_min = float(getattr(visible_cam, 'min_focal_mm', 5.1))
                    vis_max = float(getattr(visible_cam, 'max_focal_mm', 102.0))
                    target_vis_focal = vis_min + zoom_ratio * (vis_max - vis_min) * 0.75
                    if hasattr(visible_cam, 'set_focal_length_mm'):
                        visible_cam.set_focal_length_mm(target_vis_focal)
                    else:
                        visible_cam.zoom_in(speed=0.9, duration_sec=1.5)

                self._set_state(MissionState.ZOOMING_IN)
                zoom_wait = float(self.cfg.get("zoom_settle_wait_sec", 2.0))
                time.sleep(zoom_wait)

                if getattr(self, "_abort_cycle", False) or self.state in (MissionState.IDLE, MissionState.PAUSED):
                    return

                focus_wait = float(self.cfg.get("focus_settle_sec", 2.5))
                logger.info(f" Waiting {focus_wait:.1f}s for Thermal & Visible Auto-Focus to stabilize...")
                self._set_state(MissionState.VERIFYING_FOCUS)

                start_focus_t = time.time()
                while time.time() - start_focus_t < focus_wait:
                    if getattr(self, "_abort_cycle", False) or self.state in (MissionState.IDLE, MissionState.PAUSED):
                        return
                    if thermal_cam:
                        sharpness = thermal_cam.compute_sharpness()
                        logger.debug(f"Thermal focus sharpness: {sharpness:.1f}")
                    time.sleep(0.4)

                logger.info(" Image Focus Stabilized & Ready. Resuming AI Deep Confirmation...")
                self.verifier.tracks.clear()
                self.is_ai_paused = False
                self._set_state(MissionState.DEEP_CONFIRMATION)
                time.sleep(2.0)

                if getattr(self, "_abort_cycle", False) or self.state in (MissionState.IDLE, MissionState.PAUSED):
                    return

                # Strict Deep Zoom Evaluation (Must pass AI Verifier or strict multi-pixel Core Cluster)
                is_fire_confirmed, best_target, bbox = self._evaluate_deep_zoom_hotspot(thermal_cam)

                if is_fire_confirmed:
                    self.current_fire_target = best_target
                    self._target_bbox = bbox
                    logger.info(f"🔥 Fire Threat Confirmed in Zoom! Triggering Alarm & Archiving Snapshots...")
                    self._set_state(MissionState.ALARM_ACTIVE)
                    self._capture_and_record_incident()
                    alarm_hold = min(5.0, max(2.0, float(self.cfg.get("alarm_cooldown_sec", 4.0))))
                    time.sleep(alarm_hold)
                else:
                    logger.info("ℹ️ Zoom verification: No fire confirmed (False Alarm / Disappeared). Skipping Incident Record.")
                    self.current_fire_target = None
                    self._target_bbox = None

                if getattr(self, "_abort_cycle", False) or self.state in (MissionState.IDLE, MissionState.PAUSED):
                    return

                base_focal = float(self.cfg.get("scan_focal_length_mm", 31.0))
                logger.info(f" Returning Thermal Camera zoom back to scan focal length {base_focal:.1f}mm...")
                self.verifier.tracks.clear()
                self.is_ai_paused = True
                if thermal_cam and hasattr(thermal_cam, 'set_focal_length_mm'):
                    thermal_cam.set_focal_length_mm(base_focal)
                    if hasattr(thermal_cam, 'trigger_auto_focus'):
                        thermal_cam.trigger_auto_focus()
                elif thermal_cam and thermal_cam.ptz:
                    thermal_cam.zoom_out(speed=0.9, duration_sec=1.5)

                if visible_cam and hasattr(visible_cam, 'set_focal_length_mm') and bool(self.cfg.get("visible_sync_scan_zoom", True)):
                    target_vis_focal = self.calculate_synchronized_visible_focal(base_focal)
                    logger.info(f" Returning Visible Camera zoom back to synchronized scan focal length {target_vis_focal:.1f}mm...")
                    visible_cam.set_focal_length_mm(target_vis_focal)
                    if hasattr(visible_cam, 'trigger_auto_focus'):
                        visible_cam.trigger_auto_focus()
                elif visible_cam and visible_cam.ptz:
                    visible_cam.zoom_out(speed=0.9, duration_sec=1.5)

                self._set_state(MissionState.ZOOMING_OUT)
                time.sleep(zoom_wait)

                # Wait for wide-angle autofocus to settle before resuming scan sweep
                logger.info(f" Waiting {focus_wait:.1f}s for Thermal & Visible Auto-Focus to settle after Zoom Out...")
                self._set_state(MissionState.ZOOMING_OUT)
                start_focus_out_t = time.time()
                while time.time() - start_focus_out_t < focus_wait:
                    if getattr(self, "_abort_cycle", False) or self.state in (MissionState.IDLE, MissionState.PAUSED):
                        return
                    if thermal_cam:
                        sharpness = thermal_cam.compute_sharpness()
                        logger.debug(f"Wide-angle focus sharpness: {sharpness:.1f}")
                    time.sleep(0.4)

                logger.info(" Wide-angle focus settled & stabilized. Resuming search sweep.")
                self.verifier.tracks.clear()
                self.is_ai_paused = False
            else:
                confirmed_tracks = [
                    t for t in self.verifier.tracks
                    if t.state == "CONFIRMED_FIRE" or getattr(t, 'thermal_core_pass', True)
                ]
                if confirmed_tracks:
                    self._set_state(MissionState.ALARM_ACTIVE)
                    self._capture_and_record_incident()
                    time.sleep(3.0)
                else:
                    logger.info("ℹ️ No fire verified. Skipping Incident Record.")

            # Record lock target to prevent re-zooming immediately onto the same angle
            cur_az, cur_alt = self.ptz.get_position()
            self.locked_targets_history.append({"az": cur_az, "alt": cur_alt, "time": time.time()})
            self.verifier.tracks.clear()  # Clear lingering hold tracks completely
            self.current_fire_target = None
        except Exception as e:
            logger.error(f"Error during fire verification cycle: {e}", exc_info=True)
        finally:
            self.is_ai_paused = False
            self.current_fire_target = None
            if not getattr(self, "_abort_cycle", False) and self.state not in (MissionState.IDLE, MissionState.PAUSED):
                self._set_state(MissionState.SEARCH_SWEEP)

    def _find_watchlist_item_to_intercept(
        self,
        cur_az: float,
        cur_alt: float,
        row_alt: float,
        direction: float,
        v_fov: float
    ) -> Optional[dict]:
        """Checks if camera is in intercept path of an active remembered hotspot for this cycle."""
        inc_cfg = self.cfg.get("incident", {})
        if not inc_cfg.get("hotspot_recheck_enabled", self.cfg.get("hotspot_recheck_enabled", True)):
            return None

        now = time.time()
        for inc_id, item in list(self.hotspot_watchlist.items()):
            if item.get("status") != "ACTIVE":
                continue
            # Must not have been checked in this cycle
            if item.get("last_checked_cycle", -1) == self.sweep_cycle_count:
                continue
            # Cooldown: must be at least 60 seconds since last check
            if (now - float(item.get("last_checked_time", 0.0))) < 60.0:
                continue

            target_az = float(item["azimuth"])
            target_alt = float(item["altitude"])

            # Vertical proximity: must be within current layer's vertical FOV
            if abs(row_alt - target_alt) > (v_fov * 0.60):
                continue

            # Angular difference from current azimuth to target azimuth
            diff = shortest_angular_diff(target_az, cur_az)

            # Check if camera is currently passing or about to intercept target
            if direction > 0:
                is_intercept = (-0.4 <= diff <= 1.8)
            else:
                is_intercept = (-1.8 <= diff <= 0.4)

            if is_intercept:
                return item
        return None

    def _find_step_watchlist_item_to_intercept(
        self,
        cur_az: float,
        cur_alt: float,
        h_fov: float,
        v_fov: float
    ) -> Optional[dict]:
        """Checks if step sweep waypoint is in proximity of an active remembered hotspot."""
        inc_cfg = self.cfg.get("incident", {})
        if not inc_cfg.get("hotspot_recheck_enabled", self.cfg.get("hotspot_recheck_enabled", True)):
            return None

        now = time.time()
        for inc_id, item in list(self.hotspot_watchlist.items()):
            if item.get("status") != "ACTIVE":
                continue
            if item.get("last_checked_cycle", -1) == self.sweep_cycle_count:
                continue
            if (now - float(item.get("last_checked_time", 0.0))) < 60.0:
                continue

            target_az = float(item["azimuth"])
            target_alt = float(item["altitude"])

            d_az = abs(shortest_angular_diff(target_az, cur_az))
            d_alt = abs(target_alt - cur_alt)
            dist = math.sqrt(d_az**2 + d_alt**2)

            if dist <= (max(h_fov, v_fov) * 0.65):
                return item
        return None

    def _handle_watchlist_recheck(self, item: dict):
        """Executes deep optical zoom re-inspection on a remembered hotspot location."""
        try:
            if getattr(self, "_abort_cycle", False) or self.state in (MissionState.IDLE, MissionState.PAUSED):
                return

            inc_id = item["incident_id"]
            target_az = float(item["azimuth"])
            target_alt = float(item["altitude"])
            now_t = time.time()
            item["last_checked_cycle"] = self.sweep_cycle_count
            item["last_checked_time"] = now_t
            self._current_watchlist_incident_id = inc_id

            # Also update all neighboring active watchlist items within 2.0 degrees
            for other_id, other_item in self.hotspot_watchlist.items():
                if other_id != inc_id and other_item.get("status") == "ACTIVE":
                    d = math.hypot(
                        shortest_angular_diff(float(other_item.get("azimuth", 0.0)), target_az),
                        float(other_item.get("altitude", 0.0)) - target_alt
                    )
                    if d <= 2.0:
                        other_item["last_checked_cycle"] = self.sweep_cycle_count
                        other_item["last_checked_time"] = now_t

            logger.info(
                f"🔎 [HotspotRecheck] Re-checking remembered hotspot [{inc_id}] at "
                f"Az={target_az:.2f}°, Alt={target_alt:.2f}° (Cycle #{self.sweep_cycle_count + 1})..."
            )

            # Center on target
            self._set_state(MissionState.TARGET_CENTERING)
            self.locked_azimuth = target_az
            self.locked_altitude = target_alt
            goto_speed = max(2.0, float(self.cfg.get("max_goto_speed", 10.0)))
            self.ptz.goto_position(target_az, target_alt, speed=goto_speed, wait=True, tolerance=0.3)
            time.sleep(0.4)

            if getattr(self, "_abort_cycle", False) or self.state in (MissionState.IDLE, MissionState.PAUSED):
                return

            # Proceed to Optical Zoom
            thermal_cam = self.cam_mgr.get_thermal_camera()
            visible_cam = self.cam_mgr.get_visible_camera()
            has_zoom_cam = (thermal_cam and thermal_cam.ptz) or (visible_cam and visible_cam.ptz)

            if has_zoom_cam:
                self.verifier.tracks.clear()
                self.is_ai_paused = True

                cur_th_focal = float(thermal_cam.get_zoom_info().get("focal_mm", self.cfg.get("scan_focal_length_mm", 31.0))) if thermal_cam else 31.0
                max_th_focal = float(getattr(thermal_cam, 'max_focal_mm', 155.0))
                target_th_focal = float(item.get("target_focal_mm", max_th_focal))
                target_th_focal = max(cur_th_focal, min(max_th_focal, target_th_focal))

                logger.info(f"🔭 [HotspotRecheck] Zooming In to {target_th_focal:.1f}mm for verification...")

                if thermal_cam and hasattr(thermal_cam, 'set_focal_length_mm'):
                    thermal_cam.set_focal_length_mm(target_th_focal)
                    if hasattr(thermal_cam, 'trigger_auto_focus'):
                        thermal_cam.trigger_auto_focus()
                elif thermal_cam and thermal_cam.ptz:
                    thermal_cam.zoom_in(speed=0.9, duration_sec=1.5)

                if visible_cam and visible_cam.ptz:
                    zoom_ratio = (target_th_focal - cur_th_focal) / max(1.0, max_th_focal - cur_th_focal)
                    vis_min = float(getattr(visible_cam, 'min_focal_mm', 5.1))
                    vis_max = float(getattr(visible_cam, 'max_focal_mm', 102.0))
                    target_vis_focal = vis_min + zoom_ratio * (vis_max - vis_min) * 0.75
                    if hasattr(visible_cam, 'set_focal_length_mm'):
                        visible_cam.set_focal_length_mm(target_vis_focal)
                    else:
                        visible_cam.zoom_in(speed=0.9, duration_sec=1.5)

                self._set_state(MissionState.ZOOMING_IN)
                zoom_wait = float(self.cfg.get("zoom_settle_wait_sec", 2.0))
                time.sleep(zoom_wait)

                if getattr(self, "_abort_cycle", False) or self.state in (MissionState.IDLE, MissionState.PAUSED):
                    return

                # Wait for autofocus to settle
                focus_wait = float(self.cfg.get("focus_settle_sec", 2.5))
                self._set_state(MissionState.VERIFYING_FOCUS)
                start_focus_t = time.time()
                while time.time() - start_focus_t < focus_wait:
                    if getattr(self, "_abort_cycle", False) or self.state in (MissionState.IDLE, MissionState.PAUSED):
                        return
                    time.sleep(0.3)

                # AI Deep Verification
                self.verifier.tracks.clear()
                self.is_ai_paused = False
                self._set_state(MissionState.DEEP_CONFIRMATION)
                time.sleep(2.0)

                if getattr(self, "_abort_cycle", False) or self.state in (MissionState.IDLE, MissionState.PAUSED):
                    return

                # Strict Deep Zoom Evaluation (Must pass AI Verifier or strict multi-pixel Core Cluster)
                is_fire_confirmed, best_target, bbox = self._evaluate_deep_zoom_hotspot(thermal_cam)

                if is_fire_confirmed:
                    self.current_fire_target = best_target
                    self._target_bbox = bbox
                    item["consecutive_misses"] = 0
                    logger.info(f"🔥 [HotspotRecheck] Fire Threat CONFIRMED STILL ACTIVE in [{inc_id}]! Triggering Alarm & Archiving...")
                    self._set_state(MissionState.ALARM_ACTIVE)
                    self._capture_and_record_incident()
                    alarm_hold = min(5.0, max(2.0, float(self.cfg.get("alarm_cooldown_sec", 4.0))))
                    time.sleep(alarm_hold)
                else:
                    self.current_fire_target = None
                    self._target_bbox = None
                    item["consecutive_misses"] = item.get("consecutive_misses", 0) + 1
                    inc_cfg = self.cfg.get("incident", {})
                    max_misses = int(inc_cfg.get("max_misses_to_extinguish", self.cfg.get("max_misses_to_extinguish", 2)))
                    logger.info(f"ℹ️ [HotspotRecheck] No fire detected at [{inc_id}] (Clean Check #{item['consecutive_misses']}/{max_misses})")

                    if item["consecutive_misses"] >= max_misses:
                        item["status"] = "EXTINGUISHED"
                        ext_rec = self.incident_mgr.mark_incident_extinguished(inc_id)
                        logger.info(f"✅ [HotspotRecheck] Incident [{inc_id}] CONFIRMED EXTINGUISHED! Dispatching Telegram alert.")
                        if hasattr(self, 'notifier') and self.notifier.enabled and ext_rec:
                            th_frame = thermal_cam.latest_bgr if thermal_cam else None
                            vis_frame = visible_cam.latest_bgr if visible_cam else None
                            self.notifier.send_extinguished_alert_async(
                                incident_rec=ext_rec,
                                thermal_frame=th_frame,
                                visible_frame=vis_frame
                            )

                if getattr(self, "_abort_cycle", False) or self.state in (MissionState.IDLE, MissionState.PAUSED):
                    return

                # Return Zoom back to scan focal length
                base_focal = float(self.cfg.get("scan_focal_length_mm", 31.0))
                logger.info(f"🔭 [HotspotRecheck] Returning Thermal Camera zoom back to {base_focal:.1f}mm...")
                self.verifier.tracks.clear()
                self.is_ai_paused = True
                if thermal_cam and hasattr(thermal_cam, 'set_focal_length_mm'):
                    thermal_cam.set_focal_length_mm(base_focal)
                    if hasattr(thermal_cam, 'trigger_auto_focus'):
                        thermal_cam.trigger_auto_focus()
                elif thermal_cam and thermal_cam.ptz:
                    thermal_cam.zoom_out(speed=0.9, duration_sec=1.5)

                if visible_cam and hasattr(visible_cam, 'set_focal_length_mm') and bool(self.cfg.get("visible_sync_scan_zoom", True)):
                    target_vis_focal = self.calculate_synchronized_visible_focal(base_focal)
                    logger.info(f"🔭 [HotspotRecheck] Returning Visible Camera zoom back to synchronized scan focal length {target_vis_focal:.1f}mm...")
                    visible_cam.set_focal_length_mm(target_vis_focal)
                    if hasattr(visible_cam, 'trigger_auto_focus'):
                        visible_cam.trigger_auto_focus()
                elif visible_cam and visible_cam.ptz:
                    visible_cam.zoom_out(speed=0.9, duration_sec=1.5)

                self._set_state(MissionState.ZOOMING_OUT)
                time.sleep(zoom_wait)

                # Wait for wide-angle autofocus
                self._set_state(MissionState.ZOOMING_OUT)
                start_focus_out_t = time.time()
                while time.time() - start_focus_out_t < focus_wait:
                    if getattr(self, "_abort_cycle", False) or self.state in (MissionState.IDLE, MissionState.PAUSED):
                        return
                    time.sleep(0.3)

                logger.info("🔭 [HotspotRecheck] Focus settled. Resuming search sweep.")
                self.verifier.tracks.clear()
                self.is_ai_paused = False

            # Add to locked_targets_history to prevent immediate false triggers
            cur_az, cur_alt = self.ptz.get_position()
            self.locked_targets_history.append({"az": cur_az, "alt": cur_alt, "time": time.time()})
            self.verifier.tracks.clear()
            self.current_fire_target = None
        except Exception as e:
            logger.error(f"Error during watchlist recheck: {e}", exc_info=True)
        finally:
            self._current_watchlist_incident_id = None
            self.is_ai_paused = False
            self.current_fire_target = None
            if not getattr(self, "_abort_cycle", False) and self.state not in (MissionState.IDLE, MissionState.PAUSED):
                self._set_state(MissionState.SEARCH_SWEEP)

    def _capture_and_record_incident(self):
        """Captures dual snapshots and registers/updates fire incident with growth analysis."""
        try:
            th_cam = self.cam_mgr.get_thermal_camera()
            vis_cam = self.cam_mgr.get_visible_camera()

            th_frame = th_cam.latest_bgr if th_cam else None
            vis_frame = vis_cam.latest_bgr if vis_cam else None

            # Fallback to decode jpeg if latest_bgr is not populated
            if th_frame is None and th_cam and th_cam.latest_jpeg:
                th_frame = cv2.imdecode(np.frombuffer(th_cam.latest_jpeg, np.uint8), cv2.IMREAD_COLOR)
            if vis_frame is None and vis_cam and vis_cam.latest_jpeg:
                vis_frame = cv2.imdecode(np.frombuffer(vis_cam.latest_jpeg, np.uint8), cv2.IMREAD_COLOR)

            # Ensure Visible snapshot aspect ratio is always 16:9
            if vis_frame is not None:
                vh, vw = vis_frame.shape[:2]
                if vh > 0 and abs((vw / float(vh)) - (16.0 / 9.0)) > 0.05:
                    target_w = int(round(vh * 16.0 / 9.0))
                    vis_frame = cv2.resize(vis_frame, (target_w, vh), interpolation=cv2.INTER_LANCZOS4)

            target_bbox = getattr(self, '_target_bbox', None)
            target_score = 0.95
            if self.current_fire_target:
                if hasattr(self.current_fire_target, 'bbox'):
                    target_bbox = self.current_fire_target.bbox
                elif hasattr(self.current_fire_target, 'tracker'):
                    target_bbox = self.current_fire_target.tracker.get_state()
                if hasattr(self.current_fire_target, 'score'):
                    target_score = self.current_fire_target.score

            zoom_info = th_cam.get_zoom_info() if th_cam else {}
            if not zoom_info or not zoom_info.get("focal_mm"):
                focal_val = getattr(self, '_last_zoom_focal', None) or float(self.cfg.get("zoom_verify_focal_mm", 155.0))
                zoom_info = {"focal_mm": focal_val, "zoom_x": round(focal_val / 31.0, 1)}

            zoom_info["thermal"] = {
                "focal_mm": zoom_info.get("focal_mm", 155.0),
                "zoom_x": zoom_info.get("zoom_x", 5.0),
                "fov_h": zoom_info.get("fov_h", 2.85),
                "fov_v": zoom_info.get("fov_v", 2.29),
                "fov_d": zoom_info.get("fov_d", 3.67),
                "zoom_pct": zoom_info.get("zoom_pct", 100.0),
                "zoom_ratio": zoom_info.get("zoom_ratio", 1.0)
            }

            if vis_cam:
                zoom_info["visible"] = vis_cam.get_zoom_info()

            target_inc_id = getattr(self, '_current_watchlist_incident_id', None)
            incident_rec = self.incident_mgr.record_fire_event(
                az=self.locked_azimuth,
                alt=self.locked_altitude,
                target_bbox=target_bbox,
                confidence=target_score,
                thermal_frame=th_frame,
                visible_frame=vis_frame,
                zoom_info=zoom_info,
                incident_id=target_inc_id
            )
            self._current_watchlist_incident_id = None
            self.latest_incident = incident_rec
            logger.info(f" Fire Incident Logged: {incident_rec.get('growth_trend_label', 'SAVED')} (ID: {incident_rec.get('id')})")

            # Dispatch real-time Telegram Hotspot alert with dual snapshots (Thermal + Visible)
            # If LLM verification is enabled, run verification first in background thread, then alert with full result!
            if hasattr(self, 'llm_verifier') and self.llm_verifier.enabled:
                def _llm_verify_and_alert():
                    vis_snap = incident_rec.get("latest_visible_snapshot", "")
                    thm_snap = incident_rec.get("latest_thermal_snapshot", "")
                    vis_file = str(self.incident_mgr.snapshots_dir / os.path.basename(vis_snap)) if vis_snap else ""
                    thm_file = str(self.incident_mgr.snapshots_dir / os.path.basename(thm_snap)) if thm_snap else ""

                    try:
                        llm_res = self.llm_verifier.verify_incident(incident_rec, vis_file, thm_file)
                        if llm_res and llm_res.get("status") == "success":
                            self.incident_mgr.update_incident_llm_result(incident_rec.get("id"), llm_res)
                            incident_rec["llm_verification"] = llm_res

                            if llm_res.get("risk_level") == "FALSE_ALARM":
                                inc_id_val = incident_rec.get("id")
                                logger.info(f"🚫 [LLM] False alarm confirmed for Incident {inc_id_val}: {llm_res.get('analysis')}")
                                if inc_id_val and inc_id_val in self.hotspot_watchlist:
                                    self.hotspot_watchlist[inc_id_val]["status"] = "FALSE_ALARM"
                                    logger.info(f"🚫 [Watchlist] Incident {inc_id_val} marked FALSE_ALARM. Excluded from active re-checks.")

                                # Add to false_alarm_exclusions (default 2 hours cooldown)
                                cooldown_hours = float(self.cfg.get("false_alarm_cooldown_hours", 2.0))
                                expires_at = time.time() + (cooldown_hours * 3600.0)
                                self.false_alarm_exclusions.append({
                                    "az": float(incident_rec.get("current_azimuth", self.locked_azimuth)),
                                    "alt": float(incident_rec.get("current_altitude", self.locked_altitude)),
                                    "expires_at": expires_at,
                                    "incident_id": inc_id_val
                                })
                                logger.info(
                                    f"🚫 [Exclusions] Suppressing Az={incident_rec.get('current_azimuth', self.locked_azimuth):.2f}°, "
                                    f"Alt={incident_rec.get('current_altitude', self.locked_altitude):.2f}° for {cooldown_hours:.1f} hours"
                                )
                    except Exception as llm_err:
                        logger.error(f"Error running LLM verification in background: {llm_err}")

                    if hasattr(self, 'notifier') and self.notifier.enabled:
                        self.notifier.send_incident_alert(
                            incident_rec=incident_rec,
                            thermal_frame=th_frame,
                            visible_frame=vis_frame
                        )

                t = threading.Thread(target=_llm_verify_and_alert, daemon=True)
                t.start()
            elif hasattr(self, 'notifier') and self.notifier.enabled:
                self.notifier.send_incident_alert_async(
                    incident_rec=incident_rec,
                    thermal_frame=th_frame,
                    visible_frame=vis_frame
                )

            # Register or update in Hotspot Watchlist for recurring round-by-round re-check
            inc_id = incident_rec.get("id")
            if inc_id:
                focal_mm = float(zoom_info.get("focal_mm", getattr(self, "_last_zoom_focal", 155.0))) if zoom_info else getattr(self, "_last_zoom_focal", 155.0)
                now_t = time.time()
                is_fa = False
                if incident_rec.get("llm_verification", {}).get("risk_level") == "FALSE_ALARM":
                    is_fa = True
                self.hotspot_watchlist[inc_id] = {
                    "incident_id": inc_id,
                    "azimuth": float(incident_rec.get("current_azimuth", self.locked_azimuth)),
                    "altitude": float(incident_rec.get("current_altitude", self.locked_altitude)),
                    "target_focal_mm": focal_mm,
                    "first_detected": incident_rec.get("first_epoch", now_t),
                    "last_checked_time": now_t,
                    "last_checked_cycle": self.sweep_cycle_count,
                    "consecutive_misses": 0,
                    "status": "FALSE_ALARM" if is_fa else "ACTIVE"
                }
                # Also mark any neighboring active checkpoints within 2.0 degrees as checked in this cycle
                for other_id, other_item in self.hotspot_watchlist.items():
                    if other_id != inc_id and other_item.get("status") == "ACTIVE":
                        d = math.hypot(
                            shortest_angular_diff(float(other_item.get("azimuth", 0.0)), self.locked_azimuth),
                            float(other_item.get("altitude", 0.0)) - self.locked_altitude
                        )
                        if d <= 2.0:
                            other_item["last_checked_cycle"] = self.sweep_cycle_count
                            other_item["last_checked_time"] = now_t
                logger.info(f"📍 [HotspotWatchlist] Hotspot [{inc_id}] registered/updated in Watchlist (Cycle #{self.sweep_cycle_count + 1})")
        except Exception as e:
            logger.error(f"Error recording fire incident snapshot: {e}", exc_info=True)
