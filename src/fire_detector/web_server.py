"""Web dashboard for monitoring the Fire Detector system."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import random
import subprocess
import sys
from threading import Event, Lock, Thread, current_thread
from time import monotonic, sleep
from typing import Any
import urllib.parse
import urllib.request

from flask import Flask, jsonify, render_template, request, send_from_directory
from flask_sock import Sock

from fire_detector.odrive_connection import (
    ODriveConnectionError,
    connect_many,
    read_dual_drive_status,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_SETTINGS_PATH = PROJECT_ROOT / "AppSetting.JSON"
UPDATE_STATE_PATH = PROJECT_ROOT / ".update_state.json"
UPDATER_SCRIPT_PATH = PROJECT_ROOT / "scripts" / "fire_detector_update.py"
DEM_PATH = PROJECT_ROOT / "GEO-Map" / "output_hh.tif"
POINTING_CACHE_DIR = PROJECT_ROOT / "data" / "pointing_cache"
ARCGIS_WORLD_IMAGERY_EXPORT_URL = "https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/export"
SYSTEM_DIST_PACKAGES = "/usr/lib/python3/dist-packages"
ODRIVE_PRO_V44_MAX_CURRENT_AMP = 150.0
DEFAULT_TORQUE_CONSTANT_NM_PER_AMP = 1.0
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
TELEMETRY_PUSH_INTERVAL_SEC = 0.05
MAX_DRIVE_ERROR_EVENTS = 100
MAX_AUTO_TUNE_STEP_EVENTS = 160
RUNTIME_LIMIT_SLOW_SPEED_DEG_PER_SEC = 30.0
RUNTIME_LIMIT_SLOW_SPEED_THRESHOLD_DEG_PER_SEC = 40.0
RUNTIME_LIMIT_SLOW_ZONE_SPEED_RATIO = 0.15
SOFTWARE_POSITION_DEFAULT_GAIN = 0.5
SOFTWARE_POSITION_INTERVAL_SEC = 0.05
SOFTWARE_POSITION_TOLERANCE_DEG = 0.08
SOFTWARE_POSITION_SETTLE_VELOCITY_DEG_PER_SEC = 0.25
SOFTWARE_POSITION_TIMEOUT_PADDING_SEC = 8.0
SINE_VELOCITY_INTERVAL_SEC = 0.05
_GPIO: Any | None = None
_GPIO_CONFIGURED_INPUTS: dict[int, str] = {}
_GPIO_LOCK = Lock()
_SETTINGS_CACHE: dict[str, Any] | None = None
_SETTINGS_MTIME: float | None = None
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
        return getattr(self._devices[axis_index], "axis0")

    @staticmethod
    def _axis_is_enabled(axis: Any) -> bool:
        try:
            return bool(getattr(axis, "is_armed"))
        except Exception:
            return False

    @staticmethod
    def _action_name(action: str) -> str:
        return "Move/Goto" if action == "goto" else "Jog/Velocity"


class ODriveMonitor:
    def __init__(self, timeout: float = 3.0, poll_interval: float = 0.05) -> None:
        self._timeout = timeout
        self._poll_interval = poll_interval
        self._devices: tuple[Any, ...] | None = None
        self._device_lock = Lock()
        self._lock = Lock()
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
        self._position_unwrap: dict[str, dict[str, float]] = {}
        self._software_position_lock = Lock()
        self._software_position_stop = Event()
        self._software_position_thread: Thread | None = None
        self._software_position_state: dict[str, dict[str, Any]] = {}
        self._sine_velocity_lock = Lock()
        self._sine_velocity_stops: dict[str, Event] = {}
        self._sine_velocity_threads: dict[str, Thread] = {}
        self._sine_velocity_state: dict[str, dict[str, Any]] = {}

    def start(self) -> None:
        with self._lock:
            if self._thread is not None:
                return
            self._thread = Thread(target=self._poll_loop, name="odrive-monitor", daemon=True)
            self._thread.start()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            if self._latest is not None:
                latest = dict(self._latest)
                latest["drive_error_events"] = self._drive_error_events_snapshot()
                latest["auto_tune_progress"] = self._auto_tune_progress_snapshot()
                latest["auto_tune_step_events"] = self._auto_tune_step_events_snapshot()
                return latest

        return {
            "connected": False,
            "error": "Waiting for the first ODrive sample.",
            "poll_interval_ms": int(self._poll_interval * 1000),
            "timestamp": _timestamp(),
            "server_started_at": _server_started_at(),
            "azimuth_sensors": _read_azimuth_sensors(),
            "drive_error_events": self._drive_error_events_snapshot(),
            "auto_tune_progress": self._auto_tune_progress_snapshot(),
            "auto_tune_step_events": self._auto_tune_step_events_snapshot(),
        }

    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            started_at = monotonic()
            latest = self._poll_once()
            with self._lock:
                self._latest = latest

            elapsed = monotonic() - started_at
            sleep_for = max(0.0, self._poll_interval - elapsed)
            if sleep_for:
                sleep(sleep_for)

    def _poll_once(self) -> dict[str, Any]:
        try:
            with self._device_lock:
                if self._devices is None:
                    self._devices = _order_devices_for_config(connect_many(count=2, timeout=self._timeout))
                status = read_dual_drive_status(self._devices)
                _require_valid_drive_status(status)
                azimuth_sensors = _read_azimuth_sensors()
                self._enforce_runtime_limits(status, azimuth_sensors)
        except Exception as exc:
            self._devices = None
            message = str(exc)
            if not isinstance(exc, ODriveConnectionError):
                message = f"Could not read ODrive status: {message}"
            return {
                "connected": False,
                "error": message,
                "poll_interval_ms": int(self._poll_interval * 1000),
                "timestamp": _timestamp(),
                "server_started_at": _server_started_at(),
                "azimuth_sensors": _read_azimuth_sensors(),
            }

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
                "azimuth_sensors": azimuth_sensors,
            }
        )
        _apply_position_offsets_to_payload(data, self._position_unwrap)
        self._filter_velocity_payload(data)
        self._apply_software_position_payload(data)
        self._apply_sine_velocity_payload(data)
        self._capture_drive_error_events(data, status_timestamp)
        data["drive_error_events"] = self._drive_error_events_snapshot()
        data["auto_tune_progress"] = self._auto_tune_progress_snapshot()
        data["auto_tune_step_events"] = self._auto_tune_step_events_snapshot()
        return data

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
        axis_index = {"Azimuth": 0, "Altitude": 1}.get(label)
        if axis_index is None:
            raise ValueError(f"Unknown axis: {label}")

        software_position_gain = values.pop("position_gain", None)
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

            status = read_dual_drive_status(self._devices)
            _require_valid_drive_status(status)

        data = asdict(status)
        data.update(
            {
                "connected": True,
                "has_bus_power": status.has_bus_power,
                "health": _health_label(
                    status.has_bus_power,
                    any(axis.active_errors for axis in status.axes if axis.available),
                ),
                "poll_interval_ms": int(self._poll_interval * 1000),
                "timestamp": _timestamp(),
                "server_started_at": _server_started_at(),
                "azimuth_sensors": _read_azimuth_sensors(),
            }
        )
        _apply_position_offsets_to_payload(data, self._position_unwrap)
        self._filter_velocity_payload(data)
        self._apply_software_position_payload(data)
        self._apply_sine_velocity_payload(data)
        with self._lock:
            self._latest = data
        return data

    def save_configuration(self, label: str) -> dict[str, Any]:
        axis_index = {"Azimuth": 0, "Altitude": 1}.get(label)
        if axis_index is None:
            raise ValueError(f"Unknown axis: {label}")

        with self._device_lock:
            devices = self._connected_devices()
            if axis_index >= len(devices):
                raise ODriveConnectionError(f"{label} drive is not connected.")
            _stop_and_disable_devices(devices)
            device = devices[axis_index]
            serial = _device_serial(device)
            warning = None
            try:
                device.save_configuration()
            except Exception:
                warning = (
                    f"{label} drive disconnected while saving configuration; "
                    "this is expected during ODrive flash/reboot."
                )
            self._devices = None
        return {"axis": label, "serial": serial, "warning": warning}

    def auto_tune_axis(self, label: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
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
                    if now - last_telemetry_at[0] < 0.10:
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
        with self._device_lock:
            self._devices = None

    def flash_motion_limits(self, settings: dict[str, Any]) -> dict[str, Any]:
        with self._device_lock:
            devices = self._connected_devices()
            _stop_and_disable_devices(devices)
            result = _flash_motion_limits_to_drives(devices, settings)
            self._devices = None
        return result

    def enable_motors(self) -> dict[str, Any]:
        with self._device_lock:
            devices = self._connected_devices()
            for device in devices[:2]:
                _clear_device_errors(device)
                axis = getattr(device, "axis0")
                _hold_axis_at_current_position(axis)
                axis.requested_state = AXIS_STATE_CLOSED_LOOP_CONTROL
            sleep(0.15)
            status = read_dual_drive_status(devices)
        return self._status_payload(status)

    def disable_motors(self) -> dict[str, Any]:
        with self._device_lock:
            devices = self._connected_devices()
            for device in devices[:2]:
                getattr(device, "axis0").requested_state = AXIS_STATE_IDLE
            sleep(0.1)
            status = read_dual_drive_status(devices)
        return self._status_payload(status)

    def set_axis_enabled(self, label: str, enabled: bool) -> dict[str, Any]:
        axis_index = {"Azimuth": 0, "Altitude": 1}.get(label)
        if axis_index is None:
            raise ValueError(f"Unknown axis: {label}")

        with self._device_lock:
            devices = self._connected_devices()
            if axis_index >= len(devices):
                raise ODriveConnectionError(f"{label} drive is not connected.")
            axis = getattr(devices[axis_index], "axis0")
            if enabled:
                _clear_device_errors(devices[axis_index])
                _configure_velocity_control(axis)
                _set_if_present(axis, "controller.input_vel", 0.0)
                axis.requested_state = AXIS_STATE_CLOSED_LOOP_CONTROL
            else:
                _hold_axis_at_current_position(axis)
                axis.requested_state = AXIS_STATE_IDLE
            sleep(0.15 if enabled else 0.1)
            status = read_dual_drive_status(devices)
        return self._status_payload(status)

    def stop_motors(self) -> dict[str, Any]:
        self._cancel_software_position_move()
        self._cancel_sine_velocity_tests()
        with self._device_lock:
            devices = self._connected_devices()
            for device in devices[:2]:
                axis = getattr(device, "axis0")
                _configure_velocity_control(axis)
                _set_if_present(axis, "controller.input_vel", 0.0)
                _set_if_present(axis, "controller.input_torque", 0.0)
            status = read_dual_drive_status(devices)
        return self._status_payload(status)

    def goto_positions(self, positions_deg: dict[str, float], velocity_target_deg_per_sec: float | None = None) -> dict[str, Any]:
        self._cancel_sine_velocity_tests(tuple(positions_deg))
        _validate_motion_targets(positions_deg)
        velocity_target_deg_per_sec = _effective_slew_rate(velocity_target_deg_per_sec) or _configured_slew_rate() or 30.0
        self._start_software_position_move(positions_deg, velocity_target_deg_per_sec)
        with self._device_lock:
            devices = self._connected_devices()
            status = read_dual_drive_status(devices)
        return self._status_payload(status)

    def _start_software_position_move(self, positions_deg: dict[str, float], max_speed_deg_per_sec: float) -> None:
        self._cancel_software_position_move()
        with self._device_lock:
            devices = self._connected_devices()
            MotionCommandGuard(devices).require_enabled("goto", positions_deg)
            _apply_slew_rate(devices, max_speed_deg_per_sec)
            for label in positions_deg:
                axis_index = MotionCommandGuard.AXIS_INDEX[label]
                axis = getattr(devices[axis_index], "axis0")
                _configure_velocity_control(axis)
                _set_if_present(axis, "controller.input_vel", 0.0)

        stop_event = Event()
        with self._software_position_lock:
            self._software_position_stop = stop_event
            now = _timestamp()
            self._software_position_state = {
                label: {
                    "active": True,
                    "target_deg": target,
                    "max_speed_deg_per_sec": max_speed_deg_per_sec,
                    "gain": _software_position_gain(label),
                    "error_deg": None,
                    "command_velocity_deg_per_sec": 0.0,
                    "phase": "moving",
                    "started_at": now,
                    "updated_at": now,
                }
                for label, target in positions_deg.items()
            }
            self._software_position_thread = Thread(
                target=self._software_position_loop,
                args=(dict(positions_deg), float(max_speed_deg_per_sec), stop_event),
                name="software-position-loop",
                daemon=True,
            )
            self._software_position_thread.start()

    def _cancel_software_position_move(self) -> None:
        self._software_position_stop.set()
        thread = self._software_position_thread
        if thread is not None and thread.is_alive() and thread is not current_thread():
            thread.join(timeout=0.4)
        with self._software_position_lock:
            for state in self._software_position_state.values():
                state["active"] = False
                state["phase"] = "cancelled"
                state["command_velocity_deg_per_sec"] = 0.0
                state["updated_at"] = _timestamp()

    def _software_position_loop(
        self,
        positions_deg: dict[str, float],
        max_speed_deg_per_sec: float,
        stop_event: Event,
    ) -> None:
        max_speed = max(0.1, abs(max_speed_deg_per_sec))
        timeout_at = monotonic() + _software_position_timeout_sec(positions_deg, max_speed)
        phase = "moving"
        try:
            while not stop_event.is_set():
                command_by_label: dict[str, float] = {}
                state_updates: dict[str, dict[str, Any]] = {}
                all_settled = True
                with self._device_lock:
                    devices = self._connected_devices()
                    status = read_dual_drive_status(devices)
                    _require_valid_drive_status(status)
                    axes_by_label = {axis.label: axis for axis in status.axes}
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
                        if axis_status is None or axis_status.position_deg is None:
                            all_settled = False
                            continue
                        current = _axis_status_display_position_deg(axis_status, self._position_unwrap)
                        error = _axis_position_delta_deg(label, target, current)
                        actual_velocity = abs(_finite_float(getattr(axis_status, "velocity_deg_per_sec", None)) or 0.0)
                        gain = _software_position_gain(label)
                        settled = (
                            abs(error) <= SOFTWARE_POSITION_TOLERANCE_DEG
                            and actual_velocity <= SOFTWARE_POSITION_SETTLE_VELOCITY_DEG_PER_SEC
                        )
                        command_velocity = 0.0 if settled else max(-max_speed, min(max_speed, gain * error))
                        lower, upper = axis_limits.get(label, (None, None))
                        command_velocity = _axis_velocity_limited_by_runtime_limits(current, command_velocity, lower, upper)
                        command_by_label[label] = command_velocity
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

                    for label, command_velocity in command_by_label.items():
                        axis_index = MotionCommandGuard.AXIS_INDEX[label]
                        axis = getattr(devices[axis_index], "axis0")
                        _configure_velocity_control(axis)
                        _set_if_present(axis, "controller.input_vel", command_velocity / 360.0)

                self._update_software_position_state(state_updates)
                if all_settled:
                    phase = "reached"
                    break
                if monotonic() >= timeout_at:
                    phase = "timeout"
                    break
                stop_event.wait(SOFTWARE_POSITION_INTERVAL_SEC)
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
                }
            )
        finally:
            try:
                with self._device_lock:
                    devices = self._connected_devices()
                    for label in positions_deg:
                        axis = getattr(devices[MotionCommandGuard.AXIS_INDEX[label]], "axis0")
                        _configure_velocity_control(axis)
                        _set_if_present(axis, "controller.input_vel", 0.0)
            except Exception:
                pass
            if phase != "error":
                self._finish_software_position_state(positions_deg, "cancelled" if stop_event.is_set() else phase)

    def _update_software_position_state(self, updates: dict[str, dict[str, Any]]) -> None:
        with self._software_position_lock:
            for label, update in updates.items():
                current = self._software_position_state.setdefault(label, {})
                current.update(update)

    def _finish_software_position_state(self, positions_deg: dict[str, float], phase: str) -> None:
        with self._software_position_lock:
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
        axis_index = MotionCommandGuard.AXIS_INDEX.get(label)
        if axis_index is None:
            raise ValueError(f"Unknown axis: {label}")
        self._cancel_software_position_move()
        self._cancel_sine_velocity_tests((label,))
        min_speed = options["min_speed_deg_per_sec"]
        max_speed = options["max_speed_deg_per_sec"]
        min_period = options["min_period_sec"]
        max_period = options["max_period_sec"]
        with self._device_lock:
            devices = self._connected_devices()
            MotionCommandGuard(devices).require_enabled("velocity", {label: max_speed})
            axis = getattr(devices[axis_index], "axis0")
            _configure_velocity_control(axis)
            _set_if_present(axis, "controller.input_vel", 0.0)

        stop_event = Event()
        with self._sine_velocity_lock:
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
                args=(label, dict(options), stop_event),
                name=f"{label.lower()}-sine-velocity-test",
                daemon=True,
            )
            self._sine_velocity_threads[label] = thread
            thread.start()

        with self._device_lock:
            status = read_dual_drive_status(self._connected_devices())
        return self._status_payload(status)

    def stop_sine_velocity_test(self, label: str) -> dict[str, Any]:
        self._cancel_sine_velocity_tests((label,))
        with self._device_lock:
            devices = self._connected_devices()
            axis_index = MotionCommandGuard.AXIS_INDEX.get(label)
            if axis_index is not None and axis_index < len(devices):
                axis = getattr(devices[axis_index], "axis0")
                _configure_velocity_control(axis)
                _set_if_present(axis, "controller.input_vel", 0.0)
            status = read_dual_drive_status(devices)
        return self._status_payload(status)

    def _cancel_sine_velocity_tests(self, labels: tuple[str, ...] | None = None) -> None:
        with self._sine_velocity_lock:
            selected = tuple(labels) if labels is not None else tuple(self._sine_velocity_stops)
            events = [(label, self._sine_velocity_stops.get(label), self._sine_velocity_threads.get(label)) for label in selected]
        for _, event, _ in events:
            if event is not None:
                event.set()
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

    def _sine_velocity_loop(self, label: str, options: dict[str, float], stop_event: Event) -> None:
        min_speed = float(options["min_speed_deg_per_sec"])
        max_speed = float(options["max_speed_deg_per_sec"])
        min_period = float(options["min_period_sec"])
        max_period = float(options["max_period_sec"])
        amplitude = random.uniform(min_speed, max_speed)
        period = random.uniform(min_period, max_period)
        cycle_started = monotonic()
        try:
            while not stop_event.is_set():
                now = monotonic()
                elapsed = now - cycle_started
                if elapsed >= period:
                    amplitude = random.uniform(min_speed, max_speed)
                    period = random.uniform(min_period, max_period)
                    cycle_started = now
                    elapsed = 0.0
                command_velocity = amplitude * math.sin((2.0 * math.pi * elapsed) / max(period, 1e-3))
                with self._device_lock:
                    devices = self._connected_devices()
                    axis_index = MotionCommandGuard.AXIS_INDEX[label]
                    axis = getattr(devices[axis_index], "axis0")
                    status = read_dual_drive_status(devices)
                    axis_status = status.axes[axis_index]
                    position = _axis_status_display_position_deg(axis_status, self._position_unwrap)
                    lower, upper = _axis_runtime_limits(label)
                    command_velocity = _axis_velocity_limited_by_runtime_limits(position, command_velocity, lower, upper)
                    _configure_velocity_control(axis)
                    _set_if_present(axis, "controller.input_vel", command_velocity / 360.0)
                with self._sine_velocity_lock:
                    state = self._sine_velocity_state.setdefault(label, {})
                    state.update(
                        {
                            "active": True,
                            "phase": "running",
                            "amplitude_deg_per_sec": amplitude,
                            "period_sec": period,
                            "cycle_elapsed_sec": elapsed,
                            "command_velocity_deg_per_sec": command_velocity,
                            "updated_at": _timestamp(),
                        }
                    )
                stop_event.wait(SINE_VELOCITY_INTERVAL_SEC)
        finally:
            try:
                with self._device_lock:
                    devices = self._connected_devices()
                    axis = getattr(devices[MotionCommandGuard.AXIS_INDEX[label]], "axis0")
                    _configure_velocity_control(axis)
                    _set_if_present(axis, "controller.input_vel", 0.0)
            except Exception:
                pass
            with self._sine_velocity_lock:
                state = self._sine_velocity_state.setdefault(label, {})
                state["active"] = False
                state["phase"] = "stopped" if not stop_event.is_set() else "cancelled"
                state["command_velocity_deg_per_sec"] = 0.0
                state["updated_at"] = _timestamp()

    def set_velocities(self, velocities_deg_per_sec: dict[str, float]) -> dict[str, Any]:
        self._cancel_software_position_move()
        self._cancel_sine_velocity_tests(tuple(velocities_deg_per_sec))
        velocities_deg_per_sec = _limit_velocities(velocities_deg_per_sec)
        velocities_deg_per_sec = self._limit_velocity_commands_to_runtime_limits(velocities_deg_per_sec)
        with self._device_lock:
            devices = self._connected_devices()
            MotionCommandGuard(devices).require_enabled("velocity", velocities_deg_per_sec)
            _apply_slew_rate(devices)
            for label, degrees_per_sec in velocities_deg_per_sec.items():
                axis_index = MotionCommandGuard.AXIS_INDEX[label]
                axis = getattr(devices[axis_index], "axis0")
                if degrees_per_sec == 0:
                    _configure_velocity_control(axis)
                    _set_if_present(axis, "controller.input_vel", 0.0)
                else:
                    _configure_velocity_control(axis)
                    _set_if_present(axis, "controller.input_vel", degrees_per_sec / 360.0)
            status = read_dual_drive_status(devices)
        return self._status_payload(status)

    def command_velocities(self, velocities_deg_per_sec: dict[str, float]) -> dict[str, Any]:
        self._cancel_software_position_move()
        self._cancel_sine_velocity_tests(tuple(velocities_deg_per_sec))
        velocities_deg_per_sec = _limit_velocities(velocities_deg_per_sec)
        velocities_deg_per_sec = self._limit_velocity_commands_to_runtime_limits(velocities_deg_per_sec)
        with self._device_lock:
            devices = self._connected_devices()
            MotionCommandGuard(devices).require_enabled("velocity", velocities_deg_per_sec)
            for label, degrees_per_sec in velocities_deg_per_sec.items():
                axis_index = MotionCommandGuard.AXIS_INDEX[label]
                axis = getattr(devices[axis_index], "axis0")
                if degrees_per_sec == 0:
                    _set_if_present(axis, "controller.input_vel", 0.0)
                else:
                    _configure_velocity_control(axis)
                    _set_if_present(axis, "controller.input_vel", degrees_per_sec / 360.0)
        return {"accepted": velocities_deg_per_sec}

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
        if self._devices is None:
            self._devices = _order_devices_for_config(connect_many(count=2, timeout=self._timeout))
        if len(self._devices) < 2:
            raise ODriveConnectionError("Both Azimuth and Altitude drives must be connected.")
        return self._devices

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
            }
        )
        _apply_position_offsets_to_payload(data, self._position_unwrap)
        self._filter_velocity_payload(data)
        self._apply_software_position_payload(data)
        self._apply_sine_velocity_payload(data)
        self._capture_drive_error_events(data, status_timestamp)
        data["drive_error_events"] = self._drive_error_events_snapshot()
        data["auto_tune_progress"] = self._auto_tune_progress_snapshot()
        data["auto_tune_step_events"] = self._auto_tune_step_events_snapshot()
        with self._lock:
            self._latest = data
        return data

    def _refresh_latest_status_unlocked(self, devices: tuple[Any, ...]) -> None:
        try:
            status = read_dual_drive_status(devices)
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
                axis["velocity_deg_per_sec"] = raw_velocity
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
            axis["velocity_deg_per_sec"] = filtered_velocity

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
            position = _axis_unwrapped_display_position_deg(
                axis_status.label,
                position,
                _axis_position_offset(axis_status.label),
                self._position_unwrap,
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


def create_app() -> Flask:
    app = Flask(
        __name__,
        static_folder=str(PROJECT_ROOT / "web" / "static"),
        template_folder=str(PROJECT_ROOT / "web" / "templates"),
    )
    sock = Sock(app)
    monitor = ODriveMonitor()
    monitor.start()

    @app.get("/")
    def index() -> str:
        return render_template("index.html")

    @app.get("/api/status")
    def api_status():
        return jsonify(monitor.snapshot())

    @sock.route("/ws/status")
    def ws_status(ws):
        while True:
            ws.send(json.dumps(monitor.snapshot(), separators=(",", ":")))
            sleep(TELEMETRY_PUSH_INTERVAL_SEC)

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
                "message": "Configuration flashed to drive. The drive may reconnect for a moment.",
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
            status = monitor.set_axis_enabled(axis_label, False)
        except (ValueError, ODriveConnectionError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"ok": False, "error": f"Could not disable {axis_label}: {exc}"}), 500
        return jsonify({"ok": True, "status": status})

    @app.post("/api/motors/stop")
    def api_stop_motors():
        try:
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
            command = monitor.command_velocities(velocities)
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

    return app


def _restart_process_soon() -> None:
    sleep(0.25)
    os._exit(1)


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


def _load_app_settings() -> dict[str, Any]:
    global _SETTINGS_CACHE, _SETTINGS_MTIME
    if not APP_SETTINGS_PATH.exists():
        return _default_app_settings()
    mtime = APP_SETTINGS_PATH.stat().st_mtime
    if _SETTINGS_CACHE is not None and _SETTINGS_MTIME == mtime:
        return _SETTINGS_CACHE
    try:
        with APP_SETTINGS_PATH.open("r", encoding="utf-8") as file:
            settings = json.load(file)
    except (OSError, json.JSONDecodeError):
        return _default_app_settings()

    default_settings = _default_app_settings()
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
    motion_limits = settings.get("motion_limits")
    if isinstance(motion_limits, dict):
        default_settings["motion_limits"].update(_clean_motion_limits(motion_limits))
    updater = settings.get("updater")
    if isinstance(updater, dict):
        default_settings["updater"].update(_clean_updater_settings(updater))
    _SETTINGS_CACHE = default_settings
    _SETTINGS_MTIME = mtime
    return default_settings


def _merge_app_settings(payload: dict[str, Any]) -> dict[str, Any]:
    settings = _load_app_settings()
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


def _default_app_settings() -> dict[str, Any]:
    return {
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
        },
        "motion_limits": {
            "azimuth_ccw_limit_deg": None,
            "azimuth_cw_limit_deg": None,
            "azimuth_position_offset_deg": 0.0,
            "azimuth_current_limit_amp": None,
            "altitude_upper_limit_deg": None,
            "altitude_lower_limit_deg": None,
            "altitude_position_offset_deg": 0.0,
            "altitude_current_limit_amp": None,
            "slew_rate_deg_per_sec": None,
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
    }


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
        "azimuth_current_limit_amp",
        "altitude_upper_limit_deg",
        "altitude_lower_limit_deg",
        "altitude_position_offset_deg",
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
        if key == "slew_rate_deg_per_sec" and number <= 0:
            raise ValueError("Max Velocity must be greater than 0.")
        if key.endswith("_current_limit_amp") and (number < 1.0 or number > ODRIVE_PRO_V44_MAX_CURRENT_AMP):
            raise ValueError(f"Current Limit must be between 1 and {ODRIVE_PRO_V44_MAX_CURRENT_AMP:g} Amp.")
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
        offset = axis["position_offset_deg"]
        absolute_position = _normalize_degrees(position_number + offset)
        unwrapped_position = _axis_unwrapped_display_position_deg(
            label,
            position_number,
            offset,
            unwrap_state,
        )
        axis["position_scale"] = 1.0
        axis["unwrapped_position_deg"] = unwrapped_position
        axis["absolute_position_deg"] = absolute_position
        axis["position_deg"] = unwrapped_position if label == "Azimuth" else _axis_display_position_deg(label, position_number, offset, azimuth_sensors)
        if label == "Azimuth":
            axis["azimuth_region"] = _azimuth_region_label(azimuth_sensors)


def _axis_display_position_deg(label: str, position_deg: float, offset_deg: float, azimuth_sensors: dict[str, Any] | None) -> float:
    if label == "Altitude":
        return _normalize_degrees(position_deg + offset_deg)
    if label == "Azimuth":
        return position_deg + offset_deg
    return _normalize_signed_degrees(_normalize_degrees(position_deg + offset_deg))


def _axis_display_degrees_to_encoder_turns(label: str, degrees: float) -> float:
    offset = _axis_position_offset(label)
    return (degrees - offset) / 360.0


def _axis_unwrapped_display_position_deg(
    label: str,
    position_deg: float,
    offset_deg: float,
    unwrap_state: dict[str, dict[str, float]] | None = None,
) -> float:
    position = position_deg + offset_deg
    if label != "Azimuth" or unwrap_state is None:
        return position

    absolute = _normalize_degrees(position)
    state = unwrap_state.get(label)
    if not state:
        initial = _azimuth_initial_unwrapped_position(absolute, position)
        unwrap_state[label] = {"absolute": absolute, "unwrapped": initial}
        return initial

    previous_absolute = float(state.get("absolute", absolute))
    previous_unwrapped = float(state.get("unwrapped", position))
    delta = _signed_degree_delta(absolute, previous_absolute)
    unwrapped = previous_unwrapped + delta
    state["absolute"] = absolute
    state["unwrapped"] = unwrapped
    return unwrapped


def _azimuth_initial_unwrapped_position(absolute_deg: float, fallback_deg: float) -> float:
    limits = _load_app_settings().get("motion_limits", {})
    lower = _finite_float(limits.get("azimuth_ccw_limit_deg"))
    upper = _finite_float(limits.get("azimuth_cw_limit_deg"))
    signed = _normalize_signed_degrees(absolute_deg)
    if lower is not None and upper is not None and lower < 0.0 < upper:
        if absolute_deg > upper and lower <= signed <= upper:
            return signed
    return fallback_deg


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
    return "unknown"


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
    if not azimuth_serial:
        return devices

    azimuth_device = None
    other_devices = []
    for device in devices:
        if str(_device_serial(device)) == str(azimuth_serial):
            azimuth_device = device
        else:
            other_devices.append(device)

    if azimuth_device is None:
        return devices
    return tuple([azimuth_device, *other_devices])


def _require_valid_drive_status(status: Any) -> None:
    serials = tuple(serial for serial in getattr(status, "device_serials", ()) if serial is not None)
    axes = tuple(getattr(status, "axes", ()))
    axis_serials = tuple(getattr(axis, "drive_serial", None) for axis in axes)
    if len(serials) < 2 or any(serial is None for serial in axis_serials[:2]):
        raise ODriveConnectionError("ODrive USB handle is stale; reconnecting to drives.")


def _device_serial(device: Any) -> Any:
    try:
        return getattr(device, "serial_number")
    except Exception:
        return None


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
    controller_limit = _configured_slew_rate()
    trap_limit = _effective_slew_rate(velocity_target_deg_per_sec)
    if controller_limit is None and trap_limit is None:
        return
    for device in devices[:2]:
        axis = getattr(device, "axis0")
        if controller_limit is not None:
            _set_if_present(axis, "controller.config.vel_limit", controller_limit / 360.0)
        if trap_limit is not None:
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
    return configured_slew_rate


def _validate_max_velocity(label: str, velocity_deg_per_sec: float) -> None:
    max_velocity = _load_app_settings().get("motion_limits", {}).get("slew_rate_deg_per_sec")
    if max_velocity is None:
        return
    if abs(velocity_deg_per_sec) > max_velocity:
        raise ValueError(f"{label} must be less than or equal to Max Velocity ({max_velocity} Deg/Sec).")


def _max_reasonable_position_delta_deg(dt: float) -> float:
    max_velocity = _load_app_settings().get("motion_limits", {}).get("slew_rate_deg_per_sec")
    if not isinstance(max_velocity, (int, float)) or not math.isfinite(max_velocity) or max_velocity <= 0:
        max_velocity = 50.0
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
    slew_rate = limits.get("slew_rate_deg_per_sec")
    for label, index, lower_limit, upper_limit, current_limit_amp in axis_specs:
        if index >= len(devices):
            warnings.append(f"{label} drive is not connected; limits were not flashed.")
            continue
        device = devices[index]
        serial = _device_serial(device)
        axis = getattr(device, "axis0")
        if slew_rate is not None:
            turns_per_second = slew_rate / 360.0
            _set_if_present(axis, "controller.config.enable_vel_limit", True)
            _set_if_present(axis, "controller.config.vel_limit", turns_per_second)
            _set_if_present(axis, "trap_traj.config.vel_limit", turns_per_second)

        if lower_limit is not None:
            _set_if_present(axis, "min_endstop.config.offset", _axis_command_degrees_to_turns(axis, label, lower_limit))
        if upper_limit is not None:
            _set_if_present(axis, "max_endstop.config.offset", _axis_command_degrees_to_turns(axis, label, upper_limit))

        if current_limit_amp is not None:
            torque_limit = current_limit_amp * DEFAULT_TORQUE_CONSTANT_NM_PER_AMP
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
        lower = -300.0 if lower is None else lower
        upper = 300.0 if upper is None else upper
    else:
        lower = _finite_float(limits.get("azimuth_ccw_limit_deg"))
        upper = _finite_float(limits.get("azimuth_cw_limit_deg"))
        lower = -300.0 if lower is None else lower
        upper = 300.0 if upper is None else upper
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
    min_speed = 0.1 if min_speed is None else max(0.001, min_speed)
    max_speed = 50.0 if max_speed is None else max(min_speed, max_speed)
    base = [0.1, 0.3, 1.0, 3.0, 10.0, 30.0, 50.0]
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
            "pos_setpoint_deg": ((_get_path_float(axis, "controller.pos_setpoint") or 0.0) * 360.0) + _axis_position_offset(label),
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
    position = turns * 360.0 + _axis_position_offset(label)
    return position if label == "Azimuth" else _normalize_degrees(position)


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


def _axis_status_display_position_deg(axis_status: Any, unwrap_state: dict[str, dict[str, float]]) -> float:
    label = getattr(axis_status, "label", "")
    position = float(getattr(axis_status, "position_deg", 0.0))
    offset = _axis_position_offset(label)
    if label == "Azimuth":
        return _axis_unwrapped_display_position_deg(label, position, offset, unwrap_state)
    return _axis_display_position_deg(label, position, offset, None)


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


def _software_position_timeout_sec(positions_deg: dict[str, float], max_speed_deg_per_sec: float) -> float:
    longest = 0.0
    for distance in (abs(value) for value in positions_deg.values()):
        longest = max(longest, distance / max(max_speed_deg_per_sec, 0.1))
    return max(10.0, longest * 4.0 + SOFTWARE_POSITION_TIMEOUT_PADDING_SEC)


def _clear_device_errors(device: Any) -> None:
    try:
        device.clear_errors()
    except Exception:
        pass


def _stop_and_disable_devices(devices: tuple[Any, ...]) -> None:
    for device in devices[:2]:
        _hold_axis_at_current_position(getattr(device, "axis0"))
    sleep(0.05)
    for device in devices[:2]:
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
    limited_velocity = _axis_velocity_limited_by_runtime_limits(position, velocity, lower, upper)
    if math.isclose(limited_velocity, velocity, abs_tol=1e-6):
        return
    _set_if_present(axis, "controller.input_vel", limited_velocity / 360.0)


def _configure_position_control(axis: Any, input_mode: int = INPUT_MODE_PASSTHROUGH, required: bool = False) -> None:
    setter = _set_required if required else _set_if_present
    setter(axis, "controller.config.control_mode", CONTROL_MODE_POSITION_CONTROL)
    setter(axis, "controller.config.input_mode", input_mode)


def _configure_velocity_control(axis: Any) -> None:
    if _get_path_int(axis, "controller.config.control_mode") != CONTROL_MODE_VELOCITY_CONTROL:
        _set_if_present(axis, "controller.config.control_mode", CONTROL_MODE_VELOCITY_CONTROL)
    if _get_path_int(axis, "controller.config.input_mode") != INPUT_MODE_VEL_RAMP:
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
    position = turns * 360.0 + _axis_position_offset(label)
    return position if label == "Azimuth" else _normalize_degrees(position)


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
        "version": 4,
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
    if visibility_path.exists():
        raster["visibility_src"] = f"/api/pointing/cache/{visibility_path.name}"
    if satellite_path.exists():
        raster["satellite_src"] = f"/api/pointing/cache/{satellite_path.name}"
        payload.setdefault("imagery", {})["available"] = True
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
) -> dict[str, str]:
    from PIL import Image

    POINTING_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    terrain_path, _ = _pointing_cache_paths(digest)
    visibility_path = POINTING_CACHE_DIR / f"pointing_{digest}_visibility.png"
    terrain_image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    visibility_image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    terrain_pixels = terrain_image.load()
    visibility_pixels = visibility_image.load()
    for index, elevation in enumerate(elevations):
        if elevation is None:
            continue
        row, col = divmod(index, size)
        terrain_pixels[col, row] = _terrain_rgba(elevation, elevation_min, elevation_max)
        visible = visibility[index]
        if visible is True:
            visibility_pixels[col, row] = (255, 246, 198, 34)
        elif visible is False:
            visibility_pixels[col, row] = (3, 7, 14, 87)
    terrain_image.save(terrain_path, format="PNG")
    visibility_image.save(visibility_path, format="PNG")
    return {
        "terrain": f"/api/pointing/cache/{terrain_path.name}",
        "visibility": f"/api/pointing/cache/{visibility_path.name}",
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
        "altitude_deg": None if altitude_deg is None else round(altitude_deg, 3),
        "visible": visible,
        "blocker": blocker,
        "inside_radius": distance_m <= POINTING_RADIUS_KM * 1000.0,
        "inside_dem": elevation is not None,
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
        "source": source,
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
