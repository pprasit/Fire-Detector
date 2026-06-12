"""ODrive USB connection helpers."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

import odrive


class ODriveConnectionError(RuntimeError):
    """Raised when an ODrive cannot be found or queried."""


@dataclass(frozen=True)
class AxisStatus:
    name: str
    label: str
    available: bool
    current_state: int | None
    active_errors: int | None
    disarm_reason: int | None
    pos_estimate: float | None
    vel_estimate: float | None
    position_deg: float | None
    velocity_deg_per_sec: float | None
    current: float | None
    is_armed: bool | None
    drive_serial: int | None
    drive_firmware: str
    drive_hardware: str
    drive_vbus_voltage: float | None
    drive_ibus: float | None
    position_gain: float | None
    velocity_gain: float | None
    velocity_integrator_gain: float | None
    velocity_integrator_limit: float | None
    velocity_integrator_decay_gain: float | None
    velocity_limit: float | None
    velocity_limit_tolerance: float | None
    velocity_ramp_rate: float | None
    torque_ramp_rate: float | None
    input_filter_bandwidth: float | None
    inertia: float | None
    trap_velocity_limit: float | None
    trap_accel_limit: float | None
    trap_decel_limit: float | None


@dataclass(frozen=True)
class ODriveStatus:
    serial_number: int | str | None
    device_serials: tuple[int | None, ...]
    firmware_version: str
    hardware_version: str
    vbus_voltage: float | None
    ibus: float | None
    axis0_state: int | None
    axis0_active_errors: int | None
    axis0_disarm_reason: int | None
    axes: tuple[AxisStatus, ...]

    @property
    def has_bus_power(self) -> bool:
        return self.vbus_voltage is not None and self.vbus_voltage > 5.0


def connect(timeout: float = 10.0, serial_number: str | None = None) -> Any:
    """Find an ODrive connected over USB.

    Args:
        timeout: Seconds to wait before giving up.
        serial_number: Optional ODrive serial number filter.
    """

    kwargs: dict[str, Any] = {"timeout": timeout}
    if serial_number:
        kwargs["serial_number"] = serial_number

    try:
        device = odrive.find_any(**kwargs)
    except Exception as exc:  # ODrive raises transport-specific errors.
        raise ODriveConnectionError(
            "Could not connect to ODrive over USB. Confirm the USB cable is "
            "connected, the ODrive appears in lsusb, and the current user has "
            "USB permission."
        ) from exc

    if device is None:
        raise ODriveConnectionError("No ODrive was found before the timeout expired.")

    return device


def connect_many(count: int = 2, timeout: float = 10.0) -> tuple[Any, ...]:
    """Find multiple ODrives connected over USB."""

    try:
        devices = odrive.find_any(count=count, timeout=timeout)
    except Exception as exc:
        raise ODriveConnectionError(
            f"Could not connect to {count} ODrive devices over USB."
        ) from exc

    if not devices:
        raise ODriveConnectionError("No ODrive devices were found before the timeout expired.")

    return tuple(devices)


def read_status(device: Any) -> ODriveStatus:
    """Read a small set of diagnostic values from an ODrive."""

    axis0 = _get(device, "axis0")
    axes = (
        _read_axis_status(axis0, "axis0", "Azimuth"),
        _read_axis_status(_get(device, "axis1"), "axis1", "Altitude"),
    )
    return ODriveStatus(
        serial_number=_get(device, "serial_number"),
        device_serials=(_get(device, "serial_number"),),
        firmware_version=_version(device, "fw"),
        hardware_version=_version(device, "hw"),
        vbus_voltage=_get(device, "vbus_voltage"),
        ibus=_get(device, "ibus"),
        axis0_state=_get(axis0, "current_state"),
        axis0_active_errors=_get(axis0, "active_errors"),
        axis0_disarm_reason=_get(axis0, "disarm_reason"),
        axes=axes,
    )


def read_dual_drive_status(devices: tuple[Any, ...]) -> ODriveStatus:
    """Read Azimuth/Altitude status from two single-axis ODrive devices."""

    azimuth_device = devices[0] if len(devices) > 0 else None
    altitude_device = devices[1] if len(devices) > 1 else None
    axes = (
        _read_axis_status(_get(azimuth_device, "axis0"), "azimuth.axis0", "Azimuth", azimuth_device),
        _read_axis_status(_get(altitude_device, "axis0"), "altitude.axis0", "Altitude", altitude_device),
    )
    serials = tuple(_get(device, "serial_number") for device in devices)
    vbus_values = [
        value
        for value in (_get_float(device, "vbus_voltage") for device in devices)
        if value is not None
    ]
    ibus_values = [
        value
        for value in (_get_float(device, "ibus") for device in devices)
        if value is not None
    ]

    return ODriveStatus(
        serial_number=" / ".join(str(serial) for serial in serials if serial is not None) or None,
        device_serials=serials,
        firmware_version=_join_versions(devices, "fw"),
        hardware_version=_join_versions(devices, "hw"),
        vbus_voltage=min(vbus_values) if vbus_values else None,
        ibus=sum(ibus_values) if ibus_values else None,
        axis0_state=axes[0].current_state,
        axis0_active_errors=axes[0].active_errors,
        axis0_disarm_reason=axes[0].disarm_reason,
        axes=axes,
    )


def _read_axis_status(axis: Any, name: str, label: str, device: Any | None = None) -> AxisStatus:
    pos_estimate = _first_float(
        axis,
        (
            "pos_estimate",
            "pos_vel_mapper.pos_rel",
            "controller.input_pos",
            "controller.pos_setpoint",
        ),
    )
    vel_estimate = _first_float(
        axis,
        (
            "vel_estimate",
            "pos_vel_mapper.vel",
            "controller.input_vel",
            "controller.vel_setpoint",
        ),
    )
    return AxisStatus(
        name=name,
        label=label,
        available=axis is not None,
        current_state=_get(axis, "current_state"),
        active_errors=_get(axis, "active_errors"),
        disarm_reason=_get(axis, "disarm_reason"),
        pos_estimate=pos_estimate,
        vel_estimate=vel_estimate,
        position_deg=_turns_to_degrees(pos_estimate),
        velocity_deg_per_sec=_turns_to_degrees(vel_estimate),
        current=_first_float(
            axis,
            (
                "motor.foc.Iq_measured",
                "motor.foc.Iq_setpoint",
                "motor.torque_estimate",
            ),
        ),
        is_armed=_get(axis, "is_armed"),
        drive_serial=_get(device, "serial_number"),
        drive_firmware=_version(device, "fw") if device is not None else "unknown",
        drive_hardware=_version(device, "hw") if device is not None else "unknown",
        drive_vbus_voltage=_get_float(device, "vbus_voltage"),
        drive_ibus=_get_float(device, "ibus"),
        position_gain=_get_path_float(axis, "controller.config.pos_gain"),
        velocity_gain=_get_path_float(axis, "controller.config.vel_gain"),
        velocity_integrator_gain=_get_path_float(axis, "controller.config.vel_integrator_gain"),
        velocity_integrator_limit=_get_path_float(axis, "controller.config.vel_integrator_limit"),
        velocity_integrator_decay_gain=_get_path_float(axis, "controller.config.vel_integrator_decay_gain"),
        velocity_limit=_get_path_float(axis, "controller.config.vel_limit"),
        velocity_limit_tolerance=_get_path_float(axis, "controller.config.vel_limit_tolerance"),
        velocity_ramp_rate=_get_path_float(axis, "controller.config.vel_ramp_rate"),
        torque_ramp_rate=_get_path_float(axis, "controller.config.torque_ramp_rate"),
        input_filter_bandwidth=_get_path_float(axis, "controller.config.input_filter_bandwidth"),
        inertia=_get_path_float(axis, "controller.config.inertia"),
        trap_velocity_limit=_get_path_float(axis, "trap_traj.config.vel_limit"),
        trap_accel_limit=_get_path_float(axis, "trap_traj.config.accel_limit"),
        trap_decel_limit=_get_path_float(axis, "trap_traj.config.decel_limit"),
    )


def _turns_to_degrees(value: float | None) -> float | None:
    if value is None:
        return None
    return value * 360.0


def _get(obj: Any, attr: str) -> Any:
    if obj is None:
        return None
    try:
        return getattr(obj, attr)
    except Exception:
        return None


def _get_float(obj: Any, attr: str) -> float | None:
    value = _get(obj, attr)
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _first_float(obj: Any, paths: tuple[str, ...]) -> float | None:
    for path in paths:
        value = _get_path_float(obj, path)
        if value is not None:
            return value
    return None


def _get_path_float(obj: Any, path: str) -> float | None:
    current = obj
    for part in path.split("."):
        current = _get(current, part)
        if current is None:
            return None
    try:
        number = float(current)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _version(device: Any, prefix: str) -> str:
    parts = [
        _get(device, f"{prefix}_version_major"),
        _get(device, f"{prefix}_version_minor"),
        _get(device, f"{prefix}_version_revision"),
    ]
    if any(part is None for part in parts):
        return "unknown"
    return ".".join(str(part) for part in parts)


def _join_versions(devices: tuple[Any, ...], prefix: str) -> str:
    versions = [_version(device, prefix) for device in devices]
    versions = [version for version in versions if version != "unknown"]
    return " / ".join(versions) if versions else "unknown"
