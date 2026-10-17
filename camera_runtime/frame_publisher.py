"""
Frame Publisher Module (Camera Frame Ingest API Client)
Publishes Thermal & Visible camera frames to the Mount Agent / Central Surveillance Server
via HTTP Compatibility API (POST /api/camera-stream/frame/<camera>?source=live).
"""

import time
import json
import logging
import datetime
import threading
from typing import Optional, Dict, Any, List
import requests

try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = None
    np = None

logger = logging.getLogger("FramePublisher")


class FramePublisher:
    """
    Background worker that periodically pushes the latest frames from
    Thermal and Visible cameras to the central Ingest API server.
    """

    def __init__(
        self,
        camera_mgr,
        cfg: Optional[dict] = None,
        ptz_ctrl: Optional[Any] = None,
        mission_ctrl: Optional[Any] = None,
        state: Optional[dict] = None,
        get_detections_fn: Optional[Any] = None,
        overlay_fn: Optional[Any] = None,
    ):
        self.camera_mgr = camera_mgr
        self.cfg = cfg or {}
        self.ptz_ctrl = ptz_ctrl
        self.mission_ctrl = mission_ctrl
        self.state = state
        self.get_detections_fn = get_detections_fn
        self.overlay_fn = overlay_fn
        self.annotate_thermal = bool(self.cfg.get("annotate_thermal", False))

        # Config parameters
        self.enabled = bool(self.cfg.get("enabled", False))
        self.server_url = str(self.cfg.get("server_url", "http://192.168.1.105:8000")).rstrip("/")
        configured_fps = self.cfg.get("target_fps")
        if configured_fps is None:
            legacy_interval = max(1.0 / 60.0, float(self.cfg.get("interval_sec", 1.0 / 15.0)))
            configured_fps = 1.0 / legacy_interval
        self.configured_target_fps = max(1.0, min(60.0, float(configured_fps)))
        self.target_fps = self.configured_target_fps
        self.interval_sec = 1.0 / self.target_fps
        self.source = str(self.cfg.get("source", "live"))
        self.cameras: List[str] = self.cfg.get("cameras", ["thermal", "visible"])
        self.adaptive = bool(self.cfg.get("adaptive", False))
        self.policy_url = str(
            self.cfg.get("policy_url") or f"{self.server_url}/api/stream/policy"
        ).strip()
        self.policy_poll_sec = max(1.0, min(30.0, float(self.cfg.get("policy_poll_sec", 2.0))))
        self.min_fps = max(1.0, min(15.0, float(self.cfg.get("min_fps", 3.0))))

        self.running = False
        self._threads: Dict[str, threading.Thread] = {}
        self._policy_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._policy_lock = threading.Lock()
        self._policy_status = "DISABLED" if not self.adaptive else "WAITING"

        # Telemetry & stats tracking
        self.seq_counters: Dict[str, int] = {"thermal": 0, "visible": 0}
        self.stats = {
            "thermal": {"sent": 0, "errors": 0, "stale": 0, "skipped": 0, "last_status": "IDLE", "last_time": None},
            "visible": {"sent": 0, "errors": 0, "stale": 0, "skipped": 0, "last_status": "IDLE", "last_time": None}
        }
        self._stats_lock = threading.Lock()
        self._metadata_lock = threading.Lock()
        self._latest_metadata: Dict[str, Dict[str, Any]] = {}

    def start(self):
        """Start one independently paced publisher worker per camera."""
        if self.running and any(thread.is_alive() for thread in self._threads.values()):
            return
        self.running = True
        self._stop_event.clear()
        self._threads = {}
        self._policy_thread = threading.Thread(
            target=self._adaptive_policy_worker,
            daemon=True,
            name="FramePublisher-AdaptivePolicy",
        )
        self._policy_thread.start()
        for cam_id in self.cameras:
            thread = threading.Thread(
                target=self._publish_camera_worker,
                args=(cam_id,),
                daemon=True,
                name=f"FramePublisher-{cam_id}",
            )
            self._threads[cam_id] = thread
            thread.start()
        logger.info(
            f"🚀 FramePublisher workers started (Server: {self.server_url}, "
            f"Target: {self.target_fps:.2f} FPS/camera, Enabled: {self.enabled})"
        )

    def stop(self):
        """Stop all publisher workers."""
        self.running = False
        self._stop_event.set()
        for thread in self._threads.values():
            if thread.is_alive():
                thread.join(timeout=2.0)
        self._threads = {}
        if self._policy_thread and self._policy_thread.is_alive():
            self._policy_thread.join(timeout=2.0)
        self._policy_thread = None
        logger.info("🛑 FramePublisher workers stopped.")

    def update_config(self, new_cfg: dict):
        """Updates runtime configuration safely."""
        if "enabled" in new_cfg:
            self.enabled = bool(new_cfg["enabled"])
        if "server_url" in new_cfg:
            self.server_url = str(new_cfg["server_url"]).rstrip("/")
        if "target_fps" in new_cfg:
            self.configured_target_fps = max(1.0, min(60.0, float(new_cfg["target_fps"])))
            with self._policy_lock:
                self.target_fps = (
                    min(self.target_fps, self.configured_target_fps)
                    if self.adaptive else self.configured_target_fps
                )
                self.interval_sec = 1.0 / self.target_fps
        elif "interval_sec" in new_cfg:
            interval = max(1.0 / 60.0, float(new_cfg["interval_sec"]))
            self.configured_target_fps = max(1.0, min(60.0, 1.0 / interval))
            with self._policy_lock:
                self.target_fps = self.configured_target_fps
                self.interval_sec = 1.0 / self.target_fps
        if "adaptive" in new_cfg:
            self.adaptive = bool(new_cfg["adaptive"])
            if not self.adaptive:
                with self._policy_lock:
                    self.target_fps = self.configured_target_fps
                    self.interval_sec = 1.0 / self.target_fps
                self._policy_status = "DISABLED"
            else:
                self._policy_status = "WAITING"
        if "policy_url" in new_cfg:
            self.policy_url = str(new_cfg["policy_url"]).strip()
        if "policy_poll_sec" in new_cfg:
            self.policy_poll_sec = max(1.0, min(30.0, float(new_cfg["policy_poll_sec"])))
        if "min_fps" in new_cfg:
            self.min_fps = max(1.0, min(15.0, float(new_cfg["min_fps"])))
        if "source" in new_cfg:
            self.source = str(new_cfg["source"])
        if "cameras" in new_cfg and isinstance(new_cfg["cameras"], list):
            self.cameras = new_cfg["cameras"]
        if "annotate_thermal" in new_cfg:
            self.annotate_thermal = bool(new_cfg["annotate_thermal"])

        logger.info(
            f"🔄 FramePublisher config updated: Enabled={self.enabled}, URL={self.server_url}, "
            f"Target={self.target_fps:.2f} FPS/camera, AnnotateThermal={self.annotate_thermal}"
        )

    def get_status(self) -> dict:
        """Returns current publisher status and transmission statistics."""
        with self._stats_lock:
            return {
                "enabled": self.enabled,
                "annotate_thermal": self.annotate_thermal,
                "server_url": self.server_url,
                "interval_sec": self.interval_sec,
                "target_fps": self.target_fps,
                "configured_target_fps": self.configured_target_fps,
                "adaptive": self.adaptive,
                "policy_url": self.policy_url,
                "policy_status": self._policy_status,
                "source": self.source,
                "is_running": self.running and bool(self._threads) and all(
                    thread.is_alive() for thread in self._threads.values()
                ),
                "stats": {
                    "thermal": dict(self.stats.get("thermal", {})),
                    "visible": dict(self.stats.get("visible", {}))
                }
            }

    def build_camera_metadata(
        self,
        cam_id: str,
        snapshot: dict,
        producer_sequence: Optional[int] = None,
    ) -> dict:
        """Build and retain frame metadata shared by publishing and Camera View."""
        capture_sequence = int(snapshot["sequence"])
        if (
            snapshot.get("source") != "live"
            or snapshot.get("simulated") is not False
            or snapshot.get("source_verified") is not True
        ):
            raise ValueError(
                f"CAMERA_SOURCE_INVALID: {cam_id} frame was not verified as live RTSP capture"
            )
        if producer_sequence is None:
            producer_sequence = capture_sequence

        cam = self.camera_mgr.get_camera(cam_id)
        zoom_info = cam.get_zoom_info() if cam and hasattr(cam, "get_zoom_info") else {}
        is_zooming = bool(getattr(cam, "is_zooming", False))

        if self.ptz_ctrl and hasattr(self.ptz_ctrl, "get_position"):
            az, alt = self.ptz_ctrl.get_position()
        else:
            az, alt = 0.0, 0.0

        mission_state = (
            self.mission_ctrl.state
            if self.mission_ctrl and hasattr(self.mission_ctrl, "state")
            else "IDLE"
        )
        scan_mode = (
            self.mission_ctrl.cfg.get("scan_mode", "CONTINUOUS")
            if self.mission_ctrl and hasattr(self.mission_ctrl, "cfg")
            else "CONTINUOUS"
        )
        is_paused = bool(getattr(self.mission_ctrl, "is_paused", False))
        curr_wp = int(getattr(self.mission_ctrl, "current_waypoint_idx", 0))
        total_wp = int(getattr(self.mission_ctrl, "total_waypoints_count", 0))
        curr_layer = int(getattr(self.mission_ctrl, "current_alt_idx", 0)) + 1
        alt_layers = getattr(self.mission_ctrl, "alt_layers", [])
        total_layers = len(alt_layers) if alt_layers else 1

        fire_detected = (
            bool(self.state.get("fire_detected", False))
            if isinstance(self.state, dict)
            else False
        )

        # Collect active detections for telemetry metadata
        dets_for_meta = []
        if cam_id == "thermal":
            if callable(self.get_detections_fn):
                try:
                    dets_for_meta = self.get_detections_fn() or []
                except Exception:
                    dets_for_meta = []
            elif isinstance(self.state, dict) and "detections" in self.state:
                dets_for_meta = self.state.get("detections") or []

        serialized_dets = []
        for d in dets_for_meta:
            if isinstance(d, dict) and "box" in d:
                serialized_dets.append({
                    "box": [int(x) for x in d["box"]],
                    "score": round(float(d.get("score", 0.0)), 3),
                    "state": str(d.get("state", "CONFIRMED_FIRE")),
                })

        if serialized_dets:
            fire_detected = True

        metadata = {
            "captured_at": snapshot.get("captured_at") or datetime.datetime.now(
                datetime.timezone.utc
            ).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "camera_id": cam_id,
            "source": "live",
            "recording_source": "live",
            "simulated": False,
            "source_verified": True,
            "width": int(snapshot["width"]),
            "height": int(snapshot["height"]),
            "producer_sequence": int(producer_sequence),
            "capture_sequence": capture_sequence,
            "focal_length_mm": float(zoom_info.get("focal_mm", 31.0 if cam_id == "thermal" else 5.1)),
            "zoom_ratio": float(zoom_info.get("zoom_ratio", 0.0)),
            "zoom_pct": float(zoom_info.get("zoom_pct", 0.0)),
            "zoom_x": float(zoom_info.get("zoom_x", 1.0)),
            "fov_h_deg": float(zoom_info.get("fov_h", 14.2 if cam_id == "thermal" else 51.69)),
            "fov_v_deg": float(zoom_info.get("fov_v", 11.4 if cam_id == "thermal" else 29.58)),
            "fov_d_deg": float(zoom_info.get("fov_d", 18.2 if cam_id == "thermal" else 59.56)),
            "is_zooming": is_zooming,
            "azimuth_deg": round(float(az), 2),
            "altitude_deg": round(float(alt), 2),
            "mission_state": mission_state,
            "scan_mode": scan_mode,
            "is_paused": is_paused,
            "current_waypoint": curr_wp,
            "total_waypoints": total_wp,
            "current_layer": curr_layer,
            "total_layers": total_layers,
            "fire_detected": fire_detected,
            "detections": serialized_dets,
            "annotated": bool(serialized_dets and self.annotate_thermal and callable(self.overlay_fn)),
        }

        with self._metadata_lock:
            self._latest_metadata[cam_id] = dict(metadata)
        return metadata

    def get_camera_metadata(self, cam_id: str, refresh: bool = True) -> Optional[dict]:
        """Return metadata for the latest captured frame of one camera."""
        if cam_id not in ("thermal", "visible"):
            return None

        if refresh:
            cam = self.camera_mgr.get_camera(cam_id)
            if cam and hasattr(cam, "get_latest_encoded_frame"):
                snapshot = cam.get_latest_encoded_frame()
                if snapshot:
                    return self.build_camera_metadata(cam_id, snapshot)

        with self._metadata_lock:
            metadata = self._latest_metadata.get(cam_id)
            return dict(metadata) if metadata else None

    def _apply_adaptive_target(self, requested_fps: float) -> float:
        """Apply the Station policy without exceeding the configured camera cap."""
        effective = max(self.min_fps, min(self.configured_target_fps, float(requested_fps)))
        with self._policy_lock:
            changed = abs(effective - self.target_fps) > 1e-6
            self.target_fps = effective
            self.interval_sec = 1.0 / effective
        if changed:
            logger.info(
                "📶 Adaptive camera publish cadence changed to %.2f FPS/camera",
                effective,
            )
        return effective

    def _adaptive_policy_worker(self):
        """Follow the Mount Station's queue-controlled FPS policy."""
        session = requests.Session()
        try:
            while self.running and not self._stop_event.is_set():
                if not self.adaptive:
                    self._policy_status = "DISABLED"
                    self._stop_event.wait(self.policy_poll_sec)
                    continue
                try:
                    response = session.get(self.policy_url, timeout=1.5)
                    response.raise_for_status()
                    payload = response.json()
                    if not payload.get("ok") or not payload.get("adaptive"):
                        raise ValueError("Station returned no active adaptive policy")
                    self._apply_adaptive_target(float(payload["target_frame_rate"]))
                    self._policy_status = "SYNCED"
                except (requests.exceptions.RequestException, ValueError, TypeError, KeyError) as exc:
                    self._policy_status = f"DEGRADED: {type(exc).__name__}"
                self._stop_event.wait(self.policy_poll_sec)
        finally:
            session.close()

    def _publish_camera_worker(self, cam_id: str):
        """Publish new capture events, capped by the configured target FPS."""
        session = requests.Session()
        last_observed_sequence = 0
        last_sent_sequence = 0
        next_publish_deadline = time.monotonic()
        try:
            while self.running:
                if not self.enabled or not self.server_url:
                    self._stop_event.wait(0.1)
                    continue

                cam = self.camera_mgr.get_camera(cam_id)
                if not cam:
                    self._stop_event.wait(0.5)
                    continue

                waiter = getattr(cam, "wait_for_encoded_frame", None)
                if callable(waiter):
                    snapshot = waiter(last_observed_sequence, timeout=1.0)
                else:
                    self._stop_event.wait(min(0.02, self.interval_sec))
                    snapshot = cam.get_latest_encoded_frame()
                if not self.running:
                    break
                if not snapshot:
                    with self._stats_lock:
                        self.stats[cam_id]["stale"] += 1
                    continue

                capture_sequence = int(snapshot["sequence"])
                if capture_sequence <= last_observed_sequence:
                    with self._stats_lock:
                        self.stats[cam_id]["stale"] += 1
                    continue
                last_observed_sequence = capture_sequence

                with self._policy_lock:
                    effective_target_fps = self.target_fps
                interval = 1.0 / effective_target_fps
                now = time.monotonic()
                camera_target_fps = float(getattr(cam, "target_fps", self.target_fps))
                should_rate_limit = effective_target_fps + 1e-6 < camera_target_fps
                if should_rate_limit and now < next_publish_deadline:
                    with self._stats_lock:
                        self.stats[cam_id]["skipped"] += 1
                    continue
                if should_rate_limit:
                    periods = int((now - next_publish_deadline) // interval) + 1
                    next_publish_deadline += periods * interval
                else:
                    next_publish_deadline = now + interval
                last_sent_sequence = self._send_single_camera_frame(
                    cam_id, session, last_sent_sequence, snapshot=snapshot
                )

        finally:
            session.close()

    def _send_single_camera_frame(
        self, cam_id: str, session: requests.Session, last_capture_sequence: int,
        snapshot: Optional[dict] = None,
    ) -> int:
        """Send a new encoded camera frame once and return its capture sequence."""
        if not snapshot:
            with self._stats_lock:
                self.stats[cam_id]["stale"] += 1
            return last_capture_sequence
        capture_sequence = int(snapshot["sequence"])
        if capture_sequence <= last_capture_sequence:
            with self._stats_lock:
                self.stats[cam_id]["stale"] += 1
            return last_capture_sequence

        jpeg_bytes = snapshot["jpeg"]

        # Check if we should overlay detections onto thermal frame
        if cam_id == "thermal" and self.annotate_thermal and callable(self.overlay_fn):
            dets = []
            if callable(self.get_detections_fn):
                try:
                    dets = self.get_detections_fn() or []
                except Exception:
                    dets = []
            elif isinstance(self.state, dict) and "detections" in self.state:
                dets = self.state.get("detections") or []

            if dets:
                cam = self.camera_mgr.get_camera(cam_id)
                bgr_frame = None
                if cam and hasattr(cam, "get_latest_frame"):
                    bgr_frame, _ = cam.get_latest_frame()
                if bgr_frame is None and "bgr" in snapshot and snapshot["bgr"] is not None:
                    bgr_frame = snapshot["bgr"]
                if bgr_frame is None and cv2 is not None:
                    try:
                        bgr_frame = cv2.imdecode(np.frombuffer(jpeg_bytes, np.uint8), cv2.IMREAD_COLOR)
                    except Exception:
                        pass

                if bgr_frame is not None:
                    try:
                        annotated = self.overlay_fn(bgr_frame, dets)
                        if cv2 is not None:
                            ret, enc_jpeg = cv2.imencode('.jpg', annotated, [cv2.IMWRITE_JPEG_QUALITY, 75])
                            if ret:
                                jpeg_bytes = enc_jpeg.tobytes()
                    except Exception as e:
                        logger.warning(f"Failed to overlay detections on {cam_id} frame: {e}")

        self.seq_counters[cam_id] = self.seq_counters.get(cam_id, 0) + 1
        seq = self.seq_counters[cam_id]

        endpoint = f"{self.server_url}/api/camera-stream/frame/{cam_id}?source={self.source}"
        try:
            metadata = self.build_camera_metadata(
                cam_id,
                snapshot,
                producer_sequence=seq,
            )
        except ValueError as exc:
            with self._stats_lock:
                self.stats[cam_id]["errors"] += 1
                self.stats[cam_id]["last_status"] = str(exc)
                self.stats[cam_id]["last_time"] = None
            logger.error("Rejected %s frame: %s", cam_id, exc)
            return capture_sequence

        headers = {
            "Content-Type": "image/jpeg",
            "X-Camera-Metadata": json.dumps(metadata)
        }

        iso_now = metadata["captured_at"]

        try:
            resp = session.post(endpoint, data=jpeg_bytes, headers=headers, timeout=1.5)
            with self._stats_lock:
                if resp.status_code == 202:
                    self.stats[cam_id]["sent"] += 1
                    self.stats[cam_id]["last_status"] = "OK (202)"
                    self.stats[cam_id]["last_time"] = iso_now
                else:
                    self.stats[cam_id]["errors"] += 1
                    self.stats[cam_id]["last_status"] = f"HTTP {resp.status_code}"
                    self.stats[cam_id]["last_time"] = iso_now
        except requests.exceptions.RequestException as e:
            with self._stats_lock:
                self.stats[cam_id]["errors"] += 1
                self.stats[cam_id]["last_status"] = f"Error: {type(e).__name__}"
                self.stats[cam_id]["last_time"] = iso_now
        return capture_sequence
