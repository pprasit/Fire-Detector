"""
Camera Manager Module
Handles RTSP Video Streaming (PyAV) for Dual Cameras (Thermal & Visible)
and ONVIF Continuous Zoom, Absolute Zoom, and Focus Control with Sharpness Verification.
"""

import os
import time
import math
import threading
import logging
import io
import json
import requests
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Tuple
import av
import cv2
import numpy as np
from PIL import Image
from onvif import ONVIFCamera

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CameraManager")


def advance_frame_deadline(now: float, next_deadline: float, interval: float) -> Tuple[bool, float]:
    """Select source frames at a stable average cadence without accumulating lag."""
    if now < next_deadline:
        return False, next_deadline
    periods = int((now - next_deadline) // interval) + 1
    return True, next_deadline + periods * interval


class CameraDevice:
    """Represents a single IP camera with ONVIF and RTSP video grabber."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.cam_id = cfg["id"]
        self.name = cfg["name"]
        self.ip = cfg["ip"]
        self.onvif_port = cfg.get("onvif_port", 80)
        self.username = cfg["username"]
        self.password = cfg["password"]
        self.rtsp_url = cfg["rtsp_url"]

        self.onvif_connected = False
        self.stream_connected = False
        self.cam = None
        self.ptz = None
        self.imaging = None
        self.media = None
        self.profile_token = None
        self.video_source_token = None

        self.latest_bgr: Optional[np.ndarray] = None
        self.latest_jpeg: Optional[bytes] = None
        self.fps: float = 0.0
        self.frame_count: int = 0
        self.last_frame_time: float = 0.0
        self.latest_frame_sequence: int = 0
        self.latest_captured_at: Optional[str] = None
        self.latest_width: int = 0
        self.latest_height: int = 0
        self._frame_lock = threading.Lock()
        self._frame_ready = threading.Condition(self._frame_lock)
        self._running = True

        # Zoom & Focus State
        self.is_zooming = False
        self.current_zoom_ratio = 0.0  # 0.0 (Wide) to 1.0 (Tele)
        self.min_focal_mm = float(cfg.get("min_focal_mm", 31.0 if self.cam_id == "thermal" else 5.1))
        self.max_focal_mm = float(cfg.get("max_focal_mm", 155.0 if self.cam_id == "thermal" else 102.0))
        self.wide_h_fov = float(cfg.get("wide_h_fov_deg", 14.2 if self.cam_id == "thermal" else 51.69))
        self.tele_h_fov = float(cfg.get("tele_h_fov_deg", 2.8 if self.cam_id == "thermal" else 3.12))
        self.wide_v_fov = float(cfg.get("wide_v_fov_deg", 11.4 if self.cam_id == "thermal" else 29.58))
        self.tele_v_fov = float(cfg.get("tele_v_fov_deg", 2.3 if self.cam_id == "thermal" else 1.75))
        self.wide_d_fov = float(cfg.get("wide_d_fov_deg", 18.2 if self.cam_id == "thermal" else 59.56))
        self.tele_d_fov = float(cfg.get("tele_d_fov_deg", 3.6 if self.cam_id == "thermal" else 3.58))

        self.target_fps = float(cfg.get("target_fps", 25.0 if self.cam_id == "thermal" else 15.0))
        self.min_frame_interval = 1.0 / self.target_fps

        # Thermal Graphic Options & Auto Brightness
        self.thermal_imaging_cfg = dict(cfg.get("imaging", {}))
        self._current_brightness = int(self.thermal_imaging_cfg.get("current_brightness", 64))
        self._current_contrast = int(self.thermal_imaging_cfg.get("current_contrast", 128))
        self._auto_brightness_last_check = 0.0
        self._cgi_token = None
        self._cgi_token_time = 0.0

        # 1. Initialize ONVIF & Thermal Power in background thread to prevent blocking server startup
        threading.Thread(target=self._init_hardware_async, daemon=True).start()

        # 2. Start RTSP streaming
        self.start_stream()

        # 3. Start Auto-Brightness background daemon for Thermal camera
        if self.cam_id == "thermal":
            threading.Thread(target=self._auto_brightness_loop, daemon=True).start()

    def _init_hardware_async(self):
        """Asynchronously connects ONVIF and powers on thermal sensor."""
        self.init_onvif()
        if self.cam_id == "thermal":
            self.set_thermal_power(enable=True)
            # Apply initial imaging profile
            self.update_imaging_config(self.thermal_imaging_cfg)

    def _get_cgi_token(self) -> Optional[str]:
        """Acquires or returns cached session token for camera CGI commands."""
        now = time.time()
        if self._cgi_token and (now - self._cgi_token_time < 300.0):
            return self._cgi_token

        url = f"http://{self.ip}/cgi-bin/proc.cgi"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "User-Agent": "Mozilla/5.0"
        }
        login_payload = {
            "cmd": "userLogin",
            "param": {
                "username": self.username,
                "password": "38566bc393f8a5385cf9527dcf9211cb"
            }
        }
        try:
            res = requests.post(url, data=json.dumps(login_payload), headers=headers, timeout=2.5)
            if res.status_code == 200:
                token = res.json().get("param", {}).get("token")
                if token:
                    self._cgi_token = token
                    self._cgi_token_time = now
                    return token
        except Exception as e:
            logger.warning(f"[{self.cam_id}] CGI login failed: {e}")
        return None

    def set_thermal_power(self, enable: bool = True) -> bool:
        """Sends CGI command to turn Thermal Camera IR/Sensor Power ON (1) or OFF (0)."""
        if self.cam_id != "thermal":
            return True

        token = self._get_cgi_token()
        if not token:
            logger.warning(f"[{self.cam_id}] Could not acquire token for thermal power command.")
            return False

        url = f"http://{self.ip}/cgi-bin/proc.cgi"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "User-Agent": "Mozilla/5.0"
        }
        power_cmd = {
            "cmd": "ptzSetPowerIrEnable",
            "param": {
                "token": token,
                "powerIr": 1 if enable else 0
            }
        }
        try:
            res_pwr = requests.post(url, data=json.dumps(power_cmd), headers=headers, timeout=2.5)
            if res_pwr.status_code == 200 and res_pwr.json().get("param", {}).get("ackvalue") == 100:
                state_str = "ON" if enable else "OFF"
                logger.info(f"[{self.cam_id}] Thermal Sensor IR Power successfully switched to {state_str}!")
                time.sleep(1.0)  # Short delay to allow sensor warm-up
                return True
            else:
                self._cgi_token = None
                logger.warning(f"[{self.cam_id}] ptzSetPowerIrEnable returned: {res_pwr.text}")
        except Exception as e:
            logger.error(f"[{self.cam_id}] Failed to switch Thermal IR Power: {e}")
        return False

    def get_thermal_graphic_options(self) -> dict:
        """Queries live graphic parameters (brightness, contrast, mode) from thermal camera."""
        if self.cam_id != "thermal":
            return {}
        token = self._get_cgi_token()
        if not token:
            return {"brightness": self._current_brightness, "contrast": self._current_contrast}
        url = f"http://{self.ip}/cgi-bin/proc.cgi"
        headers = {"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8", "X-Requested-With": "XMLHttpRequest"}
        try:
            req = {"cmd": "imgGetCfg", "param": {"token": token, "mode": 0}}
            res = requests.post(url, data=json.dumps(req), headers=headers, timeout=2.5)
            if res.status_code == 200:
                p = res.json().get("param", {})
                if p.get("ackvalue") == 100:
                    b = int(p.get("brightness_auto", p.get("brightness", self._current_brightness)))
                    c = int(p.get("contrast_auto", p.get("contrast", self._current_contrast)))
                    self._current_brightness = b
                    self._current_contrast = c
                    return {
                        "brightness": b,
                        "contrast": c,
                        "hist_mode": p.get("histMode", 2),
                        "mode": p.get("mode", 0)
                    }
        except Exception as e:
            logger.warning(f"[{self.cam_id}] get_thermal_graphic_options error: {e}")
        return {"brightness": self._current_brightness, "contrast": self._current_contrast}

    def set_thermal_graphic_options(self, brightness: int, contrast: int) -> bool:
        """Sets thermal camera brightness and contrast via CGI API."""
        if self.cam_id != "thermal":
            return False
        b = max(0, min(255, int(brightness)))
        c = max(0, min(255, int(contrast)))
        token = self._get_cgi_token()
        if not token:
            return False
        url = f"http://{self.ip}/cgi-bin/proc.cgi"
        headers = {"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8", "X-Requested-With": "XMLHttpRequest"}
        try:
            req = {
                "cmd": "imgSetCfg",
                "param": {
                    "token": token,
                    "mode": 0,
                    "brightness_auto": b,
                    "contrast_auto": c
                }
            }
            res = requests.post(url, data=json.dumps(req), headers=headers, timeout=2.5)
            if res.status_code == 200 and res.json().get("param", {}).get("ackvalue") == 100:
                logger.info(f"[{self.cam_id}] Graphic options set successfully -> Brightness: {b}, Contrast: {c}")
                self._current_brightness = b
                self._current_contrast = c
                self.thermal_imaging_cfg["current_brightness"] = b
                self.thermal_imaging_cfg["current_contrast"] = c
                return True
            else:
                self._cgi_token = None
        except Exception as e:
            logger.warning(f"[{self.cam_id}] set_thermal_graphic_options error: {e}")
        return False

    def update_imaging_config(self, new_cfg: dict):
        """Updates thermal imaging configuration and immediately applies changes."""
        if self.cam_id != "thermal":
            return
        self.thermal_imaging_cfg.update(new_cfg)
        auto_mode = self.thermal_imaging_cfg.get("auto_mode", "SCHEDULE").upper()
        if auto_mode == "OFF":
            b = int(self.thermal_imaging_cfg.get("current_brightness", self._current_brightness))
            c = int(self.thermal_imaging_cfg.get("current_contrast", self._current_contrast))
            self.set_thermal_graphic_options(b, c)
        elif auto_mode == "SCHEDULE":
            self._evaluate_schedule_brightness(force=True)
        elif auto_mode == "DYNAMIC":
            self._evaluate_dynamic_brightness(force=True)

    def _auto_brightness_loop(self):
        """Background daemon periodically checking and adjusting thermal brightness."""
        time.sleep(6.0)
        while self._running:
            try:
                auto_mode = self.thermal_imaging_cfg.get("auto_mode", "SCHEDULE").upper()
                if auto_mode == "SCHEDULE":
                    self._evaluate_schedule_brightness()
                elif auto_mode == "DYNAMIC":
                    self._evaluate_dynamic_brightness()
            except Exception as e:
                logger.debug(f"[AutoBrightness] Loop error: {e}")
            time.sleep(10.0)

    def _evaluate_schedule_brightness(self, force: bool = False):
        now_dt = datetime.now()
        now_str = now_dt.strftime("%H:%M")
        day_start = self.thermal_imaging_cfg.get("schedule_day_start", "07:30")
        night_start = self.thermal_imaging_cfg.get("schedule_night_start", "17:30")

        if day_start <= now_str < night_start:
            target_b = int(self.thermal_imaging_cfg.get("day_brightness", 46))
            target_c = int(self.thermal_imaging_cfg.get("day_contrast", 135))
            period = "DAY"
        else:
            target_b = int(self.thermal_imaging_cfg.get("night_brightness", 64))
            target_c = int(self.thermal_imaging_cfg.get("night_contrast", 128))
            period = "NIGHT"

        if force or (target_b != self._current_brightness) or (target_c != self._current_contrast):
            logger.info(f"☀️ [AutoBrightness-Schedule] Setting {period} profile -> Brightness: {target_b}, Contrast: {target_c} (Time: {now_str})")
            if self.set_thermal_graphic_options(target_b, target_c):
                self._current_brightness = target_b
                self._current_contrast = target_c
                self.thermal_imaging_cfg["current_brightness"] = target_b
                self.thermal_imaging_cfg["current_contrast"] = target_c

    def _evaluate_dynamic_brightness(self, force: bool = False):
        now = time.time()
        interval = float(self.thermal_imaging_cfg.get("dynamic_check_interval_sec", 20.0))
        if not force and (now - self._auto_brightness_last_check < interval):
            return
        self._auto_brightness_last_check = now

        with self._frame_lock:
            frame = self.latest_bgr
            if frame is None:
                return
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        scene_luma = float(np.percentile(gray, 75))
        target_luma = float(self.thermal_imaging_cfg.get("dynamic_target_luma", 35.0))
        min_b = int(self.thermal_imaging_cfg.get("dynamic_min_brightness", 38))
        max_b = int(self.thermal_imaging_cfg.get("dynamic_max_brightness", 64))

        new_b = self._current_brightness
        if scene_luma > target_luma + 8.0 and self._current_brightness > min_b:
            new_b = max(min_b, self._current_brightness - 3)
        elif scene_luma < target_luma - 8.0 and self._current_brightness < max_b:
            new_b = min(max_b, self._current_brightness + 3)

        if force or (new_b != self._current_brightness):
            logger.info(f"☀️ [AutoBrightness-Dynamic] Scene Luma={scene_luma:.1f} (Target={target_luma}) -> Adjusting Brightness: {self._current_brightness} -> {new_b}")
            c = int(self.thermal_imaging_cfg.get("day_contrast", 135)) if new_b < 55 else int(self.thermal_imaging_cfg.get("night_contrast", 128))
            if self.set_thermal_graphic_options(new_b, c):
                self._current_brightness = new_b
                self._current_contrast = c
                self.thermal_imaging_cfg["current_brightness"] = new_b
                self.thermal_imaging_cfg["current_contrast"] = c

    def get_zoom_info(self) -> dict:
        """Returns current focal length (mm), zoom percentage, optical zoom factor, and FOV."""
        # Try reading real ONVIF Status if available
        if self.ptz and self.profile_token:
            try:
                status = self.ptz.GetStatus({'ProfileToken': self.profile_token})
                if hasattr(status, 'Position') and hasattr(status.Position, 'Zoom') and status.Position.Zoom is not None:
                    self.current_zoom_ratio = max(0.0, min(1.0, float(status.Position.Zoom.x)))
            except Exception:
                pass

        focal_mm = self.min_focal_mm + (self.current_zoom_ratio * (self.max_focal_mm - self.min_focal_mm))
        zoom_x = (focal_mm / self.min_focal_mm) if self.min_focal_mm > 0 else 1.0

        # Calculate horizontal, vertical, and diagonal FOV based on exact optical trigonometry:
        # tan(FOV/2) = (f_wide / f) * tan(FOV_wide / 2)
        fov_h = self._calculate_fov(focal_mm, self.min_focal_mm, self.wide_h_fov)
        fov_v = self._calculate_fov(focal_mm, self.min_focal_mm, self.wide_v_fov)
        fov_d = self._calculate_fov(focal_mm, self.min_focal_mm, self.wide_d_fov)

        return {
            "zoom_ratio": round(self.current_zoom_ratio, 2),
            "zoom_pct": round(self.current_zoom_ratio * 100.0, 1),
            "focal_mm": round(focal_mm, 1),
            "zoom_x": round(zoom_x, 1),
            "fov_h": round(fov_h, 2),
            "fov_v": round(fov_v, 2),
            "fov_d": round(fov_d, 2)
        }

    @property
    def current_focal_mm(self) -> float:
        """Returns current estimated or measured focal length in mm."""
        return float(self.min_focal_mm + (self.current_zoom_ratio * (self.max_focal_mm - self.min_focal_mm)))

    @staticmethod
    def _calculate_fov(focal_mm: float, wide_focal_mm: float, wide_fov_deg: float) -> float:
        """
        Calculates exact optical FOV at a given focal length using optical trigonometry:
        tan(FOV / 2) = (wide_focal_mm / focal_mm) * tan(wide_fov_deg / 2)
        FOV = 2 * arctan(...)
        """
        if focal_mm <= 0 or wide_focal_mm <= 0 or wide_fov_deg <= 0:
            return wide_fov_deg
        half_wide_rad = math.radians(wide_fov_deg / 2.0)
        tan_half = (wide_focal_mm / focal_mm) * math.tan(half_wide_rad)
        return 2.0 * math.degrees(math.atan(tan_half))

    @staticmethod
    def _calculate_focal_from_fov(target_fov_deg: float, wide_focal_mm: float, wide_fov_deg: float) -> float:
        """
        Calculates required focal length (mm) to achieve target FOV (degrees):
        tan(FOV_target / 2) = (wide_focal_mm / focal_mm) * tan(wide_fov_deg / 2)
        focal_mm = wide_focal_mm * (tan(wide_fov_deg / 2) / tan(FOV_target / 2))
        """
        if target_fov_deg <= 0 or wide_focal_mm <= 0 or wide_fov_deg <= 0:
            return wide_focal_mm
        half_target_rad = math.radians(target_fov_deg / 2.0)
        half_wide_rad = math.radians(wide_fov_deg / 2.0)
        tan_target = math.tan(half_target_rad)
        if tan_target <= 0:
            return wide_focal_mm
        return float(wide_focal_mm * (math.tan(half_wide_rad) / tan_target))

    def calculate_focal_for_fov(self, target_fov_deg: float) -> float:
        """Calculates and clamps focal length in mm to achieve target horizontal FOV."""
        raw_focal = self._calculate_focal_from_fov(target_fov_deg, self.min_focal_mm, self.wide_h_fov)
        return max(self.min_focal_mm, min(self.max_focal_mm, round(raw_focal, 1)))

    # --------------------------------------------------------------------------
    # ONVIF Zoom & Focus Commands
    # --------------------------------------------------------------------------
    def start_continuous_zoom(self, speed: float):
        """Starts continuous zoom without auto-stopping (speed > 0: In, speed < 0: Out)."""
        if not self.ptz or not self.profile_token:
            logger.warning(f"[{self.cam_id}] PTZ Service not ready for zoom.")
            return
        # Clamp speed to valid ONVIF range [-1.0, 1.0]
        speed = max(-1.0, min(1.0, float(speed)))
        try:
            self.is_zooming = True
            request = self.ptz.create_type('ContinuousMove')
            request.ProfileToken = self.profile_token
            request.Velocity = {'Zoom': {'x': speed}}
            self.ptz.ContinuousMove(request)
        except Exception as e:
            logger.error(f"[{self.cam_id}] Start continuous zoom error: {e}")
            self.is_zooming = False

    def stop_zoom(self):
        """Immediately stops continuous zoom movement."""
        if not self.ptz or not self.profile_token:
            return
        try:
            stop_req = self.ptz.create_type('Stop')
            stop_req.ProfileToken = self.profile_token
            stop_req.Zoom = True
            self.ptz.Stop(stop_req)
        except Exception as e:
            logger.error(f"[{self.cam_id}] Stop zoom error: {e}")
        finally:
            self.is_zooming = False

    def continuous_zoom(self, speed: float, duration_sec: float = 0.5):
        """
        Triggers continuous zoom with timed duration.
        Clamps speed to [-1.0, 1.0] and duration to [0.05, 5.0] seconds.
        """
        clamped_speed = max(-1.0, min(1.0, float(speed)))
        clamped_duration = max(0.05, min(5.0, float(duration_sec)))
        self.start_continuous_zoom(clamped_speed)

        def _stop():
            time.sleep(clamped_duration)
            self.stop_zoom()

        threading.Thread(target=_stop, daemon=True).start()

    def set_focal_length_mm(self, target_mm: float) -> bool:
        """
        Commands the camera to zoom to a specific focal length in millimeters (e.g. 90.0 mm).
        Normalizes target_mm between min_focal_mm and max_focal_mm into ratio [0.0, 1.0]
        and dispatches ONVIF AbsoluteMove or calibrated move.
        """
        # Clamp to camera focal length limits
        target_mm = max(self.min_focal_mm, min(self.max_focal_mm, float(target_mm)))

        # Calculate normalized zoom ratio
        span = self.max_focal_mm - self.min_focal_mm
        ratio = (target_mm - self.min_focal_mm) / span if span > 0 else 0.0
        ratio = max(0.0, min(1.0, float(ratio)))

        logger.info(f"[{self.cam_id}] Setting focal length to {target_mm:.1f}mm (Normalized Ratio: {ratio:.3f})...")

        # Try ONVIF AbsoluteMove
        if self.ptz and self.profile_token:
            try:
                req = self.ptz.create_type('AbsoluteMove')
                req.ProfileToken = self.profile_token
                req.Position = {'Zoom': {'x': ratio}}
                self.ptz.AbsoluteMove(req)
                self.current_zoom_ratio = ratio
                return True
            except Exception as e:
                logger.warning(f"[{self.cam_id}] AbsoluteMove exception, trying continuous calibrated move: {e}")

        # Fallback: Calibrated timed move
        diff_ratio = ratio - self.current_zoom_ratio
        if abs(diff_ratio) > 0.02:
            direction = 1.0 if diff_ratio > 0 else -1.0
            # Assume full zoom cycle takes ~3.5s
            est_duration = min(3.5, max(0.2, abs(diff_ratio) * 3.5))
            self.continuous_zoom(speed=direction * 0.8, duration_sec=est_duration)
            self.current_zoom_ratio = ratio
            return True

        return True

    def set_zoom_pct(self, target_pct: float) -> bool:
        """
        Commands the camera to zoom to a specific percentage (0.0% to 100.0%).
        0.0% = Wide (min_focal_mm), 100.0% = Tele (max_focal_mm).
        """
        pct = max(0.0, min(100.0, float(target_pct)))
        target_mm = self.min_focal_mm + (pct / 100.0) * (self.max_focal_mm - self.min_focal_mm)
        return self.set_focal_length_mm(target_mm)

    def set_zoom_x(self, target_x: float) -> bool:
        """
        Commands the camera to zoom to a specific optical zoom factor (e.g. 1.0x to 20.0x).
        Clamps target_x between 1.0x and the camera's max optical zoom ratio.
        """
        max_optical_x = self.max_focal_mm / self.min_focal_mm if self.min_focal_mm > 0 else 1.0
        zoom_x = max(1.0, min(max_optical_x, float(target_x)))
        target_mm = self.min_focal_mm * zoom_x
        return self.set_focal_length_mm(target_mm)

    def zoom_in(self, speed: float = 0.8, duration_sec: float = 1.0):
        clamped_speed = max(0.05, min(1.0, abs(float(speed))))
        clamped_dur = max(0.05, min(5.0, float(duration_sec)))
        self.continuous_zoom(clamped_speed, clamped_dur)

    def zoom_out(self, speed: float = 0.8, duration_sec: float = 1.0):
        clamped_speed = max(0.05, min(1.0, abs(float(speed))))
        clamped_dur = max(0.05, min(5.0, float(duration_sec)))
        self.continuous_zoom(-clamped_speed, clamped_dur)

    def continuous_focus(self, speed: float, duration_sec: float = 0.5):
        """
        Triggers continuous focus adjustment.
        Clamps speed to [-1.0, 1.0] and duration to [0.05, 5.0] seconds.
        """
        if not self.imaging or not self.video_source_token:
            return
        clamped_speed = max(-1.0, min(1.0, float(speed)))
        clamped_duration = max(0.05, min(5.0, float(duration_sec)))
        try:
            req = self.imaging.create_type('Move')
            req.VideoSourceToken = self.video_source_token
            req.Focus = {'Continuous': {'Speed': clamped_speed}}
            self.imaging.Move(req)

            def _stop():
                time.sleep(clamped_duration)
                try:
                    stop_req = self.imaging.create_type('Stop')
                    stop_req.VideoSourceToken = self.video_source_token
                    self.imaging.Stop(stop_req)
                except Exception:
                    pass

            threading.Thread(target=_stop, daemon=True).start()
        except Exception as e:
            logger.error(f"[{self.cam_id}] Focus error: {e}")

    def trigger_auto_focus(self):
        """Sets imaging mode to AUTO focus."""
        if not self.imaging or not self.video_source_token:
            return
        try:
            req = self.imaging.create_type('SetImagingSettings')
            req.VideoSourceToken = self.video_source_token
            req.ImagingSettings = {'Focus': {'AutoFocusMode': 'AUTO'}}
            self.imaging.SetImagingSettings(req)
        except Exception as e:
            logger.error(f"[{self.cam_id}] Auto Focus error: {e}")

    def get_focus_status(self) -> dict:
        """Return normalized ONVIF focus state when the camera exposes it."""
        if not self.imaging or not self.video_source_token:
            return {"supported": False, "move_status": "UNKNOWN", "position": None}
        try:
            req = self.imaging.create_type('GetStatus')
            req.VideoSourceToken = self.video_source_token
            status = self.imaging.GetStatus(req)
            focus = getattr(status, 'FocusStatus20', None) or getattr(status, 'FocusStatus', None) or status
            move_status = str(getattr(focus, 'MoveStatus', 'UNKNOWN')).upper()
            position = getattr(focus, 'Position', None)
            return {
                "supported": move_status not in {"", "NONE", "UNKNOWN"},
                "move_status": move_status,
                "position": float(position) if position is not None else None,
            }
        except Exception as exc:
            logger.debug(f"[{self.cam_id}] ONVIF focus status unavailable: {exc}")
            return {"supported": False, "move_status": "UNKNOWN", "position": None}

    def init_onvif(self) -> bool:
        """Initialize ONVIF connection for PTZ and Imaging services."""
        try:
            logger.info(f"[{self.cam_id}] Connecting ONVIF at {self.ip}:{self.onvif_port}...")
            wsdl_dir = "/home/pi/.local/lib/python3.11/site-packages/wsdl"
            self.cam = ONVIFCamera(
                self.ip,
                self.onvif_port,
                self.username,
                self.password,
                wsdl_dir=wsdl_dir,
                adjust_time=True
            )
            self.media = self.cam.create_media_service()
            profiles = self.media.GetProfiles()
            if profiles:
                self.profile_token = profiles[0].token

            # Automatically ensure Visible camera secondary stream (Profile 102) is 16:9 (1280x720)
            if self.cam_id == "visible" and len(profiles) > 1:
                try:
                    sub_cfg = profiles[1].VideoEncoderConfiguration
                    if sub_cfg and (getattr(sub_cfg.Resolution, 'Width', 0) != 1280 or getattr(sub_cfg.Resolution, 'Height', 0) != 720):
                        sub_cfg.Resolution.Width = 1280
                        sub_cfg.Resolution.Height = 720
                        self.media.SetVideoEncoderConfiguration({'Configuration': sub_cfg, 'ForcePersistence': True})
                        logger.info(f"[{self.cam_id}] Ensured Profile 102 resolution is 16:9 (1280x720).")
                except Exception as e:
                    logger.warning(f"[{self.cam_id}] Could not verify/set Profile 102 resolution: {e}")

            sources = self.media.GetVideoSources()
            if sources:
                self.video_source_token = sources[0].token

            try:
                self.ptz = self.cam.create_ptz_service()
            except Exception:
                self.ptz = None

            try:
                self.imaging = self.cam.create_imaging_service()
            except Exception:
                self.imaging = None

            self.onvif_connected = True
            logger.info(f"[{self.cam_id}] ONVIF connected successfully.")
            return True
        except Exception as e:
            logger.warning(f"[{self.cam_id}] ONVIF Connection failed: {e}")
            self.onvif_connected = False
            return False

    def start_stream(self):
        """Starts background RTSP frame capture thread."""
        t = threading.Thread(target=self._stream_worker, daemon=True)
        t.start()

    def _stream_worker(self):
        """Continuously decode RTSP stream with FPS rate-limiting."""
        while self._running:
            container = None
            try:
                logger.info(f"[{self.cam_id}] Connecting RTSP: {self.rtsp_url} (Max FPS: {self.target_fps})")
                options = {
                    'rtsp_transport': 'tcp',
                    'stimeout': '4000000',
                    'max_delay': '500000',
                    'flags': 'low_delay',
                    'fflags': 'nobuffer'
                }
                container = av.open(self.rtsp_url, options=options)
                stream = container.streams.video[0]
                stream.thread_type = 'AUTO'
                self.stream_connected = True

                fps_timer = time.time()
                frames_in_sec = 0
                next_frame_deadline = time.monotonic()

                for frame in container.decode(stream):
                    if not self._running:
                        break

                    now_monotonic = time.monotonic()
                    should_process, next_frame_deadline = advance_frame_deadline(
                        now_monotonic, next_frame_deadline, self.min_frame_interval
                    )
                    if not should_process:
                        continue

                    # Direct hardware-accelerated ndarray conversion
                    img_bgr = frame.to_ndarray(format="bgr24")
                    ret, jpeg = cv2.imencode(".jpg", img_bgr, [cv2.IMWRITE_JPEG_QUALITY, 75])
                    if not ret:
                        continue
                    jpeg_bytes = jpeg.tobytes()
                    captured_at = datetime.now(timezone.utc).isoformat(
                        timespec="milliseconds"
                    ).replace("+00:00", "Z")
                    height, width = img_bgr.shape[:2]

                    with self._frame_ready:
                        self.latest_bgr = img_bgr
                        self.latest_jpeg = jpeg_bytes
                        self.last_frame_time = now_monotonic
                        self.latest_frame_sequence += 1
                        self.latest_captured_at = captured_at
                        self.latest_width = int(width)
                        self.latest_height = int(height)
                        self._frame_ready.notify_all()

                    frames_in_sec += 1
                    now_wall = time.time()
                    if now_wall - fps_timer >= 1.0:
                        self.fps = frames_in_sec
                        frames_in_sec = 0
                        fps_timer = now_wall

            except Exception as e:
                logger.warning(f"[{self.cam_id}] Stream error: {e}. Reconnecting in 2s...")
                self.stream_connected = False
                self._clear_stale_frames()
                time.sleep(2.0)
            finally:
                self.stream_connected = False
                self._clear_stale_frames()
                if container:
                    try:
                        container.close()
                    except Exception:
                        pass

    def _clear_stale_frames(self) -> None:
        """Discard cached camera data whenever the real RTSP source disconnects."""
        with self._frame_ready:
            self.latest_bgr = None
            self.latest_jpeg = None
            self.last_frame_time = 0.0
            self.latest_captured_at = None
            self.latest_width = 0
            self.latest_height = 0
            self._frame_ready.notify_all()

    def get_latest_frame(self) -> Tuple[Optional[np.ndarray], Optional[bytes]]:
        """Returns the latest decoded BGR frame and JPEG bytes."""
        with self._frame_lock:
            bgr = None if self.latest_bgr is None else self.latest_bgr.copy()
            jpeg = self.latest_jpeg
            return bgr, jpeg

    def get_latest_frame_snapshot(self) -> Optional[dict]:
        """Return image data and capture identity from the same atomic frame."""
        with self._frame_lock:
            snapshot = self._encoded_frame_snapshot_locked()
            if snapshot is None:
                return None
            snapshot["bgr"] = None if self.latest_bgr is None else self.latest_bgr.copy()
            return snapshot

    def get_latest_encoded_frame(self) -> Optional[dict]:
        """Return the newest JPEG and capture identity without copying the BGR array."""
        with self._frame_lock:
            return self._encoded_frame_snapshot_locked()

    def wait_for_encoded_frame(self, after_sequence: int, timeout: float = 1.0) -> Optional[dict]:
        """Wait until a newly captured JPEG is available, avoiding timer aliasing."""
        deadline = time.monotonic() + max(0.0, timeout)
        with self._frame_ready:
            while self.latest_frame_sequence <= after_sequence:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._frame_ready.wait(remaining)
            return self._encoded_frame_snapshot_locked()

    def _encoded_frame_snapshot_locked(self) -> Optional[dict]:
        # Fail closed: never expose an old cached frame after RTSP disconnects.
        if (
            not self.stream_connected
            or self.latest_jpeg is None
            or self.latest_frame_sequence <= 0
            or self.last_frame_time <= 0.0
            or time.monotonic() - self.last_frame_time > 2.0
        ):
            return None
        return {
            "jpeg": self.latest_jpeg,
            "width": self.latest_width,
            "height": self.latest_height,
            "sequence": self.latest_frame_sequence,
            "captured_at": self.latest_captured_at,
            "source": "live",
            "simulated": False,
            "source_verified": True,
        }

    def compute_sharpness(self) -> float:
        """Calculates image sharpness using Laplacian variance to detect focus."""
        with self._frame_lock:
            if self.latest_bgr is None:
                return 0.0
            gray = cv2.cvtColor(self.latest_bgr, cv2.COLOR_BGR2GRAY)
            return float(cv2.Laplacian(gray, cv2.CV_64F).var())


class CameraManager:
    """Manages all cameras in the surveillance system."""

    def __init__(self, cameras_config: dict):
        self.cameras: Dict[str, CameraDevice] = {}
        for cam_id, cfg in cameras_config.items():
            self.cameras[cam_id] = CameraDevice(cfg)

    def get_camera(self, cam_id: str) -> Optional[CameraDevice]:
        return self.cameras.get(cam_id)

    def get_thermal_camera(self) -> Optional[CameraDevice]:
        return self.cameras.get("thermal")

    def get_visible_camera(self) -> Optional[CameraDevice]:
        return self.cameras.get("visible")
