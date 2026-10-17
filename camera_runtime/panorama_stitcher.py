"""
Thermal Panorama Stitcher Module
Provides robust panorama stitching for Thermal PTZ imagery:
1. Positional Spherical / Equirectangular Projection (Guaranteed for thermal images with low texture)
   - Uses exact PTZ (Azimuth, Altitude) angles and camera FOV
   - Applies linear / distance-transform feather blending across the overlap region
2. Feature-based Stitcher fallback (OpenCV Stitcher with CLAHE thermal enhancement)
"""

import os
import math
import logging
from typing import List, Dict, Any, Tuple, Optional
import cv2
import numpy as np

logger = logging.getLogger("ThermalStitcher")


class ThermalPanoramaStitcher:
    """Stitches thermal frames into a seamless wide-angle or 360-degree panorama."""

    def __init__(self):
        pass

    @staticmethod
    def create_feather_mask(h: int, w: int, feather_pct: float = 0.15) -> np.ndarray:
        """
        Creates a 2D smooth feathering weight mask with values in [0.0, 1.0].
        Weights are 1.0 at center and smoothly fade to 0.0 at edges using a raised cosine.
        """
        fx = int(max(2, w * feather_pct))
        fy = int(max(2, h * feather_pct))

        ramp_x = np.ones(w, dtype=np.float32)
        ramp_x[:fx] = 0.5 * (1.0 - np.cos(np.linspace(0, np.pi, fx)))
        ramp_x[-fx:] = 0.5 * (1.0 - np.cos(np.linspace(np.pi, 0, fx)))

        ramp_y = np.ones(h, dtype=np.float32)
        ramp_y[:fy] = 0.5 * (1.0 - np.cos(np.linspace(0, np.pi, fy)))
        ramp_y[-fy:] = 0.5 * (1.0 - np.cos(np.linspace(np.pi, 0, fy)))

        return np.outer(ramp_y, ramp_x)

    def stitch_positional(
        self,
        frames_metadata: List[Dict[str, Any]],
        h_fov_deg: float,
        v_fov_deg: float,
        pixels_per_deg: Optional[float] = None,
        enable_alignment_refinement: bool = True
    ) -> Tuple[Optional[np.ndarray], Dict[str, Any]]:
        """
        Stitches frames using True Spherical/Equirectangular 3D Ray Projection:
        1. Projects pin-hole rectilinear perspective frames onto a 3D sphere coordinate system.
        2. Compensates for perspective distortion across wide viewing angles.
        3. Applies Sharp Cosine-Bell Distance Transform weighting to eliminate ghosting/double vision.
        4. Optionally refines adjacent frame offsets using Phase Correlation for sub-pixel accuracy.
        """
        if not frames_metadata:
            logger.error("No frames provided for positional stitching.")
            return None, {"error": "No frames provided"}

        # Read sample image to get sensor dimensions
        sample_img = None
        for item in frames_metadata:
            if os.path.exists(item.get("filepath", "")):
                sample_img = cv2.imread(item["filepath"])
                if sample_img is not None:
                    break

        if sample_img is None:
            logger.error("Could not load any frame image from disk.")
            return None, {"error": "Images not found on disk"}

        ih, iw = sample_img.shape[:2]

        # Camera Intrinsics
        fx = (iw / 2.0) / math.tan(math.radians(h_fov_deg / 2.0))
        fy = (ih / 2.0) / math.tan(math.radians(v_fov_deg / 2.0))
        cx = iw / 2.0
        cy = ih / 2.0

        # Automatic optimal resolution matching sensor pixel density
        if pixels_per_deg is None:
            pixels_per_deg = iw / h_fov_deg

        # Determine angular bounding box
        az_list = [f["az"] for f in frames_metadata]
        alt_list = [f["alt"] for f in frames_metadata]

        half_hfov = h_fov_deg * 0.55
        half_vfov = v_fov_deg * 0.55

        min_az = min(az_list) - half_hfov
        max_az = max(az_list) + half_hfov
        min_alt = min(alt_list) - half_vfov
        max_alt = max(alt_list) + half_vfov

        total_az_span = max(0.5, max_az - min_az)
        total_alt_span = max(0.5, max_alt - min_alt)

        canvas_w = int(round(total_az_span * pixels_per_deg))
        canvas_h = int(round(total_alt_span * pixels_per_deg))

        # Memory safety cap
        max_w, max_h = 10000, 5000
        if canvas_w > max_w or canvas_h > max_h:
            scale = min(max_w / canvas_w, max_h / canvas_h)
            pixels_per_deg *= scale
            canvas_w = int(round(total_az_span * pixels_per_deg))
            canvas_h = int(round(total_alt_span * pixels_per_deg))

        logger.info(
            f"Equirectangular Spherical Stitch: {len(frames_metadata)} frames onto canvas "
            f"{canvas_w}x{canvas_h} px (Scale: {pixels_per_deg:.1f} px/deg, fx={fx:.1f}, fy={fy:.1f})"
        )

        accum_bgr = np.zeros((canvas_h, canvas_w, 3), dtype=np.float32)
        accum_weight = np.zeros((canvas_h, canvas_w), dtype=np.float32)
        placed_count = 0

        # Establish a robust luminance reference from frame centers. Thermal
        # lenses often vignette asymmetrically; matching central medians before
        # feathering prevents a dark left edge from becoming a visible seam.
        frame_medians = []
        for item in frames_metadata:
            probe = cv2.imread(item.get("filepath", ""), cv2.IMREAD_GRAYSCALE)
            if probe is not None:
                ph, pw = probe.shape[:2]
                center = probe[ph // 4:3 * ph // 4, pw // 4:3 * pw // 4]
                frame_medians.append(float(np.median(center)))
        reference_median = float(np.median(frame_medians)) if frame_medians else 0.0

        # Optional Sub-pixel Alignment Refinement via Phase Correlation
        az_offsets = {i: 0.0 for i in range(len(frames_metadata))}
        alt_offsets = {i: 0.0 for i in range(len(frames_metadata))}

        if enable_alignment_refinement and len(frames_metadata) > 1:
            try:
                # Compare consecutive frames in the same row
                for i in range(len(frames_metadata) - 1):
                    f1 = frames_metadata[i]
                    f2 = frames_metadata[i + 1]
                    if f1.get("row") == f2.get("row") and os.path.exists(f1["filepath"]) and os.path.exists(f2["filepath"]):
                        im1_gray = cv2.imread(f1["filepath"], cv2.IMREAD_GRAYSCALE)
                        im2_gray = cv2.imread(f2["filepath"], cv2.IMREAD_GRAYSCALE)
                        if im1_gray is not None and im2_gray is not None:
                            d_az_deg = abs(f2["az"] - f1["az"])
                            overlap_deg = max(0.5, h_fov_deg - d_az_deg)
                            ov_px = int(min(iw * 0.45, max(30, (overlap_deg / h_fov_deg) * iw)))

                            if f2["az"] > f1["az"]:
                                roi1 = im1_gray[:, -ov_px:].astype(np.float32)
                                roi2 = im2_gray[:, :ov_px].astype(np.float32)
                            else:
                                roi1 = im1_gray[:, :ov_px].astype(np.float32)
                                roi2 = im2_gray[:, -ov_px:].astype(np.float32)

                            shift, conf = cv2.phaseCorrelate(roi1, roi2)
                            # Only apply if confidence is strong and shift is reasonable (< 25px)
                            if conf > 0.25 and abs(shift[0]) < 25.0 and abs(shift[1]) < 15.0:
                                delta_az = (shift[0] / iw) * h_fov_deg * 0.5
                                delta_alt = (-shift[1] / ih) * v_fov_deg * 0.5
                                az_offsets[i + 1] = az_offsets[i] + delta_az
                                alt_offsets[i + 1] = alt_offsets[i] + delta_alt
            except Exception as ex:
                logger.warning(f"Alignment refinement note: {ex}")

        # Map each frame using 3D Spherical Coordinate Remapping
        for idx, item in enumerate(frames_metadata):
            path = item.get("filepath")
            if not path or not os.path.exists(path):
                continue

            img = cv2.imread(path)
            if img is None:
                continue

            if reference_median > 1.0:
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                gh, gw = gray.shape[:2]
                current_median = float(np.median(gray[gh // 4:3 * gh // 4, gw // 4:3 * gw // 4]))
                if current_median > 1.0:
                    gain = float(np.clip(reference_median / current_median, 0.8, 1.25))
                    img = cv2.convertScaleAbs(img, alpha=gain, beta=0)

                # Correct the repeatable left/right lens shading before warp.
                # A vertically robust, heavily smoothed column profile ignores
                # most compact hot targets. The optical centre is deliberately
                # left unchanged; compensation increases gradually toward the
                # edges where Thermal vignetting creates visible tile bands.
                flat_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
                vertical_band = flat_gray[gh // 5:4 * gh // 5]
                column_profile = np.median(vertical_band, axis=0).astype(np.float32)
                smooth_kernel = max(9, (gw // 10) | 1)
                column_profile = cv2.GaussianBlur(
                    column_profile.reshape(1, -1),
                    (smooth_kernel, 1),
                    0,
                ).reshape(-1)
                centre_profile = column_profile[gw * 2 // 5:gw * 3 // 5]
                flat_reference = float(np.median(centre_profile)) if centre_profile.size else 0.0
                if flat_reference > 1.0:
                    column_gain = np.clip(
                        flat_reference / np.maximum(column_profile, 1.0),
                        0.78,
                        1.28,
                    )
                    edge_position = np.abs(np.linspace(-1.0, 1.0, gw, dtype=np.float32)) ** 1.5
                    column_gain = 1.0 + (column_gain - 1.0) * edge_position
                    img = np.clip(
                        img.astype(np.float32) * column_gain[np.newaxis, :, np.newaxis],
                        0,
                        255,
                    ).astype(np.uint8)

            frame_az = item["az"] + az_offsets.get(idx, 0.0)
            frame_alt = item["alt"] + alt_offsets.get(idx, 0.0)

            # Sub-canvas bounding region for this frame
            sub_az_min = frame_az - half_hfov
            sub_az_max = frame_az + half_hfov
            sub_alt_min = frame_alt - half_vfov
            sub_alt_max = frame_alt + half_vfov

            x0 = max(0, int(math.floor((sub_az_min - min_az) * pixels_per_deg)))
            x1 = min(canvas_w, int(math.ceil((sub_az_max - min_az) * pixels_per_deg)))
            y0 = max(0, int(math.floor((max_alt - sub_alt_max) * pixels_per_deg)))
            y1 = min(canvas_h, int(math.ceil((max_alt - sub_alt_min) * pixels_per_deg)))

            sub_w = x1 - x0
            sub_h = y1 - y0
            if sub_w <= 0 or sub_h <= 0:
                continue

            # Equirectangular coordinates for sub-grid
            px_indices = np.arange(x0, x1)
            py_indices = np.arange(y0, y1)

            az_grid = min_az + px_indices / pixels_per_deg
            alt_grid = max_alt - py_indices / pixels_per_deg

            az_mesh, alt_mesh = np.meshgrid(az_grid, alt_grid)

            # Angular delta to camera optical center
            d_az = np.radians(az_mesh - frame_az)
            d_alt = np.radians(alt_mesh - frame_alt)

            # 3D Direction Vector
            z_c = np.cos(d_alt) * np.cos(d_az)
            valid_ray = z_c > 0.05

            x_c = np.cos(d_alt) * np.sin(d_az)
            y_c = -np.sin(d_alt)

            # Pin-hole projection coordinates (u, v) on camera sensor
            denom = np.maximum(z_c, 1e-6)
            u = fx * (x_c / denom) + cx
            v = fy * (y_c / denom) + cy

            valid_mask = valid_ray & (u >= 0) & (u < iw - 1) & (v >= 0) & (v < ih - 1)

            # Sharp Cosine-Bell Distance Transform Weighting (Zero-Ghosting)
            du = np.minimum(u, iw - 1 - u) / (iw / 2.0)
            dv = np.minimum(v, ih - 1 - v) / (ih / 2.0)
            dist_norm = np.clip(np.minimum(du, dv), 0.0, 1.0)

            # Raised cosine bell with exponent to strongly favor image center over edges
            w_map = (np.sin(dist_norm * (np.pi / 2.0))) ** 3
            w_map[~valid_mask] = 0.0

            # Bilinear image remapping
            warped = cv2.remap(
                img,
                u.astype(np.float32),
                v.astype(np.float32),
                cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_CONSTANT,
                borderValue=(0, 0, 0)
            )

            # Match the newly projected frame to pixels already present in the
            # overlap. Apply the correction mostly near lens edges so the
            # thermal palette at the optical centre remains authoritative.
            # This compensates the common darker-left/brighter-right vignette
            # without flattening real hot objects in the middle of a frame.
            existing_weight = accum_weight[y0:y1, x0:x1]
            overlap_mask = valid_mask & (w_map > 0.03) & (existing_weight > 0.03)
            if np.count_nonzero(overlap_mask) >= 512:
                existing = np.zeros_like(warped, dtype=np.float32)
                weighted = accum_bgr[y0:y1, x0:x1]
                safe_weight = np.maximum(existing_weight, 1e-6)
                existing[:] = weighted / safe_weight[:, :, np.newaxis]
                source_gray = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY).astype(np.float32)
                existing_gray = cv2.cvtColor(
                    np.clip(existing, 0, 255).astype(np.uint8),
                    cv2.COLOR_BGR2GRAY,
                ).astype(np.float32)
                source_samples = source_gray[overlap_mask]
                target_samples = existing_gray[overlap_mask]
                source_q25, source_med, source_q75 = np.percentile(source_samples, (25, 50, 75))
                target_q25, target_med, target_q75 = np.percentile(target_samples, (25, 50, 75))
                source_iqr = max(1.0, float(source_q75 - source_q25))
                target_iqr = max(1.0, float(target_q75 - target_q25))
                overlap_gain = float(np.clip(target_iqr / source_iqr, 0.78, 1.28))
                overlap_bias = float(np.clip(target_med - overlap_gain * source_med, -28.0, 28.0))
                edge_strength = np.clip(1.0 - dist_norm, 0.0, 1.0)[:, :, np.newaxis]
                local_gain = 1.0 + (overlap_gain - 1.0) * edge_strength
                local_bias = overlap_bias * edge_strength
                warped = np.clip(
                    warped.astype(np.float32) * local_gain + local_bias,
                    0,
                    255,
                ).astype(np.uint8)

            # Accumulate weighted color and weight sum
            accum_bgr[y0:y1, x0:x1] += warped.astype(np.float32) * w_map[:, :, np.newaxis]
            accum_weight[y0:y1, x0:x1] += w_map

            placed_count += 1

        # Normalize by total accumulated weight
        valid_pixels = accum_weight > 1e-4
        result = np.zeros((canvas_h, canvas_w, 3), dtype=np.uint8)

        for c in range(3):
            ch = np.zeros((canvas_h, canvas_w), dtype=np.float32)
            ch[valid_pixels] = accum_bgr[valid_pixels, c] / accum_weight[valid_pixels]
            result[:, :, c] = np.clip(ch, 0, 255).astype(np.uint8)

        # Remove residual frame-period brightness bands without blurring scene
        # detail. A robust median is measured down each valid panorama column;
        # only variations faster than roughly two frame widths are corrected.
        # Slow illumination changes across the real scene remain intact.
        valid_columns = np.flatnonzero(np.any(valid_pixels, axis=0))
        if valid_columns.size >= 3:
            result_gray = cv2.cvtColor(result, cv2.COLOR_BGR2GRAY)
            column_level = np.full(canvas_w, np.nan, dtype=np.float32)
            for column in valid_columns:
                samples = result_gray[valid_pixels[:, column], column]
                if samples.size:
                    column_level[column] = float(np.median(samples))
            measured = np.flatnonzero(np.isfinite(column_level) & (column_level > 1.0))
            if measured.size >= 3:
                interpolated = np.interp(
                    np.arange(canvas_w, dtype=np.float32),
                    measured.astype(np.float32),
                    column_level[measured],
                ).astype(np.float32)
                frame_width_px = max(9, int(round(h_fov_deg * pixels_per_deg)))
                smooth_kernel = min(canvas_w if canvas_w % 2 else canvas_w - 1, frame_width_px * 3 | 1)
                if smooth_kernel >= 3:
                    smooth_level = cv2.GaussianBlur(
                        interpolated.reshape(1, -1),
                        (smooth_kernel, 1),
                        0,
                    ).reshape(-1)
                    residual_gain = np.clip(
                        smooth_level / np.maximum(interpolated, 1.0),
                        0.85,
                        1.18,
                    )
                    corrected = np.clip(
                        result.astype(np.float32) * residual_gain[np.newaxis, :, np.newaxis],
                        0,
                        255,
                    ).astype(np.uint8)
                    result[valid_pixels] = corrected[valid_pixels]

        # Auto-crop black empty borders
        non_zero = np.where(valid_pixels)
        if len(non_zero[0]) > 0:
            min_r, max_r = int(np.min(non_zero[0])), int(np.max(non_zero[0]))
            min_c, max_c = int(np.min(non_zero[1])), int(np.max(non_zero[1]))
            result_cropped = result[min_r:max_r+1, min_c:max_c+1]
        else:
            result_cropped = result

        stats = {
            "method": "spherical_ray_warp",
            "canvas_width": result_cropped.shape[1],
            "canvas_height": result_cropped.shape[0],
            "total_frames": len(frames_metadata),
            "placed_frames": placed_count,
            "az_range": [round(min_az, 2), round(max_az, 2)],
            "alt_range": [round(min_alt, 2), round(max_alt, 2)],
            "pixels_per_deg": round(pixels_per_deg, 2),
            "photometric_normalization": "center_median+column_flat_field+overlap_gain_bias_edge_compensation+cosine_feather+panorama_column_equalization",
        }

        return result_cropped, stats

    def stitch_feature_based(
        self,
        image_paths: List[str]
    ) -> Tuple[Optional[np.ndarray], Dict[str, Any]]:
        """
        Attempts feature-based panorama stitching using OpenCV Stitcher.
        Applies CLAHE (Contrast Limited Adaptive Histogram Equalization) to assist thermal features.
        """
        images = []
        for p in image_paths:
            if os.path.exists(p):
                img = cv2.imread(p)
                if img is not None:
                    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
                    l, a, b = cv2.split(lab)
                    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
                    cl = clahe.apply(l)
                    enhanced = cv2.cvtColor(cv2.merge((cl, a, b)), cv2.COLOR_LAB2BGR)
                    images.append(enhanced)

        if len(images) < 2:
            return None, {"error": "Need at least 2 images for feature stitching"}

        try:
            stitcher = cv2.Stitcher_create(cv2.Stitcher_PANORAMA)
            status, stitched = stitcher.stitch(images)
            if status == cv2.Stitcher_OK and stitched is not None:
                return stitched, {
                    "method": "opencv_features",
                    "status": "OK",
                    "width": stitched.shape[1],
                    "height": stitched.shape[0]
                }
            else:
                return None, {"error": f"OpenCV stitcher failed with status code {status}"}
        except Exception as e:
            logger.warning(f"Feature stitcher exception: {e}")
            return None, {"error": str(e)}
