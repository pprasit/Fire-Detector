"""
Classic Thermal Hotspot Detector Module
Computer Vision pipeline using Luminance/Heat Thresholding, Morphological Filtering,
and Contour Analysis to detect heat sources/fire directly from thermal BGR imagery.
Ultra-fast (<5ms), robust, deterministic, and ideal for thermal surveillance cameras.
"""

import cv2
import numpy as np
from typing import List, Dict, Any, Optional, Tuple


class ClassicThermalDetector:
    """Detects thermal hotspots and fire signatures using classic computer vision."""

    def __init__(
        self,
        threshold: int = 190,
        min_area: int = 15,
        max_area: int = 40000,
        morph_kernel_size: int = 5,
        dilate_iterations: int = 2,
        blur_ksize: int = 3,
        use_tophat: bool = True,
        tophat_ksize: int = 15,
        tophat_threshold: int = 35,
        use_adaptive: bool = True,
        adaptive_k: float = 3.0,
        adaptive_min_threshold: int = 170,
        zoom_aware: bool = True,
        min_focal_mm: float = 31.0,
        max_focal_mm: float = 155.0,
        use_clutter_suppression: bool = True,
        clutter_threshold: int = 8,
        clutter_min_core_ratio: float = 0.035,
        clutter_min_hot_pixels: int = 6
    ):
        self.threshold = int(threshold)
        self.min_area = int(min_area)
        self.max_area = int(max_area)
        self.morph_kernel_size = int(morph_kernel_size)
        self.dilate_iterations = int(dilate_iterations)
        self.blur_ksize = int(blur_ksize)

        # Method 1: White Top-Hat
        self.use_tophat = bool(use_tophat)
        self.tophat_ksize = int(tophat_ksize)
        self.tophat_threshold = int(tophat_threshold)

        # Method 2: Adaptive Saliency
        self.use_adaptive = bool(use_adaptive)
        self.adaptive_k = float(adaptive_k)
        self.adaptive_min_threshold = int(adaptive_min_threshold)

        # Method 4: Zoom-Aware Scaling
        self.zoom_aware = bool(zoom_aware)
        self.min_focal_mm = float(min_focal_mm)
        self.max_focal_mm = float(max_focal_mm)
        self.current_zoom_ratio = 0.0

        # Method 3: Canopy Clutter Storm Suppression
        self.use_clutter_suppression = bool(use_clutter_suppression)
        self.clutter_threshold = int(clutter_threshold)
        self.clutter_min_core_ratio = float(clutter_min_core_ratio)
        self.clutter_min_hot_pixels = int(clutter_min_hot_pixels)

    def update_params(
        self,
        threshold: Optional[int] = None,
        min_area: Optional[int] = None,
        max_area: Optional[int] = None,
        morph_kernel_size: Optional[int] = None,
        dilate_iterations: Optional[int] = None,
        blur_ksize: Optional[int] = None,
        use_tophat: Optional[bool] = None,
        tophat_ksize: Optional[int] = None,
        tophat_threshold: Optional[int] = None,
        use_adaptive: Optional[bool] = None,
        adaptive_k: Optional[float] = None,
        adaptive_min_threshold: Optional[int] = None,
        zoom_aware: Optional[bool] = None,
        min_focal_mm: Optional[float] = None,
        max_focal_mm: Optional[float] = None,
        use_clutter_suppression: Optional[bool] = None,
        clutter_threshold: Optional[int] = None,
        clutter_min_core_ratio: Optional[float] = None,
        clutter_min_hot_pixels: Optional[int] = None
    ):
        """Live updates detection parameters."""
        if threshold is not None:
            self.threshold = max(50, min(255, int(threshold)))
        if min_area is not None:
            self.min_area = max(1, int(min_area))
        if max_area is not None:
            self.max_area = max(self.min_area, int(max_area))
        if morph_kernel_size is not None:
            self.morph_kernel_size = max(1, int(morph_kernel_size))
            if self.morph_kernel_size % 2 == 0:
                self.morph_kernel_size += 1
        if dilate_iterations is not None:
            self.dilate_iterations = max(0, int(dilate_iterations))
        if blur_ksize is not None:
            self.blur_ksize = max(1, int(blur_ksize))
            if self.blur_ksize % 2 == 0:
                self.blur_ksize += 1

        if use_tophat is not None:
            self.use_tophat = bool(use_tophat)
        if tophat_ksize is not None:
            self.tophat_ksize = max(3, int(tophat_ksize))
            if self.tophat_ksize % 2 == 0:
                self.tophat_ksize += 1
        if tophat_threshold is not None:
            self.tophat_threshold = max(5, min(255, int(tophat_threshold)))

        if use_adaptive is not None:
            self.use_adaptive = bool(use_adaptive)
        if adaptive_k is not None:
            self.adaptive_k = float(adaptive_k)
        if adaptive_min_threshold is not None:
            self.adaptive_min_threshold = max(50, min(250, int(adaptive_min_threshold)))

        if zoom_aware is not None:
            self.zoom_aware = bool(zoom_aware)
        if min_focal_mm is not None:
            self.min_focal_mm = float(min_focal_mm)
        if max_focal_mm is not None:
            self.max_focal_mm = float(max_focal_mm)

        if use_clutter_suppression is not None:
            self.use_clutter_suppression = bool(use_clutter_suppression)
        if clutter_threshold is not None:
            self.clutter_threshold = max(2, int(clutter_threshold))
        if clutter_min_core_ratio is not None:
            self.clutter_min_core_ratio = max(0.005, min(0.5, float(clutter_min_core_ratio)))
        if clutter_min_hot_pixels is not None:
            self.clutter_min_hot_pixels = max(1, int(clutter_min_hot_pixels))

    def detect(self, frame_bgr: np.ndarray, zoom_ratio: Optional[float] = None) -> List[Dict[str, Any]]:
        """
        Executes hotspot extraction pipeline on a thermal BGR frame.
        Supports:
          - Method 1: White Top-Hat Transform for background gradient/AGC shift rejection.
          - Method 2: Dynamic/Adaptive Saliency Thresholding (Mean + k*Std).
          - Method 4: Zoom-Aware Area & Parameters Scaling based on real camera focal length.
        Returns a list of detections: [{'box': [x1, y1, x2, y2], 'score': float, 'label': 'fire', 'area': int, 'max_val': int}]
        """
        if frame_bgr is None or frame_bgr.size == 0:
            return []

        h, w = frame_bgr.shape[:2]

        if zoom_ratio is not None:
            self.current_zoom_ratio = max(0.0, min(1.0, float(zoom_ratio)))

        # ----------------------------------------------------------------------
        # Method 4: Zoom-Aware Parameters & Area Scaling
        # ----------------------------------------------------------------------
        focal_range = max(1.0, self.max_focal_mm - self.min_focal_mm)
        current_focal = self.min_focal_mm + (self.current_zoom_ratio * focal_range)
        optical_zoom_factor = current_focal / max(1.0, self.min_focal_mm)  # 1.0x (Wide) to 5.0x (Tele)

        if self.zoom_aware and optical_zoom_factor > 1.05:
            # Preserve min_area so small distant campfires/hotspots are never discarded when zoomed in!
            effective_min_area = self.min_area
            # Max area scales quadratically with optical zoom (area grows as zoom^2)
            effective_max_area = max(effective_min_area, int(self.max_area * (optical_zoom_factor ** 2)))
            min_fireline_thickness = 2.5 * (1.0 + 0.4 * self.current_zoom_ratio)
        else:
            effective_min_area = self.min_area
            effective_max_area = self.max_area
            min_fireline_thickness = 2.5

        # 1. Grayscale Conversion (represents thermal intensity)
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)

        # 2. Gaussian Blur to reduce sensor noise / single-pixel artifacts
        if self.blur_ksize > 1:
            k = self.blur_ksize if self.blur_ksize % 2 != 0 else self.blur_ksize + 1
            blurred = cv2.GaussianBlur(gray, (k, k), 0)
        else:
            blurred = gray

        # ----------------------------------------------------------------------
        # Method 2: Dynamic / Adaptive Saliency Thresholding (Sky-Aware)
        # ----------------------------------------------------------------------
        # Cold sky pixels (<= 20) distort terrain background statistics. Exclude sky if ground is prominent.
        ground_pixels = blurred[blurred > 20]
        if ground_pixels.size > 1000:
            mean_scene = float(np.mean(ground_pixels))
            std_scene = float(np.std(ground_pixels))
        else:
            mean_scene = float(np.mean(blurred))
            std_scene = float(np.std(blurred))

        if self.use_adaptive:
            # Hot targets must be significantly brighter than scene background
            dyn_thresh = int(mean_scene + self.adaptive_k * std_scene)
            # Threshold respects user configured base threshold and adapts upward when scene is hot (capped at 245)
            active_threshold = max(self.threshold, self.adaptive_min_threshold, min(245, dyn_thresh))
        else:
            active_threshold = self.threshold

        # Base Luminance Mask
        _, lum_mask = cv2.threshold(blurred, active_threshold, 255, cv2.THRESH_BINARY)

        # ----------------------------------------------------------------------
        # Method 1: White Top-Hat Morphological Filtering
        # Removes background gradient & AGC shift, isolates bright local anomalies
        # ----------------------------------------------------------------------
        if self.use_tophat:
            k_top = self.tophat_ksize if self.tophat_ksize % 2 != 0 else self.tophat_ksize + 1
            tophat_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k_top, k_top))
            tophat = cv2.morphologyEx(blurred, cv2.MORPH_TOPHAT, tophat_kernel)
            _, tophat_mask = cv2.threshold(tophat, self.tophat_threshold, 255, cv2.THRESH_BINARY)

            # Combined Heat Mask:
            # 1) Targets with prominent local contrast (tophat >= threshold) AND warm baseline
            # 2) OR intense absolute hotspots (lum_mask)
            baseline_warmth = max(140, active_threshold - 40)
            heat_mask = (tophat_mask & (blurred >= baseline_warmth)) | lum_mask
        else:
            heat_mask = lum_mask

        # 4. Morphological Dilation & Closing (Merges disjoint heat fragments into unified objects)
        if self.morph_kernel_size >= 1 and self.dilate_iterations > 0:
            k = max(3, self.morph_kernel_size)
            if k % 2 == 0:
                k += 1
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
            # Dilate to expand and bridge adjacent heat points
            dilated_mask = cv2.dilate(heat_mask, kernel, iterations=self.dilate_iterations)
            # Morphological close to fill any interior holes
            cleaned_mask = cv2.morphologyEx(dilated_mask, cv2.MORPH_CLOSE, kernel, iterations=1)
        else:
            cleaned_mask = heat_mask

        # 5. Contour Analysis
        contours, _ = cv2.findContours(cleaned_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        detections = []
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < effective_min_area or area > effective_max_area:
                continue

            # Bounding Box
            x, y, bw, bh = cv2.boundingRect(cnt)
            x1 = max(0, x)
            y1 = max(0, y)
            x2 = min(w, x + bw)
            y2 = min(h, y + bh)

            if x2 <= x1 or y2 <= y1:
                continue

            # Analyze ROI thermal properties
            roi_gray = gray[y1:y2, x1:x2]
            if roi_gray.size == 0:
                continue

            max_val = int(np.max(roi_gray))
            mean_val = float(np.mean(roi_gray))
            std_val = float(np.std(roi_gray))
            thermal_gradient = max_val - mean_val

            # True Physical Heat Geometry (Independent of Morphological Dilation):
            raw_hot_pixels = int(np.count_nonzero(roi_gray >= active_threshold))
            # Require at least 3 real hot pixels to eliminate single-pixel noise specks
            min_raw_pixels = max(3, int(effective_min_area * 0.2))
            if raw_hot_pixels < min_raw_pixels:
                continue
            aspect_ratio = max(bw / max(1.0, float(bh)), bh / max(1.0, float(bw)))
            max_span = max(1.0, float(max(bw, bh)))
            raw_thickness = raw_hot_pixels / max_span  # True physical thickness in pixels

            # Aspect Ratio & Fireline (แนวไฟป่า / Flaming Front) Handling:
            is_fireline = (aspect_ratio > 3.5) and (max_val >= 220 or thermal_gradient >= 28.0 or std_val >= 16.0) and (raw_thickness >= min_fireline_thickness)
            is_thin_wire_or_gutter = (aspect_ratio > 4.0) and (raw_thickness < min_fireline_thickness * 0.85) and (max_val < 235 and thermal_gradient < 30.0)

            if is_thin_wire_or_gutter:
                continue

            # Solar Heat Rejection: Flat/uniformly heated surfaces (sun-baked rocks, metal roofs)
            if not is_fireline and (thermal_gradient < 15.0 and std_val < 10.0 and max_val < 240):
                continue

            # Heat Confidence Calculation
            peak_norm = min(1.0, max(0.0, (max_val - active_threshold) / max(1.0, 255.0 - active_threshold)))
            gradient_norm = min(1.0, max(0.0, thermal_gradient / 80.0))
            score = round(0.40 + 0.40 * peak_norm + 0.20 * gradient_norm, 3)
            score = min(0.99, max(0.35, score))

            detections.append({
                "box": [x1, y1, x2, y2],
                "score": score,
                "label": "fire",
                "area": int(area),
                "max_val": max_val,
                "gradient": round(thermal_gradient, 1),
                "raw_hot_pixels": raw_hot_pixels,
                "active_threshold": active_threshold,
                "zoom_ratio": round(self.current_zoom_ratio, 2),
                "engine": "classic"
            })

        # ----------------------------------------------------------------------
        # Method 3: Canopy Clutter Storm Suppression (Foliage Density Filter)
        # ----------------------------------------------------------------------
        if self.use_clutter_suppression and len(detections) >= self.clutter_threshold:
            # When many candidate blobs appear simultaneously, this indicates solar heating across foliage.
            # Real wildfires are concentrated combustion sources; suppress scattered leaf glints.
            filtered_dets = []
            for d in detections:
                box_w = max(1, d["box"][2] - d["box"][0])
                box_h = max(1, d["box"][3] - d["box"][1])
                box_area = box_w * box_h
                core_ratio = d.get("raw_hot_pixels", 0) / float(box_area)

                # In clutter storm:
                # 1) Must have a concentrated core (core_ratio >= clutter_min_core_ratio)
                # 2) Must have substantial combustion mass (raw_hot_pixels >= clutter_min_hot_pixels)
                # 3) Must reach high thermal intensity
                # 4) Overly large diluted boxes (area > 900) created by bridging multiple leaves are pruned
                min_peak = max(245, self.threshold)
                if (core_ratio >= self.clutter_min_core_ratio and
                    d.get("raw_hot_pixels", 0) >= self.clutter_min_hot_pixels and
                    d["max_val"] >= min_peak and
                    box_area <= 900):
                    filtered_dets.append(d)
            detections = filtered_dets

        # Sort by score descending
        detections.sort(key=lambda d: (d["score"], d.get("area", 0)), reverse=True)
        return detections
