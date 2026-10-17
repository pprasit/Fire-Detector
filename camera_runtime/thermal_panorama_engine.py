"""
Thermal 360 Panorama Capture & Grid Execution Engine
Manages:
- Optical FOV calculations from thermal focal length
- Overlap & angular step calculations (Snake / Zigzag pattern)
- Hardware constraints enforcement (Azimuth >= 95.0 deg)
- Lens focal length pre-adjustment with stabilization wait
- Dedicated session directory & atomic frame capture
- Automatic positional stitching & progress reporting
"""

import os
import time
import math
import json
import logging
import re
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

import cv2
import numpy as np

from panorama_stitcher import ThermalPanoramaStitcher

logger = logging.getLogger("ThermalPanoramaEngine")


class ThermalPanoramaEngine:
    """Orchestrates automated 360 / wide-angle thermal imaging missions."""

    MIN_HARDWARE_AZIMUTH = -300.0    # PTZ mount physical pan limits
    MAX_HARDWARE_AZIMUTH = 300.0
    WIDE_FOCAL_MM = 31.0             # Thermal camera wide focal length
    MAX_FOCAL_MM = 155.0             # Thermal camera tele focal length
    WIDE_H_FOV_DEG = 14.2            # H-FOV at 31.0mm
    WIDE_V_FOV_DEG = 11.4            # V-FOV at 31.0mm
    FOCUS_TIMEOUT_SEC = 8.0
    FOCUS_SAMPLE_SEC = 0.25
    MIN_FOCUS_SHARPNESS = 40.0
    POSITION_TOLERANCE_DEG = 0.35
    MAX_POSITION_ATTEMPTS = 5

    def __init__(self, camera_mgr, ptz_ctrl, base_dir: Path):
        self.camera_mgr = camera_mgr
        self.ptz_ctrl = ptz_ctrl
        self.base_dir = Path(base_dir)
        self.panoramas_dir = self.base_dir / "panoramas"
        self.panoramas_dir.mkdir(parents=True, exist_ok=True)

        self.stitcher = ThermalPanoramaStitcher()

        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._abort_requested = False
        self._live_preview_lock = threading.Lock()
        self._live_preview_thread: Optional[threading.Thread] = None
        self._live_preview_pending = {}

        self.session_state = {
            "is_running": False,
            "status": "IDLE",
            "session_id": None,
            "session_dir": None,
            "message": "Ready",
            "progress_pct": 0,
            "current_step": 0,
            "total_steps": 0,
            "current_az": 0.0,
            "current_alt": 0.0,
            "target_az": 0.0,
            "target_alt": 0.0,
            "latest_thumbnail": None,
            "latest_thumbnail_step": None,
            "captured_thumbnails": [],
            "latest_thumbnail_visible": None,
            "latest_thumbnail_step_visible": None,
            "captured_thumbnails_visible": [],
            "stitched_image": None,
            "stitched_image_visible": None,
            "live_mosaic": None,
            "live_mosaic_bounds": None,
            "live_mosaic_visible": None,
            "live_mosaic_bounds_visible": None,
            "camera_fov": {},
            "error": None,
            "start_time": None,
            "elapsed_sec": 0,
            "estimated_remaining_sec": 0
        }

    @classmethod
    def calculate_fov(cls, focal_mm: float) -> Tuple[float, float]:
        focal_mm = max(cls.WIDE_FOCAL_MM, min(cls.MAX_FOCAL_MM, float(focal_mm)))
        half_h_rad = math.radians(cls.WIDE_H_FOV_DEG / 2.0)
        half_v_rad = math.radians(cls.WIDE_V_FOV_DEG / 2.0)
        ratio = cls.WIDE_FOCAL_MM / focal_mm
        h_fov = 2.0 * math.degrees(math.atan(ratio * math.tan(half_h_rad)))
        v_fov = 2.0 * math.degrees(math.atan(ratio * math.tan(half_v_rad)))
        return round(h_fov, 2), round(v_fov, 2)

    def calculate_grid_plan(
        self,
        az_min: float,
        az_max: float,
        alt_min: float,
        alt_max: float,
        focal_mm: float,
        overlap_pct: float = 25.0,
        settle_sec: float = 1.0
    ) -> Dict[str, Any]:
        warnings = []
        az_min = float(az_min)
        az_max = float(az_max)
        alt_min = float(alt_min)
        alt_max = float(alt_max)
        overlap_pct = max(5.0, min(80.0, float(overlap_pct)))
        overlap_ratio = overlap_pct / 100.0
        settle_sec = max(0.2, min(5.0, float(settle_sec)))

        # Validate against mount limits
        if az_min < self.MIN_HARDWARE_AZIMUTH:
            warnings.append(
                f"Azimuth Min ({az_min:.1f}°) clamped to mount limit {self.MIN_HARDWARE_AZIMUTH:.1f}°"
            )
            az_min = self.MIN_HARDWARE_AZIMUTH

        if az_max > self.MAX_HARDWARE_AZIMUTH:
            warnings.append(
                f"Azimuth Max ({az_max:.1f}°) clamped to mount limit {self.MAX_HARDWARE_AZIMUTH:.1f}°"
            )
            az_max = self.MAX_HARDWARE_AZIMUTH

        if az_max <= az_min:
            az_max = az_min + 10.0
            warnings.append(f"Azimuth Max adjusted to {az_max:.1f}° to maintain valid span.")

        if alt_max < alt_min:
            alt_min, alt_max = alt_max, alt_min

        h_fov, v_fov = self.calculate_fov(focal_mm)
        step_alt = max(0.5, v_fov * (1.0 - overlap_ratio))

        alt_span = alt_max - alt_min
        if alt_span <= 0.1:
            alt_points = [alt_min]
        else:
            num_alt_steps = max(1, int(math.ceil(alt_span / step_alt)))
            alt_points = [round(alt_min + i * (alt_span / num_alt_steps), 2) for i in range(num_alt_steps + 1)]

        waypoints = []
        total_az_span = az_max - az_min
        # Keep the same azimuth columns on every altitude row. Latitude-based
        # cos() compensation made row column counts differ and visually
        # staggered the capture/mosaic grid.
        step_az = max(0.5, h_fov * (1.0 - overlap_ratio))

        for row_idx, alt in enumerate(alt_points):
            if total_az_span <= 0.1:
                az_row = [az_min]
            else:
                num_az_steps = max(1, int(math.ceil(total_az_span / step_az)))
                az_row = [round(az_min + j * (total_az_span / num_az_steps), 2) for j in range(num_az_steps + 1)]

            # Mission Design displays a full dome as 0..360. Begin at physical
            # AZ 0 instead of the equivalent -180/180 seam.
            if math.isclose(az_min, -180.0) and math.isclose(az_max, 180.0) and len(az_row) > 2:
                full_dome_steps = max(1, int(math.ceil(360.0 / step_az)))
                exact_step = 360.0 / full_dome_steps
                # Choose one continuous 360-degree branch that fits within the
                # configured multi-turn window. With the current -300..+330
                # limits this starts slightly below zero and ends at +330,
                # avoiding a seam reversal or an unreachable +330.6 target.
                branch_start = min(0.0, self.MAX_HARDWARE_AZIMUTH - ((full_dome_steps - 1) * exact_step))
                if branch_start < self.MIN_HARDWARE_AZIMUTH:
                    branch_start = self.MIN_HARDWARE_AZIMUTH
                az_row = [round(branch_start + (step_index * exact_step), 2) for step_index in range(full_dome_steps)]

            if row_idx % 2 == 1:
                az_row = list(reversed(az_row))

            for col_idx, az in enumerate(az_row):
                safe_az = max(self.MIN_HARDWARE_AZIMUTH, min(self.MAX_HARDWARE_AZIMUTH, az))
                waypoints.append({
                    "step_index": len(waypoints),
                    "row": row_idx,
                    "col": col_idx,
                    "az": round(safe_az, 2),
                    "alt": round(alt, 2)
                })

        est_seconds = int(len(waypoints) * (2.2 + settle_sec) + 4.0)

        return {
            "valid": True,
            "warnings": warnings,
            "az_min": az_min,
            "az_max": az_max,
            "alt_min": alt_min,
            "alt_max": alt_max,
            "focal_mm": focal_mm,
            "overlap_pct": overlap_pct,
            "settle_sec": settle_sec,
            "h_fov_deg": h_fov,
            "v_fov_deg": v_fov,
            "step_alt_deg": round(step_alt, 2),
            "rows_count": len(alt_points),
            "total_waypoints": len(waypoints),
            "estimated_duration_sec": est_seconds,
            "waypoints": waypoints
        }

    def start_panorama_mission(
        self,
        az_min: float,
        az_max: float,
        alt_min: float,
        alt_max: float,
        focal_mm: float = 31.0,
        overlap_pct: float = 25.0,
        settle_sec: float = 1.0,
        user_label: str = ""
    ) -> Dict[str, Any]:
        with self._lock:
            if self.session_state["is_running"]:
                return {"success": False, "error": "A panorama capture session is already in progress"}

            plan = self.calculate_grid_plan(
                az_min=az_min,
                az_max=az_max,
                alt_min=alt_min,
                alt_max=alt_max,
                focal_mm=focal_mm,
                overlap_pct=overlap_pct,
                settle_sec=settle_sec
            )

            if len(plan["waypoints"]) == 0:
                return {"success": False, "error": "Calculated zero waypoints with given parameters"}

            timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            session_id = f"session_{timestamp_str}_az{int(plan['az_min'])}_{int(plan['az_max'])}_f{int(focal_mm)}"
            session_dir = self.panoramas_dir / session_id
            raw_frames_dir = session_dir / "raw_frames"
            raw_frames_dir.mkdir(parents=True, exist_ok=True)
            (session_dir / "raw_frames_visible").mkdir(parents=True, exist_ok=True)
            with open(session_dir / "sequence_plan.json", "w", encoding="utf-8") as plan_file:
                json.dump({"plan": plan, "user_label": user_label}, plan_file, indent=2)

            self._abort_requested = False
            self.session_state = {
                "is_running": True,
                "status": "ADJUSTING_LENS",
                "session_id": session_id,
                "session_dir": str(session_dir),
                "message": f"Pre-adjusting Thermal Camera Focal Length to {focal_mm:.1f} mm...",
                "progress_pct": 0,
                "current_step": 0,
                "total_steps": len(plan["waypoints"]),
                "current_az": 0.0,
                "current_alt": 0.0,
                "target_az": plan["waypoints"][0]["az"],
                "target_alt": plan["waypoints"][0]["alt"],
                "latest_thumbnail": None,
                "latest_thumbnail_step": None,
                "captured_thumbnails": [],
                "latest_thumbnail_visible": None,
                "latest_thumbnail_step_visible": None,
                "captured_thumbnails_visible": [],
                "stitched_image": None,
                "stitched_image_visible": None,
                "live_mosaic": None,
                "live_mosaic_bounds": None,
                "live_mosaic_visible": None,
                "live_mosaic_bounds_visible": None,
                "camera_fov": {},
                "error": None,
                "start_time": time.time(),
                "elapsed_sec": 0,
                "estimated_remaining_sec": plan["estimated_duration_sec"],
                "plan": plan
            }

            self._thread = threading.Thread(
                target=self._worker_capture,
                args=(session_dir, plan, focal_mm, settle_sec, user_label, False),
                daemon=True
            )
            self._thread.start()

            return {
                "success": True,
                "session_id": session_id,
                "total_waypoints": len(plan["waypoints"]),
                "estimated_duration_sec": plan["estimated_duration_sec"],
                "warnings": plan["warnings"]
            }

    def resume_panorama_mission(self) -> Dict[str, Any]:
        """Resume the latest interrupted session, preserving completed frames."""
        with self._lock:
            if self.session_state["is_running"]:
                return {"success": False, "error": "A panorama capture session is already in progress"}
            if self.session_state.get("status") not in {"ABORTED", "ERROR", "MOTION_ERROR", "IDLE"}:
                return {"success": False, "error": "There is no interrupted Panorama sequence to resume"}
            plan = self.session_state.get("plan")
            session_dir_value = self.session_state.get("session_dir")
            if not isinstance(plan, dict) or not session_dir_value:
                candidates = sorted(self.panoramas_dir.glob("session_*/sequence_plan.json"), reverse=True)
                for candidate in candidates:
                    if (candidate.parent / "metadata.json").exists():
                        continue
                    try:
                        checkpoint = json.loads(candidate.read_text(encoding="utf-8"))
                    except (OSError, ValueError):
                        continue
                    if isinstance(checkpoint.get("plan"), dict):
                        plan = checkpoint["plan"]
                        session_dir_value = str(candidate.parent)
                        self.session_state["plan"] = plan
                        self.session_state["session_dir"] = session_dir_value
                        self.session_state["session_id"] = candidate.parent.name
                        break
            if not isinstance(plan, dict) or not session_dir_value:
                return {"success": False, "error": "The interrupted sequence plan is unavailable"}
            session_dir = Path(session_dir_value)
            if not session_dir.is_dir():
                return {"success": False, "error": "The interrupted sequence folder is unavailable"}

            captured = len(list((session_dir / "raw_frames").glob("frame_r*_c*_*.jpg")))
            self._abort_requested = False
            self.session_state.update({
                "is_running": True,
                "status": "RESUMING",
                "message": f"Resuming after {captured} captured frames...",
                "error": None,
                "start_time": time.time(),
                "current_step": captured,
                "progress_pct": int((captured / max(1, len(plan["waypoints"]))) * 85),
            })
            self._thread = threading.Thread(
                target=self._worker_capture,
                args=(
                    session_dir,
                    plan,
                    float(plan["focal_mm"]),
                    float(plan["settle_sec"]),
                    "Resumed Mission Design thermal panorama",
                    True,
                ),
                daemon=True,
            )
            self._thread.start()
            return {
                "success": True,
                "resumed": True,
                "session_id": session_dir.name,
                "captured_frames": captured,
                "total_waypoints": len(plan["waypoints"]),
            }

    def _wait_for_thermal_focus(self, thermal_cam, step: int, total_steps: int) -> Dict[str, Any]:
        """Wait until autofocus reports idle and consecutive frames are sharp/stable."""
        if thermal_cam is None:
            return {"reason": "camera-unavailable", "sharpness": 0.0, "elapsed_sec": 0.0}

        if hasattr(thermal_cam, "trigger_auto_focus"):
            thermal_cam.trigger_auto_focus()

        started = time.monotonic()
        samples: List[float] = []
        telemetry_supported = False
        move_status = "UNKNOWN"
        while not self._abort_requested:
            elapsed = time.monotonic() - started
            if elapsed >= self.FOCUS_TIMEOUT_SEC:
                sharpness = samples[-1] if samples else 0.0
                return {
                    "reason": "bounded-timeout-fallback",
                    "sharpness": round(sharpness, 2),
                    "elapsed_sec": round(elapsed, 2),
                    "onvif_status": move_status,
                }

            if hasattr(thermal_cam, "get_focus_status"):
                focus_status = thermal_cam.get_focus_status()
                telemetry_supported = bool(focus_status.get("supported"))
                move_status = str(focus_status.get("move_status", "UNKNOWN")).upper()

            sharpness = float(thermal_cam.compute_sharpness()) if hasattr(thermal_cam, "compute_sharpness") else 0.0
            samples.append(sharpness)
            samples = samples[-3:]
            mean = sum(samples) / len(samples)
            spread = (max(samples) - min(samples)) / max(mean, 1.0) if len(samples) >= 3 else float("inf")
            stable_image = len(samples) >= 3 and spread <= 0.12
            stable_sharp = stable_image and mean >= self.MIN_FOCUS_SHARPNESS
            focus_idle = not telemetry_supported or move_status in {"IDLE", "STOPPED"}

            with self._lock:
                self.session_state["status"] = "FOCUSING"
                self.session_state["message"] = (
                    f"Cell {step}/{total_steps}: autofocus {move_status.lower()}, "
                    f"sharpness {sharpness:.1f}"
                )

            if elapsed >= 0.75 and focus_idle and stable_sharp:
                return {
                    "reason": "onvif-idle-and-sharp" if telemetry_supported else "sharpness-stable",
                    "sharpness": round(sharpness, 2),
                    "elapsed_sec": round(elapsed, 2),
                    "onvif_status": move_status,
                }
            # A low-texture thermal view can be correctly focused while its
            # absolute Laplacian score remains low. Once autofocus is idle (or
            # unavailable) and three consecutive frames are stable, accept the
            # frame after a slightly longer guard period instead of waiting the
            # full timeout at every panorama cell.
            if elapsed >= 1.25 and focus_idle and stable_image:
                return {
                    "reason": "stable-low-texture",
                    "sharpness": round(sharpness, 2),
                    "elapsed_sec": round(elapsed, 2),
                    "onvif_status": move_status,
                }
            time.sleep(self.FOCUS_SAMPLE_SEC)

        return {
            "reason": "aborted",
            "sharpness": round(samples[-1] if samples else 0.0, 2),
            "elapsed_sec": round(time.monotonic() - started, 2),
            "onvif_status": move_status,
        }

    def _worker_capture(
        self,
        session_dir: Path,
        plan: Dict[str, Any],
        target_focal_mm: float,
        settle_sec: float,
        user_label: str,
        resume_existing: bool = False,
    ):
        raw_frames_dir = session_dir / "raw_frames"
        visible_frames_dir = session_dir / "raw_frames_visible"
        visible_frames_dir.mkdir(parents=True, exist_ok=True)
        waypoints = plan["waypoints"]
        total_steps = len(waypoints)
        frames_meta = []
        visible_frames_meta = []
        thermal_cam = getattr(self.camera_mgr, "get_thermal_camera", lambda: None)()
        visible_cam = getattr(self.camera_mgr, "get_visible_camera", lambda: None)()

        if resume_existing:
            for wp in waypoints:
                matches = sorted(raw_frames_dir.glob(f"frame_r{wp['row']:02d}_c{wp['col']:02d}_*.jpg"))
                if not matches:
                    continue
                frame_path = matches[-1]
                match = re.search(r"_az([+-]\d+(?:\.\d+)?)_alt([+-]\d+(?:\.\d+)?)\.jpg$", frame_path.name)
                actual_az = float(match.group(1)) if match else float(wp["az"])
                actual_alt = float(match.group(2)) if match else float(wp["alt"])
                frames_meta.append({
                    "step_index": wp["step_index"],
                    "row": wp["row"],
                    "col": wp["col"],
                    "target_az": wp["az"],
                    "target_alt": wp["alt"],
                    "az": actual_az,
                    "alt": actual_alt,
                    "filename": frame_path.name,
                    "focus": {"reason": "preserved-from-interrupted-sequence"},
                    "filepath": str(frame_path),
                    "captured_at": datetime.fromtimestamp(frame_path.stat().st_mtime, timezone.utc).isoformat(),
                })
        completed_steps = {int(frame["step_index"]) for frame in frames_meta}
        if frames_meta:
            restored_thumbnails = []
            for frame in frames_meta:
                thumb_name = f"thumb_{frame['filename']}"
                if (raw_frames_dir / thumb_name).exists():
                    restored_thumbnails.append({
                        "step_index": int(frame["step_index"]),
                        "url": f"/api/panorama/image/{session_dir.name}/raw_frames/{thumb_name}",
                    })
            with self._lock:
                self.session_state["captured_thumbnails"] = restored_thumbnails
                if restored_thumbnails:
                    self.session_state["latest_thumbnail_step"] = restored_thumbnails[-1]["step_index"]
                    self.session_state["latest_thumbnail"] = restored_thumbnails[-1]["url"]

        try:
            logger.info(f"📸 Step A: Adjusting Thermal Lens to {target_focal_mm:.1f} mm...")
            if thermal_cam:
                thermal_cam.set_focal_length_mm(target_focal_mm)
            # Keep both sensors at the same optical zoom percentage. Their
            # native FOVs remain different and are reported separately so the
            # UI can draw each grid with the correct footprint/aspect ratio.
            zoom_pct = max(0.0, min(100.0, (float(target_focal_mm) - 31.0) / (155.0 - 31.0) * 100.0))
            if visible_cam and hasattr(visible_cam, "set_zoom_pct"):
                visible_cam.set_zoom_pct(zoom_pct)

            time.sleep(3.0)

            thermal_zoom = thermal_cam.get_zoom_info() if thermal_cam and hasattr(thermal_cam, "get_zoom_info") else {}
            visible_zoom = visible_cam.get_zoom_info() if visible_cam and hasattr(visible_cam, "get_zoom_info") else {}
            camera_fov = {
                "thermal": {
                    "horizontal_deg": float(thermal_zoom.get("fov_h", plan["h_fov_deg"])),
                    "vertical_deg": float(thermal_zoom.get("fov_v", plan["v_fov_deg"])),
                    "zoom_pct": zoom_pct,
                },
                "visible": {
                    "horizontal_deg": float(visible_zoom.get("fov_h", plan["h_fov_deg"])),
                    "vertical_deg": float(visible_zoom.get("fov_v", plan["v_fov_deg"])),
                    "zoom_pct": zoom_pct,
                },
            }
            with self._lock:
                self.session_state["camera_fov"] = camera_fov

            if self._abort_requested:
                self._handle_abort(session_dir)
                return

            with self._lock:
                self.session_state["status"] = "CAPTURING"
                self.session_state["message"] = "Capturing panorama frames..."

            for idx, wp in enumerate(waypoints):
                if idx in completed_steps:
                    continue
                if self._abort_requested:
                    self._handle_abort(session_dir)
                    return

                target_az = wp["az"]
                target_alt = wp["alt"]

                with self._lock:
                    self.session_state["current_step"] = idx + 1
                    self.session_state["target_az"] = target_az
                    self.session_state["target_alt"] = target_alt
                    self.session_state["progress_pct"] = int((idx / total_steps) * 85)
                    self.session_state["elapsed_sec"] = int(time.time() - self.session_state["start_time"])
                    remaining_steps = total_steps - idx
                    self.session_state["estimated_remaining_sec"] = int(remaining_steps * (2.2 + settle_sec) + 4.0)

                logger.info(f"[{idx+1}/{total_steps}] PTZ GOTO -> Az={target_az:.2f}°, Alt={target_alt:.2f}°")
                before_az, before_alt = self.ptz_ctrl.get_position()
                # Targets are unwrapped physical coordinates. Use the actual
                # travel distance so an older checkpoint crossing +323 to -29
                # receives enough time to safely traverse the long way around.
                az_distance = abs(float(target_az) - float(before_az))
                alt_distance = abs(float(target_alt) - float(before_alt))
                motion_timeout = min(45.0, max(15.0, max(az_distance, alt_distance) / 10.0 + 6.0))
                reached = False
                final_az, final_alt = before_az, before_alt
                for attempt in range(1, self.MAX_POSITION_ATTEMPTS + 1):
                    if self._abort_requested:
                        self._handle_abort(session_dir)
                        return
                    attempt_timeout = motion_timeout if attempt == 1 else min(12.0, max(5.0, az_distance / 10.0 + 3.0))
                    command_ok = self.ptz_ctrl.goto_position(
                        az=target_az,
                        alt=target_alt,
                        speed=10.0,
                        wait=True,
                        tolerance=self.POSITION_TOLERANCE_DEG,
                        timeout=attempt_timeout
                    )
                    final_az, final_alt = self.ptz_ctrl.get_position()
                    final_az_error = abs((float(target_az) - float(final_az) + 180.0) % 360.0 - 180.0)
                    final_alt_error = abs(float(target_alt) - float(final_alt))
                    reached = (
                        command_ok
                        and final_az_error <= self.POSITION_TOLERANCE_DEG
                        and final_alt_error <= self.POSITION_TOLERANCE_DEG
                    )
                    if reached:
                        logger.info(
                            "[%d/%d] Set point verified on attempt %d/%d (Az err %.3f°, Alt err %.3f°)",
                            idx + 1, total_steps, attempt, self.MAX_POSITION_ATTEMPTS,
                            final_az_error, final_alt_error,
                        )
                        break
                    if attempt < self.MAX_POSITION_ATTEMPTS:
                        with self._lock:
                            self.session_state["status"] = "RETRYING_MOTION"
                            self.session_state["message"] = (
                                f"Cell {idx + 1}/{total_steps}: set point missed "
                                f"(AZ error {final_az_error:.2f}°, ALT error {final_alt_error:.2f}°); "
                                f"retrying {attempt + 1}/{self.MAX_POSITION_ATTEMPTS}..."
                            )
                        logger.warning(
                            "[%d/%d] Set point missed on attempt %d/%d; retrying (Az err %.3f°, Alt err %.3f°)",
                            idx + 1, total_steps, attempt, self.MAX_POSITION_ATTEMPTS,
                            final_az_error, final_alt_error,
                        )
                        time.sleep(0.25)

                if not reached:
                    self.ptz_ctrl.stop()
                    with self._lock:
                        self.session_state["status"] = "MOTION_ERROR"
                        self.session_state["is_running"] = False
                        self.session_state["error"] = "Mount did not reach the requested panorama cell."
                        self.session_state["message"] = (
                            f"Cell {idx + 1}/{total_steps}: mount did not reach "
                            f"AZ {target_az:.2f}°, ALT {target_alt:.2f}° after "
                            f"{self.MAX_POSITION_ATTEMPTS} attempts. No frame was captured."
                        )
                    logger.error("[%d/%d] Mount failed to reach target; capture blocked.", idx + 1, total_steps)
                    return

                # Step B-1: Settling delay to eliminate mount vibration & inertia
                time.sleep(settle_sec)

                # Step B-2: Telemetry stationary verification (ensure PTZ is completely still)
                p1_az, p1_alt = self.ptz_ctrl.get_position()
                time.sleep(0.08)
                p2_az, p2_alt = self.ptz_ctrl.get_position()
                if abs(p2_az - p1_az) > 0.05 or abs(p2_alt - p1_alt) > 0.05:
                    time.sleep(0.3)
                    p2_az, p2_alt = self.ptz_ctrl.get_position()

                cur_az, cur_alt = p2_az, p2_alt
                with self._lock:
                    self.session_state["current_az"] = cur_az
                    self.session_state["current_alt"] = cur_alt

                # Step B-3: ask the lens to autofocus, then gate capture on
                # ONVIF focus-idle plus stable image sharpness. A bounded timeout
                # is only the final fallback for cameras without focus telemetry.
                focus_result = self._wait_for_thermal_focus(thermal_cam, idx + 1, total_steps)
                visible_focus_result = self._wait_for_thermal_focus(visible_cam, idx + 1, total_steps)
                if self._abort_requested:
                    self._handle_abort(session_dir)
                    return
                logger.info(
                    "[%d/%d] Thermal focus ready: %s (sharpness=%.1f, %.2fs)",
                    idx + 1,
                    total_steps,
                    focus_result["reason"],
                    focus_result["sharpness"],
                    focus_result["elapsed_sec"],
                )
                with self._lock:
                    self.session_state["status"] = "CAPTURING"
                    self.session_state["message"] = f"Cell {idx + 1}/{total_steps}: focus verified, capturing frame..."

                frame_bgr = None
                if thermal_cam:
                    frame_bgr, _ = thermal_cam.get_latest_frame()
                visible_bgr = None
                if visible_cam:
                    visible_bgr, _ = visible_cam.get_latest_frame()

                if frame_bgr is None:
                    frame_bgr = np.zeros((480, 640, 3), dtype=np.uint8)
                    cv2.putText(
                        frame_bgr,
                        f"Thermal Cam (Az:{cur_az:.1f}, Alt:{cur_alt:.1f})",
                        (30, 240),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.7,
                        (0, 165, 255),
                        2
                    )

                # One canonical file per grid cell. A later recapture replaces
                # this file atomically instead of leaving multiple ambiguous
                # angle-suffixed images for the same cell on disk.
                frame_filename = f"frame_r{wp['row']:02d}_c{wp['col']:02d}_latest.jpg"
                frame_path = raw_frames_dir / frame_filename
                self._atomic_write_image(frame_path, frame_bgr, 90)

                thumb_filename = f"thumb_{frame_filename}"
                thumb_path = raw_frames_dir / thumb_filename
                thumb_img = cv2.resize(frame_bgr, (240, 180))
                self._atomic_write_image(thumb_path, thumb_img, 88)

                if visible_bgr is None:
                    visible_bgr = np.zeros((1080, 1920, 3), dtype=np.uint8)
                    cv2.putText(visible_bgr, f"Visible Cam (Az:{cur_az:.1f}, Alt:{cur_alt:.1f})",
                                (60, 540), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 165, 255), 3)
                visible_path = visible_frames_dir / frame_filename
                self._atomic_write_image(visible_path, visible_bgr, 92)
                visible_thumb_filename = f"thumb_{frame_filename}"
                visible_thumb_path = visible_frames_dir / visible_thumb_filename
                # Keep preview dimensions identical across sensors. The UI
                # derives the physical cell aspect from each camera's FOV,
                # while full-resolution Visible frames remain 16:9 on disk.
                visible_thumb = cv2.resize(visible_bgr, (240, 180))
                self._atomic_write_image(visible_thumb_path, visible_thumb, 88)

                with self._lock:
                    thumbnail_url = f"/api/panorama/image/{session_dir.name}/raw_frames/{thumb_filename}"
                    self.session_state["latest_thumbnail"] = thumbnail_url
                    self.session_state["latest_thumbnail_step"] = idx
                    thumbnails = self.session_state.setdefault("captured_thumbnails", [])
                    thumbnails[:] = [item for item in thumbnails if int(item.get("step_index", -1)) != idx]
                    thumbnails.append({
                        "step_index": idx,
                        "url": thumbnail_url,
                    })
                    visible_thumbnail_url = f"/api/panorama/image/{session_dir.name}/raw_frames_visible/{visible_thumb_filename}"
                    self.session_state["latest_thumbnail_visible"] = visible_thumbnail_url
                    self.session_state["latest_thumbnail_step_visible"] = idx
                    visible_thumbnails = self.session_state.setdefault("captured_thumbnails_visible", [])
                    visible_thumbnails[:] = [item for item in visible_thumbnails if int(item.get("step_index", -1)) != idx]
                    visible_thumbnails.append({"step_index": idx, "url": visible_thumbnail_url})

                frames_meta.append({
                    "step_index": idx,
                    "row": wp["row"],
                    "col": wp["col"],
                    "target_az": target_az,
                    "target_alt": target_alt,
                    "az": cur_az,
                    "alt": cur_alt,
                    "filename": frame_filename,
                    "focus": focus_result,
                    "filepath": str(frame_path),
                    "captured_at": datetime.now(timezone.utc).isoformat()
                })
                visible_frames_meta.append({
                    "step_index": idx,
                    "row": wp["row"],
                    "col": wp["col"],
                    "target_az": target_az,
                    "target_alt": target_alt,
                    "az": cur_az,
                    "alt": cur_alt,
                    "filename": frame_filename,
                    "focus": visible_focus_result,
                    "filepath": str(visible_path),
                    "captured_at": datetime.now(timezone.utc).isoformat(),
                })
                partial_path = session_dir / "partial_metadata.json"
                partial_tmp = session_dir / "partial_metadata.json.tmp"
                with open(partial_tmp, "w", encoding="utf-8") as partial_file:
                    json.dump({
                        "session_id": session_dir.name,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                        "total_frames": len(frames_meta),
                        "frames": frames_meta,
                        "visible_frames": visible_frames_meta,
                        "camera_fov": camera_fov,
                    }, partial_file, indent=2, ensure_ascii=False)
                partial_tmp.replace(partial_path)
                self._schedule_live_mosaic(session_dir, frames_meta, plan, "thermal", camera_fov["thermal"])
                self._schedule_live_mosaic(session_dir, visible_frames_meta, plan, "visible", camera_fov["visible"])

            if self._abort_requested:
                self._handle_abort(session_dir)
                return

            with self._lock:
                self.session_state["status"] = "STITCHING"
                self.session_state["message"] = "Stitching frames into high-resolution panorama..."
                self.session_state["progress_pct"] = 90

            logger.info("🧵 Stitching panorama via Spherical 3D Ray Warper...")
            h_fov, v_fov = plan["h_fov_deg"], plan["v_fov_deg"]
            stitched_img, stitch_stats = self.stitcher.stitch_positional(
                frames_metadata=frames_meta,
                h_fov_deg=h_fov,
                v_fov_deg=v_fov,
                enable_alignment_refinement=True
            )
            stitched_visible, visible_stitch_stats = self.stitcher.stitch_positional(
                frames_metadata=visible_frames_meta,
                h_fov_deg=camera_fov["visible"]["horizontal_deg"],
                v_fov_deg=camera_fov["visible"]["vertical_deg"],
                enable_alignment_refinement=True,
            )

            stitched_path = session_dir / "stitched_panorama.jpg"
            thumb_stitched_path = session_dir / "thumbnail.jpg"
            visible_stitched_path = session_dir / "stitched_panorama_visible.jpg"
            visible_thumb_stitched_path = session_dir / "thumbnail_visible.jpg"

            if stitched_img is not None:
                cv2.imwrite(str(stitched_path), stitched_img, [cv2.IMWRITE_JPEG_QUALITY, 92])

                preview_w = min(1200, stitched_img.shape[1])
                preview_h = int(stitched_img.shape[0] * (preview_w / stitched_img.shape[1]))
                preview_img = cv2.resize(stitched_img, (preview_w, preview_h))
                cv2.imwrite(str(thumb_stitched_path), preview_img)

                logger.info(f"✅ Stitched panorama saved: {stitched_path}")
            if stitched_visible is not None:
                cv2.imwrite(str(visible_stitched_path), stitched_visible, [cv2.IMWRITE_JPEG_QUALITY, 92])
                preview_w = min(1600, stitched_visible.shape[1])
                preview_h = int(stitched_visible.shape[0] * (preview_w / stitched_visible.shape[1]))
                cv2.imwrite(str(visible_thumb_stitched_path), cv2.resize(stitched_visible, (preview_w, preview_h)))

            metadata_record = {
                "session_id": session_dir.name,
                "user_label": user_label,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "focal_mm": target_focal_mm,
                "overlap_pct": plan["overlap_pct"],
                "h_fov_deg": h_fov,
                "v_fov_deg": v_fov,
                "az_range": [plan["az_min"], plan["az_max"]],
                "alt_range": [plan["alt_min"], plan["alt_max"]],
                "total_frames": len(frames_meta),
                "stitch_stats": stitch_stats,
                "stitched_image": "stitched_panorama.jpg" if stitched_img is not None else None,
                "frames": frames_meta
                ,"visible_frames": visible_frames_meta
                ,"camera_fov": camera_fov
                ,"visible_stitch_stats": visible_stitch_stats
                ,"stitched_image_visible": "stitched_panorama_visible.jpg" if stitched_visible is not None else None
            }

            with open(session_dir / "metadata.json", "w", encoding="utf-8") as f:
                json.dump(metadata_record, f, indent=2, ensure_ascii=False)

            with self._lock:
                self.session_state["status"] = "COMPLETED"
                self.session_state["message"] = f"Panorama completed successfully ({len(frames_meta)} frames)!"
                self.session_state["progress_pct"] = 100
                self.session_state["is_running"] = False
                self.session_state["stitched_image"] = f"/api/panorama/image/{session_dir.name}/stitched_panorama.jpg"
                self.session_state["latest_thumbnail"] = f"/api/panorama/image/{session_dir.name}/thumbnail.jpg"
                if stitched_visible is not None:
                    self.session_state["stitched_image_visible"] = f"/api/panorama/image/{session_dir.name}/stitched_panorama_visible.jpg"
                    self.session_state["latest_thumbnail_visible"] = f"/api/panorama/image/{session_dir.name}/thumbnail_visible.jpg"

        except Exception as e:
            logger.error(f"Error in panorama worker: {e}", exc_info=True)
            with self._lock:
                self.session_state["status"] = "ERROR"
                self.session_state["is_running"] = False
                self.session_state["error"] = str(e)
                self.session_state["message"] = f"Capture failed: {e}"

    def _handle_abort(self, session_dir: Path):
        logger.warning("⚠️ Panorama mission aborted by user.")
        self.ptz_ctrl.stop()
        with self._lock:
            self.session_state["status"] = "ABORTED"
            self.session_state["message"] = "Mission aborted by operator."
            self.session_state["is_running"] = False

    @staticmethod
    def _atomic_write_image(path: Path, image: np.ndarray, quality: int) -> None:
        """Encode beside the destination and atomically replace one grid image."""
        temporary = path.with_name(f".{path.stem}.tmp{path.suffix}")
        if not cv2.imwrite(str(temporary), image, [cv2.IMWRITE_JPEG_QUALITY, int(quality)]):
            raise RuntimeError(f"Could not encode panorama image {path.name}")
        temporary.replace(path)

    def save_current_session(self) -> Dict[str, Any]:
        """Persist a durable snapshot of the current grid and queue a fresh mosaic."""
        with self._lock:
            session_dir_value = self.session_state.get("session_dir")
            session_id = self.session_state.get("session_id")
            plan = self.session_state.get("plan")

        # A service restart clears the in-memory session state, but it must not
        # make already captured survey cells unsaveable. Recover the newest
        # on-disk session and its plan when necessary.
        if not session_dir_value or not session_id or not isinstance(plan, dict):
            candidates = [path for path in self.panoramas_dir.glob("session_*") if path.is_dir()]
            if not candidates:
                return {"success": False, "error": "No Panorama session is available to save"}
            session_dir = max(candidates, key=lambda path: path.stat().st_mtime)
            session_id = session_dir.name
            recovered = None
            for candidate_name in ("partial_metadata.json", "metadata.json", "sequence_plan.json"):
                candidate_path = session_dir / candidate_name
                if not candidate_path.exists():
                    continue
                try:
                    candidate_data = json.loads(candidate_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                possible_plan = candidate_data.get("plan", candidate_data)
                if isinstance(possible_plan, dict) and isinstance(possible_plan.get("waypoints"), list):
                    recovered = possible_plan
                    break
            if recovered is None:
                return {"success": False, "error": "The latest Panorama session has no recoverable plan"}
            plan = recovered
            session_dir_value = str(session_dir)
            with self._lock:
                self.session_state["session_id"] = session_id
                self.session_state["session_dir"] = session_dir_value
                self.session_state["plan"] = plan

        session_dir = Path(str(session_dir_value))
        metadata_path = session_dir / "partial_metadata.json"
        if not metadata_path.exists():
            metadata_path = session_dir / "metadata.json"
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return {"success": False, "error": f"Could not read captured grid metadata: {exc}"}
        frames = metadata.get("frames")
        visible_frames = metadata.get("visible_frames", [])
        if not isinstance(frames, list) or not frames:
            return {"success": False, "error": "No captured grid images are available to save"}

        saved_at = datetime.now(timezone.utc).isoformat()
        saved_grid_dir = session_dir / "saved_grid"
        saved_grid_dir.mkdir(exist_ok=True)
        saved_frames = []
        for frame in frames:
            if not isinstance(frame, dict):
                continue
            source = Path(str(frame.get("filepath", "")))
            if not source.is_file():
                continue
            row = int(frame.get("row", 0))
            col = int(frame.get("col", 0))
            destination = saved_grid_dir / f"cell_r{row:02d}_c{col:02d}.jpg"
            temporary = destination.with_name(f".{destination.stem}.tmp{destination.suffix}")
            shutil.copyfile(source, temporary)
            temporary.replace(destination)
            saved_frame = dict(frame)
            saved_frame["saved_filepath"] = str(destination)
            saved_frames.append(saved_frame)

        if not saved_frames:
            return {"success": False, "error": "Captured grid image files could not be read"}
        saved_visible_frames = []
        saved_visible_dir = session_dir / "saved_grid_visible"
        saved_visible_dir.mkdir(exist_ok=True)
        for frame in visible_frames if isinstance(visible_frames, list) else []:
            if not isinstance(frame, dict):
                continue
            source = Path(str(frame.get("filepath", "")))
            if not source.is_file():
                continue
            destination = saved_visible_dir / f"cell_r{int(frame.get('row', 0)):02d}_c{int(frame.get('col', 0)):02d}.jpg"
            temporary = destination.with_name(f".{destination.stem}.tmp{destination.suffix}")
            shutil.copyfile(source, temporary)
            temporary.replace(destination)
            saved_frame = dict(frame)
            saved_frame["saved_filepath"] = str(destination)
            saved_visible_frames.append(saved_frame)
        manifest = {
            "session_id": str(session_id),
            "saved_at": saved_at,
            "total_frames": len(saved_frames),
            "plan": plan,
            "frames": saved_frames,
            "visible_frames": saved_visible_frames,
            "camera_fov": metadata.get("camera_fov", {}),
        }
        manifest_path = session_dir / "saved_manifest.json"
        manifest_tmp = session_dir / ".saved_manifest.json.tmp"
        manifest_tmp.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        manifest_tmp.replace(manifest_path)
        with self._lock:
            if self.session_state.get("session_id") == session_id:
                self.session_state["saved_at"] = saved_at
                self.session_state["saved_frames"] = len(saved_frames)
                self.session_state["save_mosaic_pending"] = True
                self.session_state["save_mosaic_pending_visible"] = bool(saved_visible_frames)
        self._schedule_live_mosaic(session_dir, saved_frames, plan)
        if saved_visible_frames:
            visible_fov = (metadata.get("camera_fov") or {}).get("visible", {})
            self._schedule_live_mosaic(session_dir, saved_visible_frames, plan, "visible", visible_fov)
        usage = shutil.disk_usage(self.panoramas_dir)
        return {
            "success": True,
            "session_id": str(session_id),
            "saved_frames": len(saved_frames),
            "saved_visible_frames": len(saved_visible_frames),
            "manifest": "saved_manifest.json",
            "grid_directory": "saved_grid",
            "mosaic_pending": True,
            "free_bytes": usage.free,
        }

    def _schedule_live_mosaic(self, session_dir: Path, frames_meta: List[Dict[str, Any]], plan: Dict[str, Any], camera: str = "thermal", fov: Optional[Dict[str, Any]] = None):
        """Coalesce low-resolution preview stitches without blocking capture motion."""
        snapshot = (session_dir, [dict(frame) for frame in frames_meta], dict(plan), camera, dict(fov or {}))
        with self._live_preview_lock:
            self._live_preview_pending[camera] = snapshot
            if self._live_preview_thread and self._live_preview_thread.is_alive():
                return
            self._live_preview_thread = threading.Thread(target=self._live_mosaic_worker, daemon=True)
            self._live_preview_thread.start()

    def _live_mosaic_worker(self):
        while True:
            with self._live_preview_lock:
                pending = next(iter(self._live_preview_pending.values()), None)
                if pending is not None:
                    self._live_preview_pending.pop(pending[3], None)
            if pending is None:
                return
            session_dir, frames_meta, plan, camera, fov = pending
            try:
                h_fov = float(fov.get("horizontal_deg", plan["h_fov_deg"]))
                v_fov = float(fov.get("vertical_deg", plan["v_fov_deg"]))
                mosaic, stats = self.stitcher.stitch_positional(
                    frames_metadata=frames_meta,
                    h_fov_deg=h_fov,
                    v_fov_deg=v_fov,
                    pixels_per_deg=8.0,
                    enable_alignment_refinement=True,
                )
                if mosaic is None:
                    continue
                suffix = "" if camera == "thermal" else "_visible"
                preview_path = session_dir / f"live_mosaic{suffix}.jpg"
                preview_tmp = session_dir / f"live_mosaic{suffix}.tmp.jpg"
                cv2.imwrite(str(preview_tmp), mosaic, [cv2.IMWRITE_JPEG_QUALITY, 88])
                preview_tmp.replace(preview_path)
                frames_folder = "raw_frames" if camera == "thermal" else "raw_frames_visible"
                aligned_dir = session_dir / frames_folder / "aligned_preview"
                aligned_dir.mkdir(exist_ok=True)
                az_bounds = stats.get("az_range") or [0.0, 0.0]
                alt_bounds = stats.get("alt_range") or [0.0, 0.0]
                ppd = float(stats.get("pixels_per_deg") or 8.0)
                cell_az = max(0.5, h_fov * (1.0 - float(plan["overlap_pct"]) / 100.0))
                cell_alt = max(0.5, v_fov * (1.0 - float(plan["overlap_pct"]) / 100.0))
                aligned_thumbnails = []
                for frame in frames_meta:
                    cx = int(round((float(frame["az"]) - float(az_bounds[0])) * ppd))
                    cy = int(round((float(alt_bounds[1]) - float(frame["alt"])) * ppd))
                    half_w = max(2, int(round(cell_az * ppd / 2.0)))
                    half_h = max(2, int(round(cell_alt * ppd / 2.0)))
                    x0, x1 = max(0, cx - half_w), min(mosaic.shape[1], cx + half_w)
                    y0, y1 = max(0, cy - half_h), min(mosaic.shape[0], cy + half_h)
                    if x1 <= x0 or y1 <= y0:
                        continue
                    aligned_name = f"cell_{int(frame['step_index']):05d}.jpg"
                    cv2.imwrite(str(aligned_dir / aligned_name), mosaic[y0:y1, x0:x1], [cv2.IMWRITE_JPEG_QUALITY, 88])
                    aligned_thumbnails.append({
                        "step_index": int(frame["step_index"]),
                        "url": f"/api/panorama/image/{session_dir.name}/{frames_folder}/aligned_preview/{aligned_name}",
                    })
                with self._lock:
                    if self.session_state.get("session_id") == session_dir.name:
                        mosaic_key = "live_mosaic" if camera == "thermal" else "live_mosaic_visible"
                        bounds_key = "live_mosaic_bounds" if camera == "thermal" else "live_mosaic_bounds_visible"
                        thumbnails_key = "captured_thumbnails" if camera == "thermal" else "captured_thumbnails_visible"
                        self.session_state[mosaic_key] = f"/api/panorama/image/{session_dir.name}/live_mosaic{suffix}.jpg"
                        self.session_state[bounds_key] = {
                            "az": stats.get("az_range"),
                            "alt": stats.get("alt_range"),
                            "frames": len(frames_meta),
                        }
                        self.session_state[thumbnails_key] = aligned_thumbnails
                        save_key = "save_mosaic_pending" if camera == "thermal" else "save_mosaic_pending_visible"
                        if self.session_state.pop(save_key, False):
                            saved_path = session_dir / f"saved_mosaic{suffix}.jpg"
                            saved_tmp = session_dir / f".saved_mosaic{suffix}.tmp.jpg"
                            cv2.imwrite(str(saved_tmp), mosaic, [cv2.IMWRITE_JPEG_QUALITY, 92])
                            saved_tmp.replace(saved_path)
                            saved_key = "saved_mosaic" if camera == "thermal" else "saved_mosaic_visible"
                            self.session_state[saved_key] = (
                                f"/api/panorama/image/{session_dir.name}/saved_mosaic{suffix}.jpg"
                            )
            except Exception as exc:
                logger.warning("Live mosaic preview failed: %s", exc)

    def stop_panorama_mission(self) -> bool:
        with self._lock:
            if not self.session_state["is_running"]:
                return False
            self._abort_requested = True
            self.session_state["message"] = "Aborting mission..."
        self.ptz_ctrl.stop()
        return True

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            st = dict(self.session_state)
            if st["is_running"] and st["start_time"]:
                st["elapsed_sec"] = int(time.time() - st["start_time"])
            return st

    def list_sessions(self) -> List[Dict[str, Any]]:
        sessions = []
        if not self.panoramas_dir.exists():
            return sessions

        for sdir in sorted(self.panoramas_dir.glob("session_*"), reverse=True):
            if not sdir.is_dir():
                continue

            has_stitched = (sdir / "stitched_panorama.jpg").exists()
            raw_dir = sdir / "raw_frames"
            actual_frames = 0
            if raw_dir.exists():
                actual_frames = len([f for f in raw_dir.glob("*.jpg") if not f.name.startswith("thumb_")])

            meta_path = sdir / "metadata.json"
            cfg_path = sdir / "config.json"

            if meta_path.exists():
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        data["folder_name"] = sdir.name
                        data["has_stitched"] = has_stitched
                        data["actual_frames"] = actual_frames
                        sessions.append(data)
                        continue
                except Exception:
                    pass

            # Fallback to config.json if available
            if cfg_path.exists():
                try:
                    with open(cfg_path, "r", encoding="utf-8") as f:
                        cfg_data = json.load(f)
                        grid_info = cfg_data.get("grid_info", {})
                        sessions.append({
                            "session_id": sdir.name,
                            "folder_name": sdir.name,
                            "timestamp": cfg_data.get("created_at"),
                            "focal_mm": grid_info.get("focal_length_mm"),
                            "overlap_pct": grid_info.get("overlap_pct"),
                            "az_range": [grid_info.get("az_min"), grid_info.get("az_max")],
                            "alt_range": [grid_info.get("alt_min"), grid_info.get("alt_max")],
                            "total_frames": grid_info.get("total_shots", 0),
                            "actual_frames": actual_frames,
                            "has_stitched": has_stitched
                        })
                        continue
                except Exception:
                    pass

            # Minimal fallback
            sessions.append({
                "session_id": sdir.name,
                "folder_name": sdir.name,
                "total_frames": actual_frames,
                "actual_frames": actual_frames,
                "has_stitched": has_stitched
            })

        return sessions

    def delete_session(self, session_id: str) -> bool:
        """Safely removes a session folder and all its contents from disk."""
        import shutil
        clean_id = Path(session_id).name
        if not clean_id or not clean_id.startswith("session_"):
            return False
        sdir = self.panoramas_dir / clean_id
        if sdir.exists() and sdir.is_dir():
            try:
                shutil.rmtree(sdir, ignore_errors=True)
                logger.info(f"🗑️ Panorama session deleted: {clean_id}")
                return True
            except Exception as e:
                logger.error(f"Failed to delete session {clean_id}: {e}")
                return False
        return False

    def restitch_session(self, session_id: str, enable_alignment_refinement: bool = True) -> Dict[str, Any]:
        """Re-stitches an existing panorama session using the upgraded Spherical 3D Ray Warper."""
        clean_id = Path(session_id).name
        session_dir = self.panoramas_dir / clean_id
        if not session_dir.exists() or not session_dir.is_dir():
            return {"success": False, "error": f"Session folder '{clean_id}' not found"}

        meta_path = session_dir / "metadata.json"
        if not meta_path.exists():
            return {"success": False, "error": "Session metadata.json not found"}

        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)

            frames = meta.get("frames", [])
            if not frames:
                return {"success": False, "error": "No frames recorded in metadata"}

            h_fov = float(meta.get("h_fov_deg", 14.2))
            v_fov = float(meta.get("v_fov_deg", 11.4))

            stitched_img, stats = self.stitcher.stitch_positional(
                frames_metadata=frames,
                h_fov_deg=h_fov,
                v_fov_deg=v_fov,
                enable_alignment_refinement=enable_alignment_refinement
            )

            if stitched_img is None:
                return {"success": False, "error": stats.get("error", "Stitching failed")}

            stitched_path = session_dir / "stitched_panorama.jpg"
            thumb_path = session_dir / "thumbnail.jpg"

            cv2.imwrite(str(stitched_path), stitched_img, [cv2.IMWRITE_JPEG_QUALITY, 93])

            preview_w = min(1200, stitched_img.shape[1])
            preview_h = int(stitched_img.shape[0] * (preview_w / stitched_img.shape[1]))
            preview_img = cv2.resize(stitched_img, (preview_w, preview_h))
            cv2.imwrite(str(thumb_path), preview_img)

            meta["stitch_stats"] = stats
            meta["stitched_image"] = "stitched_panorama.jpg"
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2, ensure_ascii=False)

            logger.info(f"✨ Successfully restitched session {clean_id} ({stitched_img.shape[1]}x{stitched_img.shape[0]})")
            return {
                "success": True,
                "session_id": clean_id,
                "stats": stats,
                "stitched_url": f"/api/panorama/image/{clean_id}/stitched_panorama.jpg",
                "thumbnail_url": f"/api/panorama/image/{clean_id}/thumbnail.jpg"
            }
        except Exception as e:
            logger.error(f"Error restitching session {clean_id}: {e}", exc_info=True)
            return {"success": False, "error": str(e)}
