"""
Integrated Fire Detection & Automated PTZ Surveillance Server
Combines:
- Multi-threaded NCNN AI (10 Hz / 0.1s rate, ~87ms latency)
- Dual Live RTSP Video Feeds (Thermal + Visible/RGB)
- Kalman Filter Verification & Thermal Core Analysis with Alarm Persistence
- PTZ Sweep Control & Master Mission Controller (Autonomous Sentry Workflow)
- Unified Glassmorphism Operations Dashboard (Port 5005)
"""

import os
import sys
import time
import threading
import logging
import io
import json
from pathlib import Path
from typing import Optional, List, Dict, Any

import cv2
import numpy as np
import ncnn
from flask import Flask, render_template, Response, jsonify, request, send_file, send_from_directory

# Add local path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

import config
from camera_manager import CameraManager
from ptz_controller import PTZController
from fire_verifier import ThermalFireVerifier
from mission_controller import MissionController, MissionState
from thermal_detector import ClassicThermalDetector
from frame_publisher import FramePublisher
from thermal_panorama_engine import ThermalPanoramaEngine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("IntegratedServer")

# Suppress repetitive 200 OK access logs for /api/telemetry polling
class TelemetryLogFilter(logging.Filter):
    def filter(self, record):
        msg = record.getMessage()
        return not ("/api/telemetry" in msg and " 200 " in msg)

logging.getLogger("werkzeug").addFilter(TelemetryLogFilter())

app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "templates"),
    static_folder=str(BASE_DIR / "static")
)
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.jinja_env.auto_reload = True
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

# ==============================================================================
# Global Subsystems Initialization
# ==============================================================================
camera_mgr = CameraManager(config.CAMERAS)
ptz_ctrl = PTZController(
    host=config.MOUNT["tcp_host"],
    port=config.MOUNT["tcp_port"],
    fallback_sim=config.MOUNT["use_simulator_fallback"]
)
fire_verifier = ThermalFireVerifier(
    iou_threshold=config.AI_CONFIG["iou_match_threshold"],
    max_age=config.AI_CONFIG["alarm_hold_cycles"],
    min_hits=config.AI_CONFIG["min_verification_hits"],
    confirmed_hold_cycles=config.AI_CONFIG["alarm_hold_cycles"],
    thermal_core_min_val=config.AI_CONFIG.get("thermal_core_min_val", 190),
    hotspot_threshold=config.AI_CONFIG.get("hotspot_threshold", 190)
)
classic_detector = ClassicThermalDetector(
    threshold=config.AI_CONFIG.get("hotspot_threshold", 190),
    min_area=config.AI_CONFIG.get("min_hotspot_area", 15),
    max_area=config.AI_CONFIG.get("max_hotspot_area", 40000),
    morph_kernel_size=config.AI_CONFIG.get("morph_kernel_size", 5),
    dilate_iterations=config.AI_CONFIG.get("dilate_iterations", 2),
    blur_ksize=config.AI_CONFIG.get("blur_ksize", 3),
    use_tophat=config.AI_CONFIG.get("use_tophat", True),
    tophat_ksize=config.AI_CONFIG.get("tophat_ksize", 15),
    tophat_threshold=config.AI_CONFIG.get("tophat_threshold", 35),
    use_adaptive=config.AI_CONFIG.get("use_adaptive", True),
    adaptive_k=config.AI_CONFIG.get("adaptive_k", 3.0),
    adaptive_min_threshold=config.AI_CONFIG.get("adaptive_min_threshold", 170),
    zoom_aware=config.AI_CONFIG.get("zoom_aware", True),
    min_focal_mm=config.CAMERAS["thermal"].get("min_focal_mm", 31.0),
    max_focal_mm=config.CAMERAS["thermal"].get("max_focal_mm", 155.0),
    use_clutter_suppression=config.AI_CONFIG.get("use_clutter_suppression", True),
    clutter_threshold=config.AI_CONFIG.get("clutter_threshold", 8),
    clutter_min_core_ratio=config.AI_CONFIG.get("clutter_min_core_ratio", 0.035)
)
mission_ctrl = MissionController(
    camera_mgr=camera_mgr,
    ptz_ctrl=ptz_ctrl,
    fire_verifier=fire_verifier,
    cfg={**config.MISSION_CONFIG, "incident": config.INCIDENT_CONFIG, "telegram": config.TELEGRAM_CONFIG, "llm": config.LLM_CONFIG}
)
panorama_engine = ThermalPanoramaEngine(
    camera_mgr=camera_mgr,
    ptz_ctrl=ptz_ctrl,
    base_dir=BASE_DIR
)
# Application Real-time State
state = {
    "running": True,
    "thermal_fps": 0.0,
    "visible_fps": 0.0,
    "latency_ms": 5.0,
    "detections": [],
    "fire_detected": False,
    "confirmed_count": 0,
    "verifying_count": 0,
    "pending_count": 0,
    "total_frames": 0,
    "detector_engine": config.AI_CONFIG.get("detector_engine", "CLASSIC_THERMAL"),
    "hotspot_threshold": config.AI_CONFIG.get("hotspot_threshold", 190),
    "min_hotspot_area": config.AI_CONFIG.get("min_hotspot_area", 15),
    "max_hotspot_area": config.AI_CONFIG.get("max_hotspot_area", 40000),
    "morph_kernel_size": config.AI_CONFIG.get("morph_kernel_size", 5),
    "dilate_iterations": config.AI_CONFIG.get("dilate_iterations", 2),
    "blur_ksize": config.AI_CONFIG.get("blur_ksize", 3),
    "use_tophat": config.AI_CONFIG.get("use_tophat", True),
    "use_adaptive": config.AI_CONFIG.get("use_adaptive", True),
    "zoom_aware": config.AI_CONFIG.get("zoom_aware", True),
    "ai_engine": "Classic Thermal Hotspot" if config.AI_CONFIG.get("detector_engine", "CLASSIC_THERMAL") == "CLASSIC_THERMAL" else "NCNN YOLO26n",
    "conf_threshold": config.AI_CONFIG["conf_threshold"],
    "infer_interval_sec": config.AI_CONFIG["infer_interval_sec"],
    "capture_az_step": config.AI_CONFIG.get("capture_az_step", 5.0),
    "trigger_mode": config.AI_CONFIG.get("trigger_mode", "FIXED_INTERVAL"),
    "last_infer_az": None,
    "trigger_count": 0,
    "use_kalman_filter": True,
    "show_boxes": True,
    "show_hud": True
}

frame_publisher = FramePublisher(
    camera_mgr=camera_mgr,
    cfg=config.FRAME_PUBLISHER,
    ptz_ctrl=ptz_ctrl,
    mission_ctrl=mission_ctrl,
    state=state
)

active_detections = []
detections_lock = threading.Lock()


# ==============================================================================
# Fast NMS Postprocessing
# ==============================================================================
def nms_boxes(boxes: np.ndarray, scores: np.ndarray, iou_thresh: float) -> List[int]:
    if len(boxes) == 0:
        return []
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = (x2 - x1) * (y2 - y1)
    order = scores.argsort()[::-1]

    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(i)
        if order.size == 1:
            break
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])

        w = np.maximum(0.0, xx2 - xx1)
        h = np.maximum(0.0, yy2 - yy1)
        inter = w * h
        ovr = inter / (areas[i] + areas[order[1:]] - inter)

        inds = np.where(ovr <= iou_thresh)[0]
        order = order[inds + 1]
    return keep


# ==============================================================================
# Thermal & AI Detection Worker Thread (Classic Hotspot / NCNN YOLO / Hybrid)
# ==============================================================================
def ncnn_ai_worker():
    global active_detections, state, fire_verifier, classic_detector

    net = None
    try:
        param_path = config.AI_CONFIG["model_param"]
        bin_path = config.AI_CONFIG["model_bin"]
        net = ncnn.Net()
        net.opt.use_vulkan_compute = False
        net.opt.num_threads = 4
        if net.load_param(param_path) != 0 or net.load_model(bin_path) != 0:
            logger.warning("[Detector Worker] NCNN model files not loaded; AI_NCNN mode will be unavailable.")
            net = None
        else:
            logger.info("[Detector Worker] NCNN model loaded successfully.")
    except Exception as e:
        logger.warning(f"[Detector Worker] NCNN init error: {e}")
        net = None

    logger.info(
        f"[Detector Worker] Detection Engine Ready! "
        f"(Engine: {state['detector_engine']}, Trigger: {state['trigger_mode']} @ {state['infer_interval_sec']}s)"
    )
    mean_vals = [0.0, 0.0, 0.0]
    norm_vals = [1.0 / 255.0, 1.0 / 255.0, 1.0 / 255.0]

    thermal_cam = camera_mgr.get_thermal_camera()
    last_infer_az = None
    last_infer_time = 0.0

    while state["running"]:
        try:
            # 1. Check if Detection is manually stopped or Mission Controller paused it (e.g. during lens zooming)
            m_state = mission_ctrl.state
            is_lens_moving = mission_ctrl.is_ai_paused or m_state in ("ZOOMING_IN", "ZOOMING_OUT", "VERIFYING_FOCUS", "PREPARING_OPTICS")
            if not state.get("ai_enabled", True) or is_lens_moving:
                fire_verifier.reset()
                with detections_lock:
                    active_detections = []
                state["active_detections"] = []
                state["fire_detected"] = False
                state["confirmed_count"] = 0
                state["verifying_count"] = 0
                time.sleep(0.05)
                continue

            # 2. Check Trigger Conditions
            is_deep_verify = m_state in ("TARGET_CENTERING", "DEEP_CONFIRMATION", "ALARM_ACTIVE", "STEP_DWELLING")
            trigger_mode = state.get("trigger_mode", "FIXED_INTERVAL")
            az_step = max(0.5, float(state.get("capture_az_step", 5.0)))
            now = time.time()

            should_infer = False

            if is_deep_verify or trigger_mode == "FIXED_INTERVAL":
                # Deep Confirmation / Dwelling / Fixed mode: periodic check
                if now - last_infer_time >= state.get("infer_interval_sec", 0.2):
                    should_infer = True
            else:
                # Azimuth Step Trigger Mode: Trigger whenever PTZ moves >= az_step
                cur_az, _ = ptz_ctrl.get_position()
                if last_infer_az is None:
                    should_infer = True
                    last_infer_az = cur_az
                else:
                    d_az = abs(cur_az - last_infer_az)
                    if d_az >= az_step:
                        should_infer = True
                        last_infer_az = cur_az

            if not should_infer:
                time.sleep(0.01)
                continue

            last_infer_time = now

            if thermal_cam:
                frame, _ = thermal_cam.get_latest_frame()
                if frame is not None:
                    orig_h, orig_w = frame.shape[:2]
                    engine = state.get("detector_engine", "CLASSIC_THERMAL")
                    raw_dets = []
                    t0 = time.perf_counter()

                    # A. Classic Thermal Hotspot Detection (Fast & Deterministic)
                    if engine in ("CLASSIC_THERMAL", "HYBRID"):
                        zoom_ratio = getattr(thermal_cam, "current_zoom_ratio", 0.0)
                        classic_dets = classic_detector.detect(frame, zoom_ratio=zoom_ratio)
                        raw_dets.extend(classic_dets)

                    # B. Deep Learning AI NCNN Detection
                    if engine in ("AI_NCNN", "HYBRID") and net is not None:
                        scale_x = orig_w / 640.0
                        scale_y = orig_h / 640.0

                        in_mat = ncnn.Mat.from_pixels_resize(
                            frame,
                            ncnn.Mat.PixelType.PIXEL_BGR2RGB,
                            orig_w, orig_h,
                            640, 640
                        )
                        in_mat.substract_mean_normalize(mean_vals, norm_vals)

                        ex = net.create_extractor()
                        ex.input("in0", in_mat)
                        _, out_mat = ex.extract("out0")

                        out_arr = np.array(out_mat)
                        if out_arr.ndim == 2 and out_arr.shape[0] == 5:
                            out_arr = out_arr.T

                        conf_thresh = state["conf_threshold"]
                        ai_boxes, ai_scores = [], []

                        for row in out_arr:
                            score = float(row[4])
                            if score >= conf_thresh:
                                cx, cy, w, h = float(row[0]), float(row[1]), float(row[2]), float(row[3])
                                x1 = max(0, min(orig_w, (cx - w / 2.0) * scale_x))
                                y1 = max(0, min(orig_h, (cy - h / 2.0) * scale_y))
                                x2 = max(0, min(orig_w, (cx + w / 2.0) * scale_x))
                                y2 = max(0, min(orig_h, (cy + h / 2.0) * scale_y))
                                ai_boxes.append([x1, y1, x2, y2])
                                ai_scores.append(score)

                        ai_boxes = np.array(ai_boxes) if ai_boxes else np.empty((0, 4))
                        ai_scores = np.array(ai_scores) if ai_scores else np.empty((0,))

                        keep_indices = nms_boxes(ai_boxes, ai_scores, config.AI_CONFIG["nms_threshold"])
                        for idx in keep_indices:
                            b = ai_boxes[idx].astype(int)
                            raw_dets.append({
                                "box": b.tolist(),
                                "score": round(float(ai_scores[idx]), 3),
                                "label": "fire",
                                "engine": "ncnn"
                            })

                    latency_ms = (time.perf_counter() - t0) * 1000.0

                    cur_az, cur_alt = ptz_ctrl.get_position()
                    now_ts = time.time()

                    # Retrieve Thermal FOV for motion compensation
                    th_zoom = thermal_cam.get_zoom_info() if thermal_cam else {"fov_h": 5.89, "fov_v": 4.72}
                    fov_h = float(th_zoom.get("fov_h", 5.89))
                    fov_v = float(th_zoom.get("fov_v", 4.72))

                    # Kalman Verification with Motion Compensation and World-Coordinate Tracking
                    if state["use_kalman_filter"]:
                        processed_dets = fire_verifier.update(
                            raw_dets,
                            frame_bgr=frame,
                            ptz_pos=(cur_az, cur_alt),
                            fov=(fov_h, fov_v)
                        )
                    else:
                        processed_dets = [
                            {"id": idx, "box": d["box"], "score": d["score"], "state": "CONFIRMED_FIRE", "label": "fire"}
                            for idx, d in enumerate(raw_dets)
                        ]

                    for d in processed_dets:
                        d["timestamp"] = now_ts
                        d["azimuth"] = cur_az
                        d["altitude"] = cur_alt

                    with detections_lock:
                        active_detections = processed_dets

                    confirmed = sum(1 for d in processed_dets if d.get("state") == "CONFIRMED_FIRE")
                    verifying = sum(1 for d in processed_dets if d.get("state") == "VERIFYING")
                    pending = sum(1 for d in processed_dets if d.get("state") == "PENDING")

                    state["latency_ms"] = round(max(2.0, latency_ms), 1)
                    state["detections"] = processed_dets
                    state["confirmed_count"] = confirmed
                    state["verifying_count"] = verifying
                    state["pending_count"] = pending
                    state["fire_detected"] = (confirmed > 0)
                    state["total_frames"] += 1
                    state["last_infer_az"] = cur_az
                    state["trigger_count"] = state.get("trigger_count", 0) + 1
        except Exception as e:
            logger.error(f"[Detector Worker] Unexpected inference loop error: {e}", exc_info=True)
            time.sleep(0.05)

        time.sleep(0.01)


# ==============================================================================
# Video Annotation & Overlays
# ==============================================================================
def draw_thermal_overlays(frame: np.ndarray, detections: list) -> np.ndarray:
    out = frame.copy()
    h, w = out.shape[:2]

    # Draw boxes
    for det in detections:
        x1, y1, x2, y2 = det["box"]
        score = det["score"]
        track_state = det.get("state", "CONFIRMED_FIRE")
        is_held = det.get("is_held", False)

        if track_state == "CONFIRMED_FIRE":
            box_color = (0, 30, 255)  # Bright Fire Red
            label = f" HOTSPOT HOLD {score*100:.1f}% " if is_held else f" HOTSPOT {score*100:.1f}% "
        elif track_state == "VERIFYING":
            box_color = (0, 140, 255)  # Orange
            label = f" VERIFYING {score*100:.1f}% "
        else:
            box_color = (0, 220, 255)  # Yellow
            label = f" PENDING {score*100:.1f}% "

        cv2.rectangle(out, (x1, y1), (x2, y2), box_color, 2, cv2.LINE_AA)

        # Tactical corners
        clen = min(14, max(4, (x2 - x1) // 4))
        cv2.line(out, (x1, y1), (x1 + clen, y1), (255, 255, 255), 2)
        cv2.line(out, (x1, y1), (x1, y1 + clen), (255, 255, 255), 2)
        cv2.line(out, (x2, y2), (x2 - clen, y2), (255, 255, 255), 2)
        cv2.line(out, (x2, y2), (x2, y2 - clen), (255, 255, 255), 2)

        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
        tag_y = max(th + 6, y1 - 6)
        cv2.rectangle(out, (x1, tag_y - th - 4), (x1 + tw, tag_y + 4), (0, 0, 0), -1)
        cv2.rectangle(out, (x1, tag_y - th - 4), (x1 + tw, tag_y + 4), box_color, 1)
        cv2.putText(out, label, (x1, tag_y - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)

    return out


def get_current_detections() -> list:
    """Returns a snapshot of active AI detections for frame publishing and overlays."""
    with detections_lock:
        return list(active_detections)


# Connect frame publisher with AI detection bounding box overlays
frame_publisher.get_detections_fn = get_current_detections
frame_publisher.overlay_fn = draw_thermal_overlays
# Flask Streaming Endpoints (Optimized for Tailscale / 4G VPN Low Latency)
# ==============================================================================
def resolve_stream_params(mode: Optional[str], req_fps: Optional[float], req_quality: Optional[int], req_width: Optional[int], is_thermal: bool = False):
    cfg = config.STREAMING_CONFIG
    mode_str = (mode or cfg.get("bandwidth_mode", "4G_SAVER")).upper()

    if mode_str in ("4G", "4G_SAVER", "SAVER", "LOW"):
        fps = 6.0
        quality = 50
        max_w = 640
    elif mode_str in ("EXTREME", "EXTREME_SAVER", "ULTRA_LOW"):
        fps = 4.0
        quality = 40
        max_w = 480
    elif mode_str in ("BALANCED", "MID"):
        fps = 10.0
        quality = 60
        max_w = 800 if not is_thermal else 640
    elif mode_str in ("LAN", "LAN_HIGH", "HIGH", "MAX"):
        fps = 15.0
        quality = 75
        max_w = 0  # 0 means full resolution
    else:
        fps = float(cfg.get("stream_fps", 6.0))
        quality = int(cfg.get("jpeg_quality", 50))
        max_w = int(cfg.get("thermal_max_width" if is_thermal else "visible_max_width", 640))

    if req_fps is not None and req_fps > 0:
        fps = float(req_fps)
    if req_quality is not None and req_quality > 0:
        quality = int(req_quality)
    if req_width is not None:
        max_w = int(req_width)

    return fps, quality, max_w


def build_mjpeg_part(camera_id: str, jpeg_bytes: bytes, snapshot: Optional[dict] = None) -> bytes:
    """Attach the frame metadata header to each MJPEG part shown in Camera View."""
    metadata = (
        frame_publisher.build_camera_metadata(camera_id, snapshot)
        if snapshot
        else frame_publisher.get_camera_metadata(camera_id)
    )
    metadata_json = json.dumps(metadata or {}, separators=(",", ":"), ensure_ascii=True)
    headers = (
        "--frame\r\n"
        "Content-Type: image/jpeg\r\n"
        f"Content-Length: {len(jpeg_bytes)}\r\n"
        f"X-Camera-Metadata: {metadata_json}\r\n\r\n"
    ).encode("ascii")
    return headers + jpeg_bytes + b"\r\n"


def gen_thermal_frames(fps: float = 6.0, quality: int = 50, max_width: int = 640):
    thermal_cam = camera_mgr.get_thermal_camera()
    interval = 1.0 / max(1.0, min(30.0, fps))
    encode_params = [cv2.IMWRITE_JPEG_QUALITY, max(20, min(95, quality))]

    while True:
        t0 = time.monotonic()
        if thermal_cam:
            snapshot = thermal_cam.get_latest_frame_snapshot()
            frame = snapshot.get("bgr") if snapshot else None
            raw_jpeg = snapshot.get("jpeg") if snapshot else None
            if frame is not None:
                with detections_lock:
                    valid_dets = list(active_detections)

                if len(valid_dets) > 0:
                    annotated = draw_thermal_overlays(frame, valid_dets)
                    if max_width > 0 and annotated.shape[1] > max_width:
                        scale = max_width / float(annotated.shape[1])
                        new_h = int(annotated.shape[0] * scale)
                        annotated = cv2.resize(annotated, (max_width, new_h), interpolation=cv2.INTER_AREA)
                    ret, jpeg = cv2.imencode('.jpg', annotated, encode_params)
                    if ret:
                        yield build_mjpeg_part("thermal", jpeg.tobytes(), snapshot)
                elif max_width > 0 and frame.shape[1] > max_width:
                    scale = max_width / float(frame.shape[1])
                    new_h = int(frame.shape[0] * scale)
                    resized = cv2.resize(frame, (max_width, new_h), interpolation=cv2.INTER_AREA)
                    ret, jpeg = cv2.imencode('.jpg', resized, encode_params)
                    if ret:
                        yield build_mjpeg_part("thermal", jpeg.tobytes(), snapshot)
                elif quality <= 65:
                    ret, jpeg = cv2.imencode('.jpg', frame, encode_params)
                    if ret:
                        yield build_mjpeg_part("thermal", jpeg.tobytes(), snapshot)
                elif raw_jpeg is not None:
                    yield build_mjpeg_part("thermal", raw_jpeg, snapshot)
            elif raw_jpeg is not None:
                yield build_mjpeg_part("thermal", raw_jpeg, snapshot)

        # Zero-lag pacing: Dynamically sleep remainder of frame interval
        elapsed = time.monotonic() - t0
        sleep_time = max(0.005, interval - elapsed)
        time.sleep(sleep_time)


def gen_visible_frames(fps: float = 6.0, quality: int = 50, max_width: int = 640):
    visible_cam = camera_mgr.get_visible_camera()
    interval = 1.0 / max(1.0, min(30.0, fps))
    encode_params = [cv2.IMWRITE_JPEG_QUALITY, max(20, min(95, quality))]

    while True:
        t0 = time.monotonic()
        if visible_cam:
            snapshot = visible_cam.get_latest_frame_snapshot()
            frame = snapshot.get("bgr") if snapshot else None
            raw_jpeg = snapshot.get("jpeg") if snapshot else None
            if frame is not None:
                if max_width > 0 and frame.shape[1] > max_width:
                    scale = max_width / float(frame.shape[1])
                    new_h = int(frame.shape[0] * scale)
                    resized = cv2.resize(frame, (max_width, new_h), interpolation=cv2.INTER_AREA)
                    ret, jpeg = cv2.imencode('.jpg', resized, encode_params)
                    if ret:
                        yield build_mjpeg_part("visible", jpeg.tobytes(), snapshot)
                elif quality <= 65 or max_width > 0:
                    ret, jpeg = cv2.imencode('.jpg', frame, encode_params)
                    if ret:
                        yield build_mjpeg_part("visible", jpeg.tobytes(), snapshot)
                elif raw_jpeg is not None:
                    yield build_mjpeg_part("visible", raw_jpeg, snapshot)
            elif raw_jpeg is not None:
                yield build_mjpeg_part("visible", raw_jpeg, snapshot)

        # Zero-lag pacing
        elapsed = time.monotonic() - t0
        sleep_time = max(0.005, interval - elapsed)
        time.sleep(sleep_time)


@app.route('/thermal_feed')
def thermal_feed():
    mode = request.args.get('mode')
    fps = request.args.get('fps', type=float)
    quality = request.args.get('quality', type=int)
    width = request.args.get('width', type=int)
    f, q, w = resolve_stream_params(mode, fps, quality, width, is_thermal=True)
    res = Response(gen_thermal_frames(fps=f, quality=q, max_width=w), mimetype='multipart/x-mixed-replace; boundary=frame')
    res.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    res.headers['Pragma'] = 'no-cache'
    res.headers['Expires'] = '0'
    return res


@app.route('/visible_feed')
def visible_feed():
    mode = request.args.get('mode')
    fps = request.args.get('fps', type=float)
    quality = request.args.get('quality', type=int)
    width = request.args.get('width', type=int)
    f, q, w = resolve_stream_params(mode, fps, quality, width, is_thermal=False)
    res = Response(gen_visible_frames(fps=f, quality=q, max_width=w), mimetype='multipart/x-mixed-replace; boundary=frame')
    res.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    res.headers['Pragma'] = 'no-cache'
    res.headers['Expires'] = '0'
    return res


@app.route('/api/camera/metadata/<camera_id>')
def api_camera_metadata(camera_id: str):
    """Return metadata associated with the newest frame for Camera View."""
    if camera_id not in ("thermal", "visible"):
        return jsonify({"status": "error", "message": "Unknown camera"}), 404

    metadata = frame_publisher.get_camera_metadata(camera_id)
    if metadata is None:
        return jsonify({
            "status": "unavailable",
            "camera_id": camera_id,
            "message": "No frame metadata available yet",
        }), 503

    return jsonify({"status": "ok", "metadata": metadata})


@app.route('/')
def index():
    return render_template('index.html', config=config.get_all_config())


@app.route('/settings')
def settings():
    return render_template('settings.html', config=config.get_all_config())


@app.route('/ptz_test')
def ptz_test():
    return render_template('ptz_test.html', config=config.get_all_config())


@app.route('/api/config/save', methods=['POST'])
def api_config_save():
    new_cfg = request.json or {}
    success = config.update_and_save_config(new_cfg)
    if success:
        # Live update memory parameters
        if "ai" in new_cfg:
            ai_cfg = new_cfg["ai"]
            if "detector_engine" in ai_cfg:
                state["detector_engine"] = str(ai_cfg["detector_engine"])
                state["ai_engine"] = "Classic Thermal Hotspot" if state["detector_engine"] == "CLASSIC_THERMAL" else ("Hybrid Detection" if state["detector_engine"] == "HYBRID" else "NCNN YOLO26n")
            if "hotspot_threshold" in ai_cfg:
                state["hotspot_threshold"] = int(ai_cfg["hotspot_threshold"])
                classic_detector.threshold = state["hotspot_threshold"]
                fire_verifier.hotspot_threshold = state["hotspot_threshold"]
                fire_verifier.thermal_core_min_val = int(ai_cfg.get("thermal_core_min_val", state["hotspot_threshold"]))
                mission_ctrl.hotspot_threshold = state["hotspot_threshold"]
            if "thermal_core_min_val" in ai_cfg:
                fire_verifier.thermal_core_min_val = int(ai_cfg["thermal_core_min_val"])
            if "min_hotspot_area" in ai_cfg:
                state["min_hotspot_area"] = int(ai_cfg["min_hotspot_area"])
                classic_detector.min_area = state["min_hotspot_area"]
            if "max_hotspot_area" in ai_cfg:
                state["max_hotspot_area"] = int(ai_cfg["max_hotspot_area"])
                classic_detector.max_area = state["max_hotspot_area"]
            if "morph_kernel_size" in ai_cfg:
                state["morph_kernel_size"] = int(ai_cfg["morph_kernel_size"])
                classic_detector.morph_kernel_size = state["morph_kernel_size"]
            if "dilate_iterations" in ai_cfg:
                state["dilate_iterations"] = int(ai_cfg["dilate_iterations"])
                classic_detector.dilate_iterations = state["dilate_iterations"]
            if "blur_ksize" in ai_cfg:
                state["blur_ksize"] = int(ai_cfg["blur_ksize"])
                classic_detector.blur_ksize = state["blur_ksize"]
            if "use_tophat" in ai_cfg:
                state["use_tophat"] = bool(ai_cfg["use_tophat"])
                classic_detector.use_tophat = state["use_tophat"]
            if "tophat_ksize" in ai_cfg:
                state["tophat_ksize"] = int(ai_cfg["tophat_ksize"])
                classic_detector.tophat_ksize = state["tophat_ksize"]
            if "tophat_threshold" in ai_cfg:
                state["tophat_threshold"] = int(ai_cfg["tophat_threshold"])
                classic_detector.tophat_threshold = state["tophat_threshold"]
            if "use_adaptive" in ai_cfg:
                state["use_adaptive"] = bool(ai_cfg["use_adaptive"])
                classic_detector.use_adaptive = state["use_adaptive"]
            if "adaptive_k" in ai_cfg:
                state["adaptive_k"] = float(ai_cfg["adaptive_k"])
                classic_detector.adaptive_k = state["adaptive_k"]
            if "adaptive_min_threshold" in ai_cfg:
                state["adaptive_min_threshold"] = int(ai_cfg["adaptive_min_threshold"])
                classic_detector.adaptive_min_threshold = state["adaptive_min_threshold"]
            if "zoom_aware" in ai_cfg:
                state["zoom_aware"] = bool(ai_cfg["zoom_aware"])
                classic_detector.zoom_aware = state["zoom_aware"]
            if "use_clutter_suppression" in ai_cfg:
                state["use_clutter_suppression"] = bool(ai_cfg["use_clutter_suppression"])
                classic_detector.use_clutter_suppression = state["use_clutter_suppression"]
            if "clutter_threshold" in ai_cfg:
                state["clutter_threshold"] = int(ai_cfg["clutter_threshold"])
                classic_detector.clutter_threshold = state["clutter_threshold"]
            if "clutter_min_core_ratio" in ai_cfg:
                state["clutter_min_core_ratio"] = float(ai_cfg["clutter_min_core_ratio"])
                classic_detector.clutter_min_core_ratio = state["clutter_min_core_ratio"]
            if "conf_threshold" in ai_cfg:
                state["conf_threshold"] = float(ai_cfg["conf_threshold"])
            if "min_verification_hits" in ai_cfg:
                fire_verifier.min_hits = int(ai_cfg["min_verification_hits"])
            if "alarm_hold_cycles" in ai_cfg:
                fire_verifier.confirmed_hold_cycles = int(ai_cfg["alarm_hold_cycles"])
            if "capture_az_step" in ai_cfg:
                state["capture_az_step"] = float(ai_cfg["capture_az_step"])
            if "infer_interval_sec" in ai_cfg:
                state["infer_interval_sec"] = float(ai_cfg["infer_interval_sec"])
            if "trigger_mode" in ai_cfg:
                state["trigger_mode"] = str(ai_cfg["trigger_mode"])
        if "mission" in new_cfg:
            m_cfg = new_cfg["mission"]
            mission_ctrl.cfg.update(m_cfg)
            if "capture_az_step" in m_cfg:
                state["capture_az_step"] = float(m_cfg["capture_az_step"])
        if "frame_publisher" in new_cfg:
            frame_publisher.update_config(new_cfg["frame_publisher"])
        if "streaming" in new_cfg:
            config.STREAMING_CONFIG.update(new_cfg["streaming"])
        if "incident" in new_cfg:
            inc_cfg = new_cfg["incident"]
            if "match_tolerance_deg" in inc_cfg:
                mission_ctrl.incident_mgr.match_tolerance_deg = float(inc_cfg["match_tolerance_deg"])
            if "max_inactive_gap_hours" in inc_cfg:
                mission_ctrl.incident_mgr.max_inactive_gap_hours = float(inc_cfg["max_inactive_gap_hours"])
        if "telegram" in new_cfg:
            config.TELEGRAM_CONFIG.update(new_cfg["telegram"])
            if hasattr(mission_ctrl, 'notifier'):
                mission_ctrl.notifier.update_config(
                    bot_token=new_cfg["telegram"].get("bot_token"),
                    chat_id=new_cfg["telegram"].get("chat_id"),
                    enabled=new_cfg["telegram"].get("enabled")
                )
        if "llm" in new_cfg:
            config.LLM_CONFIG.update(new_cfg["llm"])
            if hasattr(mission_ctrl, 'llm_verifier'):
                mission_ctrl.llm_verifier.update_config(new_cfg["llm"])
        if "thermal_imaging" in new_cfg:
            th_cam = camera_mgr.get_thermal_camera()
            if th_cam:
                th_cam.update_imaging_config(new_cfg["thermal_imaging"])
        return jsonify({"status": "ok", "message": "Config updated successfully"})
    return jsonify({"status": "error", "message": "Failed to write config"}), 500


@app.route('/api/camera/thermal/imaging', methods=['GET', 'POST'])
def api_camera_thermal_imaging():
    th_cam = camera_mgr.get_thermal_camera()
    if not th_cam:
        return jsonify({"status": "error", "message": "Thermal camera unavailable"}), 404

    if request.method == 'POST':
        data = request.json or {}
        if "brightness" in data or "contrast" in data:
            b = int(data.get("brightness", th_cam._current_brightness))
            c = int(data.get("contrast", th_cam._current_contrast))
            ok = th_cam.set_thermal_graphic_options(b, c)
            if ok:
                if "auto_mode" in data:
                    th_cam.thermal_imaging_cfg["auto_mode"] = data["auto_mode"]
                config.update_and_save_config({"thermal_imaging": th_cam.thermal_imaging_cfg})
                return jsonify({"status": "ok", "brightness": b, "contrast": c, "config": th_cam.thermal_imaging_cfg})
            return jsonify({"status": "error", "message": "Failed to set camera graphic options"}), 500

        th_cam.update_imaging_config(data)
        config.update_and_save_config({"thermal_imaging": th_cam.thermal_imaging_cfg})
        return jsonify({"status": "ok", "config": th_cam.thermal_imaging_cfg})

    # GET
    live = th_cam.get_thermal_graphic_options()
    return jsonify({
        "status": "ok",
        "live": live,
        "config": th_cam.thermal_imaging_cfg,
        "current_brightness": th_cam._current_brightness,
        "current_contrast": th_cam._current_contrast
    })


@app.route('/api/ai/toggle', methods=['POST'])
def api_ai_toggle():
    state["ai_enabled"] = not state.get("ai_enabled", True)
    if not state["ai_enabled"]:
        with detections_lock:
            active_detections.clear()
        state["fire_detected"] = False
        state["confirmed_count"] = 0
        state["verifying_count"] = 0
        state["pending_count"] = 0
    return jsonify({
        "status": "ok",
        "ai_enabled": state["ai_enabled"],
        "message": "Detection Enabled" if state["ai_enabled"] else "Detection Paused / Stopped"
    })


@app.route('/api/publisher/toggle', methods=['POST'])
def api_publisher_toggle():
    data = request.json or {}
    if "enabled" in data:
        new_state = bool(data["enabled"])
    else:
        new_state = not frame_publisher.enabled

    frame_publisher.update_config({"enabled": new_state})
    config.update_and_save_config({"frame_publisher": {"enabled": new_state}})
    return jsonify({
        "status": "ok",
        "publisher_enabled": frame_publisher.enabled,
        "message": "Frame Publisher Enabled" if frame_publisher.enabled else "Frame Publisher Disabled"
    })


@app.route('/api/publisher/status')
def api_publisher_status():
    return jsonify({"status": "ok", "publisher": frame_publisher.get_status()})


@app.route('/api/telemetry')
def api_telemetry():
    thermal_cam = camera_mgr.get_thermal_camera()
    visible_cam = camera_mgr.get_visible_camera()
    mission_status = mission_ctrl.get_status()

    th_zoom = thermal_cam.get_zoom_info() if thermal_cam else {"focal_mm": 31.0, "zoom_pct": 0.0, "zoom_x": 1.0, "fov_h": 14.2}
    vis_zoom = visible_cam.get_zoom_info() if visible_cam else {"focal_mm": 4.0, "zoom_pct": 0.0, "zoom_x": 1.0, "fov_h": 60.0}

    return jsonify({
        "thermal_fps": thermal_cam.fps if thermal_cam else 0.0,
        "visible_fps": visible_cam.fps if visible_cam else 0.0,
        "latency_ms": state["latency_ms"],
        "fire_detected": state["fire_detected"],
        "confirmed_count": state["confirmed_count"],
        "verifying_count": state["verifying_count"],
        "pending_count": state["pending_count"],
        "total_frames": state["total_frames"],
        "ai_enabled": state.get("ai_enabled", True),
        "detector_engine": state.get("detector_engine", "CLASSIC_THERMAL"),
        "hotspot_threshold": state.get("hotspot_threshold", 190),
        "capture_az_step": state.get("capture_az_step", 5.0),
        "infer_interval_sec": state.get("infer_interval_sec", 0.2),
        "last_infer_az": state.get("last_infer_az"),
        "trigger_mode": state.get("trigger_mode", "FIXED_INTERVAL"),
        "trigger_count": state.get("trigger_count", 0),
        "frame_publisher": frame_publisher.get_status(),
        "ptz": {
            "az": mission_status["current_az"],
            "alt": mission_status["current_alt"],
            "locked_az": mission_status["locked_az"],
            "locked_alt": mission_status["locked_alt"],
            "is_armed": ptz_ctrl.is_armed,
            "is_connected": ptz_ctrl.is_connected
        },
        "mission": mission_status,
        "latest_incident": mission_status.get("latest_incident"),
        "thermal_zoom": th_zoom,
        "visible_zoom": vis_zoom,
        "use_kalman": state["use_kalman_filter"],
        "conf_threshold": state["conf_threshold"],
        "min_hits": fire_verifier.min_hits,
        "alarm_hold_cycles": fire_verifier.confirmed_hold_cycles
    })


@app.route('/api/ptz/control', methods=['POST'])
def api_ptz_control():
    data = request.json or {}
    action = data.get("action")

    if action in ("enable", "enable_motors", "arm"):
        axis = data.get("axis")
        success = ptz_ctrl.enable_motors(axis=axis)
        return jsonify({"status": "ok" if success else "error", "is_armed": ptz_ctrl.is_armed})
    elif action in ("disable", "disable_motors", "disarm"):
        axis = data.get("axis")
        success = ptz_ctrl.disable_motors(axis=axis)
        return jsonify({"status": "ok" if success else "error", "is_armed": ptz_ctrl.is_armed})
    elif action == "start_sentry":
        az_start = data.get("az_start")
        az_end = data.get("az_end")
        alt = data.get("alt")
        alt_start = data.get("alt_start")
        alt_end = data.get("alt_end")
        alt_step = data.get("alt_step")
        speed = data.get("speed")
        scan_mode = data.get("scan_mode")
        focal_length_mm = data.get("focal_length_mm") or data.get("scan_focal_length_mm")
        fov_overlap_pct = data.get("fov_overlap_pct") or data.get("scan_fov_overlap_pct") or data.get("step_overlap_pct")
        visible_sync_scan_zoom = data.get("visible_sync_scan_zoom")
        visible_fov_multiplier = data.get("visible_fov_multiplier")
        max_goto_speed = data.get("max_goto_speed") or data.get("step_goto_speed")
        settle_sec = data.get("settle_sec") or data.get("scan_settle_sec")
        step_calc_mode = data.get("step_calc_mode")
        step_az_deg = data.get("step_az_deg")
        step_overlap_pct = data.get("step_overlap_pct")
        step_dwell_sec = data.get("step_dwell_sec")
        step_goto_speed = data.get("step_goto_speed")
        capture_az_step = data.get("capture_az_step")

        if capture_az_step is not None:
            try:
                state["capture_az_step"] = float(capture_az_step)
            except (ValueError, TypeError):
                pass

        mission_ctrl.start_sentry(
            az_start=az_start,
            az_end=az_end,
            speed=speed,
            alt=alt,
            alt_start=alt_start,
            alt_end=alt_end,
            alt_step=alt_step,
            scan_mode=scan_mode,
            focal_length_mm=focal_length_mm,
            fov_overlap_pct=fov_overlap_pct,
            visible_sync_scan_zoom=visible_sync_scan_zoom,
            visible_fov_multiplier=visible_fov_multiplier,
            max_goto_speed=max_goto_speed,
            settle_sec=settle_sec,
            step_calc_mode=step_calc_mode,
            step_az_deg=step_az_deg,
            step_overlap_pct=step_overlap_pct,
            step_dwell_sec=step_dwell_sec,
            step_goto_speed=step_goto_speed,
            capture_az_step=capture_az_step
        )
    elif action in ("pause_sentry", "pause"):
        mission_ctrl.pause_sentry()
    elif action in ("stop_sentry", "stop"):
        mission_ctrl.stop_sentry()
        with detections_lock:
            active_detections.clear()
        state["fire_detected"] = False
        state["confirmed_count"] = 0
        state["verifying_count"] = 0
        state["pending_count"] = 0
        state["detections"] = []
        if hasattr(fire_verifier, 'tracks'):
            fire_verifier.tracks.clear()
    elif action in ("goto", "slew_to"):
        target_az = float(data.get("az", 0.0))
        target_alt = float(data.get("alt", 0.0))
        speed = float(data.get("speed", 15.0))
        threading.Thread(target=ptz_ctrl.goto_position, args=(target_az, target_alt, speed, True), daemon=True).start()
    elif action == "step_move":
        d_az = float(data.get("d_az", 0.0))
        d_alt = float(data.get("d_alt", 0.0))
        speed = float(data.get("speed", 10.0))
        cur_az, cur_alt = ptz_ctrl.get_position()
        min_az = float(config.MOUNT.get("az_min", -300.0))
        max_az = float(config.MOUNT.get("az_max", 300.0))
        target_az = max(min_az, min(max_az, cur_az + d_az))
        min_alt = float(config.MOUNT.get("alt_min", -30.0))
        max_alt = float(config.MOUNT.get("alt_max", 60.0))
        target_alt = max(min_alt, min(max_alt, cur_alt + d_alt))
        step_mag = max(abs(d_az), abs(d_alt))
        step_tol = min(0.2, max(0.05, step_mag * 0.15))
        threading.Thread(target=ptz_ctrl.goto_position, args=(target_az, target_alt, speed, True, step_tol), daemon=True).start()
    elif action in ("jog", "velocity"):
        az_vel = float(data.get("az_vel", 0.0))
        alt_vel = float(data.get("alt_vel", 0.0))
        ptz_ctrl.set_velocity(az_vel, alt_vel)
    elif action in ("stop", "stop_move"):
        ptz_ctrl.stop()
    elif action == "home":
        speed = float(data.get("speed", 15.0))
        threading.Thread(target=ptz_ctrl.goto_position, args=(0.0, 0.0, speed, True), daemon=True).start()
    elif action == "pan_continuous":
        speed = float(data.get("speed", 1.0))
        direction = data.get("direction", "right")
        signed_speed = abs(speed) if direction == "right" else -abs(speed)
        ptz_ctrl.continuous_pan(signed_speed)
    elif action == "zoom_start":
        cam_id = data.get("cam_id", "thermal")
        cam = camera_mgr.get_camera(cam_id)
        speed = float(data.get("speed", 0.8))
        direction = data.get("direction", "in")
        if cam:
            signed_speed = abs(speed) if direction == "in" else -abs(speed)
            cam.start_continuous_zoom(signed_speed)
    elif action == "zoom_stop":
        cam_id = data.get("cam_id", "thermal")
        cam = camera_mgr.get_camera(cam_id)
        if cam:
            cam.stop_zoom()
    elif action in ("zoom_in", "zoom_out"):
        cam_id = data.get("cam_id") or data.get("camera") or "thermal"
        cam = camera_mgr.get_camera(cam_id)
        speed = max(0.05, min(1.0, abs(float(data.get("speed", 0.8)))))
        duration = max(0.05, min(5.0, float(data.get("duration", 1.0))))
        if cam:
            if action == "zoom_in":
                cam.zoom_in(speed=speed, duration_sec=duration)
            else:
                cam.zoom_out(speed=speed, duration_sec=duration)
    elif action in ("zoom_pct", "set_zoom_pct"):
        cam_id = data.get("cam_id") or data.get("camera") or "thermal"
        pct = max(0.0, min(100.0, float(data.get("zoom_pct", data.get("pct", 0.0)))))
        cam = camera_mgr.get_camera(cam_id)
        if cam:
            cam.set_zoom_pct(pct)
    elif action in ("zoom_x", "set_zoom_x"):
        cam_id = data.get("cam_id") or data.get("camera") or "thermal"
        raw_x = float(data.get("zoom_x", data.get("x", 1.0)))
        cam = camera_mgr.get_camera(cam_id)
        if cam:
            cam.set_zoom_x(raw_x)
    elif action == "zoom_mm":
        cam_id = data.get("cam_id") or data.get("camera") or "thermal"
        focal_mm = float(data.get("focal_mm", 90.0))
        cam = camera_mgr.get_camera(cam_id)
        if cam:
            cam.set_focal_length_mm(focal_mm)
    elif action in ("focus_near", "focus_far"):
        cam_id = data.get("cam_id") or data.get("camera") or "thermal"
        cam = camera_mgr.get_camera(cam_id)
        speed = max(0.05, min(1.0, abs(float(data.get("speed", 0.5)))))
        duration = max(0.05, min(5.0, float(data.get("duration", 0.5))))
        if cam:
            signed_speed = speed if action == "focus_far" else -speed
            cam.continuous_focus(signed_speed, duration_sec=duration)
    elif action == "focus_auto":
        cam_id = data.get("cam_id") or data.get("camera") or "thermal"
        cam = camera_mgr.get_camera(cam_id)
        if cam:
            cam.trigger_auto_focus()

    cur_az, cur_alt = ptz_ctrl.get_position()
    return jsonify({
        "status": "ok",
        "position": {"az": cur_az, "alt": cur_alt},
        "mission": mission_ctrl.get_status()
    })


@app.route('/api/camera/zoom', methods=['POST'])
def api_camera_zoom():
    """
    Unified Camera Zoom Endpoint with strict clamping & limit validation
    Accepts:
    - camera / cam_id: "thermal" | "visible" | "all" | "dual"
    - zoom_pct / pct / percentage: float (0.0 to 100.0)
    - focal_mm / focal_length_mm / mm: float
    - zoom_x / multiplier / x: float (e.g. 1.0 to 20.0)
    """
    data = request.json or {}
    cam_id = data.get("camera") or data.get("cam_id") or "thermal"
    cam_id = str(cam_id).lower()

    target_cams = []
    if cam_id in ("all", "dual", "both"):
        th = camera_mgr.get_thermal_camera()
        vis = camera_mgr.get_visible_camera()
        if th: target_cams.append(th)
        if vis: target_cams.append(vis)
    else:
        cam = camera_mgr.get_camera(cam_id)
        if not cam:
            return jsonify({
                "status": "error",
                "message": f"Camera '{cam_id}' not found. Available: {list(camera_mgr.cameras.keys())}"
            }), 404
        target_cams.append(cam)

    applied_mode = None
    target_value = None

    if "zoom_pct" in data or "pct" in data or "percentage" in data:
        applied_mode = "zoom_pct"
        target_value = float(data.get("zoom_pct", data.get("pct", data.get("percentage"))))
    elif "focal_mm" in data or "focal_length_mm" in data or "focal" in data or "mm" in data:
        applied_mode = "focal_mm"
        target_value = float(data.get("focal_mm", data.get("focal_length_mm", data.get("focal", data.get("mm")))))
    elif "zoom_x" in data or "multiplier" in data or "x" in data:
        applied_mode = "zoom_x"
        target_value = float(data.get("zoom_x", data.get("multiplier", data.get("x"))))
    elif "ratio" in data or "zoom_ratio" in data:
        applied_mode = "zoom_pct"
        target_value = float(data.get("ratio", data.get("zoom_ratio", 0.0))) * 100.0
    else:
        return jsonify({
            "status": "error",
            "message": "Missing zoom parameter. Please provide 'zoom_pct' (0-100), 'focal_mm', or 'zoom_x' (multiplier)."
        }), 400

    results = {}
    any_clamped = False

    for c in target_cams:
        max_optical_x = round(c.max_focal_mm / c.min_focal_mm, 1) if c.min_focal_mm > 0 else 1.0
        is_cam_clamped = False

        if applied_mode == "zoom_pct":
            clamped_val = max(0.0, min(100.0, target_value))
            if clamped_val != target_value:
                is_cam_clamped = True
            c.set_zoom_pct(clamped_val)

        elif applied_mode == "focal_mm":
            clamped_val = max(c.min_focal_mm, min(c.max_focal_mm, target_value))
            if clamped_val != target_value:
                is_cam_clamped = True
            c.set_focal_length_mm(clamped_val)

        elif applied_mode == "zoom_x":
            clamped_val = max(1.0, min(max_optical_x, target_value))
            if clamped_val != target_value:
                is_cam_clamped = True
            c.set_zoom_x(clamped_val)

        if is_cam_clamped:
            any_clamped = True

        results[c.cam_id] = {
            "zoom_info": c.get_zoom_info(),
            "clamped": is_cam_clamped,
            "limits": {
                "min_focal_mm": c.min_focal_mm,
                "max_focal_mm": c.max_focal_mm,
                "max_zoom_x": max_optical_x
            }
        }

    if len(target_cams) == 1:
        c = target_cams[0]
        return jsonify({
            "status": "ok",
            "camera": c.cam_id,
            "applied_mode": applied_mode,
            "requested_value": target_value,
            "clamped": any_clamped,
            "zoom_info": results[c.cam_id]["zoom_info"],
            "limits": results[c.cam_id]["limits"]
        })
    else:
        return jsonify({
            "status": "ok",
            "camera": "all",
            "applied_mode": applied_mode,
            "requested_value": target_value,
            "clamped": any_clamped,
            "results": results
        })


@app.route('/api/camera/focus', methods=['POST'])
def api_camera_focus():
    """
    Dedicated Camera Focus Control Endpoint with speed & duration clamping
    Accepts:
    - camera / cam_id: "thermal" | "visible" | "all"
    - action / mode: "near" | "far" | "auto"
    - speed: float (0.05 to 1.0, default 0.5)
    - duration_sec / duration: float (0.05 to 5.0, default 0.5)
    """
    data = request.json or {}
    cam_id = data.get("camera") or data.get("cam_id") or "thermal"
    action = str(data.get("action") or data.get("mode") or "auto").lower()

    target_cams = []
    if str(cam_id).lower() in ("all", "dual", "both"):
        th = camera_mgr.get_thermal_camera()
        vis = camera_mgr.get_visible_camera()
        if th: target_cams.append(th)
        if vis: target_cams.append(vis)
    else:
        cam = camera_mgr.get_camera(cam_id)
        if not cam:
            return jsonify({
                "status": "error",
                "message": f"Camera '{cam_id}' not found. Available: {list(camera_mgr.cameras.keys())}"
            }), 404
        target_cams.append(cam)

    raw_speed = float(data.get("speed", 0.5))
    raw_duration = float(data.get("duration_sec", data.get("duration", 0.5)))

    clamped_speed = max(0.05, min(1.0, abs(raw_speed)))
    clamped_duration = max(0.05, min(5.0, abs(raw_duration)))
    is_clamped = (raw_speed != clamped_speed) or (raw_duration != clamped_duration)

    results = {}
    for c in target_cams:
        if action == "auto":
            c.trigger_auto_focus()
        elif action in ("near", "focus_near"):
            c.continuous_focus(-clamped_speed, duration_sec=clamped_duration)
        elif action in ("far", "focus_far"):
            c.continuous_focus(clamped_speed, duration_sec=clamped_duration)
        else:
            return jsonify({
                "status": "error",
                "message": f"Unknown focus action '{action}'. Valid actions: 'auto', 'near', 'far'."
            }), 400

        results[c.cam_id] = {
            "focus_mode": action,
            "sharpness_score": round(c.compute_sharpness(), 1)
        }

    return jsonify({
        "status": "ok",
        "camera": cam_id,
        "action": action,
        "speed": clamped_speed,
        "duration_sec": clamped_duration,
        "clamped": is_clamped,
        "results": results if len(target_cams) > 1 else results[target_cams[0].cam_id]
    })


@app.route('/api/camera/zoom_mm', methods=['POST'])
def api_camera_zoom_mm():
    data = request.json or {}
    cam_id = data.get("cam_id") or data.get("camera") or "thermal"
    focal_mm = float(data.get("focal_mm", 90.0))
    cam = camera_mgr.get_camera(cam_id)
    if not cam:
        return jsonify({"status": "error", "message": f"Camera '{cam_id}' not found"}), 404

    success = cam.set_focal_length_mm(focal_mm)
    return jsonify({
        "status": "ok" if success else "error",
        "cam_id": cam_id,
        "target_focal_mm": focal_mm,
        "zoom_info": cam.get_zoom_info()
    })


@app.route('/api/sweep/control', methods=['POST'])
def api_sweep_control():
    """
    Dedicated Sweep / Sentry Scan Control Endpoint for PTZ Systems
    Actions:
    - start: starts or updates sentry sweep with az, alt, speed, focal_length_mm (or zoom_pct)
    - pause: holds sentry sweep at current position
    - resume: resumes sentry sweep from current waypoint/layer
    - stop: halts sentry sweep, resets to IDLE, and returns camera to wide-angle
    - status: returns current sweep telemetry and trajectory calculation
    """
    data = request.json or {}
    action = str(data.get("action", "status")).lower()

    # In-memory detector parameter tuning (no JSON file write)
    raw_thresh = data.get("hotspot_threshold") or data.get("hotspot_thresh") or data.get("threshold")
    if raw_thresh is not None:
        thresh_val = max(50, min(255, int(raw_thresh)))
        state["hotspot_threshold"] = thresh_val
        classic_detector.threshold = thresh_val
        fire_verifier.hotspot_threshold = thresh_val
        fire_verifier.thermal_core_min_val = min(fire_verifier.thermal_core_min_val, thresh_val)
        mission_ctrl.hotspot_threshold = thresh_val
        config.AI_CONFIG["hotspot_threshold"] = thresh_val

    raw_adaptive = (
        data.get("use_adaptive")
        if "use_adaptive" in data
        else (
            data.get("adaptive_saliency")
            if "adaptive_saliency" in data
            else (
                data.get("dynamic_saliency")
                if "dynamic_saliency" in data
                else (data.get("saliency") if "saliency" in data else None)
            )
        )
    )
    if raw_adaptive is not None:
        adaptive_val = bool(raw_adaptive)
        state["use_adaptive"] = adaptive_val
        classic_detector.use_adaptive = adaptive_val
        config.AI_CONFIG["use_adaptive"] = adaptive_val

    if action in ("start", "resume"):
        az_start = data.get("az_start")
        az_end = data.get("az_end")
        alt = data.get("alt")
        alt_start = data.get("alt_start")
        alt_end = data.get("alt_end")
        speed = data.get("speed")

        focal_mm = data.get("focal_length_mm", data.get("focal_mm"))
        if focal_mm is None and "zoom_pct" in data:
            pct = max(0.0, min(100.0, float(data["zoom_pct"])))
            focal_mm = 31.0 + (pct / 100.0) * (155.0 - 31.0)

        if focal_mm is not None:
            focal_mm = float(focal_mm)

        if action == "resume" and (mission_ctrl.is_paused or mission_ctrl.state == MissionState.PAUSED):
            mission_ctrl.start_sentry()
        else:
            mission_ctrl.start_sentry(
                az_start=az_start,
                az_end=az_end,
                alt=alt,
                alt_start=alt_start,
                alt_end=alt_end,
                speed=speed,
                focal_length_mm=focal_mm,
                visible_sync_scan_zoom=data.get("visible_sync_scan_zoom"),
                visible_fov_multiplier=data.get("visible_fov_multiplier")
            )

    elif action in ("pause", "pause_sentry"):
        mission_ctrl.pause_sentry()

    elif action in ("stop", "stop_sentry"):
        mission_ctrl.stop_sentry()
        with detections_lock:
            active_detections.clear()
        state["fire_detected"] = False
        state["confirmed_count"] = 0
        state["verifying_count"] = 0
        state["pending_count"] = 0
        state["detections"] = []
        if hasattr(fire_verifier, 'tracks'):
            fire_verifier.tracks.clear()

    cur_az, cur_alt = ptz_ctrl.get_position()
    traj_info = mission_ctrl.get_trajectory_info() if hasattr(mission_ctrl, "get_trajectory_info") else {}

    return jsonify({
        "status": "ok",
        "action": action,
        "mission_state": mission_ctrl.state,
        "is_paused": mission_ctrl.is_paused,
        "current_position": {
            "azimuth_deg": round(float(cur_az), 2),
            "altitude_deg": round(float(cur_alt), 2)
        },
        "active_parameters": {
            "az_start": float(mission_ctrl.cfg.get("scan_az_start", -90.0)),
            "az_end": float(mission_ctrl.cfg.get("scan_az_end", 90.0)),
            "alt_start": float(mission_ctrl.cfg.get("scan_alt_start", -10.0)),
            "alt_end": float(mission_ctrl.cfg.get("scan_alt_end", 0.0)),
            "speed_deg_s": float(mission_ctrl.cfg.get("sweep_speed_deg_s", 1.0)),
            "focal_length_mm": float(mission_ctrl.cfg.get("scan_focal_length_mm", 31.0)),
            "hotspot_threshold": int(classic_detector.threshold),
            "use_adaptive": bool(classic_detector.use_adaptive)
        },
        "trajectory": traj_info
    })


@app.route('/api/sweep/status', methods=['GET'])
def api_sweep_status():
    """Returns current sweep status, active parameters, and trajectory details."""
    cur_az, cur_alt = ptz_ctrl.get_position()
    traj_info = mission_ctrl.get_trajectory_info() if hasattr(mission_ctrl, "get_trajectory_info") else {}
    return jsonify({
        "status": "ok",
        "mission_state": mission_ctrl.state,
        "is_paused": mission_ctrl.is_paused,
        "current_position": {
            "azimuth_deg": round(float(cur_az), 2),
            "altitude_deg": round(float(cur_alt), 2)
        },
        "active_parameters": {
            "az_start": float(mission_ctrl.cfg.get("scan_az_start", -90.0)),
            "az_end": float(mission_ctrl.cfg.get("scan_az_end", 90.0)),
            "alt_start": float(mission_ctrl.cfg.get("scan_alt_start", -10.0)),
            "alt_end": float(mission_ctrl.cfg.get("scan_alt_end", 0.0)),
            "speed_deg_s": float(mission_ctrl.cfg.get("sweep_speed_deg_s", 1.0)),
            "focal_length_mm": float(mission_ctrl.cfg.get("scan_focal_length_mm", 31.0)),
            "hotspot_threshold": int(classic_detector.threshold),
            "use_adaptive": bool(classic_detector.use_adaptive)
        },
        "trajectory": traj_info
    })


@app.route('/api/detector/config', methods=['GET', 'POST'])
def api_detector_config():
    """
    Runtime Thermal Detector Configuration (In-Memory only, no JSON file write)
    Allows PTZ systems to toggle Dynamic / Adaptive Saliency and adjust Hotspot Threshold on the fly.
    """
    if request.method == 'POST':
        data = request.json or {}

        # 1. Hotspot Threshold (0-255 luminance)
        raw_thresh = data.get("hotspot_threshold") or data.get("hotspot_thresh") or data.get("threshold")
        if raw_thresh is not None:
            thresh_val = max(50, min(255, int(raw_thresh)))
            state["hotspot_threshold"] = thresh_val
            classic_detector.threshold = thresh_val
            fire_verifier.hotspot_threshold = thresh_val
            fire_verifier.thermal_core_min_val = min(fire_verifier.thermal_core_min_val, thresh_val)
            mission_ctrl.hotspot_threshold = thresh_val
            config.AI_CONFIG["hotspot_threshold"] = thresh_val

        # 2. Dynamic / Adaptive Saliency Toggle
        raw_adaptive = (
            data.get("use_adaptive")
            if "use_adaptive" in data
            else (
                data.get("adaptive_saliency")
                if "adaptive_saliency" in data
                else (
                    data.get("dynamic_saliency")
                    if "dynamic_saliency" in data
                    else (data.get("saliency") if "saliency" in data else None)
                )
            )
        )
        if raw_adaptive is not None:
            adaptive_val = bool(raw_adaptive)
            state["use_adaptive"] = adaptive_val
            classic_detector.use_adaptive = adaptive_val
            config.AI_CONFIG["use_adaptive"] = adaptive_val

        # 3. Optional Adaptive Saliency Parameters
        raw_k = data.get("adaptive_k") or data.get("k")
        if raw_k is not None:
            k_val = max(1.0, min(6.0, float(raw_k)))
            state["adaptive_k"] = k_val
            classic_detector.adaptive_k = k_val
            config.AI_CONFIG["adaptive_k"] = k_val

        raw_adaptive_min = data.get("adaptive_min_threshold") or data.get("min_threshold")
        if raw_adaptive_min is not None:
            min_thresh_val = max(50, min(255, int(raw_adaptive_min)))
            state["adaptive_min_threshold"] = min_thresh_val
            classic_detector.adaptive_min_threshold = min_thresh_val
            config.AI_CONFIG["adaptive_min_threshold"] = min_thresh_val

    return jsonify({
        "status": "ok",
        "saved_to_disk": False,
        "detector_config": {
            "hotspot_threshold": int(classic_detector.threshold),
            "use_adaptive": bool(classic_detector.use_adaptive),
            "adaptive_k": float(classic_detector.adaptive_k),
            "adaptive_min_threshold": int(classic_detector.adaptive_min_threshold)
        }
    })


@app.route('/api/thermal/power', methods=['POST', 'GET'])
def api_thermal_power():
    thermal_cam = camera_mgr.get_thermal_camera()
    if not thermal_cam:
        return jsonify({"status": "error", "message": "Thermal camera not found"}), 404

    if request.method == 'POST':
        data = request.json or {}
        enable = bool(data.get("enable", True))
        success = thermal_cam.set_thermal_power(enable=enable)
        return jsonify({"status": "ok" if success else "error", "power": "ON" if enable else "OFF"})

    # GET request - trigger auto power on if requested
    return jsonify({"status": "ok", "message": "Thermal power endpoint ready"})


@app.route('/api/snapshot')
@app.route('/api/snapshot/<cam_type>')
def api_snapshot(cam_type=None):
    cam_id = (request.args.get('cam') or cam_type or 'thermal').lower()
    if cam_id in ('visible', 'vis', 'optical'):
        cam = camera_mgr.get_visible_camera()
        filename_prefix = "visible_snapshot"
    else:
        cam = camera_mgr.get_thermal_camera()
        filename_prefix = "thermal_snapshot"

    if cam:
        bgr, jpeg = cam.get_latest_frame()
        if bgr is not None and cam_id in ('visible', 'vis', 'optical'):
            vh, vw = bgr.shape[:2]
            if vh > 0 and abs((vw / float(vh)) - (16.0 / 9.0)) > 0.05:
                target_w = int(round(vh * 16.0 / 9.0))
                bgr = cv2.resize(bgr, (target_w, vh), interpolation=cv2.INTER_LANCZOS4)
            ret, enc_jpeg = cv2.imencode('.jpg', bgr, [cv2.IMWRITE_JPEG_QUALITY, 90])
            if ret:
                jpeg = enc_jpeg.tobytes()

        if jpeg:
            return send_file(
                io.BytesIO(jpeg),
                mimetype='image/jpeg',
                as_attachment=True,
                download_name=f"{filename_prefix}_{int(time.time())}.jpg"
            )
    return jsonify({"error": f"No frame available for {cam_id}"}), 404


@app.route('/api/incidents')
def api_incidents():
    limit = request.args.get('limit', default=50, type=int)
    incidents = mission_ctrl.incident_mgr.get_incidents(limit=limit)
    return jsonify({"status": "ok", "count": len(incidents), "incidents": incidents})


@app.route('/api/incidents/latest')
def api_incidents_latest():
    latest = mission_ctrl.incident_mgr.get_latest_incident()
    if latest:
        return jsonify({"status": "ok", "incident": latest})
    return jsonify({"status": "empty", "incident": None})


@app.route('/incidents')
@app.route('/records')
def incidents_view():
    return render_template('incidents.html', config=config.get_all_config())


@app.route('/api/incidents/snapshots/<path:filename>')
def api_incident_snapshot(filename):
    snapshots_dir = mission_ctrl.incident_mgr.snapshots_dir
    return send_from_directory(snapshots_dir, filename)


@app.route('/api/incidents/<incident_id>/delete', methods=['POST', 'DELETE'])
def api_incident_delete(incident_id):
    success = mission_ctrl.incident_mgr.delete_incident(incident_id)
    if mission_ctrl.latest_incident and mission_ctrl.latest_incident.get("id") == incident_id:
        mission_ctrl.latest_incident = mission_ctrl.incident_mgr.get_latest_incident()
    return jsonify({
        "status": "ok" if success else "error",
        "message": f"Incident {incident_id} deleted" if success else "Incident not found"
    })


@app.route('/api/incidents/<incident_id>/rounds/<int:round_idx>/delete', methods=['POST', 'DELETE'])
def api_incident_round_delete(incident_id, round_idx):
    updated = mission_ctrl.incident_mgr.delete_incident_round(incident_id, round_idx)
    if updated is not None:
        if mission_ctrl.latest_incident and mission_ctrl.latest_incident.get("id") == incident_id:
            mission_ctrl.latest_incident = mission_ctrl.incident_mgr.get_latest_incident()
        return jsonify({
            "status": "ok",
            "message": "Round deleted successfully",
            "incident": updated
        })
    return jsonify({"status": "error", "message": "Round or incident not found"}), 404


@app.route('/api/incidents/clear', methods=['POST'])
def api_incidents_clear():
    success = mission_ctrl.incident_mgr.clear_history()
    mission_ctrl.latest_incident = None
    return jsonify({"status": "ok" if success else "error", "message": "Incident records cleared"})


@app.route('/api/incidents/<incident_id>/verify_llm', methods=['POST'])
def api_incident_verify_llm(incident_id):
    """Triggers on-demand LLM verification for a specific recorded incident."""
    incident = mission_ctrl.incident_mgr.get_incident_by_id(incident_id)
    if not incident:
        return jsonify({"status": "error", "message": f"Incident {incident_id} not found"}), 404

    vis_snap = incident.get("latest_visible_snapshot") or incident.get("initial_visible_snapshot", "")
    thm_snap = incident.get("latest_thermal_snapshot") or incident.get("initial_thermal_snapshot", "")

    vis_file = str(mission_ctrl.incident_mgr.snapshots_dir / os.path.basename(vis_snap)) if vis_snap else ""
    thm_file = str(mission_ctrl.incident_mgr.snapshots_dir / os.path.basename(thm_snap)) if thm_snap else ""

    if not os.path.exists(vis_file) or not os.path.exists(thm_file):
        return jsonify({
            "status": "error",
            "message": f"Snapshot files not found on disk ({vis_file} / {thm_file})"
        }), 404

    llm_res = mission_ctrl.llm_verifier.verify_incident(incident, vis_file, thm_file)
    if llm_res.get("status") == "success":
        updated = mission_ctrl.incident_mgr.update_incident_llm_result(incident_id, llm_res)
        return jsonify({
            "status": "ok",
            "message": "LLM Verification completed successfully",
            "llm_verification": llm_res,
            "incident": updated or incident
        })
    else:
        return jsonify({
            "status": "error",
            "message": llm_res.get("message", "LLM verification failed"),
            "detail": llm_res
        }), 500


@app.route('/api/llm/test', methods=['POST'])
def api_llm_test():
    """Tests connectivity to LLM vision models endpoint with provided or default credentials."""
    data = request.json or {}
    api_key = data.get("api_key")
    base_url = data.get("base_url")
    result = mission_ctrl.llm_verifier.test_connection(api_key=api_key, base_url=base_url)
    return jsonify(result)


# ==============================================================================
# Thermal 360 Panorama Studio Routes & APIs
# ==============================================================================
@app.route('/panorama')
def panorama_view():
    """Renders the Thermal 360 Panorama Studio interface."""
    return render_template('panorama.html')


@app.route('/api/panorama/calculate', methods=['POST'])
def api_panorama_calculate():
    """Calculates FOV, steps, and waypoint trajectory without capturing."""
    data = request.get_json() or {}
    az_min = float(data.get('az_min', -90.0))
    az_max = float(data.get('az_max', 90.0))
    alt_min = float(data.get('alt_min', -20.0))
    alt_max = float(data.get('alt_max', 0.0))
    focal_mm = float(data.get('focal_mm', 60.0))
    overlap_pct = float(data.get('overlap_pct', 25.0))
    settle_sec = float(data.get('settle_sec', 1.0))

    plan = panorama_engine.calculate_grid_plan(
        az_min=az_min,
        az_max=az_max,
        alt_min=alt_min,
        alt_max=alt_max,
        focal_mm=focal_mm,
        overlap_pct=overlap_pct,
        settle_sec=settle_sec
    )
    return jsonify(plan)


@app.route('/api/panorama/start', methods=['POST'])
def api_panorama_start():
    """Initiates an automated Thermal 360 panorama capture mission."""
    data = request.get_json() or {}
    az_min = float(data.get('az_min', -90.0))
    az_max = float(data.get('az_max', 90.0))
    alt_min = float(data.get('alt_min', -20.0))
    alt_max = float(data.get('alt_max', 0.0))
    focal_mm = float(data.get('focal_mm', 60.0))
    overlap_pct = float(data.get('overlap_pct', 25.0))
    settle_sec = float(data.get('settle_sec', 1.0))
    user_label = str(data.get('user_label', ''))

    result = panorama_engine.start_panorama_mission(
        az_min=az_min,
        az_max=az_max,
        alt_min=alt_min,
        alt_max=alt_max,
        focal_mm=focal_mm,
        overlap_pct=overlap_pct,
        settle_sec=settle_sec,
        user_label=user_label
    )
    return jsonify(result)


@app.route('/api/panorama/stop', methods=['POST'])
def api_panorama_stop():
    """Aborts current panorama mission."""
    stopped = panorama_engine.stop_panorama_mission()
    return jsonify({"status": "ok" if stopped else "not_running"})


@app.route('/api/panorama/resume', methods=['POST'])
def api_panorama_resume():
    """Resumes the latest interrupted panorama sequence."""
    return jsonify(panorama_engine.resume_panorama_mission())


@app.route('/api/panorama/status', methods=['GET'])
def api_panorama_status():
    """Returns current real-time mission execution progress."""
    return jsonify(panorama_engine.get_status())


@app.route('/api/panorama/save', methods=['POST'])
def api_panorama_save():
    """Save the current grid images and queue an updated seamless mosaic."""
    return jsonify(panorama_engine.save_current_session())


@app.route('/api/panorama/sessions', methods=['GET'])
def api_panorama_sessions():
    """Lists all completed panorama capture sessions stored on disk."""
    return jsonify(panorama_engine.list_sessions())


@app.route('/api/panorama/image/<session_id>/<path:filename>')
def api_panorama_image(session_id, filename):
    """Serves raw captured frames or stitched panorama images from session directories."""
    session_dir = BASE_DIR / "panoramas" / session_id
    file_path = session_dir / filename
    if not file_path.exists():
        return jsonify({"error": "File not found"}), 404
    return send_file(str(file_path))


@app.route('/api/panorama/session/<session_id>', methods=['DELETE', 'POST'])
def api_panorama_delete_session(session_id):
    """Deletes a panorama session and all associated files from disk."""
    success = panorama_engine.delete_session(session_id)
    return jsonify({
        "status": "ok" if success else "error",
        "deleted": success,
        "session_id": session_id
    })


@app.route('/api/panorama/restitch/<session_id>', methods=['POST'])
def api_panorama_restitch(session_id):
    """Re-stitches an existing panorama session using the upgraded Spherical 3D Ray Warper."""
    data = request.get_json() or {}
    enable_align = bool(data.get('enable_align', True))
    result = panorama_engine.restitch_session(session_id, enable_alignment_refinement=enable_align)
    return jsonify(result)


def main():
    # Start NCNN AI Worker Thread
    t_ai = threading.Thread(target=ncnn_ai_worker, daemon=True)
    t_ai.start()

    # Start Frame Ingest Publisher Thread
    frame_publisher.start()

    logger.info(f"🔥 Starting Integrated Fire Surveillance System on http://{config.SERVER_HOST}:{config.SERVER_PORT}")
    app.run(host=config.SERVER_HOST, port=config.SERVER_PORT, debug=False, threaded=True)


if __name__ == '__main__':
    main()
