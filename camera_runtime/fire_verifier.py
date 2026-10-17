"""
Kalman Filter Object Tracking & Thermal Core Fire Verification Pipeline
Provides IoU track association, Thermal Core High-Heat verification,
and Temporal State Machine (PENDING -> VERIFYING -> CONFIRMED_FIRE) with Alarm Hold.
"""

import numpy as np
import cv2
import time
from typing import List, Dict, Tuple, Optional


class KalmanBoxTracker:
    """Kalman Filter for tracking bounding boxes in image coordinates."""
    count = 0

    def __init__(self, bbox: List[float]):
        KalmanBoxTracker.count += 1
        self.id = KalmanBoxTracker.count

        # State: [x1, y1, x2, y2, vx1, vy1, vx2, vy2]
        self.dim_x = 8
        self.dim_z = 4

        x1, y1, x2, y2 = bbox
        self.x = np.array([x1, y1, x2, y2, 0.0, 0.0, 0.0, 0.0], dtype=np.float32)

        # Transition matrix F
        self.F = np.eye(self.dim_x, dtype=np.float32)
        for i in range(4):
            self.F[i, i + 4] = 1.0

        # Measurement matrix H
        self.H = np.zeros((self.dim_z, self.dim_x), dtype=np.float32)
        for i in range(4):
            self.H[i, i] = 1.0

        self.R = np.eye(self.dim_z, dtype=np.float32) * 1.0
        self.R[2:, 2:] *= 5.0

        self.Q = np.eye(self.dim_x, dtype=np.float32) * 0.01
        self.Q[4:, 4:] *= 0.1

        self.P = np.eye(self.dim_x, dtype=np.float32) * 10.0
        self.P[4:, 4:] *= 100.0

        self.time_since_update = 0
        self.history = []
        self.hits = 1
        self.hit_streak = 1
        self.age = 0

    def predict(self) -> np.ndarray:
        self.x = np.dot(self.F, self.x)
        self.P = np.dot(np.dot(self.F, self.P), self.F.T) + self.Q

        self.age += 1
        if self.time_since_update > 0:
            self.hit_streak = 0
        self.time_since_update += 1
        self.history.append(self.get_state())
        return self.get_state()

    def update(self, bbox: List[float]):
        self.time_since_update = 0
        self.history = []
        self.hits += 1
        self.hit_streak += 1

        z = np.array(bbox, dtype=np.float32)
        y = z - np.dot(self.H, self.x)
        S = np.dot(np.dot(self.H, self.P), self.H.T) + self.R
        K = np.dot(np.dot(self.P, self.H.T), np.linalg.inv(S))

        self.x = self.x + np.dot(K, y)
        I = np.eye(self.dim_x, dtype=np.float32)
        self.P = np.dot(I - np.dot(K, self.H), self.P)

    def get_state(self) -> List[int]:
        x1 = int(round(self.x[0]))
        y1 = int(round(self.x[1]))
        x2 = int(round(self.x[2]))
        y2 = int(round(self.x[3]))
        if x2 < x1:
            x1, x2 = x2, x1
        if y2 < y1:
            y1, y2 = y2, y1
        return [max(0, x1), max(0, y1), max(0, x2), max(0, y2)]


def compute_iou(bb_test: List[float], bb_gt: List[float]) -> float:
    xx1 = max(bb_test[0], bb_gt[0])
    yy1 = max(bb_test[1], bb_gt[1])
    xx2 = min(bb_test[2], bb_gt[2])
    yy2 = min(bb_test[3], bb_gt[3])

    w = max(0.0, xx2 - xx1)
    h = max(0.0, yy2 - yy1)
    inter = w * h

    area1 = max(0.0, (bb_test[2] - bb_test[0]) * (bb_test[3] - bb_test[1]))
    area2 = max(0.0, (bb_gt[2] - bb_gt[0]) * (bb_gt[3] - bb_gt[1]))
    union = area1 + area2 - inter
    if union <= 0:
        return 0.0
    return inter / union


class KalmanScoreFilter:
    """
    1D Kalman Filter for smoothing detection confidence scores.
    Eliminates high-frequency flickering, sensor noise, and thermal AGC fluctuations
    while preserving fast responsiveness when a persistent hotspot emerges.
    """
    def __init__(self, initial_score: float = 0.5, q: float = 0.002, r: float = 0.03):
        self.x = float(initial_score)
        self.p = 0.1
        self.q = float(q)
        self.r = float(r)

    def update(self, z: float) -> float:
        # Predict
        self.p = self.p + self.q
        # Measurement Update
        k = self.p / (self.p + self.r)
        self.x = self.x + k * (float(z) - self.x)
        self.p = (1.0 - k) * self.p
        self.x = max(0.0, min(1.0, self.x))
        return self.x


class FireTrack:
    """Encapsulates a fire tracking instance with thermal metrics and alarm persistence."""

    STATE_PENDING = "PENDING"
    STATE_VERIFYING = "VERIFYING"
    STATE_CONFIRMED = "CONFIRMED_FIRE"

    def __init__(self, bbox: List[float], score: float, label: str = "fire", world_pos: Optional[Tuple[float, float]] = None):
        self.tracker = KalmanBoxTracker(bbox)
        self.score_filter = KalmanScoreFilter(initial_score=score, q=0.002, r=0.03)
        self.id = self.tracker.id
        self.label = label
        self.filtered_score = float(score)
        self.score = float(score)
        self.score_history = [score]
        self.box_history = [bbox]
        self.state = FireTrack.STATE_PENDING
        self.thermal_core_pass = False
        self.max_core_temp_ratio = 0.0
        self.flicker_score = 0.0
        self.confirmed_timestamp = None
        self.last_confirmed_seen = None
        self.first_seen = time.time()
        self.world_az = world_pos[0] if world_pos else None
        self.world_alt = world_pos[1] if world_pos else None

    @property
    def hits(self) -> int:
        return getattr(self.tracker, "hits", 1) if hasattr(self, "tracker") else 1

    @property
    def hit_streak(self) -> int:
        return getattr(self.tracker, "hit_streak", 1) if hasattr(self, "tracker") else 1

    def update(self, bbox: List[float], score: float, thermal_metrics: dict, min_hits: int = 3, world_pos: Optional[Tuple[float, float]] = None):
        self.tracker.update(bbox)
        self.filtered_score = self.score_filter.update(score)
        self.score = self.filtered_score
        self.score_history.append(score)
        if len(self.score_history) > 10:
            self.score_history.pop(0)

        self.box_history.append(bbox)
        if len(self.box_history) > 10:
            self.box_history.pop(0)

        if world_pos:
            self.world_az = world_pos[0]
            self.world_alt = world_pos[1]

        self.thermal_core_pass = thermal_metrics.get("core_pass", False)
        self.max_core_temp_ratio = thermal_metrics.get("core_ratio", 0.0)
        self.flicker_score = self._compute_flicker()

        hits = self.tracker.hits
        hit_streak = self.tracker.hit_streak

        # Enhanced Condition: hits >= min_hits (e.g. 3) & hit_streak >= 2 & thermal_core_pass & filtered_score >= 0.50
        if (hits >= min_hits and hit_streak >= 2 and self.thermal_core_pass and self.filtered_score >= 0.50) or \
           (self.state == FireTrack.STATE_CONFIRMED and hit_streak >= 1):
            if self.state != FireTrack.STATE_CONFIRMED:
                self.confirmed_timestamp = time.time()
            self.state = FireTrack.STATE_CONFIRMED
            self.last_confirmed_seen = time.time()
        elif hits >= 2:
            if self.state == FireTrack.STATE_CONFIRMED and self.last_confirmed_seen and (time.time() - self.last_confirmed_seen < 4.0):
                self.state = FireTrack.STATE_CONFIRMED
            else:
                self.state = FireTrack.STATE_VERIFYING
        else:
            self.state = FireTrack.STATE_PENDING

    def _compute_flicker(self) -> float:
        if len(self.box_history) < 3:
            return 0.0
        areas = [(b[2] - b[0]) * (b[3] - b[1]) for b in self.box_history]
        mean_area = np.mean(areas)
        if mean_area <= 0:
            return 0.0
        std_area = np.std(areas)
        return float(std_area / mean_area)

    def get_display_info(self) -> dict:
        box = self.tracker.get_state()
        raw = self.score_history[-1] if self.score_history else self.score
        return {
            "id": self.id,
            "box": box,
            "score": round(float(self.filtered_score), 3),
            "raw_score": round(float(raw), 3),
            "state": self.state,
            "hits": self.tracker.hits,
            "age": self.tracker.age,
            "time_since_update": self.tracker.time_since_update,
            "core_ratio": round(float(self.max_core_temp_ratio), 3),
            "flicker_score": round(float(self.flicker_score), 3),
            "world_az": self.world_az,
            "world_alt": self.world_alt,
            "label": "fire"
        }


class ThermalFireVerifier:
    """Multi-stage Fire Verification with Spatial Tracking & Thermal Core Analysis."""

    def __init__(
        self,
        iou_threshold: float = 0.15,
        max_age: int = 20,
        min_hits: int = 3,
        confirmed_hold_cycles: int = 20,
        thermal_core_min_val: int = 190,
        hotspot_threshold: int = 190
    ):
        self.iou_threshold = iou_threshold
        self.max_age = max_age
        self.min_hits = min_hits
        self.confirmed_hold_cycles = confirmed_hold_cycles
        self.thermal_core_min_val = int(thermal_core_min_val)
        self.hotspot_threshold = int(hotspot_threshold)
        self.tracks: List[FireTrack] = []

    def analyze_thermal_core(self, frame_bgr: np.ndarray, box: List[int]) -> dict:
        if frame_bgr is None:
            return {"core_pass": True, "core_ratio": 0.5, "max_val": 255}

        h, w = frame_bgr.shape[:2]
        x1 = max(0, min(w - 1, box[0]))
        y1 = max(0, min(h - 1, box[1]))
        x2 = max(x1 + 1, min(w, box[2]))
        y2 = max(y1 + 1, min(h, box[3]))

        roi = frame_bgr[y1:y2, x1:x2]
        if roi.size == 0:
            return {"core_pass": True, "core_ratio": 0.5, "max_val": 255}

        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        max_val = int(np.max(gray))
        mean_val = float(np.mean(gray))
        std_val = float(np.std(gray))
        gradient = max_val - mean_val

        threshold_val = getattr(self, "thermal_core_min_val", None) or getattr(self, "hotspot_threshold", 185)
        high_heat_mask = (gray >= threshold_val)
        core_pixels = np.count_nonzero(high_heat_mask)
        total_pixels = gray.size
        core_ratio = core_pixels / float(total_pixels) if total_pixels > 0 else 0.0

        # Solar nuisance filter: flat uniform heated structures (roofs/rocks) have low gradient and std
        is_solar_flat = (gradient < 15.0 and std_val < 10.0 and max_val < 240)
        # Require genuine multi-pixel heat core (at least 4 core pixels) and concentrated ratio to prevent dispersed leaf glints from passing
        min_ratio = getattr(self, "min_core_ratio", 0.02)
        core_pass = (core_pixels >= 4 and core_ratio >= min_ratio and max_val >= threshold_val) and not is_solar_flat

        return {
            "core_pass": core_pass,
            "core_ratio": core_ratio,
            "max_val": max_val,
            "gradient": round(gradient, 1)
        }

    def reset(self):
        """Clears all tracking states and history."""
        self.tracks.clear()

    def update(
        self,
        raw_detections: List[dict],
        frame_bgr: Optional[np.ndarray] = None,
        ptz_pos: Optional[Tuple[float, float]] = None,
        fov: Optional[Tuple[float, float]] = None
    ) -> List[dict]:
        # Compute World Coordinates for each detection if PTZ telemetry and FOV are available
        h, w = (frame_bgr.shape[:2] if frame_bgr is not None else (512, 640))
        for det in raw_detections:
            if ptz_pos and fov:
                cur_az, cur_alt = ptz_pos
                fov_h, fov_v = fov
                cx = (det["box"][0] + det["box"][2]) / 2.0
                cy = (det["box"][1] + det["box"][3]) / 2.0
                det_az = cur_az + ((cx - w / 2.0) / float(w)) * fov_h
                det_alt = cur_alt - ((cy - h / 2.0) / float(h)) * fov_v
                det["world_pos"] = (round(det_az, 3), round(det_alt, 3))
            else:
                det["world_pos"] = None

        # Step 1: Predict
        for t in self.tracks:
            t.tracker.predict()

        # Step 2: Associate using Multi-Metric Matching (IoU + Pixel Center Dist + World Angle)
        matched, unmatched_dets, unmatched_tracks = self._associate(raw_detections)

        # Step 3: Update Matched
        for det_idx, trk_idx in matched:
            det = raw_detections[det_idx]
            trk = self.tracks[trk_idx]
            metrics = self.analyze_thermal_core(frame_bgr, det["box"])
            trk.update(det["box"], det["score"], metrics, min_hits=self.min_hits, world_pos=det.get("world_pos"))

        # Step 4: Add Unmatched
        for det_idx in unmatched_dets:
            det = raw_detections[det_idx]
            metrics = self.analyze_thermal_core(frame_bgr, det["box"])
            new_trk = FireTrack(det["box"], det["score"], label=det.get("label", "fire"), world_pos=det.get("world_pos"))
            new_trk.thermal_core_pass = metrics.get("core_pass", True)
            new_trk.max_core_temp_ratio = metrics.get("core_ratio", 0.0)
            self.tracks.append(new_trk)

        # Step 5: Clean Dead Tracks
        self.tracks = [
            t for t in self.tracks
            if t.tracker.time_since_update <= self.max_age
        ]

        # Step 6: Format active list
        active_list = []
        for t in self.tracks:
            if t.tracker.time_since_update <= 1:
                active_list.append(t.get_display_info())

        return active_list

    def _associate(self, detections: List[dict]) -> Tuple[List[Tuple[int, int]], List[int], List[int]]:
        if len(self.tracks) == 0:
            return [], list(range(len(detections))), []
        if len(detections) == 0:
            return [], [], list(range(len(self.tracks)))

        cost_mat = np.zeros((len(detections), len(self.tracks)), dtype=np.float32)
        for d, det in enumerate(detections):
            d_box = det["box"]
            d_cx = (d_box[0] + d_box[2]) / 2.0
            d_cy = (d_box[1] + d_box[3]) / 2.0
            d_world = det.get("world_pos")

            for t, trk in enumerate(self.tracks):
                t_box = trk.tracker.get_state()
                t_cx = (t_box[0] + t_box[2]) / 2.0
                t_cy = (t_box[1] + t_box[3]) / 2.0

                # 1. 2D Bounding Box IoU
                iou = compute_iou(d_box, t_box)

                # 2. Pixel Center Proximity (handles horizontal pan shift while elevation stays consistent)
                dist_y = abs(d_cy - t_cy)
                dist_c = np.sqrt((d_cx - t_cx)**2 + (d_cy - t_cy)**2)
                # Allow horizontal shift up to 160px while vertical shift is within 35px
                pixel_score = float(np.exp(-dist_c / 60.0)) if (dist_y <= 35.0 and dist_c <= 180.0) else 0.0

                # 3. World Coordinate Angular Proximity (stationary fire has ~0 deg angular shift)
                ang_score = 0.0
                if d_world and trk.world_az is not None and trk.world_alt is not None:
                    d_az = abs(d_world[0] - trk.world_az) % 360.0
                    if d_az > 180.0:
                        d_az = 360.0 - d_az
                    d_alt = abs(d_world[1] - trk.world_alt)
                    ang_dist = np.sqrt(d_az**2 + d_alt**2)
                    if ang_dist <= 1.0:
                        ang_score = float(max(0.0, 1.0 - (ang_dist / 0.8)))

                # Combined affinity score
                cost_mat[d, t] = max(iou, pixel_score, ang_score)

        matched = []
        un_dets = list(range(len(detections)))
        un_trks = list(range(len(self.tracks)))

        # Greedy bipartite matching
        while True:
            if len(un_dets) == 0 or len(un_trks) == 0:
                break
            max_score = 0.0
            best_d = -1
            best_t = -1
            for d in un_dets:
                for t in un_trks:
                    if cost_mat[d, t] > max_score:
                        max_score = cost_mat[d, t]
                        best_d = d
                        best_t = t

            if max_score >= 0.15:
                matched.append((best_d, best_t))
                un_dets.remove(best_d)
                un_trks.remove(best_t)
            else:
                break

        return matched, un_dets, un_trks
