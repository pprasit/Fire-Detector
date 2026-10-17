"""
PTZ & Mount Controller Module
Connects to Mount Agent API (via WebSocket, Unix Domain Socket, or TCP),
reads real-time telemetry (Azimuth/Altitude), and sends velocity & position commands.
Includes an automatic built-in Simulator Fallback if the hardware agent is offline.
"""

import math
import time
import socket
import threading
import logging
import json
import requests
from typing import Tuple, Optional, Callable, Dict, Any, List

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("PTZController")


def normalize_angle_360(deg: float) -> float:
    """Normalizes angle to [-360.0, 360.0] range."""
    deg = float(deg)
    while deg > 360.0:
        deg -= 360.0
    while deg < -360.0:
        deg += 360.0
    return deg


# Alias for backward compatibility
normalize_angle_180 = normalize_angle_360


def shortest_angular_diff(target: float, current: float) -> float:
    """Computes shortest signed angular difference (target - current) in [-180.0, 180.0] degrees."""
    diff = (float(target) - float(current)) % 360.0
    if diff > 180.0:
        diff -= 360.0
    return diff


class PTZController:
    """Controls PTZ / Mount hardware with continuous sweep and slew capabilities."""

    def __init__(self, host: str = "192.168.1.105", port: int = 8000, fallback_sim: bool = True):
        self.host = host
        self.port = port
        self.fallback_sim = fallback_sim

        self.is_connected = False
        self.is_simulated = False
        self.is_armed = False
        self.current_az = 0.0
        self.current_alt = 0.0
        self.target_az = 0.0
        self.target_alt = 0.0
        self.is_moving = False
        self.trajectory_done = True

        self._lock = threading.Lock()
        self._running = True
        self._http_base = f"http://{self.host}:{self.port}"

        # High-performance persistent HTTP session with connection pooling
        self._session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(pool_connections=10, pool_maxsize=20, max_retries=1)
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)

        self._active_slew_id = 0
        self._abort_slew = False

        # Connect and start telemetry polling in background thread
        threading.Thread(target=self._init_ptz_async, daemon=True).start()

    def _init_ptz_async(self):
        """Connects to PTZ mount and starts telemetry poller."""
        self.connect()
        self._start_telemetry_poller()

    def enable_motors(self, axis: Optional[str] = None) -> bool:
        """Enables / arms mount motors for closed-loop control."""
        if not self.is_simulated and self.is_connected:
            try:
                endpoint = f"/api/motors/enable/{axis}" if axis else "/api/motors/enable"
                url = f"{self._http_base}{endpoint}"
                res = self._session.post(url, json={}, timeout=1.5)
                if res.status_code == 200:
                    with self._lock:
                        self.is_armed = True
                    logger.info(f"⚡ Mount Motors ENABLED ({axis if axis else 'ALL'})")
                    return True
            except Exception as e:
                logger.error(f"Error enabling Mount motors: {e}")
                return False
        else:
            with self._lock:
                self.is_armed = True
            return True

    def disable_motors(self, axis: Optional[str] = None) -> bool:
        """Disables / disarms mount motors into idle state."""
        if not self.is_simulated and self.is_connected:
            try:
                endpoint = f"/api/motors/disable/{axis}" if axis else "/api/motors/disable"
                url = f"{self._http_base}{endpoint}"
                res = self._session.post(url, json={}, timeout=1.5)
                if res.status_code == 200:
                    with self._lock:
                        self.is_armed = False
                    logger.info(f"🔒 Mount Motors DISABLED ({axis if axis else 'ALL'})")
                    return True
            except Exception as e:
                logger.error(f"Error disabling Mount motors: {e}")
                return False
        else:
            with self._lock:
                self.is_armed = False
            return True

    def connect(self) -> bool:
        """Tries to connect to Mount Agent Server via HTTP REST."""
        try:
            url = f"{self._http_base}/api/status"
            res = self._session.get(url, timeout=1.5)
            if res.status_code == 200:
                data = res.json()
                self._update_coords_from_status(data)
                self.is_connected = True
                self.is_simulated = False
                logger.info(f"✅ Mount Agent Hardware connected via REST ({self._http_base})")
                return True
        except Exception as e:
            logger.warning(f"Mount Agent HTTP unreachable: {e}")

        if self.fallback_sim:
            logger.info("Enabling Mount Hardware Simulator Fallback.")
            self.is_connected = True
            self.is_simulated = True
            self._start_sim_loop()
            return True
        return False

    def _update_coords_from_status(self, data: dict):
        axes = data.get("axes", [])
        if len(axes) >= 2:
            az = axes[0].get("position_deg", axes[0].get("absolute_position_deg", 0.0))
            alt = axes[1].get("position_deg", axes[1].get("absolute_position_deg", 0.0))
            az_armed = bool(axes[0].get("is_armed", False))
            alt_armed = bool(axes[1].get("is_armed", False))
            az_done = bool(axes[0].get("trajectory_done", True))
            alt_done = bool(axes[1].get("trajectory_done", True))
            with self._lock:
                self.current_az = normalize_angle_360(float(az))
                self.current_alt = float(alt)
                self.is_armed = az_armed and alt_armed
                self.trajectory_done = az_done and alt_done

    def _start_telemetry_poller(self):
        """Polls real mount telemetry every 80ms."""
        def _poller():
            while self._running:
                if not self.is_simulated and self.is_connected:
                    try:
                        url = f"{self._http_base}/api/status"
                        res = self._session.get(url, timeout=0.8)
                        if res.status_code == 200:
                            data = res.json()
                            self._update_coords_from_status(data)
                    except Exception:
                        pass
                time.sleep(0.08)

        threading.Thread(target=_poller, daemon=True).start()

    def _start_sim_loop(self):
        """Simulates physical mount physics (inertia & continuous pan)."""
        def _worker():
            last_t = time.time()

            while self._running:
                now = time.time()
                dt = now - last_t
                last_t = now

                with self._lock:
                    if self.is_moving:
                        az_diff = shortest_angular_diff(self.target_az, self.current_az)
                        if abs(az_diff) > 0.05:
                            step = math.copysign(min(abs(az_diff), 15.0 * dt), az_diff)
                            self.current_az = normalize_angle_360(self.current_az + step)
                        else:
                            self.current_az = self.target_az

                        alt_diff = (self.target_alt - self.current_alt)
                        if abs(alt_diff) > 0.05:
                            step = math.copysign(min(abs(alt_diff), 15.0 * dt), alt_diff)
                            self.current_alt += step
                        else:
                            self.current_alt = self.target_alt

                time.sleep(0.04)

        t = threading.Thread(target=_worker, daemon=True)
        t.start()

    def get_position(self) -> Tuple[float, float]:
        """Returns (current_azimuth, current_altitude) with normalized [-360, 360] azimuth."""
        with self._lock:
            return round(self.current_az, 2), round(self.current_alt, 2)

    def set_velocity(self, az_vel: float, alt_vel: float = 0.0):
        """Sends velocity vector command to Mount with instant dispatch."""
        self._active_slew_id += 1  # Cancel any ongoing GOTO
        if not self.is_simulated and self.is_connected:
            if not self.is_armed and (abs(az_vel) > 0.01 or abs(alt_vel) > 0.01):
                self.enable_motors()
            try:
                url = f"{self._http_base}/api/motors/velocity"
                self._session.post(
                    url,
                    json={"Azimuth": float(az_vel), "Altitude": float(alt_vel)},
                    timeout=0.6
                )
            except Exception as e:
                logger.error(f"Error sending velocity to Mount: {e}")
        else:
            with self._lock:
                self.is_moving = True

    def continuous_pan(self, speed_deg_s: float = 1.0):
        """Starts continuous sweep across 360 degrees."""
        if not self.is_armed:
            self.enable_motors()
        self.set_velocity(speed_deg_s, 0.0)
        logger.info(f"PTZ Continuous Pan started @ {speed_deg_s} deg/sec")

    def goto_position(self, az: float, alt: float, speed: float = 10.0, wait: bool = True, tolerance: float = 0.3, timeout: float = 20.0) -> bool:
        """
        Slews mount to specified absolute azimuth and altitude coordinates using Mount Agent's native GoTo API.
        Single command dispatch allows Mount hardware to handle trapezoidal acceleration and safety limits natively.
        """
        if not self.is_armed:
            self.enable_motors()

        # Normalize target azimuth to [-360, 360]
        norm_az = normalize_angle_360(az)
        # Preserve the requested unwrapped branch. Mount Agent resolves an
        # equivalent heading inside its configured multi-turn software limits;
        # converting -29 to 331 here would incorrectly hit a +330 CW limit.
        command_az = norm_az
        target_alt = float(alt)

        self._active_slew_id += 1
        slew_id = self._active_slew_id
        self._abort_slew = False

        # Mechanical safety cap: no GoTo caller may slew faster than 10 deg/s.
        limit_speed = max(0.5, min(10.0, float(speed)))
        logger.info(f"PTZ Native GoTo [ID={slew_id}]: Target Az={norm_az:.2f}°, Alt={target_alt:.2f}° (speed={limit_speed}°/s, tol={tolerance}°)")

        if not self.is_simulated and self.is_connected:
            # 1. Dispatch Native GoTo API command ONCE to Mount Agent
            try:
                url = f"{self._http_base}/api/motors/goto"
                res = self._session.post(
                    url,
                    json={
                        "Azimuth": float(command_az),
                        "Altitude": float(target_alt),
                        "velocity_target_deg_per_sec": limit_speed,
                        # Mount Agent's closed-loop API accepts at most 0.08°.
                        # Panorama applies its separate capture tolerance after
                        # the trajectory, but the hardware should aim precisely.
                        "position_tolerance_deg": min(0.08, float(tolerance)),
                    },
                    timeout=1.5
                )
                try:
                    response_body = res.json()
                except ValueError:
                    response_body = {}
                if res.status_code >= 400 or response_body.get("ok") is False:
                    error = response_body.get("error") or f"HTTP {res.status_code}"
                    logger.error(f"Mount Agent rejected GoTo [ID={slew_id}]: {error}")
                    return False
            except Exception as e:
                logger.error(f"Error dispatching GoTo to Mount: {e}")
                return False

            if not wait:
                return True

            # 2. Wait for trajectory arrival via passive telemetry polling (No velocity flooding!)
            start_time = time.time()
            time.sleep(0.1)  # Brief delay for hardware trajectory initiation

            while time.time() - start_time < timeout:
                if self._abort_slew or self._active_slew_id != slew_id:
                    logger.debug(f"GoTo [ID={slew_id}] canceled/superseded.")
                    return False

                cur_az, cur_alt = self.get_position()
                az_err = shortest_angular_diff(norm_az, cur_az)
                alt_err = target_alt - cur_alt

                # Check if reached within tolerance
                if abs(az_err) <= tolerance and abs(alt_err) <= tolerance:
                    logger.info(f"✅ Target Reached [ID={slew_id}]: Az={cur_az:.2f}°, Alt={cur_alt:.2f}° (err: Az={az_err:+.2f}°, Alt={alt_err:+.2f}°)")
                    return True

                time.sleep(0.08)  # Standard 12.5Hz passive monitoring

            logger.warning(f"⚠️ GoTo wait timeout after {timeout:.1f}s (Current Az={cur_az:.2f}°, Alt={cur_alt:.2f}°)")
            return False
        else:
            with self._lock:
                self.target_az = norm_az
                self.target_alt = target_alt
                self.is_moving = True
            if wait:
                time.sleep(0.3)
            return True

    def stop(self):
        """Immediately stops all mount motion and cancels any pending GOTO."""
        self._abort_slew = True
        self._active_slew_id += 1
        if not self.is_simulated and self.is_connected:
            try:
                url = f"{self._http_base}/api/motors/stop"
                self._session.post(url, json={}, timeout=0.6)
            except Exception as e:
                logger.error(f"Error sending stop to Mount: {e}")
        else:
            with self._lock:
                self.target_az = self.current_az
                self.target_alt = self.current_alt
                self.is_moving = False
        logger.info("PTZ Slew/Scan STOPPED.")
