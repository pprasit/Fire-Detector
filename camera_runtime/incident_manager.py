"""
Fire Incident Manager Module
Handles archiving fire incidents, dual camera snapshots (Thermal + Visible),
spatial matching of coordinates (Azimuth/Altitude) across scan rounds,
and fire growth size analysis (EXPANDING, STABLE, SHRINKING).
"""

import os
import json
import time
import math
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
import cv2
import numpy as np

logger = logging.getLogger("FireIncidentManager")

BASE_DIR = Path(__file__).resolve().parent
INCIDENTS_BASE_DIR = BASE_DIR / "incident_records"
SNAPSHOTS_DIR = INCIDENTS_BASE_DIR / "snapshots"
HISTORY_FILE = INCIDENTS_BASE_DIR / "incident_history.json"


class FireIncidentManager:
    """Manages recording, matching, and growth calculation for fire incidents."""

    def __init__(
        self,
        base_dir: Optional[Path] = None,
        snapshots_dir: Optional[Path] = None,
        history_file: Optional[Path] = None,
        match_tolerance_deg: float = 1.0,
        max_inactive_gap_hours: float = 2.0
    ):
        self.base_dir = base_dir or INCIDENTS_BASE_DIR
        self.snapshots_dir = snapshots_dir or (self.base_dir / "snapshots")
        self.history_file = history_file or (self.base_dir / "incident_history.json")
        self.match_tolerance_deg = match_tolerance_deg
        self.max_inactive_gap_hours = max_inactive_gap_hours
        self.incidents: List[Dict[str, Any]] = []

        # Ensure directories exist
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        self._load_history()

    def _load_history(self):
        """Loads incident history from JSON file and recalculates regression trends."""
        if self.history_file.exists():
            try:
                with open(self.history_file, "r", encoding="utf-8") as f:
                    self.incidents = json.load(f)

                # Auto-migrate / recalculate trends for historical records
                for inc in self.incidents:
                    hist = inc.get("history", [])
                    if len(hist) > 0:
                        all_areas = [h.get("area_px", 0) for h in hist]
                        curr_area = inc.get("current_area_px", all_areas[-1])
                        init_area = inc.get("initial_area_px", all_areas[0])
                        prev_area = all_areas[-2] if len(all_areas) > 1 else init_area

                        trend_info = self.compute_multi_round_trend(
                            history_areas=all_areas[:-1],
                            current_area=curr_area,
                            initial_area=init_area,
                            prev_area=prev_area
                        )

                        inc["trend_slope_pct"] = trend_info["trend_slope_pct"]
                        inc["total_rounds"] = trend_info["total_rounds"]
                        inc["growth_trend"] = trend_info["trend"]
                        inc["growth_trend_label"] = trend_info["trend_label"]
                        inc["total_growth_pct"] = trend_info["total_growth_pct"]
                        inc["growth_from_prev_pct"] = trend_info["growth_from_prev_pct"]

                    if not inc.get("zoom_info") and len(hist) > 0:
                        inc["zoom_info"] = dict(hist[-1].get("zoom_info", {}))

                    # Normalize visible camera optics if missing
                    default_vis_optics = {
                        "focal_mm": 15.1,
                        "zoom_x": 3.0,
                        "zoom_pct": 10.3,
                        "fov_h": 18.59,
                        "fov_v": 10.20,
                        "fov_d": 21.89
                    }
                    if inc.get("zoom_info") and not inc["zoom_info"].get("visible"):
                        inc["zoom_info"]["visible"] = default_vis_optics
                    for h in hist:
                        if "zoom_info" in h and not h["zoom_info"].get("visible"):
                            h["zoom_info"]["visible"] = default_vis_optics

                logger.info(f"Loaded and normalized {len(self.incidents)} fire incidents from {self.history_file.name}")
            except Exception as e:
                logger.warning(f"Error loading incident history: {e}")
                self.incidents = []
        else:
            self.incidents = []

    def _save_history(self):
        """Persists incident history to JSON file."""
        try:
            with open(self.history_file, "w", encoding="utf-8") as f:
                json.dump(self.incidents, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save incident history: {e}")

    @staticmethod
    def angular_distance(az1: float, alt1: float, az2: float, alt2: float) -> float:
        """Calculates Euclidean angular distance accounting for 360° Azimuth wrap-around."""
        d_az = abs(az1 - az2) % 360.0
        if d_az > 180.0:
            d_az = 360.0 - d_az
        d_alt = abs(alt1 - alt2)
        return math.sqrt(d_az ** 2 + d_alt ** 2)

    def find_matching_incident(
        self,
        az: float,
        alt: float,
        current_time: Optional[float] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Finds existing fire incident recorded within angular proximity tolerance
        and within the active time window (not expired).
        """
        best_match = None
        min_dist = float("inf")
        now = current_time if current_time is not None else time.time()
        max_gap_sec = self.max_inactive_gap_hours * 3600.0

        for inc in self.incidents:
            status = inc.get("status") or "ACTIVE"
            last_epoch = inc.get("last_epoch", 0)

            # Never match closed or extinguished incidents
            if status in ("EXTINGUISHED", "CLOSED"):
                continue

            # Expire if inactivity gap exceeded (do not match incidents older than max_gap_sec)
            if max_gap_sec > 0 and (now - last_epoch) > max_gap_sec:
                continue

            # Compare against both initial origin and latest current position
            dist_init = self.angular_distance(az, alt, inc["azimuth"], inc["altitude"])
            dist_curr = self.angular_distance(
                az, alt,
                inc.get("current_azimuth", inc["azimuth"]),
                inc.get("current_altitude", inc["altitude"])
            )
            dist = min(dist_init, dist_curr)

            if dist <= self.match_tolerance_deg and dist < min_dist:
                min_dist = dist
                best_match = inc

        return best_match

    @staticmethod
    def extract_thermal_hot_pixels(thermal_frame: Optional[np.ndarray], bbox: List[int]) -> int:
        """
        Extracts actual heat-emitting pixels (True Thermal Mask) within or near the target bounding box,
        eliminating ambient background noise from standard bounding box area (w*h).
        """
        if thermal_frame is None or thermal_frame.size == 0 or not bbox or len(bbox) != 4:
            return 0

        h, w = thermal_frame.shape[:2]
        x1, y1, x2, y2 = bbox
        if x2 <= x1 or y2 <= y1:
            return 0

        x1_c = max(0, min(w - 1, x1))
        y1_c = max(0, min(h - 1, y1))
        x2_c = max(x1_c + 1, min(w, x2))
        y2_c = max(y1_c + 1, min(h, y2))

        if len(thermal_frame.shape) == 3:
            gray = cv2.cvtColor(thermal_frame, cv2.COLOR_BGR2GRAY)
        else:
            gray = thermal_frame

        roi = gray[y1_c:y2_c, x1_c:x2_c]
        if roi.size == 0:
            return 0

        max_val = int(np.max(roi))
        if max_val >= 160:
            # Core heat threshold: 70% of peak heat but at least 150
            th_core = max(150, int(max_val * 0.70))
        else:
            # Mild hotspot threshold
            th_core = max(120, int(max_val * 0.85))

        hot_pixels = int(np.count_nonzero(roi >= th_core))
        return hot_pixels if hot_pixels > 0 else (x2 - x1) * (y2 - y1)

    @staticmethod
    def compute_multi_round_trend(
        history_areas: List[float],
        current_area: float,
        initial_area: float,
        prev_area: float
    ) -> Dict[str, Any]:
        """
        Computes overall growth trend using linear regression slope across ALL recorded historical rounds
        for this hotspot location.
        """
        all_areas = history_areas + [current_area]
        n = len(all_areas)

        total_growth_pct = round(((current_area - initial_area) / initial_area) * 100.0, 1) if initial_area > 0 else 0.0
        growth_from_prev_pct = round(((current_area - prev_area) / prev_area) * 100.0, 1) if prev_area > 0 else 0.0

        if n <= 1:
            return {
                "trend": "NEW_DETECTION",
                "trend_label": "NEW DETECTION",
                "total_growth_pct": 0.0,
                "growth_from_prev_pct": 0.0,
                "trend_slope_pct": 0.0,
                "total_rounds": 1
            }

        # Linear regression over all historical rounds
        x = np.arange(n, dtype=float)
        y = np.array(all_areas, dtype=float)

        mean_x = float(np.mean(x))
        mean_y = float(np.mean(y))
        denom = float(np.sum((x - mean_x) ** 2))

        if denom > 0:
            slope = float(np.sum((x - mean_x) * (y - mean_y)) / denom)
        else:
            slope = 0.0

        mean_area_safe = max(1.0, mean_y)
        slope_pct_per_round = round((slope / mean_area_safe) * 100.0, 1)

        # Unified Trend Classification based on full historical regression slope & cumulative growth
        if slope_pct_per_round > 3.0 or (slope_pct_per_round > 0 and total_growth_pct > 15.0):
            trend = "EXPANDING"
            trend_label = f"EXPANDING ({'+' if slope_pct_per_round >= 0 else ''}{slope_pct_per_round}%/rnd)"
        elif slope_pct_per_round < -3.0 or (slope_pct_per_round < 0 and total_growth_pct < -15.0):
            trend = "SHRINKING"
            trend_label = f"SHRINKING ({slope_pct_per_round}%/rnd)"
        else:
            trend = "STABLE"
            trend_label = f"STABLE ({'+' if slope_pct_per_round >= 0 else ''}{slope_pct_per_round}%/rnd)"

        return {
            "trend": trend,
            "trend_label": trend_label,
            "total_growth_pct": total_growth_pct,
            "growth_from_prev_pct": growth_from_prev_pct,
            "trend_slope_pct": slope_pct_per_round,
            "total_rounds": n
        }

    def record_fire_event(
        self,
        az: float,
        alt: float,
        target_bbox: Optional[List[float]] = None,
        confidence: float = 0.0,
        thermal_frame: Optional[np.ndarray] = None,
        visible_frame: Optional[np.ndarray] = None,
        zoom_info: Optional[Dict[str, Any]] = None,
        incident_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Records a confirmed fire detection event, saves snapshots,
        and computes growth comparison using True Thermal Mask Pixels and Multi-round Regression Trend.
        """
        now = time.time()
        time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))
        file_timestamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(now))

        # Calculate bounding box dimensions & True Thermal Heat Pixels
        if target_bbox and len(target_bbox) == 4:
            x1, y1, x2, y2 = [int(v) for v in target_bbox]
            w_px = max(1, x2 - x1)
            h_px = max(1, y2 - y1)
            bbox_area_px = w_px * h_px
        else:
            x1, y1, x2, y2 = 0, 0, 0, 0
            w_px, h_px, bbox_area_px = 0, 0, 0

        # Extract true thermal hot pixel count (Option 1)
        heat_pixels = self.extract_thermal_hot_pixels(thermal_frame, [x1, y1, x2, y2])
        area_px = heat_pixels if heat_pixels > 0 else (bbox_area_px if bbox_area_px > 0 else 0)

        # Save Snapshots
        th_filename = f"fire_{file_timestamp}_th.jpg"
        vis_filename = f"fire_{file_timestamp}_vis.jpg"
        th_path = self.snapshots_dir / th_filename
        vis_path = self.snapshots_dir / vis_filename

        th_url = f"/api/incidents/snapshots/{th_filename}"
        vis_url = f"/api/incidents/snapshots/{vis_filename}"

        if thermal_frame is not None:
            try:
                cv2.imwrite(str(th_path), thermal_frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            except Exception as e:
                logger.error(f"Failed to save thermal snapshot: {e}")

        if visible_frame is not None:
            try:
                cv2.imwrite(str(vis_path), visible_frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            except Exception as e:
                logger.error(f"Failed to save visible snapshot: {e}")

        # Scan record entry
        scan_entry = {
            "timestamp": time_str,
            "epoch": round(now, 2),
            "azimuth": round(az, 2),
            "altitude": round(alt, 2),
            "bbox": [x1, y1, x2, y2],
            "area_px": area_px,
            "heat_pixels_px": heat_pixels,
            "bbox_area_px": bbox_area_px,
            "width_px": w_px,
            "height_px": h_px,
            "confidence": round(confidence, 3),
            "thermal_snapshot": th_url,
            "visible_snapshot": vis_url,
            "zoom_info": zoom_info or {}
        }

        # Check if matches an existing fire location or target incident_id
        existing = None
        if incident_id:
            existing = self.get_incident_by_id(incident_id)
        if not existing:
            existing = self.find_matching_incident(az, alt, current_time=now)

        if existing:
            incident_id = existing["id"]
            scan_count = len(existing.get("history", [])) + 1
            initial_area = existing.get("initial_area_px", area_px)
            prev_area = existing.get("current_area_px", area_px)

            # Extract history areas for multi-round regression (Option 4)
            history_areas = [h.get("area_px", initial_area) for h in existing.get("history", [])]

            trend_info = self.compute_multi_round_trend(
                history_areas=history_areas,
                current_area=area_px,
                initial_area=initial_area,
                prev_area=prev_area
            )

            trend = trend_info["trend"]
            trend_label = trend_info["trend_label"]
            total_growth_pct = trend_info["total_growth_pct"]
            growth_from_prev_pct = trend_info["growth_from_prev_pct"]
            trend_slope_pct = trend_info["trend_slope_pct"]
            total_rounds = trend_info["total_rounds"]

            scan_entry["growth_from_prev_pct"] = growth_from_prev_pct
            scan_entry["total_growth_pct"] = total_growth_pct
            scan_entry["trend_slope_pct"] = trend_slope_pct
            scan_entry["trend"] = trend

            # Calculate previous scan data
            if len(existing.get("history", [])) > 0:
                last_prev = existing["history"][-1]
                prev_th = last_prev.get("thermal_snapshot", th_url)
                prev_vis = last_prev.get("visible_snapshot", vis_url)
                prev_area_val = last_prev.get("area_px", area_px)
                prev_round_num = len(existing["history"])
            else:
                prev_th = th_url
                prev_vis = vis_url
                prev_area_val = area_px
                prev_round_num = 1

            # Update existing record
            existing["last_updated"] = time_str
            existing["last_epoch"] = round(now, 2)
            existing["scan_rounds"] = scan_count
            existing["current_azimuth"] = round(az, 2)
            existing["current_altitude"] = round(alt, 2)
            existing["current_area_px"] = area_px
            existing["current_heat_pixels_px"] = heat_pixels
            existing["current_bbox_area_px"] = bbox_area_px
            existing["current_bbox"] = [x1, y1, x2, y2]
            existing["current_confidence"] = round(confidence, 3)
            existing["previous_thermal_snapshot"] = prev_th
            existing["previous_visible_snapshot"] = prev_vis
            existing["previous_area_px"] = prev_area_val
            existing["previous_round_num"] = prev_round_num
            existing["latest_thermal_snapshot"] = th_url
            existing["latest_visible_snapshot"] = vis_url
            existing["total_growth_pct"] = total_growth_pct
            existing["growth_from_prev_pct"] = growth_from_prev_pct
            existing["trend_slope_pct"] = trend_slope_pct
            existing["total_rounds"] = total_rounds
            existing["growth_trend"] = trend
            existing["growth_trend_label"] = trend_label
            existing["status"] = "ACTIVE"
            existing["zoom_info"] = zoom_info or {}
            existing["history"].append(scan_entry)

            logger.info(f" Existing Fire Location Updated [{incident_id}]: {trend_label} (Initial: {initial_area}px², Current: {area_px}px²)")
            result = existing
        else:
            # Create New Incident
            incident_id = f"INC-{file_timestamp}"
            new_incident = {
                "id": incident_id,
                "status": "ACTIVE",
                "first_detected": time_str,
                "first_epoch": round(now, 2),
                "last_updated": time_str,
                "last_epoch": round(now, 2),
                "azimuth": round(az, 2),
                "altitude": round(alt, 2),
                "current_azimuth": round(az, 2),
                "current_altitude": round(alt, 2),
                "initial_area_px": area_px,
                "previous_area_px": area_px,
                "previous_round_num": 1,
                "current_area_px": area_px,
                "initial_heat_pixels_px": heat_pixels,
                "current_heat_pixels_px": heat_pixels,
                "initial_bbox_area_px": bbox_area_px,
                "current_bbox_area_px": bbox_area_px,
                "initial_bbox": [x1, y1, x2, y2],
                "current_bbox": [x1, y1, x2, y2],
                "initial_confidence": round(confidence, 3),
                "current_confidence": round(confidence, 3),
                "initial_thermal_snapshot": th_url,
                "initial_visible_snapshot": vis_url,
                "previous_thermal_snapshot": th_url,
                "previous_visible_snapshot": vis_url,
                "latest_thermal_snapshot": th_url,
                "latest_visible_snapshot": vis_url,
                "zoom_info": zoom_info or {},
                "scan_rounds": 1,
                "total_growth_pct": 0.0,
                "growth_from_prev_pct": 0.0,
                "trend_slope_pct": 0.0,
                "window_rounds": 1,
                "growth_trend": "NEW_DETECTION",
                "growth_trend_label": " NEW DETECTION",
                "history": [scan_entry]
            }
            self.incidents.insert(0, new_incident)
            logger.info(f" New Fire Incident Registered [{incident_id}]: Az={az:.1f}°, Alt={alt:.1f}°, HeatPixels={area_px}px²")
            result = new_incident

        self._save_history()
        return result

    def get_incident_by_id(self, incident_id: str) -> Optional[Dict[str, Any]]:
        """Returns single incident by its ID."""
        for inc in self.incidents:
            if inc.get("id") == incident_id:
                return inc
        return None

    def get_active_incidents(self, max_age_hours: float = 24.0) -> List[Dict[str, Any]]:
        """Returns list of all active (non-extinguished) incidents within active time window."""
        now = time.time()
        max_gap = max_age_hours * 3600.0 if max_age_hours > 0 else 0
        active_list = []
        for inc in self.incidents:
            status = inc.get("status") or "ACTIVE"
            inc["status"] = status
            if status in ("EXTINGUISHED", "CLOSED"):
                continue
            last_epoch = inc.get("last_epoch", 0)
            if max_gap > 0 and (now - last_epoch) > max_gap:
                continue
            active_list.append(inc)
        return active_list

    def mark_incident_extinguished(self, incident_id: str, notes: str = "") -> Optional[Dict[str, Any]]:
        """Marks an active incident as extinguished and saves state."""
        now = time.time()
        time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))
        for inc in self.incidents:
            if inc.get("id") == incident_id:
                inc["status"] = "EXTINGUISHED"
                inc["extinguished_time"] = time_str
                inc["extinguished_epoch"] = round(now, 2)
                if notes:
                    inc["extinguished_notes"] = notes
                logger.info(f"✅ Incident {incident_id} marked as EXTINGUISHED at {time_str}")
                self._save_history()
                return inc
        return None

    def get_incidents(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Returns list of all incidents sorted by latest updated."""
        return sorted(self.incidents, key=lambda x: x.get("last_epoch", 0), reverse=True)[:limit]

    def get_latest_incident(self) -> Optional[Dict[str, Any]]:
        """Returns the most recently recorded or updated incident."""
        if not self.incidents:
            return None
        return sorted(self.incidents, key=lambda x: x.get("last_epoch", 0), reverse=True)[0]

    def _delete_snapshot_file_from_url(self, snapshot_url: Optional[str]):
        """Helper to delete a snapshot file given its API URL (/api/incidents/snapshots/<filename>)."""
        if not snapshot_url:
            return
        filename = os.path.basename(snapshot_url)
        filepath = self.snapshots_dir / filename
        if filepath.exists() and filepath.is_file():
            try:
                filepath.unlink()
            except Exception as e:
                logger.warning(f"Failed to delete snapshot file {filepath}: {e}")

    def delete_incident(self, incident_id: str) -> bool:
        """Deletes an incident by ID and purges all its snapshot image files."""
        matched_idx = None
        for idx, inc in enumerate(self.incidents):
            if inc.get("id") == incident_id:
                matched_idx = idx
                break

        if matched_idx is None:
            return False

        inc = self.incidents.pop(matched_idx)

        # Delete all snapshots in history
        for round_entry in inc.get("history", []):
            self._delete_snapshot_file_from_url(round_entry.get("thermal_snapshot"))
            self._delete_snapshot_file_from_url(round_entry.get("visible_snapshot"))

        # Also check direct top-level snapshot fields
        self._delete_snapshot_file_from_url(inc.get("initial_thermal_snapshot"))
        self._delete_snapshot_file_from_url(inc.get("initial_visible_snapshot"))
        self._delete_snapshot_file_from_url(inc.get("latest_thermal_snapshot"))
        self._delete_snapshot_file_from_url(inc.get("latest_visible_snapshot"))

        self._save_history()
        logger.info(f"Deleted fire incident record [{incident_id}] and associated snapshot files.")
        return True

    def delete_incident_round(self, incident_id: str, round_idx: int) -> Optional[Dict[str, Any]]:
        """Deletes a specific scan round snapshot from an incident."""
        incident = None
        for inc in self.incidents:
            if inc.get("id") == incident_id:
                incident = inc
                break

        if not incident:
            return None

        history = incident.get("history", [])
        if round_idx < 0 or round_idx >= len(history):
            return None

        removed_entry = history.pop(round_idx)
        self._delete_snapshot_file_from_url(removed_entry.get("thermal_snapshot"))
        self._delete_snapshot_file_from_url(removed_entry.get("visible_snapshot"))

        if len(history) == 0:
            # If no rounds left, remove whole incident
            self.incidents = [i for i in self.incidents if i.get("id") != incident_id]
            self._save_history()
            return {"deleted_whole_incident": True}

        # Recalculate statistics for remaining history
        all_areas = [h.get("area_px", 0) for h in history]
        initial_entry = history[0]
        latest_entry = history[-1]
        prev_entry = history[-2] if len(history) > 1 else initial_entry

        curr_area = latest_entry.get("area_px", 0)
        init_area = initial_entry.get("area_px", 0)
        prev_area = prev_entry.get("area_px", 0)

        trend_info = self.compute_multi_round_trend(
            history_areas=all_areas[:-1],
            current_area=curr_area,
            initial_area=init_area,
            prev_area=prev_area
        )

        incident["scan_rounds"] = len(history)
        incident["total_rounds"] = len(history)
        incident["first_detected"] = initial_entry.get("timestamp", incident.get("first_detected"))
        incident["first_epoch"] = initial_entry.get("epoch", incident.get("first_epoch"))
        incident["last_updated"] = latest_entry.get("timestamp", incident.get("last_updated"))
        incident["last_epoch"] = latest_entry.get("epoch", incident.get("last_epoch"))
        incident["initial_area_px"] = init_area
        incident["current_area_px"] = curr_area
        incident["previous_area_px"] = prev_area
        incident["initial_thermal_snapshot"] = initial_entry.get("thermal_snapshot")
        incident["initial_visible_snapshot"] = initial_entry.get("visible_snapshot")
        incident["latest_thermal_snapshot"] = latest_entry.get("thermal_snapshot")
        incident["latest_visible_snapshot"] = latest_entry.get("visible_snapshot")
        incident["current_azimuth"] = latest_entry.get("azimuth", incident.get("current_azimuth"))
        incident["current_altitude"] = latest_entry.get("altitude", incident.get("current_altitude"))
        incident["growth_trend"] = trend_info["trend"]
        incident["growth_trend_label"] = trend_info["trend_label"]
        incident["total_growth_pct"] = trend_info["total_growth_pct"]
        incident["growth_from_prev_pct"] = trend_info["growth_from_prev_pct"]
        incident["trend_slope_pct"] = trend_info["trend_slope_pct"]

        self._save_history()
        return incident

    def update_incident_llm_result(self, incident_id: str, llm_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Updates an existing incident record with LLM verification analysis."""
        incident = self.get_incident_by_id(incident_id)
        if not incident:
            return None

        incident["llm_verification"] = llm_data
        risk = str(llm_data.get("risk_level", "")).upper()
        if risk == "FALSE_ALARM":
            incident["status"] = "FALSE_ALARM"
            incident["growth_trend"] = "FALSE_ALARM"
            incident["growth_trend_label"] = "FALSE ALARM (VERIFIED)"

        self._save_history()
        logger.info(f"Updated LLM verification for incident {incident_id}: {llm_data.get('risk_level')} (Status: {incident.get('status')})")
        return incident

    def clear_history(self) -> bool:
        """Clears all incident history and snapshot images."""
        self.incidents = []
        self._save_history()
        try:
            for f in self.snapshots_dir.glob("*.jpg"):
                try:
                    f.unlink()
                except Exception as e:
                    logger.warning(f"Could not delete snapshot {f}: {e}")
            logger.info("Cleared all incident history and snapshots.")
            return True
        except Exception as e:
            logger.error(f"Error clearing snapshots: {e}")
            return False
