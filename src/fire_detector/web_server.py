"""Web dashboard for monitoring the Fire Detector system."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import json
import math
import os
from pathlib import Path
import sys
from threading import Event, Lock, Thread
from time import monotonic, sleep
from typing import Any

from flask import Flask, jsonify, render_template, request

from fire_detector.odrive_connection import (
    ODriveConnectionError,
    connect_many,
    read_dual_drive_status,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_SETTINGS_PATH = PROJECT_ROOT / "AppSetting.JSON"
SYSTEM_DIST_PACKAGES = "/usr/lib/python3/dist-packages"
ODRIVE_PRO_V44_MAX_CURRENT_AMP = 150.0
DEFAULT_TORQUE_CONSTANT_NM_PER_AMP = 1.0
_GPIO: Any | None = None
_GPIO_CONFIGURED_INPUTS: dict[int, str] = {}
_GPIO_LOCK = Lock()
_SETTINGS_CACHE: dict[str, Any] | None = None
_SETTINGS_MTIME: float | None = None
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
    "input_filter_bandwidth": "controller.config.input_filter_bandwidth",
    "inertia": "controller.config.inertia",
    "trap_velocity_limit": "trap_traj.config.vel_limit",
    "trap_accel_limit": "trap_traj.config.accel_limit",
    "trap_decel_limit": "trap_traj.config.decel_limit",
}

AXIS_STATE_IDLE = 1
AXIS_STATE_CLOSED_LOOP_CONTROL = 8


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
    def __init__(self, timeout: float = 3.0, poll_interval: float = 0.025) -> None:
        self._timeout = timeout
        self._poll_interval = poll_interval
        self._devices: tuple[Any, ...] | None = None
        self._device_lock = Lock()
        self._lock = Lock()
        self._stop = Event()
        self._thread: Thread | None = None
        self._latest: dict[str, Any] | None = None

    def start(self) -> None:
        with self._lock:
            if self._thread is not None:
                return
            self._thread = Thread(target=self._poll_loop, name="odrive-monitor", daemon=True)
            self._thread.start()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            if self._latest is not None:
                return dict(self._latest)

        return {
            "connected": False,
            "error": "Waiting for the first ODrive sample.",
            "poll_interval_ms": int(self._poll_interval * 1000),
            "timestamp": _timestamp(),
            "server_started_at": _server_started_at(),
            "azimuth_sensors": _read_azimuth_sensors(),
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
                "azimuth_sensors": azimuth_sensors,
            }
        )
        _apply_position_offsets_to_payload(data)
        return data

    def update_tuning(self, label: str, values: dict[str, float]) -> dict[str, Any]:
        axis_index = {"Azimuth": 0, "Altitude": 1}.get(label)
        if axis_index is None:
            raise ValueError(f"Unknown axis: {label}")

        with self._device_lock:
            if self._devices is None:
                self._devices = _order_devices_for_config(connect_many(count=2, timeout=self._timeout))
            if axis_index >= len(self._devices):
                raise ODriveConnectionError(f"{label} drive is not connected.")

            axis = getattr(self._devices[axis_index], "axis0")
            for key, value in values.items():
                _set_path_value(axis, TUNING_FIELDS[key], value)

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
        _apply_position_offsets_to_payload(data)
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
                getattr(device, "axis0").requested_state = AXIS_STATE_CLOSED_LOOP_CONTROL
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
            axis.requested_state = AXIS_STATE_CLOSED_LOOP_CONTROL if enabled else AXIS_STATE_IDLE
            sleep(0.15 if enabled else 0.1)
            status = read_dual_drive_status(devices)
        return self._status_payload(status)

    def stop_motors(self) -> dict[str, Any]:
        with self._device_lock:
            devices = self._connected_devices()
            for device in devices[:2]:
                axis = getattr(device, "axis0")
                _set_if_present(axis, "controller.input_vel", 0.0)
                position = _get_path_float(axis, "pos_estimate")
                if position is None:
                    position = _get_path_float(axis, "pos_vel_mapper.pos_rel")
                if position is not None:
                    _set_if_present(axis, "controller.input_pos", position)
            status = read_dual_drive_status(devices)
        return self._status_payload(status)

    def goto_positions(self, positions_deg: dict[str, float], velocity_target_deg_per_sec: float | None = None) -> dict[str, Any]:
        _validate_motion_targets(positions_deg)
        with self._device_lock:
            devices = self._connected_devices()
            MotionCommandGuard(devices).require_enabled("goto", positions_deg)
            _apply_slew_rate(devices, velocity_target_deg_per_sec)
            for label, degrees in positions_deg.items():
                axis_index = MotionCommandGuard.AXIS_INDEX[label]
                axis = getattr(devices[axis_index], "axis0")
                _set_if_present(axis, "controller.input_pos", _command_degrees_to_turns(label, degrees))
            status = read_dual_drive_status(devices)
        return self._status_payload(status)

    def set_velocities(self, velocities_deg_per_sec: dict[str, float]) -> dict[str, Any]:
        velocities_deg_per_sec = _limit_velocities(velocities_deg_per_sec)
        with self._device_lock:
            devices = self._connected_devices()
            MotionCommandGuard(devices).require_enabled("velocity", velocities_deg_per_sec)
            _apply_slew_rate(devices)
            for label, degrees_per_sec in velocities_deg_per_sec.items():
                axis_index = MotionCommandGuard.AXIS_INDEX[label]
                axis = getattr(devices[axis_index], "axis0")
                _set_if_present(axis, "controller.input_vel", degrees_per_sec / 360.0)
            status = read_dual_drive_status(devices)
        return self._status_payload(status)

    def _connected_devices(self) -> tuple[Any, ...]:
        if self._devices is None:
            self._devices = _order_devices_for_config(connect_many(count=2, timeout=self._timeout))
        if len(self._devices) < 2:
            raise ODriveConnectionError("Both Azimuth and Altitude drives must be connected.")
        return self._devices

    def _status_payload(self, status) -> dict[str, Any]:
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
        _apply_position_offsets_to_payload(data)
        with self._lock:
            self._latest = data
        return data

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
            position += _axis_position_offset(axis_status.label)
            position = _axis_region_position_deg(axis_status.label, position, azimuth_sensors)
            if lower is not None and position < lower:
                _hold_axis_at_limit(getattr(self._devices[index], "axis0"), axis_status.label, lower)
            elif upper is not None and position > upper:
                _hold_axis_at_limit(getattr(self._devices[index], "axis0"), axis_status.label, upper)


def create_app() -> Flask:
    app = Flask(
        __name__,
        static_folder=str(PROJECT_ROOT / "web" / "static"),
        template_folder=str(PROJECT_ROOT / "web" / "templates"),
    )
    monitor = ODriveMonitor()
    monitor.start()

    @app.get("/")
    def index() -> str:
        return render_template("index.html")

    @app.get("/api/status")
    def api_status():
        return jsonify(monitor.snapshot())

    @app.get("/api/settings")
    def api_settings():
        return jsonify(_load_app_settings())

    @app.post("/api/settings")
    def api_update_settings():
        try:
            settings = _merge_app_settings(request.get_json(silent=True) or {})
            drive_flash = monitor.flash_motion_limits(settings)
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
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"{key} must be a finite number greater than or equal to 0.")
        values[key] = value

    if not values:
        raise ValueError("No tuning values were provided.")
    return values


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
    return clean


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


def _command_degrees_to_turns(label: str, degrees: float) -> float:
    return (degrees - _axis_position_offset(label)) / 360.0


def _apply_position_offsets_to_payload(data: dict[str, Any]) -> None:
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
        absolute_position = position_number + axis["position_offset_deg"]
        axis["absolute_position_deg"] = absolute_position
        axis["position_deg"] = _axis_region_position_deg(label, absolute_position, azimuth_sensors)
        if label == "Azimuth":
            axis["azimuth_region"] = _azimuth_region_label(azimuth_sensors)


def _axis_region_position_deg(label: str, position_deg: float, azimuth_sensors: dict[str, Any] | None) -> float:
    if label != "Azimuth":
        return position_deg
    if _azimuth_region_label(azimuth_sensors) != "ccw":
        return position_deg

    normalized = position_deg % 360.0
    if math.isclose(normalized, 0.0, abs_tol=1e-9) or math.isclose(normalized, 360.0, abs_tol=1e-9):
        return 0.0
    return normalized - 360.0


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


def _limit_velocities(velocities_deg_per_sec: dict[str, float]) -> dict[str, float]:
    for label, velocity in velocities_deg_per_sec.items():
        _validate_max_velocity(f"{label} velocity", velocity)
    return velocities_deg_per_sec


def _apply_slew_rate(devices: tuple[Any, ...], velocity_target_deg_per_sec: float | None = None) -> None:
    slew_rate = _effective_slew_rate(velocity_target_deg_per_sec)
    if slew_rate is None:
        return
    turns_per_second = slew_rate / 360.0
    for device in devices[:2]:
        axis = getattr(device, "axis0")
        _set_if_present(axis, "controller.config.vel_limit", turns_per_second)
        _set_if_present(axis, "trap_traj.config.vel_limit", turns_per_second)


def _effective_slew_rate(velocity_target_deg_per_sec: float | None = None) -> float | None:
    configured_slew_rate = _load_app_settings().get("motion_limits", {}).get("slew_rate_deg_per_sec")
    if velocity_target_deg_per_sec is None:
        return configured_slew_rate
    _validate_max_velocity("Velocity target", velocity_target_deg_per_sec)
    return velocity_target_deg_per_sec


def _validate_max_velocity(label: str, velocity_deg_per_sec: float) -> None:
    max_velocity = _load_app_settings().get("motion_limits", {}).get("slew_rate_deg_per_sec")
    if max_velocity is None:
        return
    if abs(velocity_deg_per_sec) > max_velocity:
        raise ValueError(f"{label} must be less than or equal to Max Velocity ({max_velocity} Deg/Sec).")


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
            _set_if_present(axis, "min_endstop.config.offset", _command_degrees_to_turns(label, lower_limit))
        if upper_limit is not None:
            _set_if_present(axis, "max_endstop.config.offset", _command_degrees_to_turns(label, upper_limit))

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


def _stop_and_disable_devices(devices: tuple[Any, ...]) -> None:
    for device in devices[:2]:
        axis = getattr(device, "axis0")
        _set_if_present(axis, "controller.input_vel", 0.0)
        position = _get_path_float(axis, "pos_estimate")
        if position is None:
            position = _get_path_float(axis, "pos_vel_mapper.pos_rel")
        if position is not None:
            _set_if_present(axis, "controller.input_pos", position)
    sleep(0.05)
    for device in devices[:2]:
        getattr(device, "axis0").requested_state = AXIS_STATE_IDLE
    sleep(0.15)


def _hold_axis_at_limit(axis: Any, label: str, limit_deg: float) -> None:
    _set_if_present(axis, "controller.input_vel", 0.0)
    _set_if_present(axis, "controller.input_pos", _command_degrees_to_turns(label, limit_deg))


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


def _timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def _server_started_at() -> str:
    return SERVER_STARTED_AT.isoformat(timespec="seconds")
