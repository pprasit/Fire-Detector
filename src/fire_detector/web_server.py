"""Web dashboard for monitoring the Fire Detector system."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import json
import math
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
_GPIO: Any | None = None
_SETTINGS_CACHE: dict[str, Any] | None = None
_SETTINGS_MTIME: float | None = None

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
                    self._devices = connect_many(count=2, timeout=self._timeout)
                status = read_dual_drive_status(self._devices)
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
                "azimuth_sensors": _read_azimuth_sensors(),
            }
        )
        return data

    def update_tuning(self, label: str, values: dict[str, float]) -> dict[str, Any]:
        axis_index = {"Azimuth": 0, "Altitude": 1}.get(label)
        if axis_index is None:
            raise ValueError(f"Unknown axis: {label}")

        with self._device_lock:
            if self._devices is None:
                self._devices = connect_many(count=2, timeout=self._timeout)
            if axis_index >= len(self._devices):
                raise ODriveConnectionError(f"{label} drive is not connected.")

            axis = getattr(self._devices[axis_index], "axis0")
            for key, value in values.items():
                _set_path_value(axis, TUNING_FIELDS[key], value)

            status = read_dual_drive_status(self._devices)

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
                "azimuth_sensors": _read_azimuth_sensors(),
            }
        )
        with self._lock:
            self._latest = data
        return data

    def save_configuration(self, label: str) -> None:
        axis_index = {"Azimuth": 0, "Altitude": 1}.get(label)
        if axis_index is None:
            raise ValueError(f"Unknown axis: {label}")

        with self._device_lock:
            if self._devices is None:
                self._devices = connect_many(count=2, timeout=self._timeout)
            if axis_index >= len(self._devices):
                raise ODriveConnectionError(f"{label} drive is not connected.")
            self._devices[axis_index].save_configuration()
            self._devices = None


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
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        return jsonify({"ok": True, "settings": settings})

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
            monitor.save_configuration(axis_label)
        except (ValueError, ODriveConnectionError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"ok": False, "error": f"Could not save configuration: {exc}"}), 500
        return jsonify(
            {
                "ok": True,
                "message": "Configuration saved. The drive may reconnect for a moment.",
            }
        )

    return app


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
        "azimuth_sensors": {
            "ccw_pin": None,
            "cw_pin": None,
            "ccw_active_high": True,
            "cw_active_high": True,
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
    return clean


def _read_azimuth_sensors() -> dict[str, Any]:
    settings = _load_app_settings().get("azimuth_sensors", {})
    return {
        "ccw_sensor": _read_sensor_pin(
            settings.get("ccw_pin"),
            bool(settings.get("ccw_active_high", True)),
        ),
        "cw_sensor": _read_sensor_pin(
            settings.get("cw_pin"),
            bool(settings.get("cw_active_high", True)),
        ),
        "ccw_pin": settings.get("ccw_pin"),
        "cw_pin": settings.get("cw_pin"),
    }


def _read_sensor_pin(pin: int | None, active_high: bool) -> bool:
    if pin is None:
        return False
    gpio = _get_gpio()
    if gpio is None:
        return False
    try:
        gpio.setup(pin, gpio.IN)
        level = bool(gpio.input(pin))
    except Exception:
        return False
    return level if active_high else not level


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


def _health_label(has_bus_power: bool, has_axis_errors: bool) -> str:
    if has_axis_errors:
        return "attention"
    if not has_bus_power:
        return "usb-only"
    return "ready"


def _timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")
