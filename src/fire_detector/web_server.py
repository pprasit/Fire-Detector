"""Web dashboard for monitoring the Fire Detector system."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
import atexit
import ast
import base64
import hashlib
import hmac
import importlib.util
from io import BytesIO
import json
import math
import os
from pathlib import Path
import random
import re
import struct
import subprocess
import sys
import time
import tempfile
from threading import Condition, Event, Lock, Thread, Timer, current_thread
from time import monotonic, sleep
from typing import Any
import urllib.parse
import urllib.request

from flask import Flask, Response, jsonify, render_template, request, send_file, send_from_directory, stream_with_context
from flask_sock import Sock

from fire_detector.mount_agent import MountAgent, ProtocolError
from fire_detector.current_protection import CurrentEnvelope, CurrentEnvelopeConfig
from fire_detector.api_command_monitor import ApiCommandMonitor
from fire_detector.hardware_io import (
    HardwareIOQueue,
    PRIORITY_CONFIGURATION,
    PRIORITY_CONTROL,
    PRIORITY_SAFETY,
)
from fire_detector.motion_algorithm import PositionMotionAlgorithm, PositionStepInput
from fire_detector.motion_commands import ManagedMotionController, MotionCommandManager
from fire_detector.jog_commands import JogCommandRegistry
from fire_detector.telemetry_store import TelemetryStore
from fire_detector.camera_overlay import burn_camera_overlay
from fire_detector.odrive_connection import (
    ODriveConnectionError,
    connect,
    connect_many,
    read_dual_drive_status,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_SETTINGS_PATH = PROJECT_ROOT / "AppSetting.JSON"
ACTIVE_STATION_CONFIGURATION_PATH = PROJECT_ROOT / "data" / "station_configuration" / "active.json"
UPDATE_STATE_PATH = PROJECT_ROOT / ".update_state.json"
UPDATER_SCRIPT_PATH = PROJECT_ROOT / "scripts" / "fire_detector_update.py"
DEM_PATH = PROJECT_ROOT / "data" / "dem" / "output_hh.tif"
POINTING_CACHE_DIR = PROJECT_ROOT / "data" / "pointing_cache"
TELEMETRY_DATABASE_PATH = PROJECT_ROOT / "data" / "telemetry" / "mount_telemetry.sqlite3"
ARCGIS_WORLD_IMAGERY_EXPORT_URL = "https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/export"
SYSTEM_DIST_PACKAGES = "/usr/lib/python3/dist-packages"
ODRIVE_PRO_V44_MAX_CURRENT_AMP = 150.0
SAFE_MAX_SLEW_RATE_DEG_PER_SEC = 100.0
MOTOR_CURRENT_ENVELOPE = CurrentEnvelopeConfig(
    continuous_current_amp=20.0,
    peak_current_amp=40.0,
    hard_current_amp=48.0,
    peak_duration_sec=2.0,
    derating_duration_sec=0.75,
    recovery_current_amp=16.0,
    recovery_duration_sec=30.0,
    torque_constant_nm_per_amp=0.29,
)
DEFAULT_TORQUE_CONSTANT_NM_PER_AMP = MOTOR_CURRENT_ENVELOPE.torque_constant_nm_per_amp
CURRENT_LIMIT_WRITE_INTERVAL_SEC = 0.075
CURRENT_LIMIT_WRITE_STEP_AMP = 0.5
DEFAULT_UPDATE_INTERVAL_MINUTES = 15
POINTING_RADIUS_KM = 20.0
POINTING_GRID_RESOLUTION_M = 30.0
EARTH_RADIUS_M = 6371008.8
ATMOSPHERIC_REFRACTION_COEFFICIENT = 0.13
POSITION_LOWPASS_ALPHA = 0.18
VELOCITY_LOWPASS_ALPHA = 0.35
POSITION_FILTER_VELOCITY_DEADBAND_DEG_PER_SEC = 0.04
POSITION_GLITCH_SPEED_MULTIPLIER = 6.0
POSITION_GLITCH_MIN_SPEED_DEG_PER_SEC = 180.0
POSITION_GLITCH_ACCEPT_AFTER = 12
POSITION_MEDIAN_WINDOW = 11
TELEMETRY_INTERVAL_SEC = 0.025
TELEMETRY_PUSH_INTERVAL_SEC = TELEMETRY_INTERVAL_SEC
TELEMETRY_CONTENTION_YIELD_SEC = 0.005
MAX_DRIVE_ERROR_EVENTS = 100
MAX_AUTO_TUNE_STEP_EVENTS = 160
RUNTIME_LIMIT_SLOW_SPEED_DEG_PER_SEC = 30.0
RUNTIME_LIMIT_SLOW_SPEED_THRESHOLD_DEG_PER_SEC = 40.0
RUNTIME_LIMIT_SLOW_ZONE_SPEED_RATIO = 0.15
SOFTWARE_POSITION_DEFAULT_GAIN = 0.5
SOFTWARE_POSITION_INTERVAL_SEC = TELEMETRY_INTERVAL_SEC
SOFTWARE_POSITION_TOLERANCE_DEG = 0.08
SOFTWARE_POSITION_SETTLE_VELOCITY_DEG_PER_SEC = 0.25
SOFTWARE_POSITION_TIMEOUT_MULTIPLIER = 2.0
SOFTWARE_POSITION_MIN_TIMEOUT_SEC = 10.0
SINE_VELOCITY_INTERVAL_SEC = TELEMETRY_INTERVAL_SEC
SINE_LIMIT_BIAS_START_RATIO = 0.5
SINE_LIMIT_MAX_RETURN_PROBABILITY = 0.95
SINE_MAX_SAME_DIRECTION_HALF_CYCLES = 2
_GPIO: Any | None = None
_GPIO_CONFIGURED_INPUTS: dict[int, str] = {}
_GPIO_LOCK = Lock()
_SETTINGS_CACHE: dict[str, Any] | None = None
_SETTINGS_MTIME: float | None = None
_REMOTE_SETTINGS_MTIME: float | None = None
_DEM_CACHE: dict[str, Any] | None = None
_POINTING_RASTER_CACHE: dict[str, Any] | None = None
SERVER_STARTED_AT = datetime.now().astimezone()

TUNING_FIELDS = {
    "position_gain": "controller.config.pos_gain",
    "velocity_gain": "controller.config.vel_gain",
    "velocity_integrator_gain": "controller.config.vel_integrator_gain",
    "velocity_integrator_limit": "controller.config.vel_integrator_limit",
    "velocity_integrator_decay_gain": "controller.config.vel_integrator_decay_gain",
    "velocity_limit": "controller.config.vel_limit",
    "velocity_limit_tolerance": "controller.config.vel_limit_tolerance",
    "velocity_ramp_rate": "controller.config.vel_ramp_rate",
    "torque_ramp_rate": "controller.config.torque_ramp_rate",
    "torque_soft_min": "config.torque_soft_min",
    "torque_soft_max": "config.torque_soft_max",
    "spinout_electrical_power_threshold": "controller.config.spinout_electrical_power_threshold",
    "spinout_mechanical_power_threshold": "controller.config.spinout_mechanical_power_threshold",
    "spinout_electrical_power_bandwidth": "controller.config.spinout_electrical_power_bandwidth",
    "spinout_mechanical_power_bandwidth": "controller.config.spinout_mechanical_power_bandwidth",
    "encoder_bandwidth": "config.encoder_bandwidth",
    "input_filter_bandwidth": "controller.config.input_filter_bandwidth",
    "inertia": "controller.config.inertia",
    "trap_velocity_limit": "trap_traj.config.vel_limit",
    "trap_accel_limit": "trap_traj.config.accel_limit",
    "trap_decel_limit": "trap_traj.config.decel_limit",
}

TUNING_SIGNED_FIELDS = {
    "torque_soft_min",
    "spinout_mechanical_power_threshold",
}

TUNING_DEGREE_RATE_FIELDS = {
    "velocity_limit",
    "velocity_ramp_rate",
    "trap_velocity_limit",
    "trap_accel_limit",
    "trap_decel_limit",
}

AXIS_STATE_IDLE = 1
AXIS_STATE_CLOSED_LOOP_CONTROL = 8
CONTROL_MODE_POSITION_CONTROL = 3
CONTROL_MODE_VELOCITY_CONTROL = 2
INPUT_MODE_PASSTHROUGH = 1
INPUT_MODE_VEL_RAMP = 2
INPUT_MODE_TRAP_TRAJ = 5


class MotionCommandGuard:
    AXIS_INDEX = {"Azimuth": 0, "Altitude": 1}

    def __init__(self, devices: tuple[Any, ...]) -> None:
        self._devices = devices

    def require_enabled(self, action: str, targets: dict[str, float]) -> None:
        for label, value in targets.items():
            if action == "velocity" and value == 0:
                continue
            axis = self._axis_for_label(label)
            if not self._axis_is_enabled(axis):
                raise ValueError(f"{label} axis must be enabled before {self._action_name(action)} commands.")

    def _axis_for_label(self, label: str) -> Any:
        axis_index = self.AXIS_INDEX.get(label)
        if axis_index is None or axis_index >= len(self._devices):
            raise ValueError(f"Unknown axis: {label}")
        device = self._devices[axis_index]
        if device is None:
            raise ODriveConnectionError(f"{label} drive is not connected.")
        return getattr(device, "axis0")

    @staticmethod
    def _axis_is_enabled(axis: Any) -> bool:
        try:
            return bool(getattr(axis, "is_armed"))
        except Exception:
            return False

    @staticmethod
    def _action_name(action: str) -> str:
        return "Move/Goto" if action == "goto" else "Jog/Velocity"


class MountCommandRouter:
    """Routes every external control surface through the existing safety layer."""

    def __init__(self, monitor: "ODriveMonitor") -> None:
        self._monitor = monitor
        self._watchdog_lock = Lock()
        self._velocity_watchdogs: dict[str, Timer] = {}

    def dispatch(self, action: str, params: dict[str, Any], context: dict[str, Any]) -> Any:
        del context
        if action in ("system.hello", "system.get_capabilities"):
            return {
                "protocol_version": "1.0",
                "device_type": "fire-detection-mount",
                "capabilities": self.capabilities(),
            }
        if action == "system.ping":
            return {"pong": True, "timestamp": _timestamp()}
        if action == "system.get_info":
            return _system_info_payload()
        if action in ("system.get_health", "mount.get_status"):
            return self._monitor.snapshot()
        if action == "mount.enable":
            return self._monitor.enable_motors()
        if action == "mount.disable":
            self._cancel_all_watchdogs()
            return self._monitor.disable_motors()
        if action == "mount.stop":
            self._cancel_all_watchdogs()
            return self._monitor.stop_motors()
        if action in ("mount.goto", "pointing.goto_altaz"):
            self._cancel_all_watchdogs()
            positions = self._mount_positions(params)
            speed = _parse_optional_positive_float(
                params.get("max_velocity_deg_per_sec"),
                "Maximum velocity",
            )
            if speed is not None:
                _validate_max_velocity("Maximum velocity", speed)
            return self._monitor.goto_positions(positions, speed)
        if action == "mount.set_velocity":
            velocities = self._mount_velocities(params)
            self._arm_velocity_watchdogs(velocities, params)
            return self._monitor.set_velocities(velocities)

        if action.startswith("axis."):
            label = self._axis_label(params.get("axis"))
            if action == "axis.enable":
                return self._monitor.set_axis_enabled(label, True)
            if action == "axis.disable":
                self._cancel_watchdog(label)
                return self._monitor.set_axis_enabled(label, False)
            if action == "axis.stop":
                self._cancel_watchdog(label)
                return self._monitor.set_velocities({label: 0.0})
            if action == "axis.goto":
                self._cancel_watchdog(label)
                position = self._required_float(params.get("position_deg"), "position_deg")
                speed = _parse_optional_positive_float(
                    params.get("max_velocity_deg_per_sec"),
                    "Maximum velocity",
                )
                if speed is not None:
                    _validate_max_velocity("Maximum velocity", speed)
                return self._monitor.goto_positions({label: position}, speed)
            if action == "axis.set_velocity":
                velocity = self._required_float(params.get("velocity_deg_per_sec"), "velocity_deg_per_sec")
                _validate_max_velocity(f"{label} velocity", velocity)
                velocities = {label: velocity}
                self._arm_velocity_watchdogs(velocities, params)
                return self._monitor.set_velocities(velocities)

        if action == "calibration.start":
            label = self._axis_label(params.get("axis"))
            options = _parse_motor_calibration_payload(
                {
                    "min_position_deg": params.get("minimum_position_deg"),
                    "max_position_deg": params.get("maximum_position_deg"),
                    "current_amp": params.get("current_amp"),
                    "speed_deg_per_sec": params.get("velocity_deg_per_sec"),
                }
            )
            return self._monitor.start_motor_calibration(label, options)
        if action == "calibration.stop":
            return self._monitor.stop_motor_calibration(self._axis_label(params.get("axis")))
        if action == "calibration.get_status":
            return self._monitor.snapshot().get("motor_calibration", {})
        if action == "tuning.apply":
            label = self._axis_label(params.get("axis"))
            values = _parse_tuning_payload(params.get("values") if isinstance(params.get("values"), dict) else {})
            return self._monitor.update_tuning(label, values)
        if action == "tuning.save":
            return self._monitor.save_configuration(self._axis_label(params.get("axis")))

        raise ProtocolError("UNKNOWN_ACTION", f"Unsupported mount action: {action}")

    @staticmethod
    def capabilities() -> list[str]:
        return [
            "system.hello", "system.ping", "system.get_info", "system.get_health",
            "system.get_capabilities", "control.acquire", "control.renew", "control.release",
            "subscribe", "unsubscribe", "mount.get_status", "mount.enable", "mount.disable",
            "mount.stop", "mount.goto", "mount.set_velocity", "axis.enable",
            "axis.disable", "axis.stop", "axis.goto", "axis.set_velocity",
            "pointing.goto_altaz", "calibration.start", "calibration.stop",
            "calibration.get_status", "tuning.apply", "tuning.save",
        ]

    @staticmethod
    def _axis_label(value: Any) -> str:
        normalized = str(value or "").strip().lower()
        labels = {"azimuth": "Azimuth", "azm": "Azimuth", "altitude": "Altitude", "alt": "Altitude"}
        if normalized not in labels:
            raise ValueError("axis must be azimuth or altitude.")
        return labels[normalized]

    @staticmethod
    def _required_float(value: Any, field: str) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} must be a number.") from exc
        if not math.isfinite(number):
            raise ValueError(f"{field} must be finite.")
        return number

    def _mount_positions(self, params: dict[str, Any]) -> dict[str, float]:
        positions: dict[str, float] = {}
        if params.get("azimuth_deg") not in (None, ""):
            positions["Azimuth"] = self._required_float(params["azimuth_deg"], "azimuth_deg")
        if params.get("altitude_deg") not in (None, ""):
            positions["Altitude"] = self._required_float(params["altitude_deg"], "altitude_deg")
        if not positions:
            raise ValueError("At least one mount position is required.")
        _validate_motion_targets(positions)
        return positions

    def _mount_velocities(self, params: dict[str, Any]) -> dict[str, float]:
        velocities: dict[str, float] = {}
        for field, label in (
            ("azimuth_deg_per_sec", "Azimuth"),
            ("altitude_deg_per_sec", "Altitude"),
        ):
            if params.get(field) in (None, ""):
                continue
            velocity = self._required_float(params[field], field)
            _validate_max_velocity(f"{label} velocity", velocity)
            velocities[label] = velocity
        if not velocities:
            raise ValueError("At least one mount velocity is required.")
        return velocities

    def _arm_velocity_watchdogs(self, velocities: dict[str, float], params: dict[str, Any]) -> None:
        nonzero = [label for label, velocity in velocities.items() if not math.isclose(velocity, 0.0, abs_tol=1e-9)]
        for label in velocities:
            self._cancel_watchdog(label)
        if not nonzero:
            return
        try:
            timeout_ms = int(params.get("command_timeout_ms"))
        except (TypeError, ValueError) as exc:
            raise ValueError("command_timeout_ms is required for non-zero velocity commands.") from exc
        if timeout_ms < 100 or timeout_ms > 5000:
            raise ValueError("command_timeout_ms must be between 100 and 5000.")
        for label in nonzero:
            timer = Timer(timeout_ms / 1000.0, self._velocity_watchdog_expired, args=(label,))
            timer.daemon = True
            with self._watchdog_lock:
                self._velocity_watchdogs[label] = timer
            timer.start()

    def _velocity_watchdog_expired(self, label: str) -> None:
        try:
            self._monitor.command_velocities({label: 0.0})
        except Exception:
            pass
        finally:
            with self._watchdog_lock:
                self._velocity_watchdogs.pop(label, None)

    def _cancel_watchdog(self, label: str) -> None:
        with self._watchdog_lock:
            timer = self._velocity_watchdogs.pop(label, None)
        if timer is not None:
            timer.cancel()

    def _cancel_all_watchdogs(self) -> None:
        with self._watchdog_lock:
            timers = tuple(self._velocity_watchdogs.values())
            self._velocity_watchdogs.clear()
        for timer in timers:
            timer.cancel()


class ODriveMonitor:
    def __init__(self, timeout: float = 3.0, poll_interval: float = TELEMETRY_INTERVAL_SEC) -> None:
        self._timeout = timeout
        self._poll_interval = poll_interval
        self._devices: tuple[Any, ...] | None = None
        self._drive_status: Any | None = None
        self._device_lock = Lock()
        self._hardware_io = HardwareIOQueue()
        self._lock = Lock()
        self._telemetry_updated = Condition(self._lock)
        self._telemetry_sequence = 0
        self._telemetry_published_at = 0.0
        self._stop = Event()
        self._thread: Thread | None = None
        self._latest: dict[str, Any] | None = None
        self._velocity_filter: dict[str, dict[str, float]] = {}
        self._auto_tune_stop = Event()
        self._auto_tune_progress_lock = Lock()
        self._auto_tune_progress: dict[str, Any] | None = None
        self._auto_tune_step_events: list[dict[str, Any]] = []
        self._auto_tune_step_sequence = 0
        self._error_event_lock = Lock()
        self._drive_error_events: list[dict[str, Any]] = []
        self._drive_error_sequence = 0
        self._last_drive_error_state: dict[str, tuple[int, int]] = {}
        self._current_envelopes = {
            label: CurrentEnvelope(MOTOR_CURRENT_ENVELOPE)
            for label in ("Azimuth", "Altitude")
        }
        self._current_envelope_state: dict[str, dict[str, Any]] = {}
        self._current_envelope_last_step: dict[str, float] = {}
        self._current_envelope_last_write: dict[str, float] = {}
        self._current_envelope_applied_amp: dict[str, float] = {}
        self._velocity_command_lock = Lock()
        self._last_velocity_command_deg_per_sec: dict[str, float] = {}
        self._position_unwrap: dict[str, dict[str, float]] = {}
        self._software_position_lock = Lock()
        self._software_position_stop = Event()
        self._software_position_thread: Thread | None = None
        self._software_position_state: dict[str, dict[str, Any]] = {}
        self._software_position_generation = 0
        self._position_algorithm = PositionMotionAlgorithm()
        self._sine_velocity_lock = Lock()
        self._sine_velocity_stops: dict[str, Event] = {}
        self._sine_velocity_threads: dict[str, Thread] = {}
        self._sine_velocity_state: dict[str, dict[str, Any]] = {}
        self._sine_velocity_generations: dict[str, int] = {}
        self._motor_calibration_lock = Lock()
        self._motor_calibration_stops: dict[str, Event] = {}
        self._motor_calibration_threads: dict[str, Thread] = {}
        self._motor_calibration_state: dict[str, dict[str, Any]] = {}
        self._next_missing_drive_retry_at = 0.0

    def start(self) -> None:
        with self._lock:
            if self._thread is not None:
                return
            self._thread = Thread(target=self._poll_loop, name="odrive-monitor", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._hardware_io.publish_latest(
            "shutdown",
            lambda: None,
            label="shutdown",
            priority=PRIORITY_SAFETY,
        )
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not current_thread():
            thread.join(timeout=1.0)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            if self._latest is not None:
                # Consumers receive an independent view of the one centrally
                # published telemetry sample; they never read the drive and
                # cannot mutate the sample seen by another task.
                latest = deepcopy(self._latest)
                latest["hardware_io"] = self._hardware_io.stats()
                telemetry = latest.setdefault("telemetry_source", {})
                telemetry["age_ms"] = round(
                    max(0.0, monotonic() - self._telemetry_published_at) * 1000.0,
                    3,
                )
                latest["drive_error_events"] = self._drive_error_events_snapshot()
                latest["auto_tune_progress"] = self._auto_tune_progress_snapshot()
                latest["auto_tune_step_events"] = self._auto_tune_step_events_snapshot()
                latest["motor_calibration"] = self._motor_calibration_state_snapshot()
                return latest

        return {
            "connected": False,
            "run_mode": "hardware",
            "simulation_mode": False,
            "error": "Waiting for the first ODrive sample.",
            "poll_interval_ms": int(self._poll_interval * 1000),
            "timestamp": _timestamp(),
            "server_started_at": _server_started_at(),
            "azimuth_sensors": _read_azimuth_sensors(),
            "hardware_io": self._hardware_io.stats(),
            "drive_error_events": self._drive_error_events_snapshot(),
            "auto_tune_progress": self._auto_tune_progress_snapshot(),
            "auto_tune_step_events": self._auto_tune_step_events_snapshot(),
            "motor_calibration": self._motor_calibration_state_snapshot(),
        }

    def wait_for_telemetry(self, after_sequence: int, timeout: float) -> dict[str, Any]:
        """Wait for and copy a centrally published sample; never touches USB."""

        with self._telemetry_updated:
            self._telemetry_updated.wait_for(
                lambda: self._telemetry_sequence > after_sequence or self._stop.is_set(),
                timeout=max(0.0, timeout),
            )
        return self.snapshot()

    def _telemetry_cursor(self) -> int:
        with self._lock:
            return self._telemetry_sequence

    def _wait_for_command_confirmation(
        self,
        after_sequence: int,
        expected_enabled: dict[str, bool],
    ) -> dict[str, Any]:
        """Return the first central sample produced after a hardware command.

        Enable/disable writes complete before the owner performs its next
        telemetry poll. Returning the pre-command cache made the Web UI think
        an enabled axis was still idle and reject an immediately following
        velocity command. The command thread may wait here because the USB
        owner is already free to produce the confirming sample.
        """

        deadline = monotonic() + 1.0
        latest = self.snapshot()
        sequence = after_sequence
        while monotonic() < deadline:
            latest = self.wait_for_telemetry(sequence, timeout=deadline - monotonic())
            axes = latest.get("axes") if isinstance(latest.get("axes"), (list, tuple)) else []
            by_label = {
                str(axis.get("label")): axis
                for axis in axes
                if isinstance(axis, dict)
            }
            confirmed = True
            for label, expected in expected_enabled.items():
                axis = by_label.get(label)
                if axis is None or not axis.get("available", True):
                    if expected:
                        confirmed = False
                    continue
                actual = bool(axis.get("is_armed")) or (
                    _int_or_zero(axis.get("current_state")) == AXIS_STATE_CLOSED_LOOP_CONTROL
                    and _int_or_zero(axis.get("active_errors")) == 0
                    and _int_or_zero(axis.get("disarm_reason")) == 0
                )
                if actual != expected:
                    confirmed = False
            if confirmed:
                return latest
            telemetry = latest.get("telemetry_source")
            if isinstance(telemetry, dict):
                sequence = max(sequence, _int_or_zero(telemetry.get("sequence")))

        states = ", ".join(
            f"{label}={'enabled' if enabled else 'disabled'}"
            for label, enabled in expected_enabled.items()
        )
        raise ODriveConnectionError(f"Drive did not confirm requested state within 1 second: {states}.")

    def _publish_telemetry(self, latest: dict[str, Any]) -> None:
        published_at = monotonic()
        with self._telemetry_updated:
            previous_at = self._telemetry_published_at
            self._telemetry_sequence += 1
            self._telemetry_published_at = published_at
            latest["telemetry_source"] = {
                "owner": "odrive-hardware-io",
                "sequence": self._telemetry_sequence,
                "sample_interval_ms": (
                    None
                    if previous_at <= 0.0
                    else round((published_at - previous_at) * 1000.0, 3)
                ),
                "age_ms": 0.0,
            }
            self._latest = latest
            self._telemetry_updated.notify_all()

    def _motor_calibration_state_snapshot(self) -> dict[str, dict[str, Any]]:
        with self._motor_calibration_lock:
            return {label: dict(state) for label, state in self._motor_calibration_state.items()}

    def _poll_loop(self) -> None:
        self._hardware_io.bind_owner()
        next_poll_at = monotonic()
        while not self._stop.is_set():
            # Commands wake the owner immediately. At most one command runs
            # between due telemetry samples, so neither control nor status can
            # starve the other. No other task is allowed to touch ODrive USB.
            task = self._hardware_io.take(timeout=max(0.0, next_poll_at - monotonic()))
            if task is not None:
                self._hardware_io.execute(task)
                if monotonic() < next_poll_at:
                    continue
            started_at = monotonic()
            latest = self._poll_once()
            self._publish_telemetry(latest)

            elapsed = monotonic() - started_at
            next_poll_at = monotonic() + max(
                TELEMETRY_CONTENTION_YIELD_SEC,
                self._poll_interval - elapsed,
            )

    def _hardware_call(
        self,
        callback: Any,
        *,
        label: str,
        priority: int = PRIORITY_CONTROL,
        coalesce_key: str | None = None,
    ) -> Any:
        if self._thread is None:
            self.start()
        return self._hardware_io.call(
            callback,
            label=label,
            priority=priority,
            coalesce_key=coalesce_key,
        )

    def _hardware_publish_latest(
        self,
        coalesce_key: str,
        callback: Any,
        *,
        label: str,
    ) -> None:
        if self._thread is None:
            self.start()
        self._hardware_io.publish_latest(
            coalesce_key,
            callback,
            label=label,
            priority=PRIORITY_CONTROL,
        )

    def _poll_once(self) -> dict[str, Any]:
        try:
            with self._device_lock:
                if self._devices is None:
                    self._connected_devices()
                status = self._read_drive_status(self._devices, telemetry_only=True)
                _require_valid_drive_status(status)
                if _status_has_missing_configured_drive(status):
                    now = monotonic()
                    if now >= self._next_missing_drive_retry_at:
                        self._next_missing_drive_retry_at = now + 5.0
                        raise ODriveConnectionError("A configured ODrive is missing; reconnecting to both drives.")
                else:
                    self._next_missing_drive_retry_at = 0.0
                azimuth_sensors = _read_azimuth_sensors()
                self._enforce_runtime_limits(status, azimuth_sensors)
                self._apply_current_envelopes(status, self._devices)
        except Exception as exc:
            self._devices = None
            message = str(exc)
            if not isinstance(exc, ODriveConnectionError):
                message = f"Could not read ODrive status: {message}"
            return {
                "connected": False,
                "run_mode": "hardware",
                "simulation_mode": False,
                "error": message,
                "poll_interval_ms": int(self._poll_interval * 1000),
                "timestamp": _timestamp(),
                "server_started_at": _server_started_at(),
                "azimuth_sensors": _read_azimuth_sensors(),
                "hardware_io": self._hardware_io.stats(),
            }

        data = asdict(status)
        status_timestamp = _timestamp()
        data.update(
            {
                "connected": True,
                "run_mode": "hardware",
                "simulation_mode": False,
                "has_bus_power": status.has_bus_power,
                "health": _health_label(
                    status.has_bus_power,
                    any(axis.active_errors for axis in status.axes if axis.available),
                ),
                "poll_interval_ms": int(self._poll_interval * 1000),
                "timestamp": status_timestamp,
                "server_started_at": _server_started_at(),
                "azimuth_sensors": azimuth_sensors,
                "hardware_io": self._hardware_io.stats(),
            }
        )
        _apply_position_offsets_to_payload(data, self._position_unwrap)
        self._filter_velocity_payload(data)
        self._apply_current_envelope_payload(data)
        self._apply_software_position_payload(data)
        self._apply_sine_velocity_payload(data)
        self._capture_drive_error_events(data, status_timestamp)
        data["drive_error_events"] = self._drive_error_events_snapshot()
        data["auto_tune_progress"] = self._auto_tune_progress_snapshot()
        data["auto_tune_step_events"] = self._auto_tune_step_events_snapshot()
        return data

    def _apply_current_envelopes(self, status: Any, devices: tuple[Any, ...]) -> None:
        now = monotonic()
        for axis_index, axis_status in enumerate(status.axes[:2]):
            if not axis_status.available or axis_index >= len(devices) or devices[axis_index] is None:
                continue
            label = axis_status.label
            envelope = self._current_envelopes.get(label)
            if envelope is None:
                continue
            previous_step = self._current_envelope_last_step.get(label, now)
            self._current_envelope_last_step[label] = now
            output = envelope.step(
                _finite_float(axis_status.current) or 0.0,
                now - previous_step,
            )
            self._current_envelope_state[label] = {
                "phase": output.phase,
                "continuous_current_amp": MOTOR_CURRENT_ENVELOPE.continuous_current_amp,
                "peak_current_amp": MOTOR_CURRENT_ENVELOPE.peak_current_amp,
                "hard_current_amp": MOTOR_CURRENT_ENVELOPE.hard_current_amp,
                "peak_duration_sec": MOTOR_CURRENT_ENVELOPE.peak_duration_sec,
                "derating_duration_sec": MOTOR_CURRENT_ENVELOPE.derating_duration_sec,
                "allowed_current_amp": output.allowed_current_amp,
                "torque_limit_nm": output.torque_limit_nm,
                "peak_used_sec": output.peak_used_sec,
                "peak_remaining_sec": output.peak_remaining_sec,
                "recovery_current_amp": MOTOR_CURRENT_ENVELOPE.recovery_current_amp,
                "recovery_duration_sec": MOTOR_CURRENT_ENVELOPE.recovery_duration_sec,
                "recovery_sec": output.recovery_sec,
            }

            last_applied = self._current_envelope_applied_amp.get(label)
            last_write = self._current_envelope_last_write.get(label, 0.0)
            write_due = (
                last_applied is None
                or abs(output.allowed_current_amp - last_applied) >= CURRENT_LIMIT_WRITE_STEP_AMP
            ) and now - last_write >= CURRENT_LIMIT_WRITE_INTERVAL_SEC
            if not write_due:
                continue
            axis = getattr(devices[axis_index], "axis0")
            _set_if_present(axis, "config.torque_soft_max", output.torque_limit_nm)
            _set_if_present(axis, "config.torque_soft_min", -output.torque_limit_nm)
            self._current_envelope_applied_amp[label] = output.allowed_current_amp
            self._current_envelope_last_write[label] = now

    def _apply_current_envelope_payload(self, data: dict[str, Any]) -> None:
        axes = data.get("axes")
        if not isinstance(axes, (list, tuple)):
            return
        for axis in axes:
            if not isinstance(axis, dict):
                continue
            state = self._current_envelope_state.get(str(axis.get("label")))
            axis["current_protection"] = dict(state) if state is not None else None
            if state is not None:
                torque_limit = _finite_float(state.get("torque_limit_nm"))
                if torque_limit is not None:
                    # These are centrally commanded values. ODrive's compact
                    # telemetry mode deliberately reuses cached config fields,
                    # so expose the owner's latest applied envelope instead of
                    # a stale startup readback.
                    axis["torque_soft_max"] = torque_limit
                    axis["torque_soft_min"] = -torque_limit

    def _capture_drive_error_events(self, data: dict[str, Any], timestamp: str) -> None:
        axes = data.get("axes") if isinstance(data.get("axes"), (list, tuple)) else []
        with self._error_event_lock:
            seen_labels: set[str] = set()
            for axis in axes:
                if not axis.get("available"):
                    continue
                label = str(axis.get("label") or axis.get("name") or "Axis")
                seen_labels.add(label)
                active_errors = _int_or_zero(axis.get("active_errors"))
                disarm_reason = _int_or_zero(axis.get("disarm_reason"))
                state = (active_errors, disarm_reason)
                previous = self._last_drive_error_state.get(label)
                if previous == state:
                    continue

                self._last_drive_error_state[label] = state
                if active_errors == 0 and disarm_reason == 0 and previous is None:
                    continue

                self._drive_error_sequence += 1
                self._drive_error_events.append(
                    {
                        "id": self._drive_error_sequence,
                        "timestamp": timestamp,
                        "label": label,
                        "active_errors": active_errors,
                        "disarm_reason": disarm_reason,
                        "cleared": active_errors == 0 and disarm_reason == 0,
                    }
                )
                self._drive_error_events = self._drive_error_events[-MAX_DRIVE_ERROR_EVENTS:]

            for label in list(self._last_drive_error_state):
                if label in seen_labels:
                    continue
                del self._last_drive_error_state[label]

    def _drive_error_events_snapshot(self) -> list[dict[str, Any]]:
        with self._error_event_lock:
            return [dict(event) for event in self._drive_error_events]

    def _set_auto_tune_progress(self, progress: dict[str, Any] | None) -> None:
        with self._auto_tune_progress_lock:
            if progress is None:
                self._auto_tune_progress = None
                return
            progress_copy = dict(progress)
            step_event = progress_copy.pop("step_event", None)
            self._auto_tune_progress = progress_copy
            if isinstance(step_event, dict):
                self._auto_tune_step_sequence += 1
                event = dict(step_event)
                event["id"] = self._auto_tune_step_sequence
                event.setdefault("timestamp", _timestamp())
                self._auto_tune_step_events.append(event)
                self._auto_tune_step_events = self._auto_tune_step_events[-MAX_AUTO_TUNE_STEP_EVENTS:]

    def _auto_tune_progress_snapshot(self) -> dict[str, Any] | None:
        with self._auto_tune_progress_lock:
            return dict(self._auto_tune_progress) if self._auto_tune_progress is not None else None

    def _auto_tune_step_events_snapshot(self) -> list[dict[str, Any]]:
        with self._auto_tune_progress_lock:
            return [dict(event) for event in self._auto_tune_step_events]

    def update_tuning(self, label: str, values: dict[str, float]) -> dict[str, Any]:
        if not self._hardware_io.is_owner():
            return self._hardware_call(
                lambda: self.update_tuning(label, dict(values)),
                label=f"update-tuning:{label}",
                priority=PRIORITY_CONFIGURATION,
            )
        axis_index = {"Azimuth": 0, "Altitude": 1}.get(label)
        if axis_index is None:
            raise ValueError(f"Unknown axis: {label}")

        software_position_gain = values.pop("position_gain", None)
        command_velocity_limit = values.get("velocity_limit") if label == "Azimuth" else None
        if software_position_gain is not None:
            _save_software_position_gain(label, software_position_gain)
        if not values:
            data = self.snapshot()
            self._apply_software_position_payload(data)
            return data

        with self._device_lock:
            if self._devices is None:
                self._devices = _order_devices_for_config(connect_many(count=2, timeout=self._timeout))
            if axis_index >= len(self._devices):
                raise ODriveConnectionError(f"{label} drive is not connected.")

            axis = getattr(self._devices[axis_index], "axis0")
            for key, value in values.items():
                _set_path_value(axis, TUNING_FIELDS[key], _tuning_value_to_odrive_units(key, value))
            # Force the next owner poll to refresh configuration fields. The
            # command itself never performs a second hardware read.
            self._drive_status = None

        if command_velocity_limit is not None and command_velocity_limit > 0.0:
            _save_command_velocity_limit(min(command_velocity_limit, SAFE_MAX_SLEW_RATE_DEG_PER_SEC))

        return self.snapshot()

    def save_configuration(self, label: str) -> dict[str, Any]:
        if not self._hardware_io.is_owner():
            return self._hardware_call(
                lambda: self.save_configuration(label),
                label=f"save-configuration:{label}",
                priority=PRIORITY_CONFIGURATION,
            )
        axis_index = {"Azimuth": 0, "Altitude": 1}.get(label)
        if axis_index is None:
            raise ValueError(f"Unknown axis: {label}")

        with self._device_lock:
            devices = self._connected_devices()
            if axis_index >= len(devices) or devices[axis_index] is None:
                raise ODriveConnectionError(f"{label} drive is not connected.")
            _stop_and_disable_devices(devices)
            device = devices[axis_index]
            serial = _device_serial(device)
            if serial is None:
                raise ODriveConnectionError(f"Could not read the {label} drive serial number.")
            preserved_unwrapped = _finite_float(
                self._position_unwrap.get(label, {}).get("unwrapped")
            )
            warning = None
            try:
                device.save_configuration()
            except Exception:
                warning = (
                    f"{label} drive disconnected while saving configuration; "
                    "this is expected during ODrive flash/reboot."
                )

            # save_configuration reboots the selected drive and invalidates its
            # USB object. Keep the other drive handle while waiting for this
            # exact serial to return, instead of caching a (None, other-drive)
            # tuple that never repairs itself.
            reconnect_devices = list(devices)
            reconnect_devices[axis_index] = None
            self._devices = tuple(reconnect_devices)
            self._drive_status = None
            reconnected = self._wait_for_saved_drive_reconnect(
                label,
                axis_index,
                serial,
                preserved_unwrapped,
            )
        return {"axis": label, "serial": serial, "warning": warning, "reconnected": reconnected}

    def _wait_for_saved_drive_reconnect(
        self,
        label: str,
        axis_index: int,
        expected_serial: Any,
        preserved_unwrapped: float | None,
        timeout_sec: float = 15.0,
    ) -> bool:
        deadline = monotonic() + timeout_sec
        last_error: Exception | None = None
        discovery_serial = _odrive_discovery_serial(expected_serial)
        while monotonic() < deadline:
            sleep(0.35)
            remaining = max(0.25, deadline - monotonic())
            try:
                device = connect(timeout=min(1.0, remaining), serial_number=discovery_serial)
                if str(_device_serial(device)) != str(expected_serial):
                    continue
                devices = list(self._devices or ())
                while len(devices) <= axis_index:
                    devices.append(None)
                devices[axis_index] = device
                self._devices = tuple(devices)
                status, settled_absolute = self._wait_for_reconnected_axis_settle(
                    label,
                    axis_index,
                    timeout_sec=min(4.0, max(1.0, deadline - monotonic())),
                )
                self._drive_status = status
                if label == "Azimuth" and preserved_unwrapped is not None and settled_absolute is not None:
                    self._position_unwrap[label] = {
                        "absolute": settled_absolute,
                        "unwrapped": preserved_unwrapped,
                    }
                return True
            except Exception as exc:
                last_error = exc

        # Force the monitor to perform full discovery on its next poll. Preserve
        # the unwrap state so an absolute angle near 360 degrees remains on the
        # same continuous branch after the drive reboot.
        self._devices = None
        self._drive_status = None
        detail = f": {last_error}" if last_error else ""
        raise ODriveConnectionError(
            f"{label} configuration was saved, but drive serial {expected_serial} "
            f"did not reconnect within {timeout_sec:g} seconds{detail}"
        )

    def _wait_for_reconnected_axis_settle(
        self,
        label: str,
        axis_index: int,
        timeout_sec: float,
    ) -> tuple[Any, float | None]:
        deadline = monotonic() + timeout_sec
        previous_absolute: float | None = None
        stable_samples = 0
        last_status: Any | None = None
        last_absolute: float | None = None
        while monotonic() < deadline:
            status = self._read_drive_status(self._devices)
            axis_status = status.axes[axis_index] if axis_index < len(status.axes) else None
            if axis_status is None or not axis_status.available:
                raise ODriveConnectionError(f"{label} returned over USB but axis0 is unavailable.")
            raw_position = _finite_float(getattr(axis_status, "position_deg", None))
            if raw_position is not None:
                last_absolute = _normalize_degrees(raw_position * _axis_position_scale(label))
                delta = (
                    abs(_signed_degree_delta(last_absolute, previous_absolute))
                    if previous_absolute is not None
                    else math.inf
                )
                errors_clear = _int_or_zero(getattr(axis_status, "active_errors", None)) == 0
                stable_samples = stable_samples + 1 if delta <= 0.02 and errors_clear else 0
                previous_absolute = last_absolute
            last_status = status
            if stable_samples >= 5:
                return status, last_absolute
            sleep(0.1)
        if last_status is None:
            raise ODriveConnectionError(f"{label} did not produce telemetry after reconnect.")
        return last_status, last_absolute

    def auto_tune_axis(self, label: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._hardware_io.is_owner():
            options_copy = dict(options) if isinstance(options, dict) else options
            return self._hardware_call(
                lambda: self.auto_tune_axis(label, options_copy),
                label=f"auto-tune:{label}",
                priority=PRIORITY_CONFIGURATION,
            )
        axis_index = {"Azimuth": 0, "Altitude": 1}.get(label)
        if axis_index is None:
            raise ValueError(f"Unknown axis: {label}")

        self._auto_tune_stop.clear()
        with self._auto_tune_progress_lock:
            self._auto_tune_step_events = [event for event in self._auto_tune_step_events if event.get("axis") != label]
        self._set_auto_tune_progress(
            {
                "running": True,
                "axis": label,
                "phase": "starting",
                "message": f"Starting {label} auto tune...",
                "completed_steps": 0,
                "total_steps": 1,
                "percent": 0.0,
                "timestamp": _timestamp(),
            }
        )
        with self._device_lock:
            try:
                devices = self._connected_devices()
                if axis_index >= len(devices):
                    raise ODriveConnectionError(f"{label} drive is not connected.")
                last_telemetry_at = [0.0]

                def telemetry_callback() -> None:
                    now = monotonic()
                    if now - last_telemetry_at[0] < TELEMETRY_INTERVAL_SEC:
                        return
                    last_telemetry_at[0] = now
                    self._refresh_latest_status_unlocked(devices)

                result = _run_axis_auto_tune(
                    label,
                    devices[axis_index],
                    options,
                    self._auto_tune_stop,
                    self._set_auto_tune_progress,
                    telemetry_callback,
                )
                warning = None
                if result.get("save_recommended", True):
                    try:
                        devices[axis_index].save_configuration()
                    except Exception:
                        warning = (
                            f"{label} drive disconnected while saving auto tune configuration; "
                            "this is expected during ODrive flash/reboot."
                        )
                    self._devices = None
            except Exception:
                self._set_auto_tune_progress(
                    {
                        "running": False,
                        "axis": label,
                        "phase": "failed",
                        "message": f"{label} auto tune failed.",
                        "completed_steps": 0,
                        "total_steps": 1,
                        "percent": 100.0,
                        "timestamp": _timestamp(),
                    }
                )
                raise
        result["flash"] = {
            "axis": label,
            "serial": result.get("serial"),
            "warning": warning,
            "saved": bool(result.get("save_recommended", True)),
        }
        completed_steps = int(result.get("completed_steps") or 1)
        self._set_auto_tune_progress(
            {
                "running": False,
                "axis": label,
                "phase": "complete",
                "message": f"{label} auto tune complete.",
                "completed_steps": completed_steps,
                "total_steps": completed_steps,
                "current_step": completed_steps,
                "percent": 100.0,
                "timestamp": _timestamp(),
            }
        )
        return result

    def request_auto_tune_stop(self) -> dict[str, Any]:
        self._auto_tune_stop.set()
        return {"requested": True}

    def reload_configuration(self) -> None:
        if not self._hardware_io.is_owner():
            self._hardware_call(
                self.reload_configuration,
                label="reload-configuration",
                priority=PRIORITY_CONFIGURATION,
            )
            return
        with self._device_lock:
            self._devices = None

    def flash_motion_limits(self, settings: dict[str, Any]) -> dict[str, Any]:
        if not self._hardware_io.is_owner():
            return self._hardware_call(
                lambda: self.flash_motion_limits(dict(settings)),
                label="flash-motion-limits",
                priority=PRIORITY_CONFIGURATION,
            )
        with self._device_lock:
            devices = self._connected_devices()
            _stop_and_disable_devices(devices)
            result = _flash_motion_limits_to_drives(devices, settings)
            self._devices = None
        return result

    def enable_motors(self) -> dict[str, Any]:
        if not self._hardware_io.is_owner():
            after_sequence = self._telemetry_cursor()
            self._hardware_call(
                self.enable_motors,
                label="enable-motors",
                priority=PRIORITY_CONTROL,
            )
            return self._wait_for_command_confirmation(
                after_sequence,
                {"Azimuth": True, "Altitude": True},
            )
        with self._device_lock:
            devices = self._connected_devices()
            for axis_index, device in enumerate(devices[:2]):
                if device is None:
                    continue
                _clear_device_errors(device)
                axis = getattr(device, "axis0")
                _configure_velocity_control(axis)
                _set_if_present(axis, "controller.input_vel", 0.0)
                _set_if_present(axis, "controller.input_torque", 0.0)
                axis.requested_state = AXIS_STATE_CLOSED_LOOP_CONTROL
                label = "Azimuth" if axis_index == 0 else "Altitude"
                self._record_velocity_commands({label: 0.0})
            self._drive_status = None
        return self.snapshot()

    def disable_motors(self) -> dict[str, Any]:
        if not self._hardware_io.is_owner():
            after_sequence = self._telemetry_cursor()
            self._hardware_call(
                self.disable_motors,
                label="disable-motors",
                priority=PRIORITY_SAFETY,
            )
            return self._wait_for_command_confirmation(
                after_sequence,
                {"Azimuth": False, "Altitude": False},
            )
        with self._device_lock:
            devices = self._connected_devices()
            for device in devices[:2]:
                if device is None:
                    continue
                getattr(device, "axis0").requested_state = AXIS_STATE_IDLE
            with self._velocity_command_lock:
                self._last_velocity_command_deg_per_sec.clear()
        return self.snapshot()

    def set_axis_enabled(self, label: str, enabled: bool) -> dict[str, Any]:
        axis_index = {"Azimuth": 0, "Altitude": 1}.get(label)
        if axis_index is None:
            raise ValueError(f"Unknown axis: {label}")
        if not self._hardware_io.is_owner():
            if not enabled:
                self.stop_motor_calibration(label)
            after_sequence = self._telemetry_cursor()
            self._hardware_call(
                lambda: self._set_axis_enabled_hardware(label, axis_index, enabled),
                label=f"set-axis-enabled:{label}",
                priority=PRIORITY_CONTROL if enabled else PRIORITY_SAFETY,
            )
            return self._wait_for_command_confirmation(after_sequence, {label: enabled})
        return self._set_axis_enabled_hardware(label, axis_index, enabled)

    def _set_axis_enabled_hardware(
        self,
        label: str,
        axis_index: int,
        enabled: bool,
    ) -> dict[str, Any]:
        with self._device_lock:
            devices = self._connected_devices()
            if axis_index >= len(devices) or devices[axis_index] is None:
                raise ODriveConnectionError(f"{label} drive is not connected.")
            axis = getattr(devices[axis_index], "axis0")
            if enabled:
                _clear_device_errors(devices[axis_index])
                _configure_velocity_control(axis)
                _set_if_present(axis, "controller.input_vel", 0.0)
                axis.requested_state = AXIS_STATE_CLOSED_LOOP_CONTROL
                self._record_velocity_commands({label: 0.0})
                self._drive_status = None
            else:
                _hold_axis_at_current_position(axis)
                axis.requested_state = AXIS_STATE_IDLE
                with self._velocity_command_lock:
                    self._last_velocity_command_deg_per_sec.pop(label, None)
        return self.snapshot()

    def stop_motors(self) -> dict[str, Any]:
        if not self._hardware_io.is_owner():
            return self._hardware_call(
                self.stop_motors,
                label="stop-motors",
                priority=PRIORITY_SAFETY,
            )
        # Safety stop invalidates every asynchronous motion producer without
        # waiting for their thread joins. The generation guards prevent those
        # stale loops from writing after the zero command below.
        self._request_motor_calibration_stops()
        self._cancel_software_position_move(wait=False)
        self._request_sine_velocity_stops()
        velocity_control_axes = self._cached_velocity_control_axes()
        with self._device_lock:
            devices = self._connected_devices()
            for axis_index, device in enumerate(devices[:2]):
                if device is None:
                    continue
                axis = getattr(device, "axis0")
                # Land the zero setpoints first.  When an axis is already in
                # velocity mode this is the complete physical stop path; the
                # slower config/status USB traffic happens afterwards.
                _set_if_present(axis, "controller.input_vel", 0.0)
                _set_if_present(axis, "controller.input_torque", 0.0)
                label = "Azimuth" if axis_index == 0 else "Altitude"
                if label not in velocity_control_axes:
                    _configure_velocity_control(axis)
                    _set_if_present(axis, "controller.input_vel", 0.0)
                    self._drive_status = None
                self._record_velocity_commands({label: 0.0})
        return self.snapshot()

    def request_safety_stop(self) -> None:
        """Invalidate asynchronous producers without performing hardware I/O."""

        self._auto_tune_stop.set()
        self._request_motor_calibration_stops()
        self._cancel_software_position_move(wait=False)
        self._request_sine_velocity_stops()

    def start_motor_calibration(self, label: str, options: dict[str, float]) -> dict[str, Any]:
        if label not in MotionCommandGuard.AXIS_INDEX:
            raise ValueError(f"Unknown axis: {label}")
        lower = options["min_position_deg"]
        upper = options["max_position_deg"]
        speed = options["speed_deg_per_sec"]
        current_amp = options["current_amp"]
        current_limit_key = "azimuth_current_limit_amp" if label == "Azimuth" else "altitude_current_limit_amp"
        configured_current_limit = _finite_float(
            _load_app_settings().get("motion_limits", {}).get(current_limit_key)
        )
        if configured_current_limit is not None and current_amp > configured_current_limit:
            raise ValueError(
                f"Test current {current_amp:g} Amp exceeds the configured {label} limit "
                f"of {configured_current_limit:g} Amp."
            )
        _validate_motion_targets({label: lower})
        _validate_motion_targets({label: upper})
        with self._motor_calibration_lock:
            other_running = next(
                (
                    axis_label
                    for axis_label, state in self._motor_calibration_state.items()
                    if axis_label != label and state.get("running")
                ),
                None,
            )
        if other_running is not None:
            raise ValueError(f"Stop {other_running} motor calibration before starting {label}.")
        self.stop_motor_calibration(label)

        self._require_enabled_snapshot("goto", {label: lower})

        stop_event = Event()
        with self._motor_calibration_lock:
            self._motor_calibration_stops[label] = stop_event
            self._motor_calibration_state[label] = {
                "running": True,
                "phase": "starting",
                "target_deg": lower,
                **options,
                "started_at": _timestamp(),
                "updated_at": _timestamp(),
            }
            thread = Thread(
                target=self._motor_calibration_loop,
                args=(label, lower, upper, speed, current_amp, stop_event),
                name=f"motor-calibration-{label.lower()}",
                daemon=True,
            )
            self._motor_calibration_threads[label] = thread
            thread.start()
        return self.snapshot()

    def stop_motor_calibration(self, label: str) -> dict[str, Any]:
        if label not in MotionCommandGuard.AXIS_INDEX:
            raise ValueError(f"Unknown axis: {label}")
        with self._motor_calibration_lock:
            stop_event = self._motor_calibration_stops.get(label)
            thread = self._motor_calibration_threads.get(label)
        if stop_event is not None:
            stop_event.set()
        self._cancel_software_position_move()
        if thread is not None and thread.is_alive() and thread is not current_thread():
            thread.join(timeout=1.0)
            if thread.is_alive():
                raise ODriveConnectionError(
                    f"{label} calibration did not stop before the safety deadline."
                )
        with self._motor_calibration_lock:
            state = self._motor_calibration_state.setdefault(label, {})
            state.update({"running": False, "phase": "stopped", "updated_at": _timestamp()})
        return self.snapshot()

    def _cancel_motor_calibrations(self) -> None:
        with self._motor_calibration_lock:
            labels = tuple(self._motor_calibration_stops)
        for label in labels:
            self.stop_motor_calibration(label)

    def _request_motor_calibration_stops(self) -> None:
        with self._motor_calibration_lock:
            events = tuple(self._motor_calibration_stops.values())
            for state in self._motor_calibration_state.values():
                state.update({"running": False, "phase": "stopping", "updated_at": _timestamp()})
        for event in events:
            event.set()

    def _motor_calibration_loop(
        self,
        label: str,
        lower: float,
        upper: float,
        speed: float,
        current_amp: float,
        stop_event: Event,
    ) -> None:
        axis_index = MotionCommandGuard.AXIS_INDEX[label]
        previous_torque_max: float | None = None
        previous_torque_min: float | None = None
        phase = "stopped"
        try:
            latest_axis = next(
                (
                    axis
                    for axis in self.snapshot().get("axes", [])
                    if isinstance(axis, dict) and axis.get("label") == label
                ),
                {},
            )
            previous_torque_max = _finite_float(latest_axis.get("torque_soft_max"))
            previous_torque_min = _finite_float(latest_axis.get("torque_soft_min"))
            torque_limit = current_amp * DEFAULT_TORQUE_CONSTANT_NM_PER_AMP

            def apply_calibration_torque() -> None:
                devices = self._connected_devices()
                axis = getattr(devices[axis_index], "axis0")
                _set_required(axis, "config.torque_soft_max", torque_limit)
                _set_required(axis, "config.torque_soft_min", -torque_limit)

            self._hardware_call(
                apply_calibration_torque,
                label=f"motor-calibration-torque:{label}",
                priority=PRIORITY_CONFIGURATION,
            )

            target = lower
            while not stop_event.is_set():
                phase = "moving-to-min" if target == lower else "moving-to-max"
                with self._motor_calibration_lock:
                    self._motor_calibration_state[label].update(
                        {"phase": phase, "target_deg": target, "updated_at": _timestamp()}
                    )
                self._start_software_position_move({label: target}, speed)
                while not stop_event.wait(0.1):
                    with self._software_position_lock:
                        move_state = dict(self._software_position_state.get(label, {}))
                    move_phase = move_state.get("phase")
                    if move_phase == "reached":
                        break
                    if move_phase in ("error", "timeout", "cancelled"):
                        raise ODriveConnectionError(f"Calibration move {move_phase}.")
                if stop_event.is_set():
                    break
                target = upper if target == lower else lower
        except Exception as exc:
            phase = "error"
            with self._motor_calibration_lock:
                self._motor_calibration_state[label].update({"error": str(exc)})
        finally:
            if not stop_event.is_set():
                self._cancel_software_position_move()
            try:
                def restore_torque() -> None:
                    devices = self._connected_devices()
                    axis = getattr(devices[axis_index], "axis0")
                    if previous_torque_max is not None:
                        _set_if_present(axis, "config.torque_soft_max", previous_torque_max)
                    if previous_torque_min is not None:
                        _set_if_present(axis, "config.torque_soft_min", previous_torque_min)

                self._hardware_call(
                    restore_torque,
                    label=f"restore-motor-calibration-torque:{label}",
                    priority=PRIORITY_CONFIGURATION,
                )
            except Exception:
                pass
            with self._motor_calibration_lock:
                self._motor_calibration_state[label].update(
                    {"running": False, "phase": phase, "updated_at": _timestamp()}
                )

    def goto_positions(self, positions_deg: dict[str, float], velocity_target_deg_per_sec: float | None = None) -> dict[str, Any]:
        for label in positions_deg:
            self.stop_motor_calibration(label)
        self._cancel_sine_velocity_tests(tuple(positions_deg))
        _validate_motion_targets(positions_deg)
        velocity_target_deg_per_sec = _effective_slew_rate(velocity_target_deg_per_sec) or _configured_slew_rate() or 30.0
        self._start_software_position_move(positions_deg, velocity_target_deg_per_sec)
        # Command acknowledgement must not perform another full USB telemetry
        # read. The monitor thread owns status refreshes; reading here stalls
        # the newly-started control loop and couples API latency to USB latency.
        return self.snapshot()

    def _start_software_position_move(self, positions_deg: dict[str, float], max_speed_deg_per_sec: float) -> None:
        generation = self._cancel_software_position_move()
        start_positions_deg: dict[str, float] = {}
        initial_commands_deg_per_sec: dict[str, float] = {}
        resolved_positions_deg = dict(positions_deg)
        latest = self.snapshot()
        latest_axes = latest.get("axes")
        axes_by_label = {
            str(axis.get("label")): axis
            for axis in latest_axes
            if isinstance(axis, dict)
        } if isinstance(latest_axes, (list, tuple)) else {}
        self._require_enabled_snapshot("goto", positions_deg, latest)

        def prepare_hardware() -> None:
            devices = self._connected_devices()
            _apply_slew_rate(devices, max_speed_deg_per_sec)
            for label in positions_deg:
                axis_index = MotionCommandGuard.AXIS_INDEX[label]
                axis = getattr(devices[axis_index], "axis0")
                axis_status = axes_by_label.get(label)
                was_velocity_control = (
                    axis_status is not None
                    and axis_status.get("control_mode") == CONTROL_MODE_VELOCITY_CONTROL
                )
                input_velocity = (
                    _finite_float(axis_status.get("input_vel")) if axis_status is not None else None
                )
                initial_commands_deg_per_sec[label] = (
                    input_velocity or 0.0
                    if was_velocity_control
                    else 0.0
                )
                _configure_velocity_control(axis)
                if not was_velocity_control:
                    _set_if_present(axis, "controller.input_vel", 0.0)

        self._hardware_call(
            prepare_hardware,
            label="prepare-position-motion",
            priority=PRIORITY_CONTROL,
        )

        limits = _load_app_settings().get("motion_limits", {})
        for label in positions_deg:
            axis_status = axes_by_label.get(label)
            current = _finite_float(axis_status.get("position_deg")) if axis_status else None
            if current is None:
                continue
            start_positions_deg[label] = current
            if label == "Azimuth":
                resolved_positions_deg[label] = _resolve_azimuth_target_deg(
                    positions_deg[label],
                    current,
                    _finite_float(limits.get("azimuth_ccw_limit_deg")),
                    _finite_float(limits.get("azimuth_cw_limit_deg")),
                )

        positions_deg = resolved_positions_deg

        stop_event = Event()
        with self._software_position_lock:
            if generation != self._software_position_generation:
                return
            self._software_position_stop = stop_event
            now = _timestamp()
            self._software_position_state = {
                label: {
                    "active": True,
                    "target_deg": target,
                    "max_speed_deg_per_sec": max_speed_deg_per_sec,
                    "gain": _software_position_gain(label),
                    "error_deg": None,
                    "command_velocity_deg_per_sec": initial_commands_deg_per_sec.get(label, 0.0),
                    "phase": "moving",
                    "started_at": now,
                    "updated_at": now,
                }
                for label, target in positions_deg.items()
            }
            self._software_position_thread = Thread(
                target=self._software_position_loop,
                args=(
                    dict(positions_deg),
                    start_positions_deg,
                    float(max_speed_deg_per_sec),
                    initial_commands_deg_per_sec,
                    stop_event,
                    generation,
                ),
                name="software-position-loop",
                daemon=True,
            )
            self._software_position_thread.start()

    def _cancel_software_position_move(self, *, wait: bool = True) -> int:
        with self._software_position_lock:
            stop_event = self._software_position_stop
            thread = self._software_position_thread
            self._software_position_generation += 1
            generation = self._software_position_generation
        stop_event.set()
        if wait and thread is not None and thread.is_alive() and thread is not current_thread():
            thread.join(timeout=0.4)
        with self._software_position_lock:
            if generation == self._software_position_generation:
                for state in self._software_position_state.values():
                    state["active"] = False
                    state["phase"] = "cancelled"
                    state["command_velocity_deg_per_sec"] = 0.0
                    state["updated_at"] = _timestamp()
        return generation

    def _software_position_loop(
        self,
        positions_deg: dict[str, float],
        start_positions_deg: dict[str, float],
        max_speed_deg_per_sec: float,
        initial_commands_deg_per_sec: dict[str, float],
        stop_event: Event,
        generation: int,
    ) -> None:
        max_speed = max(0.1, abs(max_speed_deg_per_sec))
        previous_commands = {
            label: initial_commands_deg_per_sec.get(label, 0.0)
            for label in positions_deg
        }
        timeout_at = monotonic() + _software_position_timeout_sec(positions_deg, start_positions_deg, max_speed)
        phase = "moving"
        initial_telemetry = self.snapshot().get("telemetry_source", {})
        last_telemetry_sequence = max(
            -1,
            int(initial_telemetry.get("sequence") or 0) - 1,
        )
        previous_sample_at: float | None = None
        try:
            while not stop_event.is_set():
                command_by_label: dict[str, float] = {}
                state_updates: dict[str, dict[str, Any]] = {}
                all_settled = True
                # Telemetry is owned by the monitor task.  The algorithm reads
                # its immutable snapshot, so calculations never hold the USB
                # lock or double the number of drive reads during motion.
                latest = self.wait_for_telemetry(
                    last_telemetry_sequence,
                    timeout=max(0.05, SOFTWARE_POSITION_INTERVAL_SEC * 2.0),
                )
                telemetry_source = latest.get("telemetry_source", {})
                telemetry_sequence = int(telemetry_source.get("sequence") or 0)
                if telemetry_sequence <= last_telemetry_sequence:
                    if monotonic() >= timeout_at:
                        phase = "timeout"
                        break
                    continue
                last_telemetry_sequence = telemetry_sequence
                sample_at = monotonic()
                control_interval_sec = (
                    SOFTWARE_POSITION_INTERVAL_SEC
                    if previous_sample_at is None
                    else max(0.005, min(0.1, sample_at - previous_sample_at))
                )
                previous_sample_at = sample_at
                axes = latest.get("axes")
                axes_by_label = {
                    str(axis.get("label")): axis
                    for axis in axes
                    if isinstance(axis, dict)
                } if isinstance(axes, (list, tuple)) else {}
                limits = _load_app_settings().get("motion_limits", {})
                axis_limits = {
                    "Azimuth": (
                        _finite_float(limits.get("azimuth_ccw_limit_deg")),
                        _finite_float(limits.get("azimuth_cw_limit_deg")),
                    ),
                    "Altitude": (
                        _finite_float(limits.get("altitude_lower_limit_deg")),
                        _finite_float(limits.get("altitude_upper_limit_deg")),
                    ),
                }
                for label, target in positions_deg.items():
                    axis_status = axes_by_label.get(label)
                    current = _finite_float(axis_status.get("position_deg")) if axis_status else None
                    if current is None:
                        all_settled = False
                        continue
                    error = _axis_position_delta_deg(label, target, current)
                    actual_velocity = abs(
                        _finite_float(axis_status.get("velocity_deg_per_sec")) or 0.0
                    )
                    gain = _software_position_gain(label)
                    acceleration = _finite_float(limits.get(
                        f"{label.lower()}_remote_acceleration_deg_s2"
                    ))
                    step = self._position_algorithm.step(PositionStepInput(
                        error_deg=error,
                        actual_velocity_deg_per_sec=actual_velocity,
                        previous_command_deg_per_sec=previous_commands.get(label, 0.0),
                        max_speed_deg_per_sec=max_speed,
                        gain_per_sec=gain,
                        acceleration_deg_per_sec2=acceleration,
                        interval_sec=control_interval_sec,
                        position_tolerance_deg=SOFTWARE_POSITION_TOLERANCE_DEG,
                        settle_velocity_deg_per_sec=SOFTWARE_POSITION_SETTLE_VELOCITY_DEG_PER_SEC,
                    ))
                    settled = step.settled
                    command_velocity = step.command_velocity_deg_per_sec
                    lower, upper = axis_limits.get(label, (None, None))
                    command_velocity = _axis_velocity_limited_by_runtime_limits(
                        current,
                        command_velocity,
                        lower,
                        upper,
                    )
                    command_by_label[label] = command_velocity
                    previous_commands[label] = command_velocity
                    state_updates[label] = {
                        "active": not settled,
                        "target_deg": target,
                        "current_deg": current,
                        "max_speed_deg_per_sec": max_speed,
                        "gain": gain,
                        "error_deg": error,
                        "command_velocity_deg_per_sec": command_velocity,
                        "phase": "reached" if settled else "moving",
                        "updated_at": _timestamp(),
                    }
                    all_settled = all_settled and settled

                if not self._software_position_is_current(stop_event, generation):
                    break
                commands = dict(command_by_label)

                def write_latest_commands() -> None:
                    # Recheck on the hardware owner. A stop can invalidate this
                    # calculation while it is waiting in the mailbox.
                    if self._software_position_is_current(stop_event, generation):
                        self._write_velocity_commands_hardware(
                            commands,
                            require_enabled=False,
                        )

                self._hardware_publish_latest(
                    "software-position",
                    write_latest_commands,
                    label="software-position-setpoint",
                )

                self._update_software_position_state(state_updates, generation)
                if all_settled:
                    phase = "reached"
                    break
                if monotonic() >= timeout_at:
                    phase = "timeout"
                    break
        except Exception as exc:
            phase = "error"
            self._update_software_position_state(
                {
                    label: {
                        "active": False,
                        "phase": "error",
                        "error": str(exc),
                        "command_velocity_deg_per_sec": 0.0,
                        "updated_at": _timestamp(),
                    }
                    for label in positions_deg
                },
                generation,
            )
        finally:
            try:
                self._hardware_call(
                    lambda: self._stop_software_position_axes_if_current(
                        positions_deg,
                        generation,
                    ),
                    label="software-position-stop",
                    priority=PRIORITY_CONTROL,
                    coalesce_key="software-position",
                )
            except Exception:
                pass
            if phase != "error":
                self._finish_software_position_state(
                    positions_deg,
                    "cancelled" if stop_event.is_set() else phase,
                    generation,
                )

    def _software_position_is_current(self, stop_event: Event, generation: int) -> bool:
        if stop_event.is_set():
            return False
        with self._software_position_lock:
            return generation == self._software_position_generation

    def _stop_software_position_axes_if_current(
        self,
        positions_deg: dict[str, float],
        generation: int,
    ) -> None:
        with self._software_position_lock:
            if generation != self._software_position_generation:
                return
        self._write_velocity_commands_hardware(
            {label: 0.0 for label in positions_deg},
            require_enabled=False,
        )

    def _update_software_position_state(
        self,
        updates: dict[str, dict[str, Any]],
        generation: int,
    ) -> None:
        with self._software_position_lock:
            if generation != self._software_position_generation:
                return
            for label, update in updates.items():
                current = self._software_position_state.setdefault(label, {})
                current.update(update)

    def _finish_software_position_state(
        self,
        positions_deg: dict[str, float],
        phase: str,
        generation: int,
    ) -> None:
        with self._software_position_lock:
            if generation != self._software_position_generation:
                return
            for label in positions_deg:
                state = self._software_position_state.setdefault(label, {})
                state["active"] = False
                state["phase"] = phase
                state["command_velocity_deg_per_sec"] = 0.0
                state["updated_at"] = _timestamp()

    def _apply_software_position_payload(self, data: dict[str, Any]) -> None:
        axes = data.get("axes")
        if not isinstance(axes, (list, tuple)):
            return
        with self._software_position_lock:
            state_by_label = {label: dict(state) for label, state in self._software_position_state.items()}
        for axis in axes:
            if not isinstance(axis, dict):
                continue
            label = str(axis.get("label") or axis.get("name") or "")
            axis["software_position_gain"] = _software_position_gain(label)
            axis["position_gain"] = axis["software_position_gain"]
            state = state_by_label.get(label)
            if state and state.get("phase") != "cancelled":
                axis["software_position"] = state
            else:
                axis["software_position"] = None

    def _apply_sine_velocity_payload(self, data: dict[str, Any]) -> None:
        axes = data.get("axes")
        if not isinstance(axes, (list, tuple)):
            return
        with self._sine_velocity_lock:
            state_by_label = {label: dict(state) for label, state in self._sine_velocity_state.items()}
        for axis in axes:
            if not isinstance(axis, dict):
                continue
            label = str(axis.get("label") or axis.get("name") or "")
            state = state_by_label.get(label)
            axis["sine_velocity_test"] = state if state and state.get("active") else None

    def start_sine_velocity_test(self, label: str, options: dict[str, float]) -> dict[str, Any]:
        self.stop_motor_calibration(label)
        axis_index = MotionCommandGuard.AXIS_INDEX.get(label)
        if axis_index is None:
            raise ValueError(f"Unknown axis: {label}")
        self._cancel_software_position_move()
        self._cancel_sine_velocity_tests((label,))
        min_speed = options["min_speed_deg_per_sec"]
        max_speed = options["max_speed_deg_per_sec"]
        min_period = options["min_period_sec"]
        max_period = options["max_period_sec"]

        def prepare_hardware() -> None:
            self._write_velocity_commands_hardware(
                {label: 0.0},
                require_enabled=False,
            )

        self._require_enabled_snapshot("velocity", {label: max_speed})
        self._hardware_call(
            prepare_hardware,
            label=f"prepare-sine:{label}",
            priority=PRIORITY_CONTROL,
        )

        stop_event = Event()
        with self._sine_velocity_lock:
            generation = self._sine_velocity_generations.get(label, 0)
            self._sine_velocity_stops[label] = stop_event
            self._sine_velocity_state[label] = {
                "active": True,
                "phase": "running",
                "min_speed_deg_per_sec": min_speed,
                "max_speed_deg_per_sec": max_speed,
                "min_period_sec": min_period,
                "max_period_sec": max_period,
                "command_velocity_deg_per_sec": 0.0,
                "started_at": _timestamp(),
                "updated_at": _timestamp(),
            }
            thread = Thread(
                target=self._sine_velocity_loop,
                args=(label, dict(options), stop_event, generation),
                name=f"{label.lower()}-sine-velocity-test",
                daemon=True,
            )
            self._sine_velocity_threads[label] = thread
            thread.start()

        return self.snapshot()

    def stop_sine_velocity_test(self, label: str) -> dict[str, Any]:
        self._cancel_sine_velocity_tests((label,))
        self._hardware_call(
            lambda: self._write_velocity_commands_hardware(
                {label: 0.0},
                require_enabled=False,
            ),
            label=f"stop-sine:{label}",
            priority=PRIORITY_CONTROL,
            coalesce_key=f"sine:{label}",
        )
        return self.snapshot()

    def _cancel_sine_velocity_tests(self, labels: tuple[str, ...] | None = None) -> None:
        events = self._request_sine_velocity_stops(labels)
        for label, _, thread in events:
            if thread is not None and thread.is_alive() and thread is not current_thread():
                thread.join(timeout=0.4)
            with self._sine_velocity_lock:
                state = self._sine_velocity_state.get(label)
                if state:
                    state["active"] = False
                    state["phase"] = "cancelled"
                    state["command_velocity_deg_per_sec"] = 0.0
                    state["updated_at"] = _timestamp()

    def _request_sine_velocity_stops(
        self,
        labels: tuple[str, ...] | None = None,
    ) -> list[tuple[str, Event | None, Thread | None]]:
        with self._sine_velocity_lock:
            selected = tuple(labels) if labels is not None else tuple(self._sine_velocity_stops)
            for label in selected:
                self._sine_velocity_generations[label] = self._sine_velocity_generations.get(label, 0) + 1
            events = [(label, self._sine_velocity_stops.get(label), self._sine_velocity_threads.get(label)) for label in selected]
            for label in selected:
                state = self._sine_velocity_state.get(label)
                if state:
                    state["active"] = False
                    state["phase"] = "stopping"
                    state["updated_at"] = _timestamp()
        for _, event, _ in events:
            if event is not None:
                event.set()
        return events

    def _sine_velocity_loop(
        self,
        label: str,
        options: dict[str, float],
        stop_event: Event,
        generation: int,
    ) -> None:
        min_speed = float(options["min_speed_deg_per_sec"])
        max_speed = float(options["max_speed_deg_per_sec"])
        min_period = float(options["min_period_sec"])
        max_period = float(options["max_period_sec"])
        latest_axes = self.snapshot().get("axes", [])
        latest_axis = next(
            (axis for axis in latest_axes if isinstance(axis, dict) and axis.get("label") == label),
            {},
        )
        last_position = _finite_float(latest_axis.get("position_deg"))
        lower, upper = _axis_runtime_limits(label)
        positive_probability = _sine_positive_direction_probability(last_position, lower, upper)
        direction = 1.0 if random.random() < positive_probability else -1.0
        same_direction_count = 1
        amplitude = random.uniform(min_speed, max_speed)
        period = random.uniform(min_period, max_period)
        half_period = max(period / 2.0, SINE_VELOCITY_INTERVAL_SEC)
        half_cycle_started = monotonic()
        try:
            while not stop_event.is_set():
                now = monotonic()
                elapsed = now - half_cycle_started
                if elapsed >= half_period:
                    next_direction, positive_probability = _choose_sine_direction(
                        last_position,
                        lower,
                        upper,
                        direction,
                        same_direction_count,
                    )
                    same_direction_count = same_direction_count + 1 if next_direction == direction else 1
                    direction = next_direction
                    amplitude = random.uniform(min_speed, max_speed)
                    period = random.uniform(min_period, max_period)
                    half_period = max(period / 2.0, SINE_VELOCITY_INTERVAL_SEC)
                    half_cycle_started = now
                    elapsed = 0.0
                half_cycle_progress = min(1.0, elapsed / half_period)
                command_velocity = direction * amplitude * math.sin(math.pi * half_cycle_progress)
                latest_axes = self.snapshot().get("axes", [])
                latest_axis = next(
                    (
                        axis
                        for axis in latest_axes
                        if isinstance(axis, dict) and axis.get("label") == label
                    ),
                    {},
                )
                position = _finite_float(latest_axis.get("position_deg"))
                if position is not None:
                    last_position = position
                    command_velocity = _axis_velocity_limited_by_runtime_limits(position, command_velocity, lower, upper)
                velocity_to_write = command_velocity

                def write_latest_velocity() -> None:
                    with self._sine_velocity_lock:
                        is_current = generation == self._sine_velocity_generations.get(label, 0)
                    if is_current and not stop_event.is_set():
                        self._write_velocity_commands_hardware(
                            {label: velocity_to_write},
                            require_enabled=False,
                        )

                self._hardware_publish_latest(
                    f"sine:{label}",
                    write_latest_velocity,
                    label=f"sine-setpoint:{label}",
                )
                with self._sine_velocity_lock:
                    if generation != self._sine_velocity_generations.get(label, 0):
                        continue
                    state = self._sine_velocity_state.setdefault(label, {})
                    state.update(
                        {
                            "active": True,
                            "phase": "running",
                            "amplitude_deg_per_sec": amplitude,
                            "period_sec": period,
                            "cycle_elapsed_sec": elapsed,
                            "direction": "positive" if direction > 0.0 else "negative",
                            "positive_direction_probability": positive_probability,
                            "command_velocity_deg_per_sec": command_velocity,
                            "updated_at": _timestamp(),
                        }
                    )
                stop_event.wait(SINE_VELOCITY_INTERVAL_SEC)
        finally:
            try:
                self._hardware_call(
                    lambda: self._stop_sine_velocity_axis_if_current(label, generation),
                    label=f"sine-stop:{label}",
                    priority=PRIORITY_CONTROL,
                    coalesce_key=f"sine:{label}",
                )
            except Exception:
                pass
            with self._sine_velocity_lock:
                if generation != self._sine_velocity_generations.get(label, 0):
                    return
                state = self._sine_velocity_state.setdefault(label, {})
                state["active"] = False
                state["phase"] = "stopped" if not stop_event.is_set() else "cancelled"
                state["command_velocity_deg_per_sec"] = 0.0
                state["updated_at"] = _timestamp()

    def _stop_sine_velocity_axis_if_current(
        self,
        label: str,
        generation: int,
    ) -> None:
        with self._sine_velocity_lock:
            if generation != self._sine_velocity_generations.get(label, 0):
                return
        self._write_velocity_commands_hardware(
            {label: 0.0},
            require_enabled=False,
        )

    def set_velocities(self, velocities_deg_per_sec: dict[str, float]) -> dict[str, Any]:
        for label in velocities_deg_per_sec:
            self.stop_motor_calibration(label)
        self._cancel_software_position_move()
        self._cancel_sine_velocity_tests(tuple(velocities_deg_per_sec))
        velocities_deg_per_sec = _limit_velocities(velocities_deg_per_sec)
        velocities_deg_per_sec = self._limit_velocity_commands_to_runtime_limits(velocities_deg_per_sec)
        self._require_enabled_snapshot("velocity", velocities_deg_per_sec)
        command = dict(velocities_deg_per_sec)
        if not self._velocity_commands_are_current(command):
            self._hardware_call(
                lambda: self._write_velocity_commands_hardware(command),
                label="set-velocities",
                priority=PRIORITY_CONTROL,
                coalesce_key="external-velocity",
            )
        # Return the cached snapshot immediately. A synchronous full-status
        # read made repeated API velocity commands run at only 2-4 Hz and also
        # blocked the telemetry/control threads on the shared USB lock.
        return self.snapshot()

    def command_velocities(self, velocities_deg_per_sec: dict[str, float]) -> dict[str, Any]:
        for label in velocities_deg_per_sec:
            self.stop_motor_calibration(label)
        self._cancel_software_position_move()
        self._cancel_sine_velocity_tests(tuple(velocities_deg_per_sec))
        velocities_deg_per_sec = _limit_velocities(velocities_deg_per_sec)
        velocities_deg_per_sec = self._limit_velocity_commands_to_runtime_limits(velocities_deg_per_sec)
        self._require_enabled_snapshot("velocity", velocities_deg_per_sec)
        command = dict(velocities_deg_per_sec)
        if not self._velocity_commands_are_current(command):
            self._hardware_call(
                lambda: self._write_velocity_commands_hardware(command),
                label="command-velocities",
                priority=PRIORITY_CONTROL,
                coalesce_key="external-velocity",
            )
        return {"accepted": velocities_deg_per_sec}

    def _write_velocity_commands_hardware(
        self,
        velocities_deg_per_sec: dict[str, float],
        *,
        require_enabled: bool = True,
    ) -> None:
        if require_enabled:
            self._require_enabled_snapshot("velocity", velocities_deg_per_sec)
        velocity_control_axes = self._cached_velocity_control_axes()
        with self._device_lock:
            devices = self._connected_devices()
            for label, degrees_per_sec in velocities_deg_per_sec.items():
                axis_index = MotionCommandGuard.AXIS_INDEX[label]
                axis = getattr(devices[axis_index], "axis0")
                if label not in velocity_control_axes:
                    _configure_velocity_control(axis)
                    self._drive_status = None
                with self._velocity_command_lock:
                    previous = self._last_velocity_command_deg_per_sec.get(label)
                if label in velocity_control_axes and previous is not None and math.isclose(
                    previous,
                    degrees_per_sec,
                    abs_tol=1e-6,
                ):
                    continue
                _set_if_present(
                    axis,
                    "controller.input_vel",
                    _axis_display_velocity_to_encoder_turns(label, degrees_per_sec),
                )
                self._record_velocity_commands({label: degrees_per_sec})

    def _velocity_commands_are_current(self, commands: dict[str, float]) -> bool:
        with self._velocity_command_lock:
            return all(
                label in self._last_velocity_command_deg_per_sec
                and math.isclose(
                    self._last_velocity_command_deg_per_sec[label],
                    velocity,
                    abs_tol=1e-6,
                )
                for label, velocity in commands.items()
            )

    def _record_velocity_commands(self, commands: dict[str, float]) -> None:
        with self._velocity_command_lock:
            self._last_velocity_command_deg_per_sec.update(commands)

    def _require_enabled_snapshot(
        self,
        action: str,
        targets: dict[str, float],
        snapshot: dict[str, Any] | None = None,
    ) -> None:
        latest = snapshot or self.snapshot()
        axes = latest.get("axes") if isinstance(latest.get("axes"), (list, tuple)) else []
        by_label = {
            str(axis.get("label")): axis
            for axis in axes
            if isinstance(axis, dict)
        }
        for label, value in targets.items():
            if action == "velocity" and math.isclose(value, 0.0, abs_tol=1e-12):
                continue
            axis = by_label.get(label)
            if axis is None or not axis.get("available", True):
                raise ODriveConnectionError(f"{label} drive is not connected.")
            enabled = bool(axis.get("is_armed")) or (
                _int_or_zero(axis.get("current_state")) == AXIS_STATE_CLOSED_LOOP_CONTROL
                and _int_or_zero(axis.get("active_errors")) == 0
                and _int_or_zero(axis.get("disarm_reason")) == 0
            )
            if not enabled:
                raise ValueError(
                    f"{label} axis must be enabled before "
                    f"{MotionCommandGuard._action_name(action)} commands."
                )

    def _cached_velocity_control_axes(self) -> set[str]:
        """Return axes already known to be ready for fast velocity writes."""

        axes = self.snapshot().get("axes")
        if not isinstance(axes, (list, tuple)):
            return set()
        return {
            str(axis.get("label"))
            for axis in axes
            if isinstance(axis, dict)
            and axis.get("control_mode") == CONTROL_MODE_VELOCITY_CONTROL
            and axis.get("input_mode") == INPUT_MODE_VEL_RAMP
        }

    def _limit_velocity_commands_to_runtime_limits(self, velocities_deg_per_sec: dict[str, float]) -> dict[str, float]:
        latest = self.snapshot()
        axes = latest.get("axes") if isinstance(latest.get("axes"), (list, tuple)) else []
        axis_positions = {
            str(axis.get("label") or axis.get("name") or ""): _finite_float(axis.get("position_deg"))
            for axis in axes
            if isinstance(axis, dict)
        }
        limits = _load_app_settings().get("motion_limits", {})
        axis_limits = {
            "Azimuth": (
                _finite_float(limits.get("azimuth_ccw_limit_deg")),
                _finite_float(limits.get("azimuth_cw_limit_deg")),
            ),
            "Altitude": (
                _finite_float(limits.get("altitude_lower_limit_deg")),
                _finite_float(limits.get("altitude_upper_limit_deg")),
            ),
        }
        limited = dict(velocities_deg_per_sec)
        for label, velocity in velocities_deg_per_sec.items():
            position = axis_positions.get(label)
            lower, upper = axis_limits.get(label, (None, None))
            if position is None:
                continue
            limited[label] = _axis_velocity_limited_by_runtime_limits(position, velocity, lower, upper)
        return limited

    def _connected_devices(self) -> tuple[Any, ...]:
        if self._thread is not None and not self._hardware_io.is_owner():
            raise RuntimeError("ODrive discovery is restricted to the hardware I/O owner.")
        if self._devices is None:
            devices = _order_devices_for_config(connect_many(count=2, timeout=self._timeout))
            if not any(device is not None for device in devices):
                raise ODriveConnectionError("No ODrive drive is connected.")

            # Preserve the continuous-position branch across transient USB
            # reconnects and drive reboots. The state starts empty on process
            # startup, where region sensors still select the initial branch.
            self._drive_status = None
            self._velocity_filter.clear()
            self._devices = devices
            self._configure_current_envelope_devices(devices)
        if not any(device is not None for device in self._devices):
            raise ODriveConnectionError("No ODrive drive is connected.")
        return self._devices

    def _configure_current_envelope_devices(self, devices: tuple[Any, ...]) -> None:
        """Install hardware ceilings; software only moves the torque ceiling."""

        config = MOTOR_CURRENT_ENVELOPE
        for axis_index, device in enumerate(devices[:2]):
            if device is None:
                continue
            label = "Azimuth" if axis_index == 0 else "Altitude"
            axis = getattr(device, "axis0")
            _set_required(axis, "config.motor.torque_constant", config.torque_constant_nm_per_amp)
            _set_required(axis, "config.motor.current_soft_max", config.peak_current_amp)
            _set_required(axis, "config.motor.current_hard_max", config.hard_current_amp)
            # Thermal history is unknown after a process restart, so begin at
            # continuous torque. CurrentEnvelope releases peak torque only
            # after observing the full low-current recovery interval.
            _set_required(axis, "config.torque_soft_max", config.continuous_torque_nm)
            _set_required(axis, "config.torque_soft_min", -config.continuous_torque_nm)
            self._current_envelope_applied_amp[label] = config.continuous_current_amp
            self._current_envelope_last_write[label] = monotonic()

    def _read_drive_status(self, devices: tuple[Any, ...], telemetry_only: bool = False) -> Any:
        if self._thread is not None and not self._hardware_io.is_owner():
            raise RuntimeError("ODrive telemetry reads are restricted to the hardware I/O owner.")
        status = read_dual_drive_status(
            devices,
            telemetry_only=telemetry_only and self._drive_status is not None,
            previous=self._drive_status,
        )
        self._drive_status = status
        return status

    def _status_payload(self, status) -> dict[str, Any]:
        _require_valid_drive_status(status)
        data = asdict(status)
        status_timestamp = _timestamp()
        data.update(
            {
                "connected": True,
                "has_bus_power": status.has_bus_power,
                "health": _health_label(
                    status.has_bus_power,
                    any(axis.active_errors for axis in status.axes if axis.available),
                ),
                "poll_interval_ms": int(self._poll_interval * 1000),
                "timestamp": status_timestamp,
                "server_started_at": _server_started_at(),
                "azimuth_sensors": _read_azimuth_sensors(),
                "hardware_io": self._hardware_io.stats(),
            }
        )
        _apply_position_offsets_to_payload(data, self._position_unwrap)
        self._filter_velocity_payload(data)
        self._apply_current_envelope_payload(data)
        self._apply_software_position_payload(data)
        self._apply_sine_velocity_payload(data)
        self._capture_drive_error_events(data, status_timestamp)
        data["drive_error_events"] = self._drive_error_events_snapshot()
        data["auto_tune_progress"] = self._auto_tune_progress_snapshot()
        data["auto_tune_step_events"] = self._auto_tune_step_events_snapshot()
        self._publish_telemetry(data)
        return data

    def _refresh_latest_status_unlocked(self, devices: tuple[Any, ...]) -> None:
        try:
            status = self._read_drive_status(devices, telemetry_only=True)
            _require_valid_drive_status(status)
        except Exception:
            return
        self._status_payload(status)

    def _filter_velocity_payload(self, data: dict[str, Any]) -> None:
        axes = data.get("axes")
        if not isinstance(axes, (list, tuple)):
            return
        now = monotonic()
        for axis in axes:
            if not isinstance(axis, dict):
                continue
            label = str(axis.get("label") or axis.get("name") or "")
            measurement = _finite_float(axis.get("unwrapped_position_deg"))
            if measurement is None:
                measurement = _finite_float(axis.get("position_deg"))
            raw_velocity = _finite_float(axis.get("velocity_deg_per_sec"))
            if measurement is None:
                continue
            if raw_velocity is None:
                raw_velocity = 0.0

            axis["raw_velocity_deg_per_sec"] = raw_velocity
            axis["drive_velocity_deg_per_sec"] = raw_velocity
            axis["measured_position_deg"] = measurement
            axis["median_position_deg"] = measurement
            axis["filtered_position_deg"] = measurement
            axis["position_sample_rejected"] = False

            state = self._velocity_filter.get(label)
            if not state:
                self._velocity_filter[label] = {
                    "position": measurement,
                    "time": now,
                    "velocity": raw_velocity,
                }
                axis["computed_velocity_deg_per_sec"] = raw_velocity
                axis["filtered_velocity_deg_per_sec"] = raw_velocity
                continue

            dt = now - float(state.get("time", now))
            if dt <= 0.0 or dt > 2.0:
                computed_velocity = raw_velocity
            else:
                delta = measurement - float(state.get("position", measurement))
                if abs(delta) > _max_reasonable_position_delta_deg(dt):
                    axis["position_sample_rejected"] = True
                    computed_velocity = float(state.get("velocity", raw_velocity))
                else:
                    computed_velocity = delta / dt

            filtered_velocity = float(state.get("velocity", raw_velocity))
            filtered_velocity += (computed_velocity - filtered_velocity) * VELOCITY_LOWPASS_ALPHA
            if abs(filtered_velocity) < POSITION_FILTER_VELOCITY_DEADBAND_DEG_PER_SEC:
                filtered_velocity = 0.0

            state["position"] = measurement
            state["time"] = now
            state["velocity"] = filtered_velocity
            axis["computed_velocity_deg_per_sec"] = computed_velocity
            axis["filtered_velocity_deg_per_sec"] = filtered_velocity

    def _enforce_runtime_limits(self, status, azimuth_sensors: dict[str, Any] | None = None) -> None:
        if self._devices is None:
            return
        limits = _load_app_settings().get("motion_limits", {})
        axis_limits = {
            "Azimuth": (
                limits.get("azimuth_ccw_limit_deg"),
                limits.get("azimuth_cw_limit_deg"),
            ),
            "Altitude": (
                limits.get("altitude_lower_limit_deg"),
                limits.get("altitude_upper_limit_deg"),
            ),
        }
        for index, axis_status in enumerate(status.axes):
            if index >= len(self._devices):
                continue
            lower, upper = axis_limits.get(axis_status.label, (None, None))
            position = axis_status.position_deg
            if position is None:
                continue
            if axis_status.label == "Altitude":
                # Altitude is a signed, single-turn coordinate. Use the same
                # offset/direction/normalization path as the status payload.
                # The unwrapped helper deliberately does not normalize and
                # can otherwise turn a valid -13 Deg reading into +347/+480
                # Deg, causing the upper-limit guard to pulse Forward jogs
                # between their requested velocity and zero.
                position = _axis_display_position_deg(
                    axis_status.label,
                    position,
                    _axis_position_offset(axis_status.label),
                    azimuth_sensors,
                )
            else:
                position = _axis_unwrapped_display_position_deg(
                    axis_status.label,
                    position * _axis_position_scale(axis_status.label),
                    _axis_position_offset(axis_status.label),
                    self._position_unwrap,
                    azimuth_sensors,
                )
            if _axis_target_returns_within_limits(axis_status, lower, upper, azimuth_sensors):
                continue
            if _axis_velocity_returns_within_limits(axis_status, position, lower, upper):
                continue
            if lower is not None and position <= lower:
                _stop_axis_at_runtime_limit(getattr(self._devices[index], "axis0"), axis_status.label, lower)
            elif upper is not None and position >= upper:
                _stop_axis_at_runtime_limit(getattr(self._devices[index], "axis0"), axis_status.label, upper)
            else:
                _slow_axis_near_runtime_limit(getattr(self._devices[index], "axis0"), axis_status, position, lower, upper)


class SimulationMonitor:
    """Deterministic two-axis mount model that never opens a drive or encoder."""

    MEASUREMENT_NOISE_FRACTION = 0.0005

    def __init__(self, poll_interval: float = TELEMETRY_INTERVAL_SEC) -> None:
        self._poll_interval = poll_interval
        self._lock = Lock()
        self._stop = Event()
        self._thread: Thread | None = None
        self._axes = {
            label: {"position": 0.0, "velocity": 0.0, "command_velocity": 0.0,
                    "target": None, "target_speed": 30.0, "armed": False}
            for label in ("Azimuth", "Altitude")
        }
        self._motor_calibration: dict[str, dict[str, Any]] = {}
        self._noise = random.Random()

    def _measured(self, base: float, noise_floor: float = 0.0) -> float:
        """Apply ±0.05% sensor noise without modifying the simulation state."""
        amplitude = max(abs(base), noise_floor) * self.MEASUREMENT_NOISE_FRACTION
        return base + self._noise.uniform(
            -amplitude,
            amplitude,
        )

    def start(self) -> None:
        if self._thread is None:
            self._thread = Thread(target=self._loop, name="mount-simulation", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not current_thread():
            thread.join(timeout=1.0)

    def _loop(self) -> None:
        previous = monotonic()
        while not self._stop.wait(self._poll_interval):
            now = monotonic()
            dt = min(0.1, max(0.001, now - previous))
            previous = now
            settings = _load_app_settings()
            limits = settings["motion_limits"]
            with self._lock:
                for label, axis in self._axes.items():
                    lower, upper = (
                        (float(limits["azimuth_ccw_limit_deg"]), float(limits["azimuth_cw_limit_deg"]))
                        if label == "Azimuth" else
                        (float(limits["altitude_lower_limit_deg"]), float(limits["altitude_upper_limit_deg"]))
                    )
                    desired = 0.0
                    if axis["armed"]:
                        if axis["target"] is not None:
                            error = float(axis["target"]) - float(axis["position"])
                            if abs(error) <= 0.05:
                                axis["position"] = float(axis["target"])
                                axis["target"] = None
                            else:
                                desired = max(-axis["target_speed"], min(axis["target_speed"], error * 1.2))
                        else:
                            desired = float(axis["command_velocity"])
                    acceleration = float(limits.get(f"{label.lower()}_remote_acceleration_deg_s2") or 30.0)
                    change = acceleration * dt
                    axis["velocity"] = max(axis["velocity"] - change, min(axis["velocity"] + change, desired))
                    position = float(axis["position"]) + float(axis["velocity"]) * dt
                    if position <= lower or position >= upper:
                        position = max(lower, min(upper, position))
                        axis["velocity"] = 0.0
                        axis["command_velocity"] = 0.0
                        axis["target"] = None
                    axis["position"] = position

    def snapshot(self) -> dict[str, Any]:
        settings = _load_app_settings()
        limits = settings["motion_limits"]
        with self._lock:
            axes = []
            for index, label in enumerate(("Azimuth", "Altitude")):
                axis = dict(self._axes[label])
                position, velocity = float(axis["position"]), float(axis["velocity"])
                measured_position = self._measured(position, noise_floor=1.0)
                measured_velocity = self._measured(velocity, noise_floor=0.1)
                measured_current = self._measured(max(0.12, abs(velocity) * 0.04))
                axes.append({
                    "name": f"axis{index}", "label": label, "available": True,
                    "current_state": AXIS_STATE_CLOSED_LOOP_CONTROL if axis["armed"] else AXIS_STATE_IDLE,
                    "active_errors": 0, "disarm_reason": 0, "pos_estimate": measured_position / 360.0,
                    "position_source": "simulation_model_with_noise", "vel_estimate": measured_velocity / 360.0,
                    "position_deg": measured_position, "absolute_position_deg": measured_position,
                    "unwrapped_position_deg": measured_position, "computed_velocity_deg_per_sec": measured_velocity,
                    "velocity_deg_per_sec": measured_velocity, "current": measured_current,
                    "current_setpoint": max(0.12, abs(velocity) * 0.04), "is_armed": bool(axis["armed"]),
                    "drive_serial": f"SIM-{index + 1:04d}", "drive_firmware": "simulation-1.0",
                    "drive_hardware": "virtual", "drive_vbus_voltage": self._measured(48.0),
                    "drive_ibus": self._measured(max(0.08, abs(velocity) * 0.002)),
                    "position_gain": 1.0, "velocity_gain": 0.1, "velocity_integrator_gain": 0.0,
                    "velocity_integrator_limit": 0.0, "velocity_integrator_decay_gain": 0.0,
                    "velocity_limit": float(limits["slew_rate_deg_per_sec"]),
                    "velocity_limit_tolerance": 1.0, "velocity_ramp_rate": 30.0,
                    "torque_ramp_rate": 1.0, "control_mode": 2, "input_mode": 1,
                    "trajectory_done": axis["target"] is None,
                    "input_pos": axis["target"] if axis["target"] is not None else position,
                    "pos_setpoint": axis["target"] if axis["target"] is not None else position,
                    "input_vel": axis["command_velocity"], "vel_setpoint": velocity,
                    "torque_setpoint": 0.0, "effective_torque_setpoint": 0.0,
                    "torque_soft_min": -20.0, "torque_soft_max": 20.0,
                    "trap_velocity_limit": float(limits["slew_rate_deg_per_sec"]),
                    "trap_accel_limit": 30.0, "trap_decel_limit": 30.0,
                })
            calibration = {key: dict(value) for key, value in self._motor_calibration.items()}
        return {
            "connected": True, "run_mode": "simulation", "simulation_mode": True,
            "has_bus_power": True, "health": "ready",
            "serial_number": "SIMULATED-MOUNT", "device_serials": ["SIM-0001", "SIM-0002"],
            "firmware_version": "simulation-1.0", "hardware_version": "virtual",
            "vbus_voltage": self._measured(48.0),
            "ibus": self._measured(sum(axis["drive_ibus"] for axis in axes)), "axes": axes,
            "poll_interval_ms": int(self._poll_interval * 1000), "timestamp": _timestamp(),
            "server_started_at": _server_started_at(),
            "azimuth_sensors": {"cw_sensor": False, "ccw_sensor": False, "simulated": True},
            "drive_error_events": [], "auto_tune_progress": None, "auto_tune_step_events": [],
            "motor_calibration": calibration, "emergency_stop": False,
            "simulation_noise_percent": self.MEASUREMENT_NOISE_FRACTION * 100.0,
        }

    def enable_motors(self) -> dict[str, Any]:
        with self._lock:
            for axis in self._axes.values(): axis["armed"] = True
        return self.snapshot()

    def disable_motors(self) -> dict[str, Any]:
        with self._lock:
            for axis in self._axes.values():
                axis.update(armed=False, velocity=0.0, command_velocity=0.0, target=None)
        return self.snapshot()

    def set_axis_enabled(self, label: str, enabled: bool) -> dict[str, Any]:
        if label not in self._axes: raise ValueError(f"Unknown axis: {label}")
        with self._lock:
            self._axes[label]["armed"] = bool(enabled)
            if not enabled: self._axes[label].update(velocity=0.0, command_velocity=0.0, target=None)
        return self.snapshot()

    def stop_motors(self) -> dict[str, Any]:
        with self._lock:
            for axis in self._axes.values(): axis.update(velocity=0.0, command_velocity=0.0, target=None)
        return self.snapshot()

    def goto_positions(self, positions_deg: dict[str, float], velocity_target_deg_per_sec: float | None = None) -> dict[str, Any]:
        _validate_motion_targets(positions_deg)
        speed = _effective_slew_rate(velocity_target_deg_per_sec) or 30.0
        with self._lock:
            for label, target in positions_deg.items():
                if not self._axes[label]["armed"]: raise ODriveConnectionError(f"{label} is not enabled.")
                self._axes[label].update(target=float(target), target_speed=float(speed), command_velocity=0.0)
        return self.snapshot()

    def set_velocities(self, velocities_deg_per_sec: dict[str, float]) -> dict[str, Any]:
        velocities_deg_per_sec = _limit_velocities(velocities_deg_per_sec)
        with self._lock:
            for label, velocity in velocities_deg_per_sec.items():
                if not self._axes[label]["armed"] and velocity: raise ODriveConnectionError(f"{label} is not enabled.")
                self._axes[label].update(command_velocity=float(velocity), target=None)
        return self.snapshot()

    def command_velocities(self, velocities_deg_per_sec: dict[str, float]) -> dict[str, Any]:
        self.set_velocities(velocities_deg_per_sec)
        return {"accepted": velocities_deg_per_sec, "simulation_mode": True}

    def update_tuning(self, label: str, values: dict[str, float]) -> dict[str, Any]:
        del values
        if label not in self._axes: raise ValueError(f"Unknown axis: {label}")
        return self.snapshot()

    def save_configuration(self, label: str) -> dict[str, Any]:
        if label not in self._axes: raise ValueError(f"Unknown axis: {label}")
        return {"axis": label, "saved": True, "simulation_mode": True}

    def flash_motion_limits(self, settings: dict[str, Any]) -> dict[str, Any]:
        del settings
        return {"simulation_mode": True, "drive_flash_skipped": True}

    def reload_configuration(self) -> None: pass
    def request_auto_tune_stop(self) -> dict[str, Any]: return {"requested": True, "simulation_mode": True}
    def auto_tune_axis(self, label: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        del options
        return {"axis": label, "phase": "complete", "simulation_mode": True}
    def start_motor_calibration(self, label: str, options: dict[str, float]) -> dict[str, Any]:
        with self._lock: self._motor_calibration[label] = {"running": False, "phase": "complete", **options}
        return self.snapshot()
    def stop_motor_calibration(self, label: str) -> dict[str, Any]:
        with self._lock: self._motor_calibration.setdefault(label, {}).update(running=False, phase="cancelled")
        return self.snapshot()
    def start_sine_velocity_test(self, label: str, options: dict[str, float]) -> dict[str, Any]:
        del options
        return {"axis": label, "active": True, "simulation_mode": True}
    def stop_sine_velocity_test(self, label: str) -> dict[str, Any]:
        return {"axis": label, "active": False, "simulation_mode": True}


def create_app() -> Flask:
    app = Flask(
        __name__,
        static_folder=str(PROJECT_ROOT / "web" / "static"),
        template_folder=str(PROJECT_ROOT / "web" / "templates"),
    )
    sock = Sock(app)
    settings_at_start = _load_app_settings()
    simulation_enabled = bool(settings_at_start.get("simulation_mode", {}).get("enabled", False))
    raw_monitor = SimulationMonitor() if simulation_enabled else ODriveMonitor()
    raw_monitor.start()
    atexit.register(raw_monitor.stop)
    api_command_monitor = ApiCommandMonitor(capacity=600)
    command_manager = MotionCommandManager(raw_monitor, api_command_monitor)
    monitor = ManagedMotionController(raw_monitor, command_manager, "rest-api")
    jog_commands = JogCommandRegistry(
        lambda velocities: monitor.command_velocities(velocities),
        lease_timeout_sec=0.6,
    )
    telemetry_store = TelemetryStore(TELEMETRY_DATABASE_PATH, raw_monitor.snapshot)
    telemetry_store.start()
    atexit.register(telemetry_store.stop)
    app.extensions["telemetry_store"] = telemetry_store
    command_router = MountCommandRouter(
        ManagedMotionController(raw_monitor, command_manager, "mount-agent")
    )
    mount_agent = MountAgent(
        command_router.dispatch,
        raw_monitor.snapshot,
        _load_app_settings,
        terrain_path=DEM_PATH,
        terrain_updated=_terrain_updated,
        command_monitor=api_command_monitor,
    )
    mount_agent.start()
    atexit.register(mount_agent.stop)
    atexit.register(command_manager.close)
    atexit.register(jog_commands.close)
    app.extensions["mount_agent"] = mount_agent
    app.extensions["mount_command_router"] = command_router
    app.extensions["motion_command_manager"] = command_manager
    app.extensions["api_command_monitor"] = api_command_monitor
    app.extensions["jog_command_registry"] = jog_commands
    app.extensions["raw_monitor"] = raw_monitor
    camera_recording_lock = Lock()
    camera_recording: dict[str, Any] = {"status": "idle"}
    camera_preview_started_monotonic = monotonic()
    camera_stream_lock = Lock()
    camera_stream_updated = Condition(camera_stream_lock)
    camera_stream_frames: dict[tuple[str, str], dict[str, Any]] = {}
    camera_stream_images: dict[tuple[str, str], dict[str, Any]] = {}
    camera_stream_sequence = {"value": 0}
    camera_stream_producers = {
        "simulation": {"connections": 0, "last_frame_at": None, "last_frame_monotonic": None},
        "live": {"connections": 0, "last_frame_at": None, "last_frame_monotonic": None},
    }

    def camera_source_connected(source: str) -> bool:
        state = camera_stream_producers[source]
        last_frame = state.get("last_frame_monotonic")
        return state["connections"] > 0 or (
            isinstance(last_frame, (int, float)) and monotonic() - last_frame < 2.0
        )

    def decode_camera_image(image: dict[str, Any]) -> tuple[bytes, str] | None:
        mime_type = str(image.get("mime_type") or "image/jpeg").lower()
        encoded = image.get("data")
        if not isinstance(encoded, str) and isinstance(image.get("data_url"), str):
            header, separator, encoded = image["data_url"].partition(",")
            if not separator or ";base64" not in header:
                return None
            mime_type = header[5:].split(";", 1)[0].lower()
        if not isinstance(encoded, str) or mime_type not in {"image/jpeg", "image/png"}:
            return None
        try:
            payload = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError):
            return None
        if not payload or len(payload) > 16 * 1024 * 1024:
            return None
        return payload, mime_type

    def decode_binary_camera_frame(raw: bytes) -> tuple[str, bytes, str, dict[str, Any]] | None:
        """Decode: uint32 BE header length, UTF-8 JSON header, then image bytes."""
        if len(raw) < 5 or len(raw) > 16 * 1024 * 1024:
            return None
        header_length = struct.unpack(">I", raw[:4])[0]
        if header_length < 2 or header_length > 64 * 1024 or 4 + header_length >= len(raw):
            return None
        try:
            header = json.loads(raw[4:4 + header_length].decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(header, dict):
            return None
        camera = header.get("camera")
        mime_type = str(header.get("mime_type") or "image/jpeg").lower()
        metadata = header.get("metadata", {})
        payload = raw[4 + header_length:]
        if camera not in {"thermal", "visible"} or mime_type not in {"image/jpeg", "image/png"}:
            return None
        if not isinstance(metadata, dict) or not payload:
            return None
        expected_sha256 = str(header.get("sha256") or "").lower()
        if expected_sha256 and (
            not re.fullmatch(r"[0-9a-f]{64}", expected_sha256)
            or not hmac.compare_digest(hashlib.sha256(payload).hexdigest(), expected_sha256)
        ):
            return None
        return camera, payload, mime_type, metadata

    def store_camera_frame(source: str, camera: str, payload: bytes, mime_type: str,
                           metadata: dict[str, Any]) -> dict[str, Any]:
        camera_stream_sequence["value"] += 1
        sequence = camera_stream_sequence["value"]
        clean_metadata = {**metadata, "simulated": source == "simulation"}
        message = {
            "type": "frame",
            "camera": camera,
            "image": {"mime_type": mime_type, "data": base64.b64encode(payload).decode("ascii")},
            "metadata": clean_metadata,
            "sequence": sequence,
        }
        camera_stream_frames[(source, camera)] = message
        received_monotonic = monotonic()
        camera_stream_images[(source, camera)] = {
            "data": payload,
            "mime_type": mime_type,
            "metadata": clean_metadata,
            "sequence": sequence,
            "received_monotonic": received_monotonic,
        }
        now = datetime.now(timezone.utc).isoformat()
        camera_stream_producers[source].update(last_frame_at=now, last_frame_monotonic=received_monotonic)
        camera_stream_updated.notify_all()
        return message

    def camera_recording_snapshot() -> dict[str, Any]:
        with camera_recording_lock:
            snapshot = dict(camera_recording)
        if snapshot.get("status") == "recording":
            snapshot["elapsed_sec"] = round(max(0.0, monotonic() - snapshot["started_monotonic"]), 1)
        snapshot.pop("started_monotonic", None)
        return snapshot

    def finish_camera_recording(recording: dict[str, Any], duration_sec: float) -> None:
        event_id = str(recording["event_id"])
        output_dir = PROJECT_ROOT / "data" / "recordings" / event_id
        output_dir.mkdir(parents=True, exist_ok=True)
        sources = {
            "thermal": PROJECT_ROOT / "web" / "static" / "video" / "thermal-zoom-simulation.mp4",
            "visible": PROJECT_ROOT / "web" / "static" / "video" / "visible-zoom-simulation.mp4",
        }
        outputs = {camera: output_dir / f"{camera}.mp4" for camera in sources}
        try:
            helper_path = PROJECT_ROOT / "scripts" / "simulate_fire_events.py"
            helper_spec = importlib.util.spec_from_file_location("fire_event_ingestion", helper_path)
            if helper_spec is None or helper_spec.loader is None:
                raise RuntimeError(f"Could not load event ingestion helper: {helper_path}")
            helper = importlib.util.module_from_spec(helper_spec)
            helper_spec.loader.exec_module(helper)
            with camera_recording_lock:
                camera_recording.update(status="saving", message="Saving MP4 files on Station disk")
            for camera, source in sources.items():
                resolution = "640x512" if camera == "thermal" else "1280x720"
                zoom = 1.0
                try:
                    mission_camera = json.loads((PROJECT_ROOT / "data" / "mission" / "camera.json").read_text(encoding="utf-8"))
                    zoom = float(mission_camera[f"{camera}_zoom_x"])
                except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError):
                    pass
                start_epoch = datetime.fromisoformat(str(recording["detected_at"]).replace("Z", "+00:00")).timestamp()
                font = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
                overlay_text = output_dir / f".{camera}-overlay.txt"
                overlay_text.write_text(
                    "ELAPSED %{pts:hms}\n"
                    f"UTC %{{pts:gmtime:{start_epoch:.3f}:%Y-%m-%d %H\\:%M\\:%S}}\n"
                    f"ZOOM {zoom:.2f}x\nRES {resolution}",
                    encoding="utf-8",
                )
                overlay = (
                    f"drawtext=fontfile={font}:textfile={overlay_text}:fontcolor=white:fontsize=15:"
                    "box=1:boxcolor=black@0.36:boxborderw=6:x=10:y=10"
                )
                try:
                    subprocess.run([
                        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-stream_loop", "-1",
                        "-ss", f"{float(recording['source_phase_sec']):.3f}", "-i", str(source),
                        "-t", f"{duration_sec:.3f}", "-vf", overlay,
                        "-c:v", "libx264", "-preset", "veryfast",
                        "-crf", "22", "-an", "-movflags", "+faststart", str(outputs[camera]),
                    ], check=True)
                finally:
                    overlay_text.unlink(missing_ok=True)

            settings = _load_app_settings()
            remote = settings["mount_agent"]["remote"]
            device_id = str(remote["device_id"])
            configured_url = str(remote["media_upload_url"])
            base_url = configured_url.split("/api/", 1)[0]
            secret = Path(str(remote["secret_file"])).read_bytes().strip()
            ca_file = str(remote.get("ca_file") or "")
            duration_ms = round(duration_sec * 1000)
            payload = helper.random_payload(
                event_id, device_id, str(recording["detected_at"]), random.Random(event_id), duration_ms,
            )
            payload.update(title="Recorded simulated camera event", summary="Recorded from Station Camera View")
            with camera_recording_lock:
                camera_recording.update(status="uploading", message="Uploading thermal and visible MP4 files")
            for camera, video in outputs.items():
                helper.upload_video(base_url, ca_file, device_id, secret, event_id, camera, video, 180)
            result = helper.finalize_event(base_url, ca_file, device_id, secret, payload, 180)
            incident = result.get("incident", {}) if isinstance(result, dict) else {}
            with camera_recording_lock:
                camera_recording.update(
                    status="archived",
                    message="Video saved locally and archived on Server",
                    duration_sec=round(duration_sec, 1),
                    local_directory=str(output_dir),
                    incident_id=incident.get("id"),
                    files={camera: str(path) for camera, path in outputs.items()},
                )
        except Exception as exc:
            with camera_recording_lock:
                camera_recording.update(status="error", message=str(exc), local_directory=str(output_dir))

    @app.get("/")
    def index() -> str:
        return render_template("index.html")

    @app.get("/download/station-logo.png")
    def download_station_logo():
        return send_from_directory(
            PROJECT_ROOT / "web" / "static" / "img",
            "narit-smart-wildfire-mark.png",
            as_attachment=True,
            download_name="station-logo.png",
        )

    @app.get("/api-console")
    def api_console_page() -> str:
        return render_template("api_console.html")

    @app.get("/API-Doc/<path:filename>")
    def api_document(filename: str):
        return send_from_directory(PROJECT_ROOT / "API-Doc", filename)

    @app.post("/api/console/command")
    def api_console_command():
        payload = request.get_json(silent=True) or {}
        try:
            session_id = _console_session_id(payload.get("session_id"))
            message = payload.get("message")
            if not isinstance(message, dict):
                raise ValueError("message must be a JSON object.")
            response = mount_agent.dispatch_for_session(
                message,
                source="web-api-console",
                owner=f"web-api:{session_id}",
            )
            return jsonify(response)
        except ValueError as exc:
            return jsonify({"ok": False, "error": {"code": "INVALID_REQUEST", "message": str(exc)}}), 400

    @app.get("/api/console/command-monitor")
    def api_console_command_monitor():
        try:
            after_revision = max(0, int(request.args.get("after_revision", "0")))
            limit = max(1, min(int(request.args.get("limit", "100")), 600))
        except ValueError:
            return jsonify({"ok": False, "error": "after_revision and limit must be integers"}), 400
        include_automatic = request.args.get("include_automatic", "false").strip().lower() in {
            "1", "true", "yes", "on",
        }
        return jsonify({"ok": True, **api_command_monitor.snapshot(
            after_revision=after_revision,
            limit=limit,
            include_automatic=include_automatic,
        )})

    @app.post("/api/console/command-monitor/clear")
    def api_console_clear_command_monitor():
        return jsonify({"ok": True, **api_command_monitor.clear()})

    @app.post("/api/console/python")
    def api_console_python():
        payload = request.get_json(silent=True) or {}
        try:
            session_id = _console_session_id(payload.get("session_id"))
            code = str(payload.get("code") or "")
            if len(code.encode("utf-8")) > 16_384:
                raise ValueError("Python example is limited to 16 KiB.")

            def console_call(action: str, params: dict[str, Any], lease_id: str) -> dict[str, Any]:
                message = {
                    "version": "1.0",
                    "type": "command",
                    "message_id": f"py-{random.getrandbits(96):024x}",
                    "action": action,
                    "params": params,
                }
                if lease_id:
                    message["control_lease_id"] = lease_id
                return mount_agent.dispatch_for_session(
                    message,
                    source="web-python-console",
                    owner=f"web-api:{session_id}",
                )

            return jsonify({"ok": True, **_run_restricted_python(code, console_call)})
        except ValueError as exc:
            return jsonify({"ok": False, "error": {"code": "PYTHON_REJECTED", "message": str(exc)}}), 400

    @app.get("/api/status")
    def api_status():
        return jsonify(monitor.snapshot())

    @app.get("/api/reports/current-using")
    def api_current_using_report():
        try:
            hours = int(request.args.get("hours", "24"))
            buckets = int(request.args.get("buckets", "288"))
        except ValueError:
            return jsonify({"ok": False, "error": "hours and buckets must be integers"}), 400
        return jsonify({"ok": True, **telemetry_store.report(hours=hours, buckets=buckets)})

    @app.get("/api/camera-preview/<camera>")
    def api_camera_preview(camera: str):
        from PIL import Image

        samples = {
            "thermal": "thermal-sip30-150-sample.png",
            "visible": "visible-khao-sok-sample.jpg",
        }
        filename = samples.get(camera)
        if filename is None:
            return jsonify({"ok": False, "error": "camera must be thermal or visible"}), 404
        try:
            phase_ms = int(request.args.get("t", "0"))
        except ValueError:
            phase_ms = 0
        if phase_ms <= 0:
            phase_ms = int(datetime.now().timestamp() * 1000)
        cycle_progress = (phase_ms % 40_000) / 20_000
        zoom = 1.0 + 4.0 * (cycle_progress if cycle_progress <= 1.0 else 2.0 - cycle_progress)

        sample_path = PROJECT_ROOT / "data" / "simulated_camera" / filename
        with Image.open(sample_path) as source:
            image = source.convert("RGB")
            width, height = image.size
            crop_width = max(2, round(width / zoom))
            crop_height = max(2, round(height / zoom))
            left = (width - crop_width) // 2
            top = (height - crop_height) // 2
            frame = image.crop((left, top, left + crop_width, top + crop_height)).resize(
                (width, height), Image.Resampling.LANCZOS,
            )
            frame = burn_camera_overlay(
                frame,
                captured_at=datetime.now(timezone.utc),
                elapsed_sec=monotonic() - camera_preview_started_monotonic,
                zoom_x=zoom,
            )

        output = BytesIO()
        image_format = "PNG" if camera == "thermal" else "JPEG"
        save_options = {"optimize": True} if camera == "thermal" else {"quality": 88, "optimize": True}
        frame.save(output, format=image_format, **save_options)
        output.seek(0)
        response = send_file(output, mimetype="image/png" if camera == "thermal" else "image/jpeg")
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Simulated-Zoom"] = f"{zoom:.2f}"
        return response

    @app.get("/api/camera-recording")
    def api_camera_recording_status():
        return jsonify(camera_recording_snapshot())

    @app.post("/api/camera-recording/start")
    def api_camera_recording_start():
        payload = request.get_json(silent=True) or {}
        with camera_recording_lock:
            if camera_recording.get("status") in {"recording", "saving", "uploading"}:
                return jsonify({"ok": False, "error": "A recording is already active."}), 409
            event_id = f"fire-recording-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{random.randrange(1000):03d}"
            try:
                source_phase_sec = float(payload.get("source_phase_sec", 0.0)) % 40.0
            except (TypeError, ValueError):
                source_phase_sec = 0.0
            camera_recording.clear()
            camera_recording.update(
                status="recording",
                message="Recording thermal and visible streams",
                event_id=event_id,
                detected_at=datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                started_monotonic=monotonic(),
                source_phase_sec=source_phase_sec,
            )
        return jsonify({"ok": True, **camera_recording_snapshot()})

    @app.post("/api/camera-recording/stop")
    def api_camera_recording_stop():
        with camera_recording_lock:
            if camera_recording.get("status") != "recording":
                return jsonify({"ok": False, "error": "No camera recording is active."}), 409
            duration_sec = max(1.0, min(300.0, monotonic() - camera_recording["started_monotonic"]))
            recording = dict(camera_recording)
            camera_recording.update(status="saving", message="Finalizing local MP4 files")
        Thread(
            target=finish_camera_recording,
            args=(recording, duration_sec),
            name=f"camera-recording-{recording['event_id']}",
            daemon=True,
        ).start()
        return jsonify({"ok": True, **camera_recording_snapshot()}), 202

    @sock.route("/ws/status")
    def ws_status(ws):
        telemetry_sequence = -1
        while True:
            wait_for_telemetry = getattr(raw_monitor, "wait_for_telemetry", None)
            if callable(wait_for_telemetry):
                status = wait_for_telemetry(telemetry_sequence, timeout=1.0)
                source = status.get("telemetry_source", {})
                next_sequence = int(source.get("sequence") or 0)
                if next_sequence <= telemetry_sequence:
                    continue
                telemetry_sequence = next_sequence
            else:
                status = raw_monitor.snapshot()
                sleep(TELEMETRY_PUSH_INTERVAL_SEC)
            ws.send(json.dumps(status, separators=(",", ":")))

    @sock.route("/ws/camera-stream")
    def ws_camera_stream(ws):
        """Relay camera-service JSON frames to dashboard viewers.

        Producers connect with ``?role=producer`` and send ``type=frame`` messages.
        All other connections are read-only viewers. Keeping this as a small relay
        lets the physical-camera service evolve independently from the dashboard.
        """
        role = request.args.get("role", "viewer").strip().lower()
        source = request.args.get("source", "live").strip().lower()
        if source not in {"simulation", "live"}:
            source = "live"
        if role == "producer":
            with camera_stream_lock:
                camera_stream_producers[source]["connections"] += 1
            try:
                while True:
                    raw = ws.receive()
                    if raw is None:
                        break
                    if isinstance(raw, bytes):
                        decoded_binary = decode_binary_camera_frame(raw)
                        if decoded_binary is not None:
                            with camera_stream_updated:
                                store_camera_frame(source, *decoded_binary)
                        continue
                    if not isinstance(raw, str) or len(raw) > 16 * 1024 * 1024:
                        continue
                    try:
                        message = json.loads(raw)
                    except (TypeError, json.JSONDecodeError):
                        continue
                    messages = message.get("frames") if message.get("type") == "frame_batch" else [message]
                    if not isinstance(messages, list):
                        continue
                    clean_messages = []
                    for frame_message in messages:
                        if (not isinstance(frame_message, dict) or frame_message.get("type") != "frame"
                                or frame_message.get("camera") not in {"thermal", "visible"}):
                            continue
                        image = frame_message.get("image")
                        metadata = frame_message.get("metadata", {})
                        if not isinstance(image, dict) or not isinstance(metadata, dict):
                            continue
                        decoded = decode_camera_image(image)
                        if decoded is not None:
                            clean_messages.append((frame_message["camera"], decoded[0], decoded[1], metadata))
                    if not clean_messages:
                        continue
                    with camera_stream_lock:
                        for camera, payload, mime_type, metadata in clean_messages:
                            store_camera_frame(source, camera, payload, mime_type, metadata)
            finally:
                with camera_stream_lock:
                    camera_stream_producers[source]["connections"] = max(
                        0, camera_stream_producers[source]["connections"] - 1,
                    )
            return

        last_sequences: dict[str, int] = {}
        last_connected: bool | None = None
        while True:
            with camera_stream_updated:
                producer_connected = camera_source_connected(source)
                frames = [dict(frame) for (frame_source, _camera), frame in camera_stream_frames.items()
                          if frame_source == source]
                if producer_connected == last_connected and not any(
                    int(frame.get("sequence", 0)) > last_sequences.get(frame["camera"], 0) for frame in frames
                ):
                    camera_stream_updated.wait(timeout=0.25)
                    continue
            if producer_connected != last_connected:
                ws.send(json.dumps({
                    "type": "status",
                    "connected": producer_connected,
                    "message": (
                        f"Station {source} stream connected" if producer_connected
                        else f"Waiting for Station {source} stream"
                    ),
                }, separators=(",", ":")))
                last_connected = producer_connected
            for frame in frames if producer_connected else ():
                camera = frame["camera"]
                sequence = int(frame.get("sequence", 0))
                if sequence > last_sequences.get(camera, 0):
                    ws.send(json.dumps(frame, separators=(",", ":")))
                    last_sequences[camera] = sequence

    @app.post("/api/camera-stream/frame/<camera>")
    def api_camera_stream_frame(camera: str):
        """Receive one encoded frame from the external camera module.

        The request body is raw JPEG or PNG. Optional JSON metadata can be sent
        in ``X-Camera-Metadata``. Only the latest frame is retained, so a slow
        viewer never causes a 60 FPS producer to build an unbounded queue.
        """
        if camera not in {"thermal", "visible"}:
            return jsonify({"ok": False, "error": "camera must be thermal or visible"}), 404
        source = request.args.get("source", "live").strip().lower()
        if source not in {"simulation", "live"}:
            return jsonify({"ok": False, "error": "source must be live or simulation"}), 400
        mime_type = (request.mimetype or "").lower()
        if mime_type not in {"image/jpeg", "image/png"}:
            return jsonify({"ok": False, "error": "Content-Type must be image/jpeg or image/png"}), 415
        if request.content_length is not None and request.content_length > 16 * 1024 * 1024:
            return jsonify({"ok": False, "error": "frame exceeds the 16 MiB limit"}), 413
        payload = request.get_data(cache=False)
        if not payload or len(payload) > 16 * 1024 * 1024:
            return jsonify({"ok": False, "error": "frame is empty or exceeds the 16 MiB limit"}), 413
        metadata: dict[str, Any] = {}
        metadata_header = request.headers.get("X-Camera-Metadata", "")
        if metadata_header:
            try:
                parsed_metadata = json.loads(metadata_header)
            except json.JSONDecodeError:
                return jsonify({"ok": False, "error": "X-Camera-Metadata must be valid JSON"}), 400
            if not isinstance(parsed_metadata, dict):
                return jsonify({"ok": False, "error": "X-Camera-Metadata must be a JSON object"}), 400
            metadata = parsed_metadata
        with camera_stream_updated:
            frame = store_camera_frame(source, camera, payload, mime_type, metadata)
        return jsonify({"ok": True, "camera": camera, "source": source, "sequence": frame["sequence"]}), 202

    @app.get("/api/camera-stream")
    def api_camera_stream_status():
        with camera_stream_lock:
            now = monotonic()
            return jsonify({
                "sources": {
                    source: {
                        "connected": camera_source_connected(source),
                        "last_frame_at": state["last_frame_at"],
                        "streams": sorted(camera for frame_source, camera in camera_stream_frames if frame_source == source),
                        "cameras": {
                            camera: {
                                "connected": isinstance(
                                    camera_stream_images.get((source, camera), {}).get("received_monotonic"),
                                    (int, float),
                                ) and now - camera_stream_images[(source, camera)]["received_monotonic"] < 2.0,
                            }
                            for camera in ("thermal", "visible")
                        },
                    }
                    for source, state in camera_stream_producers.items()
                },
            })

    @app.get("/api/camera-mjpeg/<source>/<camera>")
    def api_camera_mjpeg(source: str, camera: str):
        """Stream camera video as server-originated MJPEG without Base64/JSON framing."""
        if source not in {"simulation", "live"} or camera not in {"thermal", "visible"}:
            return jsonify({"ok": False, "error": "Unknown camera stream."}), 404
        if source == "simulation":
            video = PROJECT_ROOT / "web" / "static" / "video" / f"{camera}-zoom-simulation.mp4"
            resolution = "640:512" if camera == "thermal" else "1280:720"
            phase = time.time() % 40.0
            command = [
                "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error",
                "-re", "-stream_loop", "-1", "-ss", f"{phase:.3f}", "-i", str(video),
                "-an", "-vf", f"fps=15,scale={resolution}", "-c:v", "mjpeg", "-q:v", "5",
                "-f", "mpjpeg", "-boundary_tag", "naritframe", "pipe:1",
            ]
        else:
            command = None

        def generate():
            if command is None:
                last_sequence = 0
                while True:
                    with camera_stream_updated:
                        frame = camera_stream_images.get((source, camera))
                        if frame is None or int(frame["sequence"]) <= last_sequence:
                            camera_stream_updated.wait(timeout=1.0)
                            frame = camera_stream_images.get((source, camera))
                        if frame is None or int(frame["sequence"]) <= last_sequence:
                            continue
                        payload = frame["data"]
                        mime_type = frame["mime_type"]
                        last_sequence = int(frame["sequence"])
                    yield (b"--naritframe\r\nContent-Type: " + mime_type.encode("ascii")
                           + b"\r\nContent-Length: " + str(len(payload)).encode("ascii")
                           + b"\r\n\r\n" + payload + b"\r\n")
                return
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            try:
                assert process.stdout is not None
                while True:
                    chunk = process.stdout.read(64 * 1024)
                    if not chunk:
                        break
                    yield chunk
            finally:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)

        return Response(
            stream_with_context(generate()),
            content_type="multipart/x-mixed-replace; boundary=naritframe",
            headers={"Cache-Control": "no-store, no-cache, must-revalidate", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/settings")
    def api_settings():
        return jsonify(_load_app_settings())

    @app.get("/api/system/info")
    def api_system_info():
        return jsonify(_system_info_payload())

    @app.post("/api/system/update-check")
    def api_system_update_check():
        Thread(target=_run_update_check_soon, name="firmware-update-check", daemon=True).start()
        return jsonify({"ok": True, "message": "Update check requested."})

    @app.get("/api/pointing/model")
    def api_pointing_model():
        try:
            size = int(request.args.get("size", "140"))
        except ValueError:
            size = 140
        try:
            resolution_m = float(request.args.get("resolution_m", str(POINTING_GRID_RESOLUTION_M)))
        except ValueError:
            resolution_m = POINTING_GRID_RESOLUTION_M
        try:
            if resolution_m > 0:
                return jsonify(_pointing_model_raster_payload(resolution_m=max(20.0, min(resolution_m, 500.0))))
            return jsonify(_pointing_model_payload(size=max(40, min(size, 220))))
        except Exception as exc:
            return jsonify({"ok": False, "error": f"Could not load pointing model: {exc}"}), 500

    @app.get("/api/pointing/sample")
    def api_pointing_sample():
        try:
            lat = float(request.args["lat"])
            lon = float(request.args["lon"])
        except (KeyError, TypeError, ValueError):
            return jsonify({"ok": False, "error": "lat and lon query parameters are required."}), 400
        try:
            return jsonify({"ok": True, "sample": _pointing_sample(lat, lon)})
        except Exception as exc:
            return jsonify({"ok": False, "error": f"Could not sample pointing model: {exc}"}), 500

    @app.get("/api/pointing/cache/<path:filename>")
    def api_pointing_cache(filename: str):
        return send_from_directory(POINTING_CACHE_DIR, filename)

    @app.post("/api/settings")
    def api_update_settings():
        try:
            payload = request.get_json(silent=True) or {}
            settings = _merge_app_settings(payload)
            drive_flash = monitor.flash_motion_limits(settings) if payload.get("flash_drives", True) else None
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        except ODriveConnectionError as exc:
            monitor.reload_configuration()
            return jsonify({"ok": False, "error": str(exc)}), 400
        except Exception as exc:
            monitor.reload_configuration()
            return jsonify({"ok": False, "error": f"Could not flash limits to drives: {exc}"}), 500
        monitor.reload_configuration()
        return jsonify({"ok": True, "settings": settings, "drive_flash": drive_flash})

    @app.post("/api/system/reset")
    def api_system_reset():
        monitor.reload_configuration()
        Thread(target=_restart_process_soon, name="mount-server-reset", daemon=True).start()
        return jsonify({"ok": True, "message": "Mount server reset requested."})

    @app.post("/api/system/simulation-mode")
    def api_system_simulation_mode():
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload.get("enabled"), bool):
            return jsonify({"ok": False, "error": "enabled must be a boolean."}), 400
        enabled = bool(payload["enabled"])
        try:
            settings = _set_simulation_mode(enabled)
        except Exception as exc:
            return jsonify({"ok": False, "error": f"Could not save simulation mode: {exc}"}), 500
        Thread(target=_restart_process_soon, name="simulation-mode-reset", daemon=True).start()
        return jsonify({
            "ok": True, "enabled": enabled, "settings": settings,
            "message": "Mount server is restarting in Simulation Mode." if enabled
                       else "Mount server is restarting in Hardware Mode.",
        })

    @app.get("/api/system/run-mode")
    def api_system_run_mode():
        status = monitor.snapshot()
        simulation = status.get("simulation_mode") is True
        return jsonify({
            "ok": True,
            "run_mode": "simulation" if simulation else "hardware",
            "simulation_mode": simulation,
        })

    @app.post("/api/tuning/<axis_label>")
    def api_tuning(axis_label: str):
        try:
            values = _parse_tuning_payload(request.get_json(silent=True) or {})
            status = monitor.update_tuning(axis_label, values)
        except (ValueError, ODriveConnectionError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"ok": False, "error": f"Could not update tuning: {exc}"}), 500
        return jsonify({"ok": True, "status": status})

    @app.post("/api/tuning/<axis_label>/save")
    def api_save_tuning(axis_label: str):
        try:
            flash = monitor.save_configuration(axis_label)
        except (ValueError, ODriveConnectionError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"ok": False, "error": f"Could not save configuration: {exc}"}), 500
        return jsonify(
            {
                "ok": True,
                "message": "Configuration flashed and the drive reconnected successfully.",
                "flash": flash,
            }
        )

    @app.post("/api/tuning/<axis_label>/auto")
    def api_auto_tune(axis_label: str):
        try:
            options = _parse_auto_tune_payload(request.get_json(silent=True) or {})
            result = monitor.auto_tune_axis(axis_label, options)
        except (ValueError, ODriveConnectionError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"ok": False, "error": f"Could not run auto tune: {exc}"}), 500
        return jsonify(
            {
                "ok": True,
                "message": "Auto tune completed and saved to drive.",
                "result": result,
            }
        )

    @app.post("/api/tuning/<axis_label>/auto/stop")
    def api_stop_auto_tune(axis_label: str):
        if axis_label not in ("Azimuth", "Altitude"):
            return jsonify({"ok": False, "error": f"Unknown axis: {axis_label}"}), 400
        return jsonify({"ok": True, "stop": monitor.request_auto_tune_stop()})

    @app.post("/api/motors/enable")
    def api_enable_motors():
        try:
            status = monitor.enable_motors()
        except (ValueError, ODriveConnectionError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"ok": False, "error": f"Could not enable motors: {exc}"}), 500
        return jsonify({"ok": True, "status": status})

    @app.post("/api/motors/disable")
    def api_disable_motors():
        try:
            jog_commands.supersede()
            status = monitor.disable_motors()
        except (ValueError, ODriveConnectionError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"ok": False, "error": f"Could not disable motors: {exc}"}), 500
        return jsonify({"ok": True, "status": status})

    @app.post("/api/motors/enable/<axis_label>")
    def api_enable_axis(axis_label: str):
        try:
            status = monitor.set_axis_enabled(axis_label, True)
        except (ValueError, ODriveConnectionError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"ok": False, "error": f"Could not enable {axis_label}: {exc}"}), 500
        return jsonify({"ok": True, "status": status})

    @app.post("/api/motors/disable/<axis_label>")
    def api_disable_axis(axis_label: str):
        try:
            jog_commands.supersede((axis_label,))
            status = monitor.set_axis_enabled(axis_label, False)
        except (ValueError, ODriveConnectionError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"ok": False, "error": f"Could not disable {axis_label}: {exc}"}), 500
        return jsonify({"ok": True, "status": status})

    @app.post("/api/motors/stop")
    def api_stop_motors():
        try:
            jog_commands.supersede()
            status = monitor.stop_motors()
        except (ValueError, ODriveConnectionError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"ok": False, "error": f"Could not stop motors: {exc}"}), 500
        return jsonify({"ok": True, "status": status})

    @app.post("/api/motors/goto")
    def api_goto_motors():
        try:
            positions, velocity_target = _parse_goto_payload(request.get_json(silent=True) or {})
            jog_commands.supersede(tuple(positions))
            status = monitor.goto_positions(positions, velocity_target)
        except (ValueError, ODriveConnectionError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"ok": False, "error": f"Could not move motors: {exc}"}), 500
        return jsonify({"ok": True, "status": status})

    @app.post("/api/motors/velocity")
    def api_velocity_motors():
        try:
            velocities = _parse_velocity_payload(request.get_json(silent=True) or {})
            jog_commands.supersede(tuple(velocities))
            status = monitor.set_velocities(velocities)
        except (ValueError, ODriveConnectionError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"ok": False, "error": f"Could not set motor velocity: {exc}"}), 500
        return jsonify({"ok": True, "status": status})

    @app.post("/api/motors/velocity-command")
    def api_velocity_command_motors():
        try:
            velocities = _parse_velocity_payload(request.get_json(silent=True) or {})
            client_id = request.headers.get("X-Motion-Client-ID", "")
            sequence_text = request.headers.get("X-Motion-Command-Sequence", "")
            try:
                command_sequence = int(sequence_text)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "X-Motion-Command-Sequence must be a positive integer; reload the dashboard."
                ) from exc
            accepted, ignored = jog_commands.arbitrate(
                client_id,
                velocities,
                command_sequence,
            )
            command = monitor.command_velocities(accepted) if accepted else {"accepted": {}}
            command["ignored_stale_axes"] = sorted(ignored)
        except (ValueError, ODriveConnectionError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"ok": False, "error": f"Could not command motor velocity: {exc}"}), 500
        return jsonify({"ok": True, "command": command})

    @app.post("/api/motors/sine-velocity/<axis_label>/start")
    def api_start_sine_velocity(axis_label: str):
        try:
            options = _parse_sine_velocity_payload(request.get_json(silent=True) or {})
            status = monitor.start_sine_velocity_test(axis_label, options)
        except (ValueError, ODriveConnectionError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"ok": False, "error": f"Could not start sine velocity test: {exc}"}), 500
        return jsonify({"ok": True, "status": status})

    @app.post("/api/motors/sine-velocity/<axis_label>/stop")
    def api_stop_sine_velocity(axis_label: str):
        try:
            status = monitor.stop_sine_velocity_test(axis_label)
        except (ValueError, ODriveConnectionError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"ok": False, "error": f"Could not stop sine velocity test: {exc}"}), 500
        return jsonify({"ok": True, "status": status})

    @app.post("/api/motors/calibration/<axis_label>/start")
    def api_start_motor_calibration(axis_label: str):
        try:
            options = _parse_motor_calibration_payload(request.get_json(silent=True) or {})
            status = monitor.start_motor_calibration(axis_label, options)
        except (ValueError, ODriveConnectionError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"ok": False, "error": f"Could not start motor calibration: {exc}"}), 500
        return jsonify({"ok": True, "status": status})

    @app.post("/api/motors/calibration/<axis_label>/stop")
    def api_stop_motor_calibration(axis_label: str):
        try:
            status = monitor.stop_motor_calibration(axis_label)
        except (ValueError, ODriveConnectionError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"ok": False, "error": f"Could not stop motor calibration: {exc}"}), 500
        return jsonify({"ok": True, "status": status})

    return app


def _restart_process_soon() -> None:
    sleep(0.25)
    os._exit(1)


def _set_simulation_mode(enabled: bool) -> dict[str, Any]:
    """Persist only the mode flag atomically without baking remote overlays into local safety settings."""
    raw = json.loads(APP_SETTINGS_PATH.read_text(encoding="utf-8")) if APP_SETTINGS_PATH.exists() else {}
    if not isinstance(raw, dict):
        raise ValueError("AppSetting.JSON must contain an object.")
    raw["simulation_mode"] = {"enabled": bool(enabled)}
    fd, temporary = tempfile.mkstemp(prefix=".AppSetting.JSON.", dir=APP_SETTINGS_PATH.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(raw, output, indent=2, sort_keys=True, allow_nan=False)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, APP_SETTINGS_PATH)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    global _SETTINGS_CACHE, _SETTINGS_MTIME
    _SETTINGS_CACHE = None
    _SETTINGS_MTIME = None
    return _load_app_settings()


def _parse_tuning_payload(payload: dict[str, Any]) -> dict[str, float]:
    values: dict[str, float] = {}
    for key in TUNING_FIELDS:
        if key not in payload:
            continue
        if payload[key] in (None, ""):
            continue
        try:
            value = float(payload[key])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{key} must be a number.") from exc
        if not math.isfinite(value) or (key not in TUNING_SIGNED_FIELDS and value < 0):
            raise ValueError(f"{key} must be a finite number greater than or equal to 0.")
        values[key] = value

    if not values:
        raise ValueError("No tuning values were provided.")
    return values


def _parse_auto_tune_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not payload:
        return {}

    options: dict[str, Any] = {}
    numeric_fields = {
        "min_position_deg": "minimum position",
        "max_position_deg": "maximum position",
        "speed_deg_per_sec": "move speed",
        "min_speed_deg_per_sec": "minimum speed",
        "max_speed_deg_per_sec": "maximum speed",
        "settle_position_deg": "settle error",
        "settle_velocity_deg_per_sec": "settle velocity",
        "min_step_time_sec": "minimum step time",
        "min_travel_deg": "minimum travel",
    }
    for key, label in numeric_fields.items():
        if key not in payload or payload[key] in (None, ""):
            continue
        try:
            value = float(payload[key])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Auto tune {label} must be a number.") from exc
        if not math.isfinite(value):
            raise ValueError(f"Auto tune {label} must be finite.")
        options[key] = value

    if "cycles" in payload and payload["cycles"] not in (None, ""):
        try:
            cycles = int(payload["cycles"])
        except (TypeError, ValueError) as exc:
            raise ValueError("Auto tune sweep cycles must be a whole number.") from exc
        if cycles < 1 or cycles > 20:
            raise ValueError("Auto tune sweep cycles must be between 1 and 20.")
        options["cycles"] = cycles

    for key, label, lower, upper in (
        ("max_candidates", "max profiles", 1, 8),
        ("max_failed_steps", "fail limit", 1, 64),
    ):
        if key not in payload or payload[key] in (None, ""):
            continue
        try:
            value = int(payload[key])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Auto tune {label} must be a whole number.") from exc
        if value < lower or value > upper:
            raise ValueError(f"Auto tune {label} must be between {lower} and {upper}.")
        options[key] = value

    if "speed_deg_per_sec" in options and options["speed_deg_per_sec"] <= 0:
        raise ValueError("Auto tune move speed must be greater than 0.")
    if "min_speed_deg_per_sec" in options and options["min_speed_deg_per_sec"] <= 0:
        raise ValueError("Auto tune minimum speed must be greater than 0.")
    if "max_speed_deg_per_sec" in options and options["max_speed_deg_per_sec"] <= 0:
        raise ValueError("Auto tune maximum speed must be greater than 0.")
    if "settle_position_deg" in options and options["settle_position_deg"] <= 0:
        raise ValueError("Auto tune settle error must be greater than 0.")
    if "settle_velocity_deg_per_sec" in options and options["settle_velocity_deg_per_sec"] <= 0:
        raise ValueError("Auto tune settle velocity must be greater than 0.")
    if "min_step_time_sec" in options and options["min_step_time_sec"] < 0:
        raise ValueError("Auto tune minimum step time must be 0 or greater.")
    if "min_travel_deg" in options and options["min_travel_deg"] < 0:
        raise ValueError("Auto tune minimum travel must be 0 or greater.")
    if "min_speed_deg_per_sec" in options and "max_speed_deg_per_sec" in options:
        if options["min_speed_deg_per_sec"] > options["max_speed_deg_per_sec"]:
            raise ValueError("Auto tune minimum speed must be less than or equal to maximum speed.")
    if "min_position_deg" in options and "max_position_deg" in options:
        if options["min_position_deg"] >= options["max_position_deg"]:
            raise ValueError("Auto tune minimum position must be less than maximum position.")
    return options


def _tuning_value_to_odrive_units(key: str, value: float) -> float:
    if key in TUNING_DEGREE_RATE_FIELDS:
        return value / 360.0
    return value


def _parse_goto_payload(payload: dict[str, Any]) -> tuple[dict[str, float], float | None]:
    positions: dict[str, float] = {}
    for label in ("Azimuth", "Altitude"):
        value = payload.get(label)
        if value in (None, ""):
            continue
        try:
            degrees = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} target must be a number.") from exc
        if not math.isfinite(degrees):
            raise ValueError(f"{label} target must be finite.")
        positions[label] = degrees
    if not positions:
        raise ValueError("No goto targets were provided.")
    velocity_target = _parse_optional_positive_float(
        payload.get("velocity_target_deg_per_sec"),
        "Velocity target",
    )
    if velocity_target is not None:
        _validate_max_velocity("Velocity target", velocity_target)
    return positions, velocity_target


def _parse_optional_positive_float(value: Any, label: str) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a number.") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite.")
    if number <= 0:
        raise ValueError(f"{label} must be greater than 0.")
    return number


def _parse_velocity_payload(payload: dict[str, Any]) -> dict[str, float]:
    velocities: dict[str, float] = {}
    for label in ("Azimuth", "Altitude"):
        value = payload.get(label)
        if value in (None, ""):
            continue
        try:
            degrees_per_sec = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} velocity must be a number.") from exc
        if not math.isfinite(degrees_per_sec):
            raise ValueError(f"{label} velocity must be finite.")
        _validate_max_velocity(f"{label} velocity", degrees_per_sec)
        velocities[label] = degrees_per_sec
    if not velocities:
        raise ValueError("No velocity targets were provided.")
    return velocities


def _parse_sine_velocity_payload(payload: dict[str, Any]) -> dict[str, float]:
    fields = {
        "min_speed_deg_per_sec": "Minimum speed",
        "max_speed_deg_per_sec": "Maximum speed",
        "min_period_sec": "Minimum period",
        "max_period_sec": "Maximum period",
    }
    values: dict[str, float] = {}
    for key, label in fields.items():
        value = payload.get(key)
        if value in (None, ""):
            raise ValueError(f"{label} is required.")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} must be a number.") from exc
        if not math.isfinite(number) or number <= 0:
            raise ValueError(f"{label} must be greater than 0.")
        values[key] = number
    if values["min_speed_deg_per_sec"] > values["max_speed_deg_per_sec"]:
        raise ValueError("Minimum speed must be less than or equal to maximum speed.")
    if values["min_period_sec"] > values["max_period_sec"]:
        raise ValueError("Minimum period must be less than or equal to maximum period.")
    _validate_max_velocity("Sine maximum speed", values["max_speed_deg_per_sec"])
    return values


def _parse_motor_calibration_payload(payload: dict[str, Any]) -> dict[str, float]:
    fields = {
        "min_position_deg": "Minimum position",
        "max_position_deg": "Maximum position",
        "current_amp": "Test current",
        "speed_deg_per_sec": "Move speed",
    }
    values: dict[str, float] = {}
    for key, label in fields.items():
        value = payload.get(key)
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} must be a number.") from exc
        if not math.isfinite(number):
            raise ValueError(f"{label} must be finite.")
        values[key] = number
    if values["min_position_deg"] >= values["max_position_deg"]:
        raise ValueError("Minimum position must be less than maximum position.")
    if values["speed_deg_per_sec"] <= 0:
        raise ValueError("Move speed must be greater than 0.")
    _validate_max_velocity("Move speed", values["speed_deg_per_sec"])
    if values["current_amp"] < 1 or values["current_amp"] > ODRIVE_PRO_V44_MAX_CURRENT_AMP:
        raise ValueError(f"Test current must be between 1 and {ODRIVE_PRO_V44_MAX_CURRENT_AMP:g} Amp.")
    return values


def _load_app_settings() -> dict[str, Any]:
    global _SETTINGS_CACHE, _SETTINGS_MTIME, _REMOTE_SETTINGS_MTIME
    if not APP_SETTINGS_PATH.exists():
        return _default_app_settings()
    mtime = APP_SETTINGS_PATH.stat().st_mtime
    try:
        remote_mtime = ACTIVE_STATION_CONFIGURATION_PATH.stat().st_mtime
    except OSError:
        remote_mtime = None
    if (_SETTINGS_CACHE is not None and _SETTINGS_MTIME == mtime
            and _REMOTE_SETTINGS_MTIME == remote_mtime):
        return _SETTINGS_CACHE
    try:
        with APP_SETTINGS_PATH.open("r", encoding="utf-8") as file:
            settings = json.load(file)
    except (OSError, json.JSONDecodeError):
        return _default_app_settings()

    default_settings = _default_app_settings()
    simulation_mode = settings.get("simulation_mode")
    if isinstance(simulation_mode, dict):
        default_settings["simulation_mode"]["enabled"] = simulation_mode.get("enabled") is True
    tuning_steps = settings.get("tuning_steps")
    if isinstance(tuning_steps, dict):
        default_settings["tuning_steps"] = tuning_steps
    azimuth_sensors = settings.get("azimuth_sensors")
    if isinstance(azimuth_sensors, dict):
        default_settings["azimuth_sensors"].update(_clean_sensor_settings(azimuth_sensors))
    drive_serials = settings.get("drive_serials")
    if isinstance(drive_serials, dict):
        default_settings["drive_serials"].update(_clean_drive_serials(drive_serials))
    station = settings.get("station")
    if isinstance(station, dict):
        default_settings["station"].update(_clean_station_settings(station))
    camera_metadata = settings.get("camera_metadata")
    if isinstance(camera_metadata, dict):
        default_settings["camera_metadata"] = _clean_camera_metadata(camera_metadata)
    motion_limits = settings.get("motion_limits")
    if isinstance(motion_limits, dict):
        default_settings["motion_limits"].update(_clean_motion_limits(motion_limits))
    updater = settings.get("updater")
    if isinstance(updater, dict):
        default_settings["updater"].update(_clean_updater_settings(updater))
    mount_agent = settings.get("mount_agent")
    if isinstance(mount_agent, dict):
        default_settings["mount_agent"] = _clean_mount_agent_settings(
            mount_agent,
            default_settings["mount_agent"],
        )
    # This file is written atomically by configuration_worker after validating
    # every field against the immutable local/drive safety envelope above.
    try:
        remote = json.loads(ACTIVE_STATION_CONFIGURATION_PATH.read_text(encoding="utf-8"))
        station_remote = remote["location"]
        limits_remote = remote["motion_limits"]
        default_settings["station"].update({
            "name": remote["station_name"],
            "latitude": station_remote["latitude"],
            "longitude": station_remote["longitude"],
        })
        default_settings["motion_limits"].update({
            "azimuth_ccw_limit_deg": limits_remote["azimuth_min_deg"],
            "azimuth_cw_limit_deg": limits_remote["azimuth_max_deg"],
            "altitude_lower_limit_deg": limits_remote["altitude_min_deg"],
            "altitude_upper_limit_deg": limits_remote["altitude_max_deg"],
            "slew_rate_deg_per_sec": min(
                limits_remote["azimuth_speed_max_deg_s"],
                limits_remote["altitude_speed_max_deg_s"],
            ),
            "azimuth_remote_acceleration_deg_s2": limits_remote["azimuth_acceleration_deg_s2"],
            "altitude_remote_acceleration_deg_s2": limits_remote["altitude_acceleration_deg_s2"],
        })
    except (FileNotFoundError, OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        pass
    _SETTINGS_CACHE = default_settings
    _SETTINGS_MTIME = mtime
    _REMOTE_SETTINGS_MTIME = remote_mtime
    return default_settings


def _merge_app_settings(payload: dict[str, Any]) -> dict[str, Any]:
    settings = _load_app_settings()
    simulation_mode = payload.get("simulation_mode")
    if simulation_mode is not None:
        if not isinstance(simulation_mode, dict) or not isinstance(simulation_mode.get("enabled"), bool):
            raise ValueError("simulation_mode.enabled must be a boolean.")
        settings["simulation_mode"] = {"enabled": simulation_mode["enabled"]}
    tuning_steps = payload.get("tuning_steps")
    if tuning_steps is not None:
        if not isinstance(tuning_steps, dict):
            raise ValueError("tuning_steps must be an object.")
        settings["tuning_steps"] = _clean_tuning_steps(tuning_steps)
    azimuth_sensors = payload.get("azimuth_sensors")
    if azimuth_sensors is not None:
        if not isinstance(azimuth_sensors, dict):
            raise ValueError("azimuth_sensors must be an object.")
        settings["azimuth_sensors"].update(_clean_sensor_settings(azimuth_sensors))
    drive_serials = payload.get("drive_serials")
    if drive_serials is not None:
        if not isinstance(drive_serials, dict):
            raise ValueError("drive_serials must be an object.")
        cleaned_drive_serials = _clean_drive_serials(drive_serials)
        settings["drive_serials"].update(cleaned_drive_serials)
        if "azimuth_serial" in cleaned_drive_serials:
            settings["drive_serials"]["altitude_serial"] = _derive_altitude_serial(
                cleaned_drive_serials["azimuth_serial"],
                drive_serials.get("available_serials", ()),
            )
    station = payload.get("station")
    if station is not None:
        if not isinstance(station, dict):
            raise ValueError("station must be an object.")
        settings["station"].update(_clean_station_settings(station))
    camera_metadata = payload.get("camera_metadata")
    if camera_metadata is not None:
        if not isinstance(camera_metadata, dict):
            raise ValueError("camera_metadata must be an object.")
        settings["camera_metadata"] = _clean_camera_metadata(camera_metadata)
    motion_limits = payload.get("motion_limits")
    if motion_limits is not None:
        if not isinstance(motion_limits, dict):
            raise ValueError("motion_limits must be an object.")
        settings["motion_limits"].update(_clean_motion_limits(motion_limits))
    updater = payload.get("updater")
    if updater is not None:
        if not isinstance(updater, dict):
            raise ValueError("updater must be an object.")
        settings["updater"].update(_clean_updater_settings(updater))
    mount_agent = payload.get("mount_agent")
    if mount_agent is not None:
        if not isinstance(mount_agent, dict):
            raise ValueError("mount_agent must be an object.")
        settings["mount_agent"] = _clean_mount_agent_settings(
            mount_agent,
            settings["mount_agent"],
        )

    with APP_SETTINGS_PATH.open("w", encoding="utf-8") as file:
        json.dump(settings, file, indent=2, sort_keys=True)
        file.write("\n")
    global _SETTINGS_CACHE, _SETTINGS_MTIME
    _SETTINGS_CACHE = settings
    _SETTINGS_MTIME = APP_SETTINGS_PATH.stat().st_mtime
    return settings


def _clean_tuning_steps(tuning_steps: dict[str, Any]) -> dict[str, dict[str, float]]:
    clean_steps: dict[str, dict[str, float]] = {}
    for axis_label in ("Azimuth", "Altitude"):
        axis_steps = tuning_steps.get(axis_label, {})
        if not isinstance(axis_steps, dict):
            continue
        clean_steps[axis_label] = {}
        for field_name in TUNING_FIELDS:
            if field_name not in axis_steps:
                continue
            try:
                value = float(axis_steps[field_name])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{axis_label}.{field_name} step must be a number.") from exc
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{axis_label}.{field_name} step must be greater than 0.")
            clean_steps[axis_label][field_name] = value
    return clean_steps


def _console_session_id(value: Any) -> str:
    session_id = str(value or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,80}", session_id):
        raise ValueError("A valid API Console session_id is required.")
    return session_id


def _run_restricted_python(
    code: str,
    call_api: Any,
) -> dict[str, Any]:
    """Evaluate a deliberately small Python subset without using exec/eval."""
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as exc:
        raise ValueError(f"Syntax error on line {exc.lineno}: {exc.msg}") from exc
    if len(tree.body) > 40:
        raise ValueError("The Restricted Python Console allows at most 40 statements.")
    variables: dict[str, Any] = {}
    output: list[str] = []
    calls: list[dict[str, Any]] = []

    def value(node: ast.AST) -> Any:
        if isinstance(node, ast.Constant) and isinstance(node.value, (str, int, float, bool, type(None))):
            return node.value
        if isinstance(node, ast.Dict):
            return {value(key): value(item) for key, item in zip(node.keys, node.values)}
        if isinstance(node, ast.List):
            return [value(item) for item in node.elts]
        if isinstance(node, ast.Tuple):
            return tuple(value(item) for item in node.elts)
        if isinstance(node, ast.Name) and node.id in variables:
            return variables[node.id]
        if isinstance(node, ast.Subscript):
            container = value(node.value)
            key = value(node.slice)
            if not isinstance(container, (dict, list, tuple)) or isinstance(key, (dict, list, tuple)):
                raise ValueError("Only JSON-style dictionary/list indexing is allowed.")
            return container[key]
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                if node.func.value.id != "mount" or node.func.attr != "call":
                    raise ValueError("Only mount.call(...) is allowed.")
                if node.keywords:
                    allowed = {"params", "lease_id"}
                    if any(item.arg not in allowed for item in node.keywords):
                        raise ValueError("mount.call only accepts params and lease_id keywords.")
                args = [value(item) for item in node.args]
                keywords = {item.arg: value(item.value) for item in node.keywords}
                if not args or not isinstance(args[0], str):
                    raise ValueError("mount.call requires an action string.")
                params = args[1] if len(args) > 1 else keywords.get("params", {})
                lease_id = args[2] if len(args) > 2 else keywords.get("lease_id", "")
                if not isinstance(params, dict) or not isinstance(lease_id, str):
                    raise ValueError("mount.call params must be a dict and lease_id must be a string.")
                response = call_api(args[0], params, lease_id)
                calls.append(response)
                return response
            if isinstance(node.func, ast.Name) and node.func.id == "print":
                rendered = " ".join(json.dumps(value(item), ensure_ascii=False, indent=2) for item in node.args)
                output.append(rendered)
                return None
            raise ValueError("Only mount.call(...) and print(...) calls are allowed.")
        raise ValueError(f"Python construct {type(node).__name__} is not allowed.")

    for statement in tree.body:
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1 and isinstance(statement.targets[0], ast.Name):
            name = statement.targets[0].id
            if name.startswith("_") or name in {"mount", "print"}:
                raise ValueError("That variable name is reserved.")
            variables[name] = value(statement.value)
        elif isinstance(statement, ast.Expr):
            value(statement.value)
        else:
            raise ValueError("Only assignments and mount.call/print expressions are allowed.")
    return {"stdout": "\n".join(output), "calls": calls}


def _default_app_settings() -> dict[str, Any]:
    return {
        "simulation_mode": {"enabled": False},
        "tuning_steps": {"Azimuth": {}, "Altitude": {}},
        "drive_serials": {
            "azimuth_serial": None,
            "altitude_serial": None,
        },
        "station": {
            "name": "",
            "latitude": None,
            "longitude": None,
            "elevation_above_ground_m": 0.0,
            "azimuth_north_offset_deg": 0.0,
        },
        "camera_metadata": {},
        "motion_limits": {
            "azimuth_ccw_limit_deg": -100.0,
            "azimuth_cw_limit_deg": 100.0,
            "azimuth_position_offset_deg": 0.0,
            "azimuth_position_scale": 1.0,
            "azimuth_current_limit_amp": 20.0,
            "altitude_upper_limit_deg": 100.0,
            "altitude_lower_limit_deg": -100.0,
            "altitude_position_offset_deg": 0.0,
            "altitude_position_scale": 1.0,
            "altitude_current_limit_amp": 20.0,
            "slew_rate_deg_per_sec": SAFE_MAX_SLEW_RATE_DEG_PER_SEC,
        },
        "azimuth_sensors": {
            "ccw_pin": None,
            "cw_pin": None,
            "ccw_active_high": True,
            "cw_active_high": True,
            "ccw_pull": "none",
            "cw_pull": "none",
        },
        "updater": {
            "device_id": _default_device_id(),
            "enabled": True,
            "check_interval_minutes": DEFAULT_UPDATE_INTERVAL_MINUTES,
            "channel": "main",
        },
        "mount_agent": {
            "local": {
                "enabled": True,
                "socket_path": "/run/fire-detector/mount-agent.sock",
                "mode": "660",
            },
            "remote": {
                "enabled": False,
                "host": "",
                "port": 15001,
                "server_name": "",
                "device_id": _default_device_id(),
                "ca_file": "",
                "client_cert_file": "",
                "client_key_file": "",
                "secret_file": "",
                "secret_env": "FIRE_DETECTOR_DEVICE_SECRET",
                "media_upload_url": "",
                "heartbeat_sec": 15.0,
                "telemetry_sec": 1.0,
                "allowed_commands": [
                    "system.hello", "system.get_info", "system.get_health", "mount.get_status",
                    "control.acquire", "control.renew", "control.release",
                    "mount.enable", "mount.disable", "mount.stop", "mount.goto",
                    "mount.set_velocity", "axis.enable", "axis.disable", "axis.stop",
                    "axis.goto", "axis.set_velocity",
                ],
            },
        },
    }


def _clean_mount_agent_settings(
    value: dict[str, Any],
    defaults: dict[str, Any],
) -> dict[str, Any]:
    clean = {
        "local": dict(defaults.get("local", {})),
        "remote": dict(defaults.get("remote", {})),
    }
    local = value.get("local")
    if isinstance(local, dict):
        clean["local"]["enabled"] = bool(local.get("enabled", clean["local"]["enabled"]))
        socket_path = str(local.get("socket_path", clean["local"]["socket_path"])).strip()
        if not socket_path.startswith("/run/"):
            raise ValueError("mount_agent.local.socket_path must be an absolute path below /run.")
        clean["local"]["socket_path"] = socket_path
        mode = str(local.get("mode", clean["local"]["mode"]))
        if mode not in {"600", "660"}:
            raise ValueError("mount_agent.local.mode must be 600 or 660.")
        clean["local"]["mode"] = mode

    remote = value.get("remote")
    if isinstance(remote, dict):
        for key in (
            "host", "server_name", "device_id", "ca_file", "client_cert_file",
            "client_key_file", "secret_file", "secret_env", "media_upload_url",
        ):
            if key in remote:
                clean["remote"][key] = str(remote[key] or "").strip()
        clean["remote"]["enabled"] = bool(remote.get("enabled", clean["remote"]["enabled"]))
        try:
            port = int(remote.get("port", clean["remote"]["port"]))
            heartbeat = float(remote.get("heartbeat_sec", clean["remote"]["heartbeat_sec"]))
            telemetry = float(remote.get("telemetry_sec", clean["remote"]["telemetry_sec"]))
        except (TypeError, ValueError) as exc:
            raise ValueError("Remote port and timing values must be numbers.") from exc
        if not 1 <= port <= 65535:
            raise ValueError("mount_agent.remote.port must be between 1 and 65535.")
        if not 2 <= heartbeat <= 300 or not 0.1 <= telemetry <= 60:
            raise ValueError("Remote heartbeat/telemetry intervals are outside the safe range.")
        clean["remote"].update(port=port, heartbeat_sec=heartbeat, telemetry_sec=telemetry)
        if "allowed_commands" in remote:
            allowed = remote["allowed_commands"]
            if not isinstance(allowed, list) or not all(isinstance(item, str) for item in allowed):
                raise ValueError("mount_agent.remote.allowed_commands must be an array of strings.")
            clean["remote"]["allowed_commands"] = sorted(set(allowed))
        if "secret" in remote:
            raise ValueError("Do not store a Mount Agent secret in AppSetting.JSON; use secret_file or secret_env.")
        if clean["remote"]["enabled"]:
            if not clean["remote"]["host"] or not clean["remote"]["device_id"]:
                raise ValueError("Remote host and device_id are required when Remote Device Protocol is enabled.")
            if not clean["remote"]["secret_file"] and not clean["remote"]["secret_env"]:
                raise ValueError("Remote secret_file or secret_env is required.")
    return clean


def _clean_sensor_settings(settings: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key in ("ccw_pin", "cw_pin"):
        value = settings.get(key)
        if value in (None, ""):
            clean[key] = None
            continue
        try:
            pin = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"azimuth_sensors.{key} must be a GPIO BCM pin number.") from exc
        if pin < 0:
            raise ValueError(f"azimuth_sensors.{key} must be greater than or equal to 0.")
        clean[key] = pin

    for key in ("ccw_active_high", "cw_active_high"):
        if key in settings:
            clean[key] = bool(settings[key])

    for key in ("ccw_pull", "cw_pull"):
        if key not in settings:
            continue
        value = str(settings[key]).strip().lower()
        if value in ("", "off"):
            value = "none"
        if value not in ("none", "up", "down"):
            raise ValueError(f"azimuth_sensors.{key} must be one of: none, up, down.")
        clean[key] = value
    return clean


def _clean_drive_serials(settings: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key in ("azimuth_serial", "altitude_serial"):
        if key not in settings:
            continue
        value = settings.get(key)
        if value in (None, ""):
            clean[key] = None
        else:
            clean[key] = str(value)
    return clean


def _clean_station_settings(settings: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    if "name" in settings:
        clean["name"] = str(settings.get("name") or "").strip()
    for key, minimum, maximum in (
        ("latitude", -90.0, 90.0),
        ("longitude", -180.0, 180.0),
    ):
        if key not in settings:
            continue
        value = settings.get(key)
        if value in (None, ""):
            clean[key] = None
            continue
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"station.{key} must be a number.") from exc
        if not math.isfinite(number) or number < minimum or number > maximum:
            raise ValueError(f"station.{key} must be between {minimum} and {maximum}.")
        clean[key] = number
    if "elevation_above_ground_m" in settings:
        value = settings.get("elevation_above_ground_m")
        if value in (None, ""):
            clean["elevation_above_ground_m"] = 0.0
        else:
            try:
                number = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError("station.elevation_above_ground_m must be a number.") from exc
            if not math.isfinite(number) or number < 0:
                raise ValueError("station.elevation_above_ground_m must be greater than or equal to 0.")
            clean["elevation_above_ground_m"] = number
    if "azimuth_north_offset_deg" in settings:
        value = settings.get("azimuth_north_offset_deg")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("station.azimuth_north_offset_deg must be a number.") from exc
        if not math.isfinite(number) or number < -360.0 or number > 360.0:
            raise ValueError("station.azimuth_north_offset_deg must be between -360 and 360.")
        clean["azimuth_north_offset_deg"] = number
    return clean


def _clean_camera_metadata(metadata: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Validate static camera facts advertised to the remote device registry."""
    schemas = {
        "visible_camera": {
            "native_width": (int, 1.0, None),
            "native_height": (int, 1.0, None),
            "horizontal_fov_min_deg": (float, 0.01, 360.0),
            "horizontal_fov_max_deg": (float, 0.01, 360.0),
            "vertical_fov_min_deg": (float, 0.01, 180.0),
            "vertical_fov_max_deg": (float, 0.01, 180.0),
        },
        "thermal_camera": {
            "native_width": (int, 1.0, None),
            "native_height": (int, 1.0, None),
            "horizontal_fov_min_deg": (float, 0.01, 360.0),
            "horizontal_fov_max_deg": (float, 0.01, 360.0),
            "vertical_fov_min_deg": (float, 0.01, 180.0),
            "vertical_fov_max_deg": (float, 0.01, 180.0),
            "frame_rate_hz": (float, 1.0, 240.0),
            "spectral_range_min_um": (float, 0.01, 100.0),
            "spectral_range_max_um": (float, 0.01, 100.0),
            "optical_zoom_x": (float, 1.0, 100.0),
            "focal_length_min_mm": (float, 0.01, 10000.0),
            "focal_length_max_mm": (float, 0.01, 10000.0),
            "digital_zoom_min_x": (float, 1.0, 100.0),
            "digital_zoom_max_x": (float, 1.0, 100.0),
            "palette_count": (int, 1.0, 256.0),
        },
    }
    clean: dict[str, dict[str, Any]] = {}
    for camera_name, fields in schemas.items():
        source = metadata.get(camera_name)
        if not isinstance(source, dict):
            continue
        camera: dict[str, Any] = {}
        for field, (kind, minimum, maximum) in fields.items():
            try:
                number = float(source[field])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"camera_metadata.{camera_name}.{field} must be a number.") from exc
            if not math.isfinite(number) or number < minimum or (maximum is not None and number > maximum):
                raise ValueError(f"camera_metadata.{camera_name}.{field} is outside the valid range.")
            camera[field] = int(number) if kind is int else number
        if camera_name == "visible_camera" and (
            camera["horizontal_fov_min_deg"] > camera["horizontal_fov_max_deg"]
            or camera["vertical_fov_min_deg"] > camera["vertical_fov_max_deg"]
        ):
            raise ValueError("camera_metadata.visible_camera minimum FOV cannot exceed maximum FOV.")
        if camera_name == "thermal_camera":
            if (
                camera["horizontal_fov_min_deg"] > camera["horizontal_fov_max_deg"]
                or camera["vertical_fov_min_deg"] > camera["vertical_fov_max_deg"]
                or camera["spectral_range_min_um"] > camera["spectral_range_max_um"]
                or camera["focal_length_min_mm"] > camera["focal_length_max_mm"]
                or camera["digital_zoom_min_x"] > camera["digital_zoom_max_x"]
            ):
                raise ValueError("camera_metadata.thermal_camera minimum values cannot exceed maximum values.")
            camera["radiometric"] = bool(source.get("radiometric", False))
            temperature_measurement = str(source.get("temperature_measurement") or "none").strip()
            if temperature_measurement not in {"none", "min_max", "radiometric"}:
                raise ValueError("camera_metadata.thermal_camera.temperature_measurement is invalid.")
            camera["temperature_measurement"] = temperature_measurement
        clean[camera_name] = camera
    return clean


def _clean_updater_settings(settings: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    if "device_id" in settings:
        device_id = str(settings.get("device_id") or "").strip()
        clean["device_id"] = device_id[:64] or _default_device_id()
    if "enabled" in settings:
        clean["enabled"] = bool(settings.get("enabled"))
    if "check_interval_minutes" in settings:
        try:
            interval = int(settings.get("check_interval_minutes"))
        except (TypeError, ValueError) as exc:
            raise ValueError("updater.check_interval_minutes must be a whole number.") from exc
        clean["check_interval_minutes"] = max(1, min(interval, 1440))
    if "channel" in settings:
        channel = str(settings.get("channel") or "main").strip() or "main"
        if any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_/." for character in channel):
            raise ValueError("updater.channel contains unsupported characters.")
        clean["channel"] = channel[:80]
    return clean


def _default_device_id() -> str:
    return os.uname().nodename or "fire-detector"


def _clean_motion_limits(settings: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key in (
        "azimuth_ccw_limit_deg",
        "azimuth_cw_limit_deg",
        "azimuth_position_offset_deg",
        "azimuth_position_scale",
        "azimuth_current_limit_amp",
        "altitude_upper_limit_deg",
        "altitude_lower_limit_deg",
        "altitude_position_offset_deg",
        "altitude_position_scale",
        "altitude_current_limit_amp",
        "slew_rate_deg_per_sec",
    ):
        if key not in settings:
            continue
        value = settings.get(key)
        if value in (None, ""):
            clean[key] = None
            continue
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"motion_limits.{key} must be a number.") from exc
        if not math.isfinite(number):
            raise ValueError(f"motion_limits.{key} must be finite.")
        if key == "slew_rate_deg_per_sec" and (number <= 0 or number > SAFE_MAX_SLEW_RATE_DEG_PER_SEC):
            raise ValueError(f"Max Velocity must be greater than 0 and no more than {SAFE_MAX_SLEW_RATE_DEG_PER_SEC:g} Deg/Sec.")
        if key.endswith("_current_limit_amp") and (number < 1.0 or number > ODRIVE_PRO_V44_MAX_CURRENT_AMP):
            raise ValueError(f"Current Limit must be between 1 and {ODRIVE_PRO_V44_MAX_CURRENT_AMP:g} Amp.")
        if key in ("azimuth_position_scale", "altitude_position_scale") and number not in (-1.0, 1.0):
            raise ValueError(f"motion_limits.{key} must be either -1 or 1.")
        clean[key] = number
    azimuth_ccw = clean.get("azimuth_ccw_limit_deg")
    azimuth_cw = clean.get("azimuth_cw_limit_deg")
    if azimuth_ccw is not None and azimuth_cw is not None and azimuth_ccw >= azimuth_cw:
        raise ValueError("motion_limits.azimuth_ccw_limit_deg must be less than azimuth_cw_limit_deg.")
    altitude_lower = clean.get("altitude_lower_limit_deg")
    altitude_upper = clean.get("altitude_upper_limit_deg")
    if altitude_lower is not None and altitude_upper is not None and altitude_lower >= altitude_upper:
        raise ValueError("motion_limits.altitude_lower_limit_deg must be less than altitude_upper_limit_deg.")
    return clean


def _axis_position_offset(label: str) -> float:
    limits = _load_app_settings().get("motion_limits", {})
    key = {
        "Azimuth": "azimuth_position_offset_deg",
        "Altitude": "altitude_position_offset_deg",
    }.get(label)
    if key is None:
        return 0.0
    value = limits.get(key)
    return value if isinstance(value, (int, float)) and math.isfinite(value) else 0.0


def _axis_position_scale(label: str) -> float:
    key = {
        "Azimuth": "azimuth_position_scale",
        "Altitude": "altitude_position_scale",
    }.get(label)
    if key is None:
        return 1.0
    value = _load_app_settings().get("motion_limits", {}).get(key, 1.0)
    return -1.0 if value == -1 or value == -1.0 else 1.0


def _axis_command_degrees_to_turns(axis: Any, label: str, degrees: float) -> float:
    return _axis_display_degrees_to_encoder_turns(label, degrees)


def _apply_position_offsets_to_payload(data: dict[str, Any], unwrap_state: dict[str, dict[str, float]] | None = None) -> None:
    axes = data.get("axes")
    if not isinstance(axes, (list, tuple)):
        return
    azimuth_sensors = data.get("azimuth_sensors")
    for axis in axes:
        if not isinstance(axis, dict):
            continue
        label = str(axis.get("label", ""))
        position = axis.get("position_deg")
        if position is None:
            continue
        try:
            position_number = float(position)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(position_number):
            continue
        axis["raw_position_deg"] = position_number
        axis["position_offset_deg"] = _axis_position_offset(label)
        scale = _axis_position_scale(label)
        axis["position_scale"] = scale
        offset = axis["position_offset_deg"]
        scaled_position = position_number * scale
        velocity = _finite_float(axis.get("velocity_deg_per_sec"))
        if velocity is not None:
            axis["velocity_deg_per_sec"] = velocity * scale
        for velocity_setpoint_key in ("input_vel", "vel_setpoint"):
            velocity_setpoint = _finite_float(axis.get(velocity_setpoint_key))
            if velocity_setpoint is not None:
                axis[velocity_setpoint_key] = velocity_setpoint * scale
        # Keep the encoder absolute angle raw.  The user offset calibrates the
        # displayed/unwrapped position after the sensor region selects a branch.
        absolute_position = _normalize_degrees(scaled_position)
        unwrapped_position = _axis_unwrapped_display_position_deg(
            label,
            scaled_position,
            offset,
            unwrap_state,
            azimuth_sensors,
        )
        axis["unwrapped_position_deg"] = unwrapped_position
        axis["absolute_position_deg"] = absolute_position
        axis["position_deg"] = unwrapped_position if label == "Azimuth" else _axis_display_position_deg(label, position_number, offset, azimuth_sensors)
        if label == "Azimuth":
            axis["azimuth_region"] = _azimuth_region_label(azimuth_sensors)


def _axis_display_position_deg(label: str, position_deg: float, offset_deg: float, azimuth_sensors: dict[str, Any] | None) -> float:
    if label == "Altitude":
        # Apply the zero correction before direction so a direction change
        # does not move the calibrated zero point.
        return _normalize_signed_degrees(
            (position_deg + offset_deg) * _axis_position_scale(label)
        )
    position_deg *= _axis_position_scale(label)
    if label == "Azimuth":
        return _normalize_signed_degrees(position_deg - offset_deg)
    return _normalize_signed_degrees(_normalize_degrees(position_deg - offset_deg))


def _axis_display_degrees_to_encoder_turns(label: str, degrees: float) -> float:
    offset = _axis_position_offset(label)
    if label == "Altitude":
        return ((degrees / _axis_position_scale(label)) - offset) / 360.0
    return ((degrees + offset) / _axis_position_scale(label)) / 360.0


def _axis_display_velocity_to_encoder_turns(label: str, degrees_per_sec: float) -> float:
    return (degrees_per_sec / _axis_position_scale(label)) / 360.0


def _axis_unwrapped_display_position_deg(
    label: str,
    position_deg: float,
    offset_deg: float,
    unwrap_state: dict[str, dict[str, float]] | None = None,
    azimuth_sensors: dict[str, Any] | None = None,
) -> float:
    if label == "Altitude":
        return position_deg + (offset_deg * _axis_position_scale(label))
    if label != "Azimuth" or unwrap_state is None:
        return position_deg - offset_deg

    absolute = _normalize_degrees(position_deg)
    state = unwrap_state.get(label)
    if not state:
        # Calibrate the encoder's absolute angle first.  Region selection then
        # chooses the negative or positive representation of that calibrated
        # angle.  Doing this in the opposite order would turn, for example,
        # Abs 70.762 with Offset 125 into -414.238 instead of -54.238.
        calibrated_absolute = _normalize_degrees(absolute - offset_deg)
        initial = _azimuth_initial_unwrapped_position(calibrated_absolute, azimuth_sensors)
        unwrap_state[label] = {"absolute": absolute, "unwrapped": initial}
        return initial

    previous_absolute = float(state.get("absolute", absolute))
    previous_unwrapped = float(state.get("unwrapped", position_deg - offset_deg))
    delta = _signed_degree_delta(absolute, previous_absolute)
    unwrapped = previous_unwrapped + delta
    state["absolute"] = absolute
    state["unwrapped"] = unwrapped
    return unwrapped


def _azimuth_initial_unwrapped_position(
    absolute_deg: float,
    azimuth_sensors: dict[str, Any] | None,
) -> float:
    if not isinstance(azimuth_sensors, dict):
        return absolute_deg
    ccw_active = bool(azimuth_sensors.get("ccw_sensor"))
    cw_active = bool(azimuth_sensors.get("cw_sensor"))
    if ccw_active and not cw_active:
        return absolute_deg - 360.0 if absolute_deg > 0.0 else 0.0
    if cw_active and not ccw_active:
        return absolute_deg
    # Both active (or both inactive) is an ambiguous/invalid region signal.
    # Prefer the signed representation so an angle just below 360 degrees
    # restarts near 0 instead of jumping by a full revolution.
    return _normalize_signed_degrees(absolute_deg)


def _azimuth_position_for_sensor_region(
    position_deg: float,
    azimuth_sensors: dict[str, Any] | None,
) -> float:
    if not isinstance(azimuth_sensors, dict):
        return position_deg
    ccw_active = bool(azimuth_sensors.get("ccw_sensor"))
    cw_active = bool(azimuth_sensors.get("cw_sensor"))
    if ccw_active and not cw_active and position_deg > 0.0:
        while position_deg > 0.0:
            position_deg -= 360.0
    return position_deg


def _normalize_degrees(position_deg: float) -> float:
    normalized = position_deg % 360.0
    if math.isclose(normalized, 360.0, abs_tol=1e-9) or math.isclose(normalized, 0.0, abs_tol=1e-9):
        return 0.0
    return normalized


def _normalize_signed_degrees(position_deg: float) -> float:
    normalized = _normalize_degrees(position_deg)
    if normalized > 180.0:
        return normalized - 360.0
    return normalized


def _shortest_angle_delta_deg(delta_deg: float) -> float:
    return ((delta_deg + 180.0) % 360.0) - 180.0


def _median_position_measurement(measurement: float, state: dict[str, Any]) -> float:
    reference = float(state["position"])
    history = [
        reference + _shortest_angle_delta_deg(float(value) - reference)
        for value in state.get("measurements", [])
        if _finite_float(value) is not None
    ]
    history.append(reference + _shortest_angle_delta_deg(measurement - reference))
    history = history[-POSITION_MEDIAN_WINDOW:]
    state["measurements"] = history
    closest = sorted(history, key=lambda value: abs(value - reference))[:3]
    return _wrap_degrees(sum(closest) / len(closest))


def _reject_position_glitch(measurement: float, state: dict[str, Any], dt: float) -> float:
    reference = float(state["position"])
    delta = _shortest_angle_delta_deg(measurement - reference)
    speed = abs(delta) / max(dt, 1e-3)
    max_speed = _position_glitch_speed_limit()
    if speed <= max_speed:
        state["rejected"] = 0
        state["last_rejected"] = False
        state["last_rejected_measurement"] = None
        state["pending_measurement"] = None
        return measurement

    pending = _finite_float(state.get("pending_measurement"))
    if pending is None:
        rejected = 1
    else:
        pending_delta = abs(_shortest_angle_delta_deg(measurement - pending))
        if pending_delta / max(dt, 1e-3) <= max_speed:
            rejected = int(state.get("rejected", 0)) + 1
        else:
            rejected = 1
    state["pending_measurement"] = measurement
    state["rejected"] = rejected
    state["last_rejected"] = True
    state["last_rejected_measurement"] = measurement
    if rejected >= POSITION_GLITCH_ACCEPT_AFTER:
        state["rejected"] = 0
        state["last_rejected"] = False
        state["pending_measurement"] = None
        state["measurements"] = [measurement]
        return measurement
    return reference


def _position_glitch_speed_limit() -> float:
    limits = _load_app_settings().get("motion_limits", {})
    slew_rate = _finite_float(limits.get("slew_rate_deg_per_sec"))
    if slew_rate is None:
        slew_rate = 0.0
    return max(
        POSITION_GLITCH_MIN_SPEED_DEG_PER_SEC,
        abs(slew_rate) * POSITION_GLITCH_SPEED_MULTIPLIER,
    )


def _wrap_degrees(value: float) -> float:
    return value % 360.0


def _finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _int_or_zero(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return number if number > 0 else 0


def _azimuth_region_label(azimuth_sensors: dict[str, Any] | None) -> str:
    if not isinstance(azimuth_sensors, dict):
        return "unknown"
    ccw_active = bool(azimuth_sensors.get("ccw_sensor"))
    cw_active = bool(azimuth_sensors.get("cw_sensor"))
    if ccw_active and not cw_active:
        return "ccw"
    if cw_active and not ccw_active:
        return "cw"
    return "ambiguous"


def _derive_altitude_serial(azimuth_serial: str | None, available_serials: Any) -> str | None:
    if not isinstance(available_serials, (list, tuple)):
        return None
    serials = [str(serial) for serial in available_serials if serial not in (None, "")]
    if len(serials) < 2 or azimuth_serial is None:
        return None
    for serial in serials:
        if serial != str(azimuth_serial):
            return serial
    return None


def _order_devices_for_config(devices: tuple[Any, ...]) -> tuple[Any, ...]:
    settings = _load_app_settings().get("drive_serials", {})
    azimuth_serial = settings.get("azimuth_serial")
    altitude_serial = settings.get("altitude_serial")
    if not azimuth_serial and not altitude_serial:
        return devices

    devices_by_serial = {
        str(serial): device
        for device in devices
        if (serial := _device_serial(device)) is not None
    }
    azimuth_device = devices_by_serial.get(str(azimuth_serial)) if azimuth_serial else None
    altitude_device = devices_by_serial.get(str(altitude_serial)) if altitude_serial else None
    unassigned = [
        device
        for device in devices
        if device is not azimuth_device and device is not altitude_device
    ]
    if azimuth_device is None and not azimuth_serial and unassigned:
        azimuth_device = unassigned.pop(0)
    if altitude_device is None and not altitude_serial and unassigned:
        altitude_device = unassigned.pop(0)
    return (azimuth_device, altitude_device)


def _require_valid_drive_status(status: Any) -> None:
    axes = tuple(getattr(status, "axes", ()))
    if not any(
        bool(getattr(axis, "available", False)) and getattr(axis, "drive_serial", None) is not None
        for axis in axes
    ):
        raise ODriveConnectionError("ODrive USB handle is stale; reconnecting to drives.")


def _status_has_missing_configured_drive(status: Any) -> bool:
    configured = _load_app_settings().get("drive_serials", {})
    axes = tuple(getattr(status, "axes", ()))
    for index, key in enumerate(("azimuth_serial", "altitude_serial")):
        if not configured.get(key):
            continue
        if index >= len(axes) or not bool(getattr(axes[index], "available", False)):
            return True
        if getattr(axes[index], "drive_serial", None) is None:
            return True
    return False


def _device_serial(device: Any) -> Any:
    try:
        return getattr(device, "serial_number")
    except Exception:
        return None


def _odrive_discovery_serial(serial: Any) -> str:
    """Convert the remote decimal serial value to ODrive's USB hex filter."""
    try:
        return f"{int(serial):012X}"
    except (TypeError, ValueError):
        return str(serial)


def _validate_motion_targets(positions_deg: dict[str, float]) -> None:
    limits = _load_app_settings().get("motion_limits", {})
    azimuth = positions_deg.get("Azimuth")
    if azimuth is not None:
        ccw_limit = limits.get("azimuth_ccw_limit_deg")
        cw_limit = limits.get("azimuth_cw_limit_deg")
        if ccw_limit is not None and azimuth < ccw_limit:
            raise ValueError(f"Azimuth target must be greater than or equal to CCW limit ({ccw_limit} Deg).")
        if cw_limit is not None and azimuth > cw_limit:
            raise ValueError(f"Azimuth target must be less than or equal to CW limit ({cw_limit} Deg).")

    altitude = positions_deg.get("Altitude")
    if altitude is not None:
        lower_limit = limits.get("altitude_lower_limit_deg")
        upper_limit = limits.get("altitude_upper_limit_deg")
        if lower_limit is not None and altitude < lower_limit:
            raise ValueError(f"Altitude target must be greater than or equal to lower limit ({lower_limit} Deg).")
        if upper_limit is not None and altitude > upper_limit:
            raise ValueError(f"Altitude target must be less than or equal to upper limit ({upper_limit} Deg).")


def _axis_target_returns_within_limits(axis_status: Any, lower: float | None, upper: float | None, azimuth_sensors: dict[str, Any] | None) -> bool:
    if getattr(axis_status, "control_mode", None) != CONTROL_MODE_POSITION_CONTROL:
        return False
    if getattr(axis_status, "input_mode", None) != INPUT_MODE_TRAP_TRAJ:
        return False
    target = getattr(axis_status, "input_pos", None)
    if target is None:
        return False
    target = _axis_display_position_deg(
        getattr(axis_status, "label", ""),
        target,
        _axis_position_offset(getattr(axis_status, "label", "")),
        azimuth_sensors,
    )
    if lower is not None and target < lower:
        return False
    if upper is not None and target > upper:
        return False
    return True


def _axis_velocity_returns_within_limits(axis_status: Any, position: float, lower: float | None, upper: float | None) -> bool:
    velocity = _finite_float(getattr(axis_status, "input_vel", None))
    if velocity is None or abs(velocity) < 1e-6:
        return False
    velocity *= _axis_position_scale(getattr(axis_status, "label", ""))
    if lower is not None and position <= lower and velocity > 0.0:
        return True
    if upper is not None and position >= upper and velocity < 0.0:
        return True
    return False


def _axis_velocity_hits_runtime_limit(position: float, velocity: float, lower: float | None, upper: float | None) -> bool:
    if lower is not None and position <= lower and velocity < 0.0:
        return True
    if upper is not None and position >= upper and velocity > 0.0:
        return True
    return False


def _axis_velocity_limited_by_runtime_limits(position: float, velocity: float, lower: float | None, upper: float | None) -> float:
    if _axis_velocity_hits_runtime_limit(position, velocity, lower, upper):
        return 0.0
    slow_zone_deg = _runtime_limit_slow_zone_deg(velocity)
    if slow_zone_deg <= 0.0:
        return velocity
    if (
        upper is not None
        and velocity > RUNTIME_LIMIT_SLOW_SPEED_DEG_PER_SEC
        and 0.0 <= upper - position <= slow_zone_deg
    ):
        return RUNTIME_LIMIT_SLOW_SPEED_DEG_PER_SEC
    if (
        lower is not None
        and velocity < -RUNTIME_LIMIT_SLOW_SPEED_DEG_PER_SEC
        and 0.0 <= position - lower <= slow_zone_deg
    ):
        return -RUNTIME_LIMIT_SLOW_SPEED_DEG_PER_SEC
    return velocity


def _runtime_limit_slow_zone_enabled(velocity_deg_per_sec: float) -> bool:
    return abs(velocity_deg_per_sec) > RUNTIME_LIMIT_SLOW_SPEED_THRESHOLD_DEG_PER_SEC


def _runtime_limit_slow_zone_deg(velocity_deg_per_sec: float) -> float:
    if not _runtime_limit_slow_zone_enabled(velocity_deg_per_sec):
        return 0.0
    return abs(velocity_deg_per_sec) * RUNTIME_LIMIT_SLOW_ZONE_SPEED_RATIO


def _limit_velocities(velocities_deg_per_sec: dict[str, float]) -> dict[str, float]:
    for label, velocity in velocities_deg_per_sec.items():
        _validate_max_velocity(f"{label} velocity", velocity)
    return velocities_deg_per_sec


def _apply_slew_rate(devices: tuple[Any, ...], velocity_target_deg_per_sec: float | None = None) -> None:
    trap_limit = _effective_slew_rate(velocity_target_deg_per_sec)
    if trap_limit is None:
        return
    for device in devices[:2]:
        if device is None:
            continue
        axis = getattr(device, "axis0")
        _set_if_present(axis, "trap_traj.config.vel_limit", trap_limit / 360.0)


def _effective_slew_rate(velocity_target_deg_per_sec: float | None = None) -> float | None:
    if velocity_target_deg_per_sec is None:
        return _configured_slew_rate()
    _validate_max_velocity("Velocity target", velocity_target_deg_per_sec)
    return velocity_target_deg_per_sec


def _configured_slew_rate() -> float | None:
    configured_slew_rate = _load_app_settings().get("motion_limits", {}).get("slew_rate_deg_per_sec")
    if not isinstance(configured_slew_rate, (int, float)) or not math.isfinite(configured_slew_rate) or configured_slew_rate <= 0:
        return None
    return min(configured_slew_rate, SAFE_MAX_SLEW_RATE_DEG_PER_SEC)


def _validate_max_velocity(label: str, velocity_deg_per_sec: float) -> None:
    max_velocity = _configured_slew_rate()
    if max_velocity is None:
        return
    if abs(velocity_deg_per_sec) > max_velocity:
        raise ValueError(f"{label} must be less than or equal to Max Velocity ({max_velocity} Deg/Sec).")


def _max_reasonable_position_delta_deg(dt: float) -> float:
    max_velocity = _configured_slew_rate()
    if max_velocity is None:
        max_velocity = SAFE_MAX_SLEW_RATE_DEG_PER_SEC
    return max(30.0, max_velocity * dt * 10.0)


def _flash_motion_limits_to_drives(devices: tuple[Any, ...], settings: dict[str, Any]) -> dict[str, Any]:
    limits = settings.get("motion_limits", {})
    warnings: list[str] = []
    flashed: list[dict[str, Any]] = []
    axis_specs = (
        (
            "Azimuth",
            0,
            limits.get("azimuth_ccw_limit_deg"),
            limits.get("azimuth_cw_limit_deg"),
            limits.get("azimuth_current_limit_amp"),
        ),
        (
            "Altitude",
            1,
            limits.get("altitude_lower_limit_deg"),
            limits.get("altitude_upper_limit_deg"),
            limits.get("altitude_current_limit_amp"),
        ),
    )
    slew_rate = _finite_float(limits.get("slew_rate_deg_per_sec"))
    if slew_rate is not None:
        slew_rate = min(slew_rate, SAFE_MAX_SLEW_RATE_DEG_PER_SEC)
    for label, index, lower_limit, upper_limit, current_limit_amp in axis_specs:
        if index >= len(devices):
            warnings.append(f"{label} drive is not connected; limits were not flashed.")
            continue
        device = devices[index]
        if device is None:
            warnings.append(f"{label} drive is not connected; limits were not flashed.")
            continue
        serial = _device_serial(device)
        axis = getattr(device, "axis0")
        if slew_rate is not None:
            turns_per_second = slew_rate / 360.0
            _set_if_present(axis, "trap_traj.config.vel_limit", turns_per_second)

        if lower_limit is not None:
            _set_if_present(axis, "min_endstop.config.offset", _axis_command_degrees_to_turns(axis, label, lower_limit))
        if upper_limit is not None:
            _set_if_present(axis, "max_endstop.config.offset", _axis_command_degrees_to_turns(axis, label, upper_limit))

        if current_limit_amp is not None:
            # The settings field is the continuous motor current. Peak current
            # is managed separately by CurrentEnvelope and is never converted
            # with the old 1 Nm/A placeholder.
            torque_limit = current_limit_amp * MOTOR_CURRENT_ENVELOPE.torque_constant_nm_per_amp
            _set_if_present(
                axis,
                "config.motor.torque_constant",
                MOTOR_CURRENT_ENVELOPE.torque_constant_nm_per_amp,
            )
            _set_if_present(
                axis,
                "config.motor.current_soft_max",
                MOTOR_CURRENT_ENVELOPE.peak_current_amp,
            )
            _set_if_present(
                axis,
                "config.motor.current_hard_max",
                MOTOR_CURRENT_ENVELOPE.hard_current_amp,
            )
            _set_if_present(axis, "config.torque_soft_max", torque_limit)
            _set_if_present(axis, "config.torque_soft_min", -torque_limit)

        min_enabled = _get_path_bool(axis, "min_endstop.config.enabled")
        max_enabled = _get_path_bool(axis, "max_endstop.config.enabled")
        if min_enabled or max_enabled:
            _set_if_present(axis, "pos_vel_mapper.config.use_endstop", True)
        elif lower_limit is not None or upper_limit is not None:
            warnings.append(
                f"{label} drive stored limit offsets, but ODrive endstop GPIOs are not enabled. "
                "Wire the limit sensors to ODrive min/max endstop inputs and enable them for drive-level enforcement."
            )

        save_warning = None
        try:
            device.save_configuration()
        except Exception as exc:
            save_warning = f"{label} drive disconnected while saving configuration; this is expected during ODrive flash/reboot."
            warnings.append(save_warning)
        flashed.append(
            {
                "axis": label,
                "serial": serial,
                "lower_limit_deg": lower_limit,
                "upper_limit_deg": upper_limit,
                "slew_rate_deg_per_sec": slew_rate,
                "current_limit_amp": current_limit_amp,
                "peak_current_amp": MOTOR_CURRENT_ENVELOPE.peak_current_amp,
                "hard_current_amp": MOTOR_CURRENT_ENVELOPE.hard_current_amp,
                "peak_duration_sec": MOTOR_CURRENT_ENVELOPE.peak_duration_sec,
                "drive_endstops_enabled": bool(min_enabled or max_enabled),
                "save_warning": save_warning,
            }
        )
    return {"flashed": flashed, "warnings": warnings}


AUTO_TUNE_SETTLE_POSITION_DEG = 0.5
AUTO_TUNE_SETTLE_VELOCITY_DEG_PER_SEC = 0.8
AUTO_TUNE_SETTLE_HOLD_SEC = 0.35
AUTO_TUNE_MOVE_TIMEOUT_SEC = 12.0
AUTO_TUNE_MAX_MOVE_TIMEOUT_SEC = 180.0
AUTO_TUNE_TIMEOUT_MARGIN = 1.15
AUTO_TUNE_STALL_CHECK_SEC = 5.0
AUTO_TUNE_STALL_MIN_DELTA_DEG = 0.08
AUTO_TUNE_STALL_MIN_VELOCITY_DEG_PER_SEC = 0.03
AUTO_TUNE_SAMPLE_SEC = 0.04
AUTO_TUNE_STEP_RESET_HOLD_SEC = 0.35
ODRIVE_SPINOUT_DETECTED_BIT = 0x04000000
AUTO_TUNE_CANDIDATES = (
    {
        "name": "balanced_current",
        "position_gain": 6.0,
        "velocity_gain": 6.5,
        "velocity_integrator_gain": 4.0,
        "velocity_integrator_limit": 5.0,
        "velocity_limit": 90.0,
        "trap_velocity_limit": 30.0,
        "trap_accel_limit": 80.0,
        "trap_decel_limit": 80.0,
        "input_filter_bandwidth": 8.0,
    },
    {
        "name": "stronger_follow",
        "position_gain": 8.0,
        "velocity_gain": 7.5,
        "velocity_integrator_gain": 5.0,
        "velocity_integrator_limit": 6.0,
        "velocity_limit": 100.0,
        "trap_velocity_limit": 35.0,
        "trap_accel_limit": 90.0,
        "trap_decel_limit": 90.0,
        "input_filter_bandwidth": 10.0,
    },
    {
        "name": "smooth_lower_i",
        "position_gain": 5.0,
        "velocity_gain": 6.0,
        "velocity_integrator_gain": 3.0,
        "velocity_integrator_limit": 4.0,
        "velocity_limit": 80.0,
        "trap_velocity_limit": 25.0,
        "trap_accel_limit": 60.0,
        "trap_decel_limit": 60.0,
        "input_filter_bandwidth": 7.0,
    },
)
AUTO_TUNE_LOW_SPEED_CANDIDATES = (
    {
        "name": "velocity_creep_stable",
        "position_gain": 10.0,
        "velocity_gain": 4.0,
        "velocity_integrator_gain": 0.8,
        "velocity_integrator_limit": 2.0,
        "velocity_limit": 80.0,
        "velocity_ramp_rate": 40.0,
        "torque_ramp_rate": 80.0,
        "trap_velocity_limit": 10.0,
        "trap_accel_limit": 28.0,
        "trap_decel_limit": 28.0,
        "input_filter_bandwidth": 5.0,
    },
    {
        "name": "velocity_low_friction",
        "position_gain": 14.0,
        "velocity_gain": 5.5,
        "velocity_integrator_gain": 1.5,
        "velocity_integrator_limit": 3.0,
        "velocity_limit": 80.0,
        "velocity_ramp_rate": 70.0,
        "torque_ramp_rate": 120.0,
        "trap_velocity_limit": 10.0,
        "trap_accel_limit": 36.0,
        "trap_decel_limit": 36.0,
        "input_filter_bandwidth": 8.0,
    },
    {
        "name": "velocity_high_static_friction",
        "position_gain": 18.0,
        "velocity_gain": 7.0,
        "velocity_integrator_gain": 2.5,
        "velocity_integrator_limit": 5.0,
        "velocity_limit": 90.0,
        "velocity_ramp_rate": 100.0,
        "torque_ramp_rate": 180.0,
        "trap_velocity_limit": 10.0,
        "trap_accel_limit": 44.0,
        "trap_decel_limit": 44.0,
        "input_filter_bandwidth": 10.0,
    },
)
AUTO_TUNE_RECOVERY_CANDIDATES = (
    {
        "name": "recovery_slow_stable",
        "position_gain": 4.0,
        "velocity_gain": 5.0,
        "velocity_integrator_gain": 2.0,
        "velocity_integrator_limit": 3.0,
        "velocity_limit": 60.0,
        "trap_velocity_limit": 18.0,
        "trap_accel_limit": 40.0,
        "trap_decel_limit": 40.0,
        "input_filter_bandwidth": 5.0,
    },
    {
        "name": "recovery_low_i",
        "position_gain": 3.2,
        "velocity_gain": 4.2,
        "velocity_integrator_gain": 1.2,
        "velocity_integrator_limit": 2.0,
        "velocity_limit": 50.0,
        "trap_velocity_limit": 14.0,
        "trap_accel_limit": 32.0,
        "trap_decel_limit": 32.0,
        "input_filter_bandwidth": 4.0,
    },
)


def _auto_tune_recovery_candidates(move_speed: float | None) -> tuple[dict[str, Any], ...]:
    if move_speed is None:
        return AUTO_TUNE_RECOVERY_CANDIDATES
    recovery_speed = max(5.0, min(move_speed * 0.65, move_speed))
    candidates = []
    for candidate in AUTO_TUNE_RECOVERY_CANDIDATES:
        adjusted = dict(candidate)
        adjusted["trap_velocity_limit"] = min(float(adjusted["trap_velocity_limit"]), recovery_speed)
        adjusted["velocity_limit"] = max(float(adjusted["velocity_limit"]), recovery_speed)
        candidates.append(adjusted)
    return tuple(candidates)


def _auto_tune_candidates_for_speeds(speed_profile: list[float], move_speed: float | None) -> tuple[dict[str, Any], ...]:
    has_creep_speed = any(speed <= 0.3 for speed in speed_profile)
    if has_creep_speed:
        return (*AUTO_TUNE_LOW_SPEED_CANDIDATES, *AUTO_TUNE_CANDIDATES, *_auto_tune_recovery_candidates(move_speed))
    return (*AUTO_TUNE_CANDIDATES, *AUTO_TUNE_LOW_SPEED_CANDIDATES, *_auto_tune_recovery_candidates(move_speed))


def _raise_if_auto_tune_stopped(axis: Any, stop_event: Event | None) -> None:
    if stop_event is not None and stop_event.is_set():
        _hold_axis_at_current_position(axis)
        raise ValueError("Auto tune stopped by user.")


def _publish_auto_tune_progress(
    callback: Any | None,
    label: str,
    phase: str,
    completed_steps: int,
    total_steps: int,
    message: str,
    detail: dict[str, Any] | None = None,
) -> None:
    if callback is None:
        return
    total = max(1, int(total_steps))
    completed = max(0, min(total, int(completed_steps)))
    payload: dict[str, Any] = {
        "running": phase not in {"complete", "failed", "stopped"},
        "axis": label,
        "phase": phase,
        "message": message,
        "completed_steps": completed,
        "total_steps": total,
        "current_step": min(total, completed + 1) if completed < total else total,
        "percent": round((completed / total) * 100.0, 2),
        "timestamp": _timestamp(),
    }
    if detail:
        payload.update(detail)
    callback(payload)


def _auto_tune_step_result_message(
    label: str,
    completed_steps: int,
    total_steps: int,
    summary: dict[str, Any],
    speed_deg_per_sec: float,
) -> str:
    if summary.get("stalled"):
        return (
            f"{label} step {completed_steps}/{total_steps}: no movement detected after "
            f"{summary.get('duration_sec', 0):.1f}s at {speed_deg_per_sec:g} Deg/Sec."
        )
    if summary.get("timeout"):
        return (
            f"{label} step {completed_steps}/{total_steps}: timed out after "
            f"{summary.get('duration_sec', 0):.1f}s at {speed_deg_per_sec:g} Deg/Sec."
        )
    return (
        f"{label} completed step {completed_steps}/{total_steps}: "
        f"error {float(summary['final_error_deg']):.3f} Deg at {speed_deg_per_sec:g} Deg/Sec."
    )


def _auto_tune_step_event(
    label: str,
    candidate_step: int,
    candidate_total_steps: int,
    candidate_index: int,
    candidate_total: int,
    global_step: int,
    global_total_steps: int,
    candidate_name: str,
    move: dict[str, float],
    summary: dict[str, Any],
) -> dict[str, Any]:
    if summary.get("stalled"):
        status = "stalled"
    elif summary.get("timeout"):
        status = "timeout"
    elif summary.get("active_errors") or summary.get("state") != AXIS_STATE_CLOSED_LOOP_CONTROL:
        status = "drive_error"
    elif summary.get("settled"):
        status = "settled"
    else:
        status = "not_settled"
    return {
        "axis": label,
        "step": candidate_step,
        "total_steps": candidate_total_steps,
        "candidate_index": candidate_index,
        "candidate_total": candidate_total,
        "global_step": global_step,
        "global_total_steps": global_total_steps,
        "candidate": candidate_name,
        "cycle": int(move.get("cycle", 0)),
        "speed_deg_per_sec": float(move.get("speed_deg_per_sec", 0.0)),
        "target_deg": float(move.get("target_deg", 0.0)),
        "adapted_target": bool(move.get("adapted_target")),
        "start_deg": float(summary.get("start_deg") or 0.0),
        "end_deg": float(summary.get("end_deg") or 0.0),
        "duration_sec": float(summary.get("duration_sec") or 0.0),
        "timeout_limit_sec": summary.get("timeout_limit_sec"),
        "final_error_deg": float(summary.get("final_error_deg") or 0.0),
        "peak_abs_current_a": summary.get("peak_abs_current_a"),
        "peak_abs_velocity_deg_s": summary.get("peak_abs_velocity_deg_s"),
        "peak_abs_position_velocity_deg_s": summary.get("peak_abs_position_velocity_deg_s"),
        "final_position_velocity_deg_s": summary.get("final_position_velocity_deg_s"),
        "state": summary.get("state"),
        "active_errors": summary.get("active_errors"),
        "disarm_reason": summary.get("disarm_reason"),
        "settled": bool(summary.get("settled")),
        "stalled": bool(summary.get("stalled")),
        "timeout": bool(summary.get("timeout")),
        "status": status,
        "timestamp": _timestamp(),
    }


def _auto_tune_move_has_drive_fault(move: dict[str, Any]) -> bool:
    return (
        int(move.get("active_errors") or 0) != 0
        or int(move.get("disarm_reason") or 0) != 0
        or int(move.get("state") or 0) != AXIS_STATE_CLOSED_LOOP_CONTROL
    )


def _auto_tune_move_has_spinout(move: dict[str, Any]) -> bool:
    active_errors = int(move.get("active_errors") or 0)
    disarm_reason = int(move.get("disarm_reason") or 0)
    return bool((active_errors | disarm_reason) & ODRIVE_SPINOUT_DETECTED_BIT)


def _auto_tune_result_passed(result: dict[str, Any], expected_moves: int) -> bool:
    moves = result.get("moves") or []
    if result.get("failed") or len(moves) != expected_moves:
        return False
    return all(
        move.get("settled")
        and not move.get("timeout")
        and not move.get("stalled")
        and not _auto_tune_move_has_drive_fault(move)
        for move in moves
    )


def _auto_tune_recover_axis_after_fault(
    device: Any,
    axis: Any,
    label: str,
    candidate: dict[str, Any],
    progress_callback: Any | None,
    completed_steps: int,
    total_steps: int,
) -> dict[str, Any]:
    _publish_auto_tune_progress(
        progress_callback,
        label,
        "recovering",
        completed_steps,
        total_steps,
        f"{label} drive fault detected. Clearing errors and restoring closed-loop control...",
    )
    try:
        axis.requested_state = AXIS_STATE_IDLE
        sleep(0.15)
    except Exception:
        pass
    _clear_device_errors(device)
    sleep(0.25)
    try:
        _apply_auto_tune_candidate(axis, candidate)
        _hold_axis_at_current_position(axis)
        axis.requested_state = AXIS_STATE_CLOSED_LOOP_CONTROL
        sleep(0.35)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    active_errors = int(_get_path_float(axis, "active_errors") or 0)
    disarm_reason = int(_get_path_float(axis, "disarm_reason") or 0)
    state = int(_get_path_float(axis, "current_state") or 0)
    armed = bool(getattr(axis, "is_armed", False))
    ok = active_errors == 0 and disarm_reason == 0 and state == AXIS_STATE_CLOSED_LOOP_CONTROL and armed
    _publish_auto_tune_progress(
        progress_callback,
        label,
        "running" if ok else "recovering",
        completed_steps,
        total_steps,
        (
            f"{label} recovery complete; continuing with next candidate."
            if ok
            else f"{label} recovery failed: state={state}, active_errors={active_errors}, disarm_reason={disarm_reason}."
        ),
    )
    return {
        "ok": ok,
        "state": state,
        "armed": armed,
        "active_errors": active_errors,
        "disarm_reason": disarm_reason,
    }


def _auto_tune_reset_step_state(
    device: Any,
    axis: Any,
    label: str,
    candidate: dict[str, Any],
    progress_callback: Any | None,
    completed_steps: int,
    total_steps: int,
    reason: str,
) -> dict[str, Any]:
    _publish_auto_tune_progress(
        progress_callback,
        label,
        "recovering",
        completed_steps,
        total_steps,
        f"{label} resetting auto tune step after {reason}; holding current position before next test...",
    )
    active_errors = int(_get_path_float(axis, "active_errors") or 0)
    disarm_reason = int(_get_path_float(axis, "disarm_reason") or 0)
    state = int(_get_path_float(axis, "current_state") or 0)
    if active_errors or disarm_reason or state != AXIS_STATE_CLOSED_LOOP_CONTROL:
        return _auto_tune_recover_axis_after_fault(
            device,
            axis,
            label,
            candidate,
            progress_callback,
            completed_steps,
            total_steps,
        )
    try:
        axis.controller.input_vel = 0.0
        axis.controller.input_torque = 0.0
        _apply_auto_tune_candidate(axis, candidate)
        _hold_axis_at_current_position(axis)
        sleep(AUTO_TUNE_STEP_RESET_HOLD_SEC)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "state": int(_get_path_float(axis, "current_state") or 0),
        "armed": bool(getattr(axis, "is_armed", False)),
        "active_errors": int(_get_path_float(axis, "active_errors") or 0),
        "disarm_reason": int(_get_path_float(axis, "disarm_reason") or 0),
    }


def _auto_tune_adapt_move_target(label: str, axis: Any, move: dict[str, float]) -> dict[str, float]:
    adjusted = dict(move)
    speed = max(0.001, float(adjusted.get("speed_deg_per_sec") or 0.001))
    planned_target = float(adjusted["target_deg"])
    current = _axis_current_display_deg(label, axis)
    error_to_plan = _signed_degree_delta(planned_target, current)
    amplitude = max(0.1, abs(float(adjusted.get("amplitude_deg") or error_to_plan or 0.1)))
    drift_limit = max(amplitude * 3.0, min(12.0, max(2.0, speed * 8.0)))
    if abs(error_to_plan) <= drift_limit:
        adjusted["start_deg"] = round(current, 3)
        return adjusted
    lower = float(adjusted.get("lower_limit_deg", min(current, planned_target)))
    upper = float(adjusted.get("upper_limit_deg", max(current, planned_target)))
    direction = 1.0 if error_to_plan >= 0.0 else -1.0
    adjusted["start_deg"] = round(current, 3)
    local_target = current + (direction * amplitude)
    if current < lower:
        local_target = _clamp(local_target, current, lower)
    elif current > upper:
        local_target = _clamp(local_target, upper, current)
    else:
        local_target = _clamp(local_target, lower, upper)
    adjusted["target_deg"] = round(local_target, 3)
    adjusted["adapted_target"] = 1.0
    return adjusted


def _run_axis_auto_tune(
    label: str,
    device: Any,
    options: dict[str, Any] | None = None,
    stop_event: Event | None = None,
    progress_callback: Any | None = None,
    telemetry_callback: Any | None = None,
) -> dict[str, Any]:
    options = options or {}
    axis = getattr(device, "axis0")
    sweep_plan = _auto_tune_sweep_plan(label, axis, options)
    original = _read_axis_tuning(axis)
    speed_profile = sorted({float(move["speed_deg_per_sec"]) for move in sweep_plan})
    move_speed = max(speed_profile) if speed_profile else _finite_float(options.get("speed_deg_per_sec"))
    candidates = _auto_tune_candidates_for_speeds(speed_profile, move_speed)
    max_candidates = max(1, min(int(options.get("max_candidates") or 4), len(candidates)))
    max_failed_steps = max(1, int(options.get("max_failed_steps") or 2))
    candidates = candidates[:max_candidates]
    total_steps = max(1, len(candidates) * len(sweep_plan))
    completed_steps = 0
    results = []
    all_samples: list[dict[str, Any]] = []
    _publish_auto_tune_progress(
        progress_callback,
        label,
        "running",
        0,
        total_steps,
        f"{label} auto tune prepared {len(sweep_plan)} sweep steps across {len(speed_profile)} speeds.",
    )
    for candidate_index, candidate in enumerate(candidates):
        _raise_if_auto_tune_stopped(axis, stop_event)
        candidate = dict(candidate)
        if move_speed is not None:
            if str(candidate.get("name", "")).startswith("recovery_"):
                candidate["trap_velocity_limit"] = min(float(candidate["trap_velocity_limit"]), move_speed)
            else:
                candidate["trap_velocity_limit"] = move_speed
            candidate["velocity_limit"] = max(float(candidate["velocity_limit"]), move_speed)
        _clear_device_errors(device)
        _apply_auto_tune_candidate(axis, candidate)
        axis.requested_state = AXIS_STATE_CLOSED_LOOP_CONTROL
        sleep(0.2)
        if telemetry_callback:
            telemetry_callback()
        candidate_samples: list[dict[str, Any]] = []
        moves = []
        failed = False
        failed_steps = 0
        for move_index, move in enumerate(sweep_plan):
            _raise_if_auto_tune_stopped(axis, stop_event)
            move = _auto_tune_adapt_move_target(label, axis, move)
            move_speed_deg_per_sec = float(move["speed_deg_per_sec"])
            _publish_auto_tune_progress(
                progress_callback,
                label,
                "running",
                completed_steps,
                total_steps,
                (
                    f"{label} step {completed_steps + 1}/{total_steps}: "
                    f"{candidate['name']} cycle {int(move['cycle'])}, "
                    f"{move_speed_deg_per_sec:g} Deg/Sec to {float(move['target_deg']):g} Deg."
                ),
                {
                    "candidate": candidate["name"],
                    "candidate_index": candidate_index + 1,
                    "candidate_total": len(candidates),
                    "move_index": move_index + 1,
                    "move_total": len(sweep_plan),
                    "cycle": int(move["cycle"]),
                    "speed_deg_per_sec": move_speed_deg_per_sec,
                    "target_deg": float(move["target_deg"]),
                },
            )
            _set_path_value(axis, "controller.config.vel_limit", max(float(candidate["velocity_limit"]), move_speed_deg_per_sec) / 360.0)
            _set_path_value(axis, "trap_traj.config.vel_limit", move_speed_deg_per_sec / 360.0)
            move_timeout = _auto_tune_move_timeout([float(move["start_deg"]), float(move["target_deg"])], move_speed_deg_per_sec)
            move_samples, summary = _run_auto_tune_move(
                label,
                axis,
                float(move["target_deg"]),
                move_index,
                str(candidate["name"]),
                move_timeout,
                stop_event,
                move_speed_deg_per_sec,
                telemetry_callback,
                options,
            )
            candidate_samples.extend(move_samples)
            moves.append(summary)
            completed_steps += 1
            _publish_auto_tune_progress(
                progress_callback,
                label,
                "running",
                completed_steps,
                total_steps,
                _auto_tune_step_result_message(label, completed_steps, total_steps, summary, move_speed_deg_per_sec),
                {
                    "step_event": _auto_tune_step_event(
                        label,
                        move_index + 1,
                        len(sweep_plan),
                        candidate_index + 1,
                        len(candidates),
                        completed_steps,
                        total_steps,
                        str(candidate["name"]),
                        move,
                        summary,
                    )
                },
            )
            drive_faulted = summary["active_errors"] or summary["state"] != AXIS_STATE_CLOSED_LOOP_CONTROL
            failed_step = bool(drive_faulted or summary.get("stalled") or summary.get("timeout"))
            if drive_faulted:
                recovery = _auto_tune_recover_axis_after_fault(
                    device,
                    axis,
                    label,
                    candidate,
                    progress_callback,
                    completed_steps,
                    total_steps,
                )
                summary["recovery"] = recovery
            elif summary.get("stalled") or summary.get("timeout"):
                summary["recovery"] = _auto_tune_reset_step_state(
                    device,
                    axis,
                    label,
                    candidate,
                    progress_callback,
                    completed_steps,
                    total_steps,
                    "no movement" if summary.get("stalled") else "timeout",
                )
            if failed_step:
                failed = True
                failed_steps += 1
                if not (summary.get("recovery") or {}).get("ok", False):
                    break
                if failed_steps >= max_failed_steps:
                    _publish_auto_tune_progress(
                        progress_callback,
                        label,
                        "running",
                        completed_steps,
                        total_steps,
                        (
                            f"{label} candidate {candidate['name']} reached fail limit "
                            f"({failed_steps}/{max_failed_steps}); skipping to next profile."
                        ),
                        {
                            "candidate": candidate["name"],
                            "candidate_index": candidate_index + 1,
                            "candidate_total": len(candidates),
                            "move_index": min(move_index + 2, len(sweep_plan)),
                            "move_total": len(sweep_plan),
                        },
                    )
                    break
                continue
        all_samples.extend(candidate_samples)
        score = _score_auto_tune_candidate(moves, failed, len(sweep_plan))
        results.append({"candidate": candidate, "moves": moves, "failed": failed, "score": score})
        _hold_axis_at_current_position(axis)
        if not failed and len(moves) == len(sweep_plan) and all(move["settled"] for move in moves):
            break
        sleep(0.5)

    passed_results = [result for result in results if _auto_tune_result_passed(result, len(sweep_plan))]
    best = min(passed_results or results, key=lambda item: item["score"])
    recommended = dict(best["candidate"])
    save_recommended = bool(passed_results)
    if save_recommended:
        _apply_auto_tune_candidate(axis, recommended)
    else:
        _apply_auto_tune_candidate(axis, original)
    _hold_axis_at_current_position(axis)
    _publish_auto_tune_progress(
        progress_callback,
        label,
        "complete" if save_recommended else "failed",
        completed_steps,
        completed_steps,
        (
            f"{label} auto tune selected {recommended.get('name')}."
            if save_recommended
            else f"{label} auto tune found no safe profile; restored original tuning."
        ),
    )
    sleep(0.1)
    return {
        "axis": label,
        "serial": _device_serial(device),
        "targets": [move["target_deg"] for move in sweep_plan],
        "sweep_plan": sweep_plan,
        "speed_profile_deg_per_sec": speed_profile,
        "options": options,
        "original_tuning": original,
        "results": results,
        "best_candidate": recommended.get("name"),
        "recommended_tuning": recommended,
        "save_recommended": save_recommended,
        "safe_profile_found": save_recommended,
        "sample_count": len(all_samples),
        "completed_steps": completed_steps,
        "maximum_steps": total_steps,
        "candidate_sweep_steps": len(sweep_plan),
        "attempted_candidates": len(results),
        "max_candidates": max_candidates,
        "max_failed_steps": max_failed_steps,
        "final_position_deg": _axis_current_display_deg(label, axis),
        "final_state": _get_path_float(axis, "current_state"),
        "final_active_errors": _get_path_float(axis, "active_errors"),
        "final_disarm_reason": _get_path_float(axis, "disarm_reason"),
    }


def _auto_tune_targets(label: str, axis: Any, options: dict[str, Any] | None = None) -> list[float]:
    options = options or {}
    custom_min = _finite_float(options.get("min_position_deg"))
    custom_max = _finite_float(options.get("max_position_deg"))
    cycles = int(options.get("cycles") or 0)
    if custom_min is not None or custom_max is not None:
        if custom_min is None or custom_max is None:
            raise ValueError("Auto tune custom range needs both minimum and maximum positions.")
        if custom_min >= custom_max:
            raise ValueError(f"{label} auto tune minimum position must be less than maximum position.")
        return [round(custom_min, 3), round(custom_max, 3)]

    limits = _load_app_settings().get("motion_limits", {})
    if label == "Altitude":
        lower = _finite_float(limits.get("altitude_lower_limit_deg"))
        upper = _finite_float(limits.get("altitude_upper_limit_deg"))
        lower = -100.0 if lower is None else lower
        upper = 100.0 if upper is None else upper
    else:
        lower = _finite_float(limits.get("azimuth_ccw_limit_deg"))
        upper = _finite_float(limits.get("azimuth_cw_limit_deg"))
        lower = -100.0 if lower is None else lower
        upper = 100.0 if upper is None else upper
    center = (lower + upper) / 2.0
    span = upper - lower
    if span < 80.0:
        raise ValueError(f"{label} auto tune needs at least 80 Deg of configured travel range.")
    amplitude = min(90.0, max(35.0, span * 0.25))
    inner = min(60.0, amplitude * 0.65)
    return [
        round(center - inner, 3),
        round(center + inner, 3),
        round(center - amplitude, 3),
        round(center + amplitude, 3),
        round(center - inner * 0.55, 3),
        round(center + inner * 0.55, 3),
    ]


def _auto_tune_sweep_plan(label: str, axis: Any, options: dict[str, Any] | None = None) -> list[dict[str, float]]:
    options = options or {}
    targets = _auto_tune_targets(label, axis, options)
    if len(targets) < 2:
        raise ValueError(f"{label} auto tune needs at least two sweep targets.")

    lower = min(targets)
    upper = max(targets)
    center = (lower + upper) / 2.0
    half_span = max(0.001, (upper - lower) / 2.0)
    cycles = max(1, min(int(options.get("cycles") or 3), 20))
    speed_profile = _auto_tune_speed_profile(options)
    plan: list[dict[str, float]] = []
    current = _auto_tune_current_position_for_range(label, _axis_current_display_deg(label, axis), lower, upper)
    previous = current

    for cycle_index in range(cycles):
        for speed in speed_profile:
            amplitude = _auto_tune_amplitude_for_speed(speed, half_span, options)
            first_direction = -1.0 if previous >= center else 1.0
            for direction in (first_direction, -first_direction):
                target = _clamp(previous + (direction * amplitude), lower, upper)
                if abs(target - previous) < min(0.2, amplitude * 0.25):
                    target = _clamp(center + (direction * amplitude), lower, upper)
                plan.append(
                    {
                        "cycle": float(cycle_index + 1),
                        "start_deg": round(previous, 3),
                        "target_deg": round(target, 3),
                        "speed_deg_per_sec": round(speed, 4),
                        "amplitude_deg": round(amplitude, 3),
                        "lower_limit_deg": round(lower, 3),
                        "upper_limit_deg": round(upper, 3),
                    }
                )
                previous = target
    return plan


def _auto_tune_current_position_for_range(label: str, current_deg: float, lower: float, upper: float) -> float:
    if lower <= current_deg <= upper:
        return current_deg
    if label == "Azimuth" and lower < 0.0 < upper:
        signed_current = _normalize_signed_degrees(current_deg)
        if lower <= signed_current <= upper:
            return signed_current
    raise ValueError(
        f"{label} auto tune current position {current_deg:.3f} Deg is outside configured sweep range "
        f"{lower:.3f} to {upper:.3f} Deg. Move the axis into range or set a range around the current position."
    )


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _auto_tune_speed_profile(options: dict[str, Any]) -> list[float]:
    single_speed = _finite_float(options.get("speed_deg_per_sec"))
    min_speed = _finite_float(options.get("min_speed_deg_per_sec"))
    max_speed = _finite_float(options.get("max_speed_deg_per_sec"))
    if min_speed is None and max_speed is None and single_speed is not None:
        min_speed = max(0.1, min(single_speed, 1.0))
        max_speed = single_speed
    min_speed = 0.1 if min_speed is None else min(SAFE_MAX_SLEW_RATE_DEG_PER_SEC, max(0.001, min_speed))
    max_speed = SAFE_MAX_SLEW_RATE_DEG_PER_SEC if max_speed is None else min(
        SAFE_MAX_SLEW_RATE_DEG_PER_SEC,
        max(min_speed, max_speed),
    )
    base = [0.1, 0.3, 1.0, 3.0, 10.0, SAFE_MAX_SLEW_RATE_DEG_PER_SEC]
    speeds = [min_speed, max_speed]
    speeds.extend(speed for speed in base if min_speed <= speed <= max_speed)
    return sorted({round(speed, 4) for speed in speeds if speed > 0})


def _auto_tune_amplitude_for_speed(speed_deg_per_sec: float, half_span: float, options: dict[str, Any] | None = None) -> float:
    options = options or {}
    min_travel = _finite_float(options.get("min_travel_deg"))
    min_travel = 0.45 if min_travel is None else max(0.0, min_travel)
    if speed_deg_per_sec <= 0.3:
        return min(half_span, max(min_travel, speed_deg_per_sec * 15.0))
    elif speed_deg_per_sec <= 1.0:
        return min(half_span, max(min_travel, 1.5, speed_deg_per_sec * 8.0))
    elif speed_deg_per_sec <= 3.0:
        ratio = 0.32
    elif speed_deg_per_sec <= 10.0:
        ratio = 0.48
    else:
        ratio = 0.72
    return max(min(half_span * ratio, half_span), min(half_span, max(min_travel, 2.0)))


def _auto_tune_move_timeout(targets: list[float], speed_deg_per_sec: float | None) -> float:
    if speed_deg_per_sec is None or speed_deg_per_sec <= 0 or len(targets) < 2:
        return min(AUTO_TUNE_MAX_MOVE_TIMEOUT_SEC, AUTO_TUNE_MOVE_TIMEOUT_SEC * AUTO_TUNE_TIMEOUT_MARGIN)
    longest_move = max(abs(next_target - target) for target, next_target in zip(targets, targets[1:]))
    travel_sec = longest_move / speed_deg_per_sec
    if speed_deg_per_sec <= 0.3:
        return min(AUTO_TUNE_MAX_MOVE_TIMEOUT_SEC, max(45.0, travel_sec * 1.35 + 20.0) * AUTO_TUNE_TIMEOUT_MARGIN)
    if speed_deg_per_sec <= 1.0:
        return min(AUTO_TUNE_MAX_MOVE_TIMEOUT_SEC, max(28.0, travel_sec * 1.45 + 12.0) * AUTO_TUNE_TIMEOUT_MARGIN)
    return min(AUTO_TUNE_MAX_MOVE_TIMEOUT_SEC, max(AUTO_TUNE_MOVE_TIMEOUT_SEC, travel_sec * 1.8 + 6.0) * AUTO_TUNE_TIMEOUT_MARGIN)


def _auto_tune_stall_check_sec(speed_deg_per_sec: float | None) -> float:
    if speed_deg_per_sec is None:
        return AUTO_TUNE_STALL_CHECK_SEC
    if speed_deg_per_sec <= 0.3:
        return 12.0
    if speed_deg_per_sec <= 1.0:
        return 8.0
    return AUTO_TUNE_STALL_CHECK_SEC


def _auto_tune_settle_position_deg(options: dict[str, Any] | None) -> float:
    value = _finite_float((options or {}).get("settle_position_deg"))
    return AUTO_TUNE_SETTLE_POSITION_DEG if value is None else max(0.001, value)


def _auto_tune_settle_velocity_deg_per_sec(options: dict[str, Any] | None) -> float:
    value = _finite_float((options or {}).get("settle_velocity_deg_per_sec"))
    return AUTO_TUNE_SETTLE_VELOCITY_DEG_PER_SEC if value is None else max(0.001, value)


def _auto_tune_min_step_time_sec(options: dict[str, Any] | None) -> float:
    value = _finite_float((options or {}).get("min_step_time_sec"))
    return 0.0 if value is None else max(0.0, value)


def _run_auto_tune_move(
    label: str,
    axis: Any,
    target_deg: float,
    move_index: int,
    candidate_name: str,
    move_timeout_sec: float = AUTO_TUNE_MOVE_TIMEOUT_SEC,
    stop_event: Event | None = None,
    speed_deg_per_sec: float | None = None,
    telemetry_callback: Any | None = None,
    options: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    controller = axis.controller
    controller.input_vel = 0.0
    controller.input_torque = 0.0
    controller.config.input_mode = INPUT_MODE_TRAP_TRAJ
    controller.input_pos = _axis_display_degrees_to_encoder_turns(label, target_deg)
    started = monotonic()
    settle_started: float | None = None
    samples: list[dict[str, Any]] = []
    start_deg = _axis_current_display_deg(label, axis)
    stalled = False
    timeout_reached = False
    stall_check_sec = _auto_tune_stall_check_sec(speed_deg_per_sec)
    settle_position_deg = _auto_tune_settle_position_deg(options)
    settle_velocity_deg_per_sec = _auto_tune_settle_velocity_deg_per_sec(options)
    min_step_time_sec = _auto_tune_min_step_time_sec(options)
    previous_position = start_deg
    previous_elapsed = 0.0
    position_velocity = 0.0
    while True:
        _raise_if_auto_tune_stopped(axis, stop_event)
        elapsed = monotonic() - started
        position = _axis_current_display_deg(label, axis)
        velocity = (_get_path_float(axis, "vel_estimate") or 0.0) * 360.0
        dt = elapsed - previous_elapsed
        if dt > 0:
            position_velocity = _axis_position_delta_deg(label, position, previous_position) / dt
        previous_position = position
        previous_elapsed = elapsed
        error = _axis_position_delta_deg(label, target_deg, position)
        sample = {
            "candidate": candidate_name,
            "move_index": move_index,
            "target_deg": target_deg,
            "command_speed_deg_s": speed_deg_per_sec,
            "t": round(elapsed, 3),
            "pos_deg": position,
            "vel_deg_s": velocity,
            "pos_velocity_deg_s": position_velocity,
            "error_deg": error,
            "state": int(_get_path_float(axis, "current_state") or 0),
            "active_errors": int(_get_path_float(axis, "active_errors") or 0),
            "disarm_reason": int(_get_path_float(axis, "disarm_reason") or 0),
            "iq_measured": _get_path_float(axis, "motor.foc.Iq_measured") or 0.0,
            "torque": _get_path_float(axis, "controller.effective_torque_setpoint") or 0.0,
            "pos_setpoint_deg": _axis_turns_to_display_degrees(
                label,
                _get_path_float(axis, "controller.pos_setpoint") or 0.0,
            ),
        }
        samples.append(sample)
        if telemetry_callback:
            telemetry_callback()
        if sample["active_errors"] or sample["state"] != AXIS_STATE_CLOSED_LOOP_CONTROL:
            break
        moved_delta = abs(_axis_position_delta_deg(label, position, start_deg))
        if (
            elapsed >= stall_check_sec
            and moved_delta < AUTO_TUNE_STALL_MIN_DELTA_DEG
            and abs(position_velocity) < AUTO_TUNE_STALL_MIN_VELOCITY_DEG_PER_SEC
            and abs(_axis_position_delta_deg(label, target_deg, start_deg)) > settle_position_deg
        ):
            stalled = True
            break
        settled = abs(error) <= settle_position_deg and abs(position_velocity) <= settle_velocity_deg_per_sec
        if settled and elapsed >= min_step_time_sec:
            if settle_started is None:
                settle_started = monotonic()
            if monotonic() - settle_started >= AUTO_TUNE_SETTLE_HOLD_SEC:
                break
        else:
            settle_started = None
        if elapsed >= move_timeout_sec:
            timeout_reached = True
            break
        sleep(AUTO_TUNE_SAMPLE_SEC)

    errors = [abs(sample["error_deg"]) for sample in samples]
    currents = [abs(sample["iq_measured"]) for sample in samples]
    velocities = [abs(sample["vel_deg_s"]) for sample in samples]
    position_velocities = [abs(sample["pos_velocity_deg_s"]) for sample in samples]
    final = samples[-1]
    return samples, {
        "target_deg": target_deg,
        "start_deg": start_deg,
        "end_deg": final["pos_deg"],
        "duration_sec": final["t"],
        "timeout_limit_sec": move_timeout_sec,
        "command_speed_deg_s": speed_deg_per_sec,
        "final_error_deg": final["error_deg"],
        "peak_abs_error_deg": max(errors) if errors else None,
        "rms_error_deg": math.sqrt(sum(error * error for error in errors) / len(errors)) if errors else None,
        "peak_abs_current_a": max(currents) if currents else None,
        "peak_abs_velocity_deg_s": max(velocities) if velocities else None,
        "peak_abs_position_velocity_deg_s": max(position_velocities) if position_velocities else None,
        "stalled": stalled,
        "timeout": timeout_reached,
        "settled": (
            final["t"] >= min_step_time_sec
            and abs(final["error_deg"]) <= settle_position_deg
            and abs(final["pos_velocity_deg_s"]) <= settle_velocity_deg_per_sec
        ),
        "final_position_velocity_deg_s": final["pos_velocity_deg_s"],
        "settle_position_deg": settle_position_deg,
        "settle_velocity_deg_per_sec": settle_velocity_deg_per_sec,
        "min_step_time_sec": min_step_time_sec,
        "state": final["state"],
        "active_errors": final["active_errors"],
        "disarm_reason": final["disarm_reason"],
    }


def _score_auto_tune_candidate(moves: list[dict[str, Any]], failed: bool, expected_moves: int) -> float:
    if not moves:
        return 9999.0
    final_errors = [abs(move["final_error_deg"]) for move in moves]
    durations = [move["duration_sec"] for move in moves]
    currents = [move["peak_abs_current_a"] or 0.0 for move in moves]
    velocities = [move["peak_abs_velocity_deg_s"] or 0.0 for move in moves]
    low_speed_moves = [move for move in moves if (move.get("command_speed_deg_s") or 999.0) <= 1.0]
    low_speed_errors = [abs(move["final_error_deg"]) for move in low_speed_moves]
    low_speed_unsettled = sum(1 for move in low_speed_moves if not move["settled"])
    stalled_count = sum(1 for move in moves if move.get("stalled"))
    timeout_count = sum(1 for move in moves if move.get("timeout"))
    drive_fault_count = sum(1 for move in moves if _auto_tune_move_has_drive_fault(move))
    spinout_count = sum(1 for move in moves if _auto_tune_move_has_spinout(move))
    settled_count = sum(1 for move in moves if move["settled"])
    score = (sum(final_errors) / len(final_errors)) * 8.0
    if low_speed_errors:
        score += (sum(low_speed_errors) / len(low_speed_errors)) * 18.0
        score += low_speed_unsettled * 18.0
    score += (sum(durations) / len(durations)) * 0.6
    score += max(0.0, max(currents) - 8.0) * 8.0
    score += max(0.0, max(velocities) - 120.0) * 0.6
    score += stalled_count * 120.0
    score += timeout_count * 80.0
    score += drive_fault_count * 600.0
    score += spinout_count * 2200.0
    score += (expected_moves - settled_count) * 20.0
    if failed:
        score += 200.0
    return score


def _apply_auto_tune_candidate(axis: Any, candidate: dict[str, Any]) -> None:
    _set_path_value(axis, "controller.config.control_mode", CONTROL_MODE_POSITION_CONTROL)
    _set_path_value(axis, "controller.config.input_mode", INPUT_MODE_PASSTHROUGH)
    _set_path_value(axis, "controller.config.pos_gain", float(candidate["position_gain"]))
    _set_path_value(axis, "controller.config.vel_gain", float(candidate["velocity_gain"]))
    _set_path_value(axis, "controller.config.vel_integrator_gain", float(candidate["velocity_integrator_gain"]))
    _set_path_value(axis, "controller.config.vel_integrator_limit", float(candidate["velocity_integrator_limit"]))
    _set_if_present(axis, "controller.config.vel_integrator_decay_gain", 0.0)
    _set_if_present(axis, "controller.config.input_filter_bandwidth", float(candidate["input_filter_bandwidth"]))
    if "velocity_ramp_rate" in candidate:
        _set_if_present(axis, "controller.config.vel_ramp_rate", float(candidate["velocity_ramp_rate"]) / 360.0)
    if "torque_ramp_rate" in candidate:
        _set_if_present(axis, "controller.config.torque_ramp_rate", float(candidate["torque_ramp_rate"]))
    _set_path_value(axis, "controller.config.vel_limit", float(candidate["velocity_limit"]) / 360.0)
    _set_path_value(axis, "trap_traj.config.vel_limit", float(candidate["trap_velocity_limit"]) / 360.0)
    _set_path_value(axis, "trap_traj.config.accel_limit", float(candidate["trap_accel_limit"]) / 360.0)
    _set_path_value(axis, "trap_traj.config.decel_limit", float(candidate["trap_decel_limit"]) / 360.0)


def _read_axis_tuning(axis: Any) -> dict[str, Any]:
    return {
        "position_gain": _get_path_float(axis, "controller.config.pos_gain"),
        "velocity_gain": _get_path_float(axis, "controller.config.vel_gain"),
        "velocity_integrator_gain": _get_path_float(axis, "controller.config.vel_integrator_gain"),
        "velocity_integrator_limit": _get_path_float(axis, "controller.config.vel_integrator_limit"),
        "velocity_limit": (_get_path_float(axis, "controller.config.vel_limit") or 0.0) * 360.0,
        "velocity_ramp_rate": (_get_path_float(axis, "controller.config.vel_ramp_rate") or 0.0) * 360.0,
        "torque_ramp_rate": _get_path_float(axis, "controller.config.torque_ramp_rate"),
        "spinout_electrical_power_threshold": _get_path_float(axis, "controller.config.spinout_electrical_power_threshold"),
        "spinout_mechanical_power_threshold": _get_path_float(axis, "controller.config.spinout_mechanical_power_threshold"),
        "spinout_electrical_power_bandwidth": _get_path_float(axis, "controller.config.spinout_electrical_power_bandwidth"),
        "spinout_mechanical_power_bandwidth": _get_path_float(axis, "controller.config.spinout_mechanical_power_bandwidth"),
        "trap_velocity_limit": (_get_path_float(axis, "trap_traj.config.vel_limit") or 0.0) * 360.0,
        "trap_accel_limit": (_get_path_float(axis, "trap_traj.config.accel_limit") or 0.0) * 360.0,
        "trap_decel_limit": (_get_path_float(axis, "trap_traj.config.decel_limit") or 0.0) * 360.0,
        "input_filter_bandwidth": _get_path_float(axis, "controller.config.input_filter_bandwidth"),
    }


def _axis_current_display_deg(label: str, axis: Any) -> float:
    turns = _get_path_float(axis, "pos_estimate") or 0.0
    raw_position = turns * 360.0
    return _axis_display_position_deg(label, raw_position, _axis_position_offset(label), None)


def _signed_degree_delta(target: float, current: float) -> float:
    return ((target - current + 540.0) % 360.0) - 180.0


def _axis_position_delta_deg(label: str, target: float, current: float) -> float:
    if label == "Azimuth":
        return target - current
    return _signed_degree_delta(target, current)


def _axis_runtime_limits(label: str) -> tuple[float | None, float | None]:
    limits = _load_app_settings().get("motion_limits", {})
    if label == "Azimuth":
        return (
            _finite_float(limits.get("azimuth_ccw_limit_deg")),
            _finite_float(limits.get("azimuth_cw_limit_deg")),
        )
    if label == "Altitude":
        return (
            _finite_float(limits.get("altitude_lower_limit_deg")),
            _finite_float(limits.get("altitude_upper_limit_deg")),
        )
    return (None, None)


def _sine_positive_direction_probability(
    position: float | None,
    lower: float | None,
    upper: float | None,
) -> float:
    if position is None or lower is None or upper is None or upper <= lower:
        return 0.5
    center = (lower + upper) / 2.0
    half_span = (upper - lower) / 2.0
    normalized = _clamp((position - center) / half_span, -1.0, 1.0)
    edge_amount = max(0.0, (abs(normalized) - SINE_LIMIT_BIAS_START_RATIO) / (1.0 - SINE_LIMIT_BIAS_START_RATIO))
    return_probability = 0.5 + edge_amount * (SINE_LIMIT_MAX_RETURN_PROBABILITY - 0.5)
    return return_probability if normalized < 0.0 else 1.0 - return_probability


def _choose_sine_direction(
    position: float | None,
    lower: float | None,
    upper: float | None,
    previous_direction: float,
    same_direction_count: int,
    random_value: float | None = None,
) -> tuple[float, float]:
    positive_probability = _sine_positive_direction_probability(position, lower, upper)
    if same_direction_count >= SINE_MAX_SAME_DIRECTION_HALF_CYCLES:
        return (-1.0 if previous_direction > 0.0 else 1.0), positive_probability
    draw = random.random() if random_value is None else random_value
    return (1.0 if draw < positive_probability else -1.0), positive_probability


def _axis_status_display_position_deg(
    axis_status: Any,
    unwrap_state: dict[str, dict[str, float]],
    azimuth_sensors: dict[str, Any] | None = None,
) -> float:
    label = getattr(axis_status, "label", "")
    position = float(getattr(axis_status, "position_deg", 0.0))
    offset = _axis_position_offset(label)
    if label == "Azimuth":
        position *= _axis_position_scale(label)
        return _axis_unwrapped_display_position_deg(
            label,
            position,
            offset,
            unwrap_state,
            azimuth_sensors,
        )
    return _axis_display_position_deg(label, position, offset, None)


def _resolve_azimuth_target_deg(
    requested_target_deg: float,
    current_unwrapped_deg: float,
    lower_limit_deg: float | None,
    upper_limit_deg: float | None,
) -> float:
    """Choose the shortest equivalent Azimuth target inside software limits."""
    target = float(requested_target_deg)
    current = float(current_unwrapped_deg)
    lower = -math.inf if lower_limit_deg is None else float(lower_limit_deg)
    upper = math.inf if upper_limit_deg is None else float(upper_limit_deg)

    # Check enough neighbouring revolutions to cover configured multi-turn
    # limits, while keeping an unbounded side finite for calculation.
    minimum_k = math.ceil((lower - target) / 360.0) if math.isfinite(lower) else math.floor((current - target) / 360.0) - 2
    maximum_k = math.floor((upper - target) / 360.0) if math.isfinite(upper) else math.ceil((current - target) / 360.0) + 2
    candidates = [
        target + (360.0 * k)
        for k in range(minimum_k, maximum_k + 1)
        if lower - 1e-9 <= target + (360.0 * k) <= upper + 1e-9
    ]
    if not candidates:
        raise ValueError(
            f"Azimuth target {requested_target_deg:g} Deg has no equivalent path inside "
            f"software limits {lower_limit_deg} to {upper_limit_deg} Deg."
        )
    return min(candidates, key=lambda candidate: (abs(candidate - current), abs(candidate - target)))


def _software_position_gain(label: str) -> float:
    settings = _load_app_settings().get("tuning_steps", {})
    axis_settings = settings.get(label) if isinstance(settings, dict) else None
    value = axis_settings.get("position_gain") if isinstance(axis_settings, dict) else None
    gain = _finite_float(value)
    if gain is None or gain <= 0.0:
        return SOFTWARE_POSITION_DEFAULT_GAIN
    return gain


def _save_software_position_gain(label: str, gain: float) -> None:
    if gain <= 0.0 or not math.isfinite(gain):
        raise ValueError(f"{label} Position Gain must be greater than 0.")
    settings = _load_app_settings()
    tuning_steps = settings.setdefault("tuning_steps", {"Azimuth": {}, "Altitude": {}})
    axis_settings = tuning_steps.setdefault(label, {})
    axis_settings["position_gain"] = gain
    with APP_SETTINGS_PATH.open("w", encoding="utf-8") as file:
        json.dump(settings, file, indent=2, sort_keys=True)
        file.write("\n")
    global _SETTINGS_CACHE, _SETTINGS_MTIME
    _SETTINGS_CACHE = settings
    _SETTINGS_MTIME = APP_SETTINGS_PATH.stat().st_mtime


def _save_command_velocity_limit(limit_deg_per_sec: float) -> None:
    if not math.isfinite(limit_deg_per_sec) or limit_deg_per_sec <= 0.0:
        return
    settings = _load_app_settings()
    motion_limits = settings.setdefault("motion_limits", {})
    if math.isclose(float(motion_limits.get("slew_rate_deg_per_sec") or 0.0), limit_deg_per_sec, abs_tol=1e-9):
        return
    motion_limits["slew_rate_deg_per_sec"] = limit_deg_per_sec
    with APP_SETTINGS_PATH.open("w", encoding="utf-8") as file:
        json.dump(settings, file, indent=2, sort_keys=True)
        file.write("\n")
    global _SETTINGS_CACHE, _SETTINGS_MTIME
    _SETTINGS_CACHE = settings
    _SETTINGS_MTIME = APP_SETTINGS_PATH.stat().st_mtime


def _software_position_timeout_sec(
    positions_deg: dict[str, float],
    start_positions_deg: dict[str, float],
    max_speed_deg_per_sec: float,
) -> float:
    longest_move_sec = 0.0
    speed = max(abs(max_speed_deg_per_sec), 0.1)
    for label, target in positions_deg.items():
        start = start_positions_deg.get(label)
        if start is None:
            continue
        distance = abs(_axis_position_delta_deg(label, target, start))
        gain = max(_software_position_gain(label), 1e-6)

        # The software position loop does not run at ``speed`` for the whole
        # move. Its P controller commands min(speed, gain * error), so it
        # deliberately slows down as it approaches the target. A timeout based
        # only on distance / speed cuts off medium and long moves during that
        # final approach (for example, a 55 degree move at 10 deg/s and gain
        # 0.5 needs about 14.5 seconds, not 5.5 seconds).
        proportional_start_error = min(distance, speed / gain)
        full_speed_sec = max(0.0, distance - proportional_start_error) / speed
        proportional_sec = 0.0
        if proportional_start_error > SOFTWARE_POSITION_TOLERANCE_DEG:
            proportional_sec = math.log(
                proportional_start_error / SOFTWARE_POSITION_TOLERANCE_DEG
            ) / gain
        estimated_move_sec = full_speed_sec + proportional_sec
        longest_move_sec = max(longest_move_sec, estimated_move_sec)
    return max(
        SOFTWARE_POSITION_MIN_TIMEOUT_SEC,
        longest_move_sec * SOFTWARE_POSITION_TIMEOUT_MULTIPLIER,
    )


def _clear_device_errors(device: Any) -> None:
    try:
        device.clear_errors()
    except Exception:
        pass


def _stop_and_disable_devices(devices: tuple[Any, ...]) -> None:
    for device in devices[:2]:
        if device is None:
            continue
        _hold_axis_at_current_position(getattr(device, "axis0"))
    sleep(0.05)
    for device in devices[:2]:
        if device is None:
            continue
        getattr(device, "axis0").requested_state = AXIS_STATE_IDLE
    sleep(0.15)


def _hold_axis_at_limit(axis: Any, label: str, limit_deg: float) -> None:
    _configure_position_control(axis)
    _set_if_present(axis, "controller.input_vel", 0.0)
    _set_if_present(axis, "controller.input_pos", _axis_command_degrees_to_turns(axis, label, limit_deg))


def _stop_axis_at_runtime_limit(axis: Any, label: str, limit_deg: float) -> None:
    if _get_path_int(axis, "controller.config.control_mode") == CONTROL_MODE_VELOCITY_CONTROL:
        _set_if_present(axis, "controller.input_vel", 0.0)
        _set_if_present(axis, "controller.input_torque", 0.0)
        return
    _hold_axis_at_limit(axis, label, limit_deg)


def _slow_axis_near_runtime_limit(axis: Any, axis_status: Any, position: float, lower: float | None, upper: float | None) -> None:
    if _get_path_int(axis, "controller.config.control_mode") != CONTROL_MODE_VELOCITY_CONTROL:
        return
    velocity = _finite_float(getattr(axis_status, "input_vel", None))
    if velocity is None:
        return
    label = str(getattr(axis_status, "label", ""))
    velocity *= _axis_position_scale(label)
    limited_velocity = _axis_velocity_limited_by_runtime_limits(position, velocity, lower, upper)
    if math.isclose(limited_velocity, velocity, abs_tol=1e-6):
        return
    _set_if_present(axis, "controller.input_vel", _axis_display_velocity_to_encoder_turns(label, limited_velocity))


def _configure_position_control(axis: Any, input_mode: int = INPUT_MODE_PASSTHROUGH, required: bool = False) -> None:
    setter = _set_required if required else _set_if_present
    setter(axis, "controller.config.control_mode", CONTROL_MODE_POSITION_CONTROL)
    setter(axis, "controller.config.input_mode", input_mode)


def _configure_velocity_control(axis: Any) -> None:
    # The telemetry owner already knows the cached mode. If a transition is
    # required, write the desired values directly instead of issuing extra USB
    # reads from a command path.
    _set_if_present(axis, "controller.config.control_mode", CONTROL_MODE_VELOCITY_CONTROL)
    _set_if_present(axis, "controller.config.input_mode", INPUT_MODE_VEL_RAMP)


def _hold_axis_at_current_position(axis: Any) -> None:
    _set_if_present(axis, "controller.input_vel", 0.0)
    _set_if_present(axis, "controller.input_torque", 0.0)
    position = _get_path_float(axis, "pos_estimate")
    if position is None:
        position = _get_path_float(axis, "pos_vel_mapper.pos_rel")
    if position is not None:
        _configure_position_control(axis)
        _set_if_present(axis, "controller.input_pos", position)


def _read_azimuth_sensors() -> dict[str, Any]:
    settings = _load_app_settings().get("azimuth_sensors", {})
    ccw = _read_sensor_pin(
        settings.get("ccw_pin"),
        bool(settings.get("ccw_active_high", True)),
        str(settings.get("ccw_pull", "none")),
    )
    cw = _read_sensor_pin(
        settings.get("cw_pin"),
        bool(settings.get("cw_active_high", True)),
        str(settings.get("cw_pull", "none")),
    )
    return {
        "ccw_sensor": ccw["active"],
        "ccw_raw_level": ccw["raw_level"],
        "ccw_error": ccw["error"],
        "cw_sensor": cw["active"],
        "cw_raw_level": cw["raw_level"],
        "cw_error": cw["error"],
        "ccw_pin": settings.get("ccw_pin"),
        "cw_pin": settings.get("cw_pin"),
        "ccw_pull": settings.get("ccw_pull", "none"),
        "cw_pull": settings.get("cw_pull", "none"),
    }


def _read_sensor_pin(pin: int | None, active_high: bool, pull: str) -> dict[str, Any]:
    if pin is None:
        return {"active": False, "raw_level": None, "error": "No GPIO pin configured."}
    with _GPIO_LOCK:
        gpio = _get_gpio()
        if gpio is None:
            return {"active": False, "raw_level": None, "error": "RPi.GPIO is unavailable."}
        try:
            _ensure_gpio_input(gpio, pin, pull)
            try:
                level = bool(gpio.input(pin))
            except Exception:
                _GPIO_CONFIGURED_INPUTS.pop(pin, None)
                _ensure_gpio_input(gpio, pin, pull)
                level = bool(gpio.input(pin))
        except Exception as exc:
            return {"active": False, "raw_level": None, "error": str(exc)}
    return {"active": level if active_high else not level, "raw_level": level, "error": None}


def _ensure_gpio_input(gpio: Any, pin: int, pull: str) -> None:
    configured_pull = _GPIO_CONFIGURED_INPUTS.get(pin)
    if configured_pull == pull:
        return

    pull_modes = {
        "none": getattr(gpio, "PUD_OFF", 0),
        "up": getattr(gpio, "PUD_UP", 0),
        "down": getattr(gpio, "PUD_DOWN", 0),
    }
    gpio.setup(pin, gpio.IN, pull_up_down=pull_modes.get(pull, pull_modes["none"]))
    _GPIO_CONFIGURED_INPUTS[pin] = pull


def _get_gpio() -> Any | None:
    global _GPIO
    if _GPIO is not None:
        return _GPIO
    if SYSTEM_DIST_PACKAGES not in sys.path:
        sys.path.append(SYSTEM_DIST_PACKAGES)
    try:
        import RPi.GPIO as gpio
    except Exception:
        return None
    try:
        gpio.setwarnings(False)
        gpio.setmode(gpio.BCM)
    except Exception:
        return None
    _GPIO = gpio
    return _GPIO


def _set_path_value(obj: Any, path: str, value: float) -> None:
    parts = path.split(".")
    target = obj
    for part in parts[:-1]:
        target = getattr(target, part)
    setattr(target, parts[-1], value)


def _set_if_present(obj: Any, path: str, value: float) -> None:
    try:
        _set_path_value(obj, path, value)
    except Exception:
        return


def _set_required(obj: Any, path: str, value: float) -> None:
    try:
        _set_path_value(obj, path, value)
    except Exception as exc:
        raise ODriveConnectionError(f"Could not set {path}: {exc}") from exc


def _verify_axis_target(axis: Any, label: str, target_turns: float) -> None:
    actual_turns = _get_path_float(axis, "controller.input_pos")
    if actual_turns is None:
        return
    if math.isclose(actual_turns, target_turns, abs_tol=1e-4):
        return
    actual_deg = _axis_turns_to_display_degrees(label, actual_turns)
    target_deg = _axis_turns_to_display_degrees(label, target_turns)
    raise ODriveConnectionError(
        f"{label} drive did not accept target position "
        f"({target_deg:.3f} Deg requested, {actual_deg:.3f} Deg active)."
    )


def _axis_turns_to_display_degrees(label: str, turns: float) -> float:
    return _axis_display_position_deg(label, turns * 360.0, _axis_position_offset(label), None)


def _get_path_float(obj: Any, path: str) -> float | None:
    target = obj
    try:
        for part in path.split("."):
            target = getattr(target, part)
        value = float(target)
    except Exception:
        return None
    if not math.isfinite(value):
        return None
    return value


def _get_path_int(obj: Any, path: str) -> int | None:
    target = obj
    try:
        for part in path.split("."):
            target = getattr(target, part)
        return int(target)
    except Exception:
        return None


def _get_path_bool(obj: Any, path: str) -> bool | None:
    target = obj
    try:
        for part in path.split("."):
            target = getattr(target, part)
        return bool(target)
    except Exception:
        return None


def _health_label(has_bus_power: bool, has_axis_errors: bool) -> str:
    if has_axis_errors:
        return "attention"
    if not has_bus_power:
        return "usb-only"
    return "ready"


def _run_update_check_soon() -> None:
    if not UPDATER_SCRIPT_PATH.exists():
        _write_update_state("failed", "Updater script is missing.")
        return
    _write_update_state("queued", "Update check queued.")
    try:
        subprocess.run(
            [sys.executable, str(UPDATER_SCRIPT_PATH), "--once", "--force"],
            cwd=PROJECT_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=420,
            check=False,
        )
    except Exception as exc:
        _write_update_state("failed", f"Could not run updater: {exc}")


def _system_info_payload() -> dict[str, Any]:
    settings = _load_app_settings()
    updater = settings.get("updater", {})
    return {
        "firmware_version": _firmware_version(),
        "commit_sha": _git_output("rev-parse", "HEAD"),
        "branch": _git_output("branch", "--show-current"),
        "remote_url": _git_output("remote", "get-url", "origin"),
        "device_id": updater.get("device_id") or _default_device_id(),
        "update_check_interval_minutes": updater.get("check_interval_minutes", DEFAULT_UPDATE_INTERVAL_MINUTES),
        "update_channel": updater.get("channel") or "main",
        "auto_update_enabled": updater.get("enabled", True),
        "update_state": _load_update_state(),
        "server_started_at": _server_started_at(),
    }


def _firmware_version() -> str:
    return _git_output("describe", "--tags", "--always", "--dirty") or "unknown"


def _git_output(*args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=PROJECT_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _load_update_state() -> dict[str, Any]:
    if not UPDATE_STATE_PATH.exists():
        return {}
    try:
        with UPDATE_STATE_PATH.open("r", encoding="utf-8") as file:
            state = json.load(file)
    except (OSError, json.JSONDecodeError):
        return {}
    return state if isinstance(state, dict) else {}


def _write_update_state(status: str, message: str) -> None:
    state = _load_update_state()
    state.update({"status": status, "message": message, "checked_at": datetime.now().astimezone().isoformat(timespec="seconds")})
    try:
        with UPDATE_STATE_PATH.open("w", encoding="utf-8") as file:
            json.dump(state, file, indent=2, sort_keys=True)
            file.write("\n")
    except OSError:
        return


def _pointing_model_raster_payload(resolution_m: float) -> dict[str, Any]:
    global _POINTING_RASTER_CACHE
    cache_key = _pointing_cache_key(resolution_m)
    if _POINTING_RASTER_CACHE is not None and _POINTING_RASTER_CACHE.get("key") == cache_key["digest"]:
        return _POINTING_RASTER_CACHE["payload"]
    cached_payload = _load_pointing_raster_payload(cache_key["digest"])
    if cached_payload is not None:
        _POINTING_RASTER_CACHE = {"key": cache_key["digest"], "payload": cached_payload}
        return cached_payload

    dem = _load_dem()
    station = _pointing_station(dem)
    radius_m = POINTING_RADIUS_KM * 1000.0
    size = int(math.ceil((radius_m * 2.0) / resolution_m))
    station_ground_elevation = _dem_elevation_at(station["latitude"], station["longitude"], dem)
    station_device_elevation = _station_device_elevation(station_ground_elevation, station)
    elevations: list[float | None] = [None] * (size * size)
    visibility: list[bool | None] = [None] * (size * size)
    sightline_cells: list[dict[str, float | int]] = []
    elevation_min: float | None = None
    elevation_max: float | None = None

    for row in range(size):
        north_m = radius_m - (row + 0.5) * resolution_m
        for col in range(size):
            east_m = (col + 0.5) * resolution_m - radius_m
            if math.hypot(east_m, north_m) > radius_m:
                continue
            lat, lon = _offset_lat_lon(station["latitude"], station["longitude"], east_m, north_m)
            elevation = _dem_elevation_at(lat, lon, dem)
            if elevation is None:
                continue
            index = row * size + col
            rounded = round(elevation, 1)
            elevations[index] = rounded
            elevation_min = rounded if elevation_min is None else min(elevation_min, rounded)
            elevation_max = rounded if elevation_max is None else max(elevation_max, rounded)
            distance_m = math.hypot(east_m, north_m)
            if station_device_elevation is not None:
                sightline_cells.append(
                    {
                        "index": index,
                        "azimuth": (math.degrees(math.atan2(east_m, north_m)) + 360.0) % 360.0,
                        "distance_m": distance_m,
                        "angle_deg": _sightline_angle_deg(elevation, station_device_elevation, distance_m),
                    }
                )

    if station_device_elevation is not None:
        visibility = _viewshed_visibility(visibility, sightline_cells, size)

    raster_sources = _write_pointing_raster_pngs(
        elevations,
        visibility,
        size,
        elevation_min,
        elevation_max,
        cache_key["digest"],
    )
    imagery_src = _arcgis_imagery_src(station, size, resolution_m, cache_key["digest"])
    payload = {
        "ok": True,
        "cached": False,
        "radius_km": POINTING_RADIUS_KM,
        "grid_size": size,
        "grid_resolution_m": round(resolution_m, 3),
        "grid_orientation": {
            "crs": "local-east-north",
            "north_up": True,
            "row_direction": "south",
            "column_direction": "east",
            "device_azimuth_for_true_north_deg": station["azimuth_north_offset_deg"],
        },
        "curvature": {
            "enabled": True,
            "refraction_coefficient": ATMOSPHERIC_REFRACTION_COEFFICIENT,
            "drop_at_radius_m": round(_earth_curvature_drop_m(radius_m), 2),
        },
        "station": {
            **station,
            "ground_elevation_m": None if station_ground_elevation is None else round(station_ground_elevation, 1),
            "elevation_m": None if station_device_elevation is None else round(station_device_elevation, 1),
        },
        "dem": {
            "available": True,
            "path": str(DEM_PATH.relative_to(PROJECT_ROOT)),
            "width": dem["width"],
            "height": dem["height"],
            "bounds": dem["bounds"],
            "elevation_min_m": elevation_min,
            "elevation_max_m": elevation_max,
        },
        "raster": {
            "src": raster_sources["terrain"],
            "terrain_src": raster_sources["terrain"],
            "visibility_src": raster_sources["visibility"],
            "satellite_src": imagery_src,
            "height_src": raster_sources["height"],
            "height_width": raster_sources["height_width"],
            "height_height": raster_sources["height_height"],
            "elevation_min_m": elevation_min,
            "elevation_max_m": elevation_max,
            "width_m": round(radius_m * 2.0, 3),
            "depth_m": round(radius_m * 2.0, 3),
            "width": size,
            "height": size,
        },
        "imagery": {
            "available": imagery_src is not None,
            "source": "ArcGIS World Imagery",
            "attribution": "Tiles © Esri and imagery providers",
        },
    }
    _save_pointing_raster_payload(cache_key["digest"], payload)
    _POINTING_RASTER_CACHE = {"key": cache_key["digest"], "payload": payload}
    return payload


def _pointing_cache_key(resolution_m: float) -> dict[str, Any]:
    app_stat = APP_SETTINGS_PATH.stat() if APP_SETTINGS_PATH.exists() else None
    dem_stat = DEM_PATH.stat() if DEM_PATH.exists() else None
    payload = {
        "version": 6,
        "resolution_m": round(resolution_m, 3),
        "radius_km": POINTING_RADIUS_KM,
        "refraction_coefficient": ATMOSPHERIC_REFRACTION_COEFFICIENT,
        "settings_mtime": app_stat.st_mtime if app_stat else 0.0,
        "settings_size": app_stat.st_size if app_stat else 0,
        "dem_mtime": dem_stat.st_mtime if dem_stat else 0.0,
        "dem_size": dem_stat.st_size if dem_stat else 0,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    payload["digest"] = hashlib.sha256(encoded).hexdigest()[:20]
    return payload


def _pointing_cache_paths(digest: str) -> tuple[Path, Path]:
    return POINTING_CACHE_DIR / f"pointing_{digest}.png", POINTING_CACHE_DIR / f"pointing_{digest}.json"


def _load_pointing_raster_payload(digest: str) -> dict[str, Any] | None:
    image_path, metadata_path = _pointing_cache_paths(digest)
    if not image_path.exists() or not metadata_path.exists():
        return None
    try:
        with metadata_path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    payload["cached"] = True
    raster = payload.setdefault("raster", {})
    raster.setdefault("terrain_src", f"/api/pointing/cache/{image_path.name}")
    raster.setdefault("src", raster["terrain_src"])
    visibility_path = POINTING_CACHE_DIR / f"pointing_{digest}_visibility.png"
    satellite_path = POINTING_CACHE_DIR / f"pointing_{digest}_satellite.png"
    height_path = POINTING_CACHE_DIR / f"pointing_{digest}_height.png"
    if visibility_path.exists():
        raster["visibility_src"] = f"/api/pointing/cache/{visibility_path.name}"
    if satellite_path.exists():
        raster["satellite_src"] = f"/api/pointing/cache/{satellite_path.name}"
        payload.setdefault("imagery", {})["available"] = True
    if height_path.exists():
        raster["height_src"] = f"/api/pointing/cache/{height_path.name}"
    return payload


def _save_pointing_raster_payload(digest: str, payload: dict[str, Any]) -> None:
    _, metadata_path = _pointing_cache_paths(digest)
    POINTING_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    disk_payload = dict(payload)
    disk_payload["cached"] = True
    try:
        with metadata_path.open("w", encoding="utf-8") as file:
            json.dump(disk_payload, file, indent=2, sort_keys=True)
            file.write("\n")
    except OSError:
        return


def _write_pointing_raster_pngs(
    elevations: list[float | None],
    visibility: list[bool | None],
    size: int,
    elevation_min: float | None,
    elevation_max: float | None,
    digest: str,
) -> dict[str, Any]:
    from PIL import Image

    POINTING_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    terrain_path, _ = _pointing_cache_paths(digest)
    visibility_path = POINTING_CACHE_DIR / f"pointing_{digest}_visibility.png"
    height_path = POINTING_CACHE_DIR / f"pointing_{digest}_height.png"
    terrain_image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    visibility_image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    height_source = Image.new("L", (size, size), 0)
    terrain_pixels = terrain_image.load()
    visibility_pixels = visibility_image.load()
    height_pixels = height_source.load()
    elevation_range = max(0.001, (elevation_max or 0.0) - (elevation_min or 0.0))
    for index, elevation in enumerate(elevations):
        if elevation is None:
            continue
        row, col = divmod(index, size)
        terrain_pixels[col, row] = _terrain_rgba(elevation, elevation_min, elevation_max)
        height_pixels[col, row] = round(max(0.0, min(1.0, (elevation - (elevation_min or 0.0)) / elevation_range)) * 255.0)
        visible = visibility[index]
        if visible is True:
            visibility_pixels[col, row] = (128, 245, 162, 82)
        elif visible is False:
            visibility_pixels[col, row] = (2, 10, 12, 168)
    terrain_image.save(terrain_path, format="PNG")
    visibility_image.save(visibility_path, format="PNG")
    height_size = min(384, size)
    height_image = height_source.resize((height_size, height_size), resample=Image.Resampling.BILINEAR)
    height_image.save(height_path, format="PNG")
    return {
        "terrain": f"/api/pointing/cache/{terrain_path.name}",
        "visibility": f"/api/pointing/cache/{visibility_path.name}",
        "height": f"/api/pointing/cache/{height_path.name}",
        "height_width": height_size,
        "height_height": height_size,
    }


def _terrain_rgba(elevation: float, elevation_min: float | None, elevation_max: float | None) -> tuple[int, int, int, int]:
    if elevation_min is None or elevation_max is None or elevation_min == elevation_max:
        return (55, 111, 104, 255)
    ratio = max(0.0, min(1.0, (elevation - elevation_min) / (elevation_max - elevation_min)))
    stops = (
        (30, 83, 79),
        (63, 139, 91),
        (169, 146, 83),
        (142, 104, 87),
        (226, 222, 205),
    )
    scaled = ratio * (len(stops) - 1)
    index = min(len(stops) - 2, int(math.floor(scaled)))
    amount = scaled - index
    color = tuple(round(stops[index][channel] + (stops[index + 1][channel] - stops[index][channel]) * amount) for channel in range(3))
    return (color[0], color[1], color[2], 255)


def _blend_rgba(base: tuple[int, int, int, int], overlay: tuple[int, int, int, int], alpha: float) -> tuple[int, int, int, int]:
    return (
        round(base[0] * (1.0 - alpha) + overlay[0] * alpha),
        round(base[1] * (1.0 - alpha) + overlay[1] * alpha),
        round(base[2] * (1.0 - alpha) + overlay[2] * alpha),
        base[3],
    )


def _arcgis_imagery_src(station: dict[str, Any], size: int, resolution_m: float, digest: str) -> str | None:
    image_path = POINTING_CACHE_DIR / f"pointing_{digest}_satellite.png"
    if image_path.exists():
        return f"/api/pointing/cache/{image_path.name}"
    try:
        bbox = _web_mercator_bbox(station["latitude"], station["longitude"], POINTING_RADIUS_KM * 1000.0)
        query = urllib.parse.urlencode(
            {
                "bbox": ",".join(f"{value:.6f}" for value in bbox),
                "bboxSR": "3857",
                "imageSR": "3857",
                "size": f"{size},{size}",
                "format": "png32",
                "transparent": "false",
                "f": "image",
            }
        )
        request_url = f"{ARCGIS_WORLD_IMAGERY_EXPORT_URL}?{query}"
        request = urllib.request.Request(request_url, headers={"User-Agent": "FireDetector/1.0"})
        with urllib.request.urlopen(request, timeout=90) as response:
            content_type = response.headers.get("Content-Type", "")
            if response.status != 200 or "image" not in content_type:
                return None
            data = response.read()
        if not data.startswith(b"\x89PNG"):
            return None
        POINTING_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        image_path.write_bytes(data)
    except Exception:
        return None
    return f"/api/pointing/cache/{image_path.name}"


def _web_mercator_bbox(latitude: float, longitude: float, radius_m: float) -> tuple[float, float, float, float]:
    earth_radius_m = 6378137.0
    clamped_latitude = max(-85.05112878, min(85.05112878, latitude))
    x = earth_radius_m * math.radians(longitude)
    y = earth_radius_m * math.log(math.tan(math.pi / 4.0 + math.radians(clamped_latitude) / 2.0))
    return (x - radius_m, y - radius_m, x + radius_m, y + radius_m)


def _pointing_model_payload(size: int) -> dict[str, Any]:
    dem = _load_dem()
    station = _pointing_station(dem)
    radius_m = POINTING_RADIUS_KM * 1000.0
    station_ground_elevation = _dem_elevation_at(station["latitude"], station["longitude"], dem)
    station_device_elevation = _station_device_elevation(station_ground_elevation, station)
    values: list[float | None] = []
    visibility: list[bool | None] = []
    sightline_cells: list[dict[str, float | int]] = []
    elevation_min: float | None = None
    elevation_max: float | None = None
    for row in range(size):
        y_ratio = 1.0 - (row + 0.5) / size
        north_m = (y_ratio * 2.0 - 1.0) * radius_m
        for col in range(size):
            x_ratio = (col + 0.5) / size
            east_m = (x_ratio * 2.0 - 1.0) * radius_m
            if math.hypot(east_m, north_m) > radius_m:
                values.append(None)
                visibility.append(None)
                continue
            lat, lon = _offset_lat_lon(station["latitude"], station["longitude"], east_m, north_m)
            elevation = _dem_elevation_at(lat, lon, dem)
            if elevation is None:
                values.append(None)
                visibility.append(None)
                continue
            rounded = round(elevation, 1)
            values.append(rounded)
            visibility.append(None)
            elevation_min = rounded if elevation_min is None else min(elevation_min, rounded)
            elevation_max = rounded if elevation_max is None else max(elevation_max, rounded)
            distance_m = math.hypot(east_m, north_m)
            if station_device_elevation is not None:
                sightline_cells.append(
                    {
                        "index": len(values) - 1,
                        "azimuth": (math.degrees(math.atan2(east_m, north_m)) + 360.0) % 360.0,
                        "distance_m": distance_m,
                        "angle_deg": _sightline_angle_deg(elevation, station_device_elevation, distance_m),
                    }
                )

    if station_device_elevation is not None:
        visibility = _viewshed_visibility(visibility, sightline_cells, size)

    return {
        "ok": True,
        "radius_km": POINTING_RADIUS_KM,
        "grid_size": size,
        "curvature": {
            "enabled": True,
            "refraction_coefficient": ATMOSPHERIC_REFRACTION_COEFFICIENT,
            "drop_at_radius_m": round(_earth_curvature_drop_m(radius_m), 2),
        },
        "station": {
            **station,
            "ground_elevation_m": None if station_ground_elevation is None else round(station_ground_elevation, 1),
            "elevation_m": None if station_device_elevation is None else round(station_device_elevation, 1),
        },
        "dem": {
            "available": True,
            "path": str(DEM_PATH.relative_to(PROJECT_ROOT)),
            "width": dem["width"],
            "height": dem["height"],
            "bounds": dem["bounds"],
            "elevation_min_m": elevation_min,
            "elevation_max_m": elevation_max,
        },
        "elevations": values,
        "visibility": visibility,
    }


def _pointing_sample(lat: float, lon: float) -> dict[str, Any]:
    dem = _load_dem()
    station = _pointing_station(dem)
    elevation = _dem_elevation_at(lat, lon, dem)
    station_ground_elevation = _dem_elevation_at(station["latitude"], station["longitude"], dem)
    station_device_elevation = _station_device_elevation(station_ground_elevation, station)
    distance_m = _haversine_m(station["latitude"], station["longitude"], lat, lon)
    azimuth_deg = None if distance_m < 1.0 else _bearing_deg(station["latitude"], station["longitude"], lat, lon)
    device_azimuth_deg = (
        None
        if azimuth_deg is None
        else (azimuth_deg + station["azimuth_north_offset_deg"]) % 360.0
    )
    altitude_deg = None
    visible = None
    blocker = None
    if elevation is not None and station_device_elevation is not None and distance_m >= 1.0:
        altitude_deg = _sightline_angle_deg(elevation, station_device_elevation, distance_m)
        visibility = _target_visibility(station, station_device_elevation, lat, lon, elevation, dem)
        visible = visibility["visible"]
        blocker = visibility["blocker"]
    return {
        "latitude": lat,
        "longitude": lon,
        "elevation_m": None if elevation is None else round(elevation, 1),
        "station_ground_elevation_m": None if station_ground_elevation is None else round(station_ground_elevation, 1),
        "station_elevation_above_ground_m": round(station["elevation_above_ground_m"], 3),
        "station_elevation_m": None if station_device_elevation is None else round(station_device_elevation, 1),
        "distance_m": round(distance_m, 1),
        "distance_km": round(distance_m / 1000.0, 3),
        "azimuth_deg": None if azimuth_deg is None else round(azimuth_deg, 3),
        "device_azimuth_deg": None if device_azimuth_deg is None else round(device_azimuth_deg, 3),
        "altitude_deg": None if altitude_deg is None else round(altitude_deg, 3),
        "visible": visible,
        "blocker": blocker,
        "inside_radius": distance_m <= POINTING_RADIUS_KM * 1000.0,
        "inside_dem": elevation is not None,
        "grid_cell": _pointing_grid_cell(lat, lon, station),
    }


def _pointing_station(dem: dict[str, Any]) -> dict[str, Any]:
    station = _load_app_settings().get("station", {})
    latitude = station.get("latitude")
    longitude = station.get("longitude")
    source = "settings"
    if not isinstance(latitude, (int, float)) or not math.isfinite(latitude):
        latitude = (dem["bounds"]["south"] + dem["bounds"]["north"]) / 2.0
        source = "dem_center"
    if not isinstance(longitude, (int, float)) or not math.isfinite(longitude):
        longitude = (dem["bounds"]["west"] + dem["bounds"]["east"]) / 2.0
        source = "dem_center"
    return {
        "name": station.get("name") or "",
        "latitude": float(latitude),
        "longitude": float(longitude),
        "elevation_above_ground_m": _station_installation_elevation(station),
        "azimuth_north_offset_deg": float(station.get("azimuth_north_offset_deg", 0.0)),
        "source": source,
    }


def _pointing_grid_cell(
    latitude: float,
    longitude: float,
    station: dict[str, Any],
    resolution_m: float = POINTING_GRID_RESOLUTION_M,
) -> dict[str, Any] | None:
    radius_m = POINTING_RADIUS_KM * 1000.0
    size = int(math.ceil((radius_m * 2.0) / resolution_m))
    north_m = math.radians(latitude - station["latitude"]) * EARTH_RADIUS_M
    east_m = (
        math.radians(longitude - station["longitude"])
        * EARTH_RADIUS_M
        * max(0.01, math.cos(math.radians(station["latitude"])))
    )
    row = int(math.floor((radius_m - north_m) / resolution_m))
    col = int(math.floor((east_m + radius_m) / resolution_m))
    if row < 0 or col < 0 or row >= size or col >= size or math.hypot(east_m, north_m) > radius_m:
        return None
    center_east_m = (col + 0.5) * resolution_m - radius_m
    center_north_m = radius_m - (row + 0.5) * resolution_m
    center_lat, center_lon = _offset_lat_lon(
        station["latitude"],
        station["longitude"],
        center_east_m,
        center_north_m,
    )
    return {
        "id": f"R{row:04d}C{col:04d}",
        "row": row,
        "column": col,
        "resolution_m": resolution_m,
        "center_latitude": round(center_lat, 7),
        "center_longitude": round(center_lon, 7),
    }


def _station_installation_elevation(station: dict[str, Any]) -> float:
    value = station.get("elevation_above_ground_m", 0.0)
    if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        return 0.0
    return float(value)


def _station_device_elevation(ground_elevation: float | None, station: dict[str, Any]) -> float | None:
    if ground_elevation is None:
        return None
    return ground_elevation + station["elevation_above_ground_m"]


def _sightline_angle_deg(target_elevation: float, station_device_elevation: float, distance_m: float) -> float:
    if distance_m < 1.0:
        return 90.0
    apparent_drop_m = _earth_curvature_drop_m(distance_m)
    return math.degrees(math.atan2(target_elevation - station_device_elevation - apparent_drop_m, distance_m))


def _earth_curvature_drop_m(distance_m: float) -> float:
    effective_radius_m = EARTH_RADIUS_M / (1.0 - ATMOSPHERIC_REFRACTION_COEFFICIENT)
    return (distance_m * distance_m) / (2.0 * effective_radius_m)


def _viewshed_visibility(
    visibility: list[bool | None],
    cells: list[dict[str, float | int]],
    grid_size: int,
) -> list[bool | None]:
    ray_count = max(720, grid_size * 6)
    rays: list[list[dict[str, float | int]]] = [[] for _ in range(ray_count)]
    for cell in cells:
        bin_index = int(float(cell["azimuth"]) / 360.0 * ray_count) % ray_count
        rays[bin_index].append(cell)
    for ray in rays:
        highest_angle: float | None = None
        for cell in sorted(ray, key=lambda item: float(item["distance_m"])):
            index = int(cell["index"])
            distance_m = float(cell["distance_m"])
            angle_deg = float(cell["angle_deg"])
            if distance_m < 1.0:
                visibility[index] = True
                highest_angle = angle_deg if highest_angle is None else max(highest_angle, angle_deg)
                continue
            is_visible = highest_angle is None or angle_deg >= highest_angle - 0.02
            visibility[index] = is_visible
            if highest_angle is None or angle_deg > highest_angle:
                highest_angle = angle_deg
    return visibility


def _target_visibility(
    station: dict[str, Any],
    station_device_elevation: float,
    target_latitude: float,
    target_longitude: float,
    target_elevation: float,
    dem: dict[str, Any],
) -> dict[str, Any]:
    target_distance_m = _haversine_m(station["latitude"], station["longitude"], target_latitude, target_longitude)
    if target_distance_m < 1.0:
        return {"visible": True, "blocker": None}
    target_angle = _sightline_angle_deg(target_elevation, station_device_elevation, target_distance_m)
    samples = max(8, min(240, int(target_distance_m / 100.0)))
    highest_angle: float | None = None
    blocker: dict[str, Any] | None = None
    for step in range(1, samples):
        ratio = step / samples
        latitude = station["latitude"] + (target_latitude - station["latitude"]) * ratio
        longitude = station["longitude"] + (target_longitude - station["longitude"]) * ratio
        elevation = _dem_elevation_at(latitude, longitude, dem)
        if elevation is None:
            continue
        distance_m = target_distance_m * ratio
        angle = _sightline_angle_deg(elevation, station_device_elevation, distance_m)
        if highest_angle is None or angle > highest_angle:
            highest_angle = angle
            blocker = {
                "latitude": round(latitude, 6),
                "longitude": round(longitude, 6),
                "distance_m": round(distance_m, 1),
                "distance_km": round(distance_m / 1000.0, 3),
                "elevation_m": round(elevation, 1),
                "altitude_deg": round(angle, 3),
            }
    visible = highest_angle is None or target_angle >= highest_angle - 0.02
    return {"visible": visible, "blocker": None if visible else blocker}


def _load_dem() -> dict[str, Any]:
    global _DEM_CACHE
    if _DEM_CACHE is not None:
        return _DEM_CACHE
    if not DEM_PATH.exists():
        raise FileNotFoundError(f"{DEM_PATH} does not exist")
    from PIL import Image

    image = Image.open(DEM_PATH)
    scale = image.tag_v2.get(33550)
    tiepoint = image.tag_v2.get(33922)
    if not scale or not tiepoint:
        raise ValueError("DEM is missing GeoTIFF scale/tiepoint tags.")
    pixel_scale_x = float(scale[0])
    pixel_scale_y = float(scale[1])
    tie_pixel_x = float(tiepoint[0])
    tie_pixel_y = float(tiepoint[1])
    tie_lon = float(tiepoint[3])
    tie_lat = float(tiepoint[4])
    width, height = image.size
    west = tie_lon - tie_pixel_x * pixel_scale_x
    north = tie_lat + tie_pixel_y * pixel_scale_y
    east = west + width * pixel_scale_x
    south = north - height * pixel_scale_y
    _DEM_CACHE = {
        "image": image,
        "width": width,
        "height": height,
        "west": west,
        "north": north,
        "pixel_scale_x": pixel_scale_x,
        "pixel_scale_y": pixel_scale_y,
        "bounds": {
            "west": west,
            "south": south,
            "east": east,
            "north": north,
        },
    }
    return _DEM_CACHE


def _reset_dem_cache() -> dict[str, Any]:
    global _DEM_CACHE
    cached = _DEM_CACHE
    _DEM_CACHE = None
    image = cached.get("image") if isinstance(cached, dict) else None
    if image is not None:
        try:
            image.close()
        except Exception:
            pass
    return _load_dem()


def _terrain_updated() -> None:
    """Drop open DEM/render caches after an atomic terrain synchronization."""
    global _DEM_CACHE, _POINTING_RASTER_CACHE
    cached = _DEM_CACHE
    _DEM_CACHE = None
    _POINTING_RASTER_CACHE = None
    image = cached.get("image") if isinstance(cached, dict) else None
    if image is not None:
        try:
            image.close()
        except Exception:
            pass


def _dem_elevation_at(latitude: float, longitude: float, dem: dict[str, Any] | None = None) -> float | None:
    dem = dem or _load_dem()
    col = (longitude - dem["west"]) / dem["pixel_scale_x"]
    row = (dem["north"] - latitude) / dem["pixel_scale_y"]
    width = int(dem["width"])
    height = int(dem["height"])
    if col < 0 or row < 0 or col > width - 1 or row > height - 1:
        return None
    col0 = int(math.floor(col))
    row0 = int(math.floor(row))
    col1 = min(col0 + 1, width - 1)
    row1 = min(row0 + 1, height - 1)
    x = col - col0
    y = row - row0
    def sample(image: Any, sample_col: int, sample_row: int) -> float | None:
        value = image.getpixel((sample_col, sample_row))
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) and number > -10000 else None

    def sample_corners(source: dict[str, Any]) -> tuple[float | None, float | None, float | None, float | None]:
        image = source["image"]
        return (
            sample(image, col0, row0),
            sample(image, col1, row0),
            sample(image, col0, row1),
            sample(image, col1, row1),
        )

    try:
        q00, q10, q01, q11 = sample_corners(dem)
    except OSError:
        fresh_dem = _reset_dem_cache()
        dem.clear()
        dem.update(fresh_dem)
        q00, q10, q01, q11 = sample_corners(dem)
    if None in (q00, q10, q01, q11):
        return q00
    top = q00 * (1.0 - x) + q10 * x
    bottom = q01 * (1.0 - x) + q11 * x
    return top * (1.0 - y) + bottom * y


def _offset_lat_lon(latitude: float, longitude: float, east_m: float, north_m: float) -> tuple[float, float]:
    lat_rad = math.radians(latitude)
    new_lat = latitude + math.degrees(north_m / EARTH_RADIUS_M)
    cos_lat = max(0.01, math.cos(lat_rad))
    new_lon = longitude + math.degrees(east_m / (EARTH_RADIUS_M * cos_lat))
    return new_lat, new_lon


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2.0) ** 2
    return EARTH_RADIUS_M * 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def _bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_lambda = math.radians(lon2 - lon1)
    y = math.sin(d_lambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(d_lambda)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def _timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def _server_started_at() -> str:
    return SERVER_STARTED_AT.isoformat(timespec="seconds")
