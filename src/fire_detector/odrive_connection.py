"""ODrive USB connection helpers."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

import odrive
from odrive.enums import AXIS_STATE_IDLE

TURN_DEGREES = 360.0


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
    position_source: str
    vel_estimate: float | None
    position_deg: float | None
    velocity_deg_per_sec: float | None
    current: float | None
    current_setpoint: float | None
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
    control_mode: int | None
    input_mode: int | None
    trajectory_done: bool | None
    input_pos: float | None
    pos_setpoint: float | None
    input_vel: float | None
    vel_setpoint: float | None
    torque_setpoint: float | None
    effective_torque_setpoint: float | None
    torque_soft_min: float | None
    torque_soft_max: float | None
    spinout_electrical_power_threshold: float | None
    spinout_mechanical_power_threshold: float | None
    spinout_electrical_power_bandwidth: float | None
    spinout_mechanical_power_bandwidth: float | None
    encoder_bandwidth: float | None
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
        if count <= 1:
            raise ODriveConnectionError(
                f"Could not connect to {count} ODrive devices over USB."
            ) from exc
        try:
            devices = odrive.find_any(count=1, timeout=timeout)
        except Exception as fallback_exc:
            raise ODriveConnectionError(
                f"Could not connect to {count} ODrive devices over USB."
            ) from fallback_exc

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


def read_dual_drive_status(
    devices: tuple[Any, ...],
    *,
    telemetry_only: bool = False,
    previous: ODriveStatus | None = None,
) -> ODriveStatus:
    """Read Azimuth/Altitude status from two single-axis ODrive devices."""

    azimuth_device = devices[0] if len(devices) > 0 else None
    altitude_device = devices[1] if len(devices) > 1 else None
    axes = (
        _read_axis_status(
            _get(azimuth_device, "axis0"), "azimuth.axis0", "Azimuth", azimuth_device,
            telemetry_only=telemetry_only, previous=previous.axes[0] if previous else None,
        ),
        _read_axis_status(
            _get(altitude_device, "axis0"), "altitude.axis0", "Altitude", altitude_device,
            telemetry_only=telemetry_only, previous=previous.axes[1] if previous else None,
        ),
    )
    if telemetry_only and previous is not None:
        serials = previous.device_serials
        vbus_voltage = previous.vbus_voltage
        ibus = previous.ibus
        serial_number = previous.serial_number
        firmware_version = previous.firmware_version
        hardware_version = previous.hardware_version
    else:
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
        vbus_voltage = min(vbus_values) if vbus_values else None
        ibus = sum(ibus_values) if ibus_values else None
        serial_number = " / ".join(str(serial) for serial in serials if serial is not None) or None
        firmware_version = _join_versions(devices, "fw")
        hardware_version = _join_versions(devices, "hw")

    return ODriveStatus(
        serial_number=serial_number,
        device_serials=serials,
        firmware_version=firmware_version,
        hardware_version=hardware_version,
        vbus_voltage=vbus_voltage,
        ibus=ibus,
        axis0_state=axes[0].current_state,
        axis0_active_errors=axes[0].active_errors,
        axis0_disarm_reason=axes[0].disarm_reason,
        axes=axes,
    )


def _read_axis_status(
    axis: Any,
    name: str,
    label: str,
    device: Any | None = None,
    *,
    telemetry_only: bool = False,
    previous: AxisStatus | None = None,
) -> AxisStatus:
    def config_value(field: str, getter: Any) -> Any:
        if telemetry_only and previous is not None:
            return getattr(previous, field)
        return getter()

    if device is not None:
        _ensure_axis_feedback_config(label, device)
    # The FOC current registers retain their last value after the axis enters
    # IDLE.  Treating that latched value as live current makes the dashboard
    # show phantom load and can keep the software current envelope out of its
    # recovery state.  Reading the state once also avoids an unnecessary Fibre
    # round trip in the compact telemetry loop.
    current_state = _get(axis, "current_state")
    is_armed = _get(axis, "is_armed")
    axis_is_idle = current_state == AXIS_STATE_IDLE
    measured_current = (
        0.0
        if axis_is_idle
        else _first_float(
            axis,
            (
                "motor.foc.Iq_measured",
                "motor.foc.Iq_setpoint",
                "motor.torque_estimate",
            ),
        )
    )
    current_setpoint = (
        0.0 if axis_is_idle else _get_path_float(axis, "motor.foc.Iq_setpoint")
    )
    mapper_vel_estimate = _first_float(
        axis,
        (
            "vel_estimate",
            "pos_vel_mapper.vel",
            "controller.input_vel",
            "controller.vel_setpoint",
        ),
    )
    pos_estimate = _axis_feedback_turns(label, device) if device is not None else None
    position_source = _axis_feedback_position_source(device) if pos_estimate is not None else "pos_estimate"
    if pos_estimate is None:
        pos_estimate = _first_float(
            axis,
            (
                "pos_estimate",
                "pos_vel_mapper.pos_rel",
                "controller.input_pos",
                "controller.pos_setpoint",
            ),
        )
    vel_estimate = _axis_feedback_turns_per_second(label, device) if device is not None else None
    if vel_estimate is None:
        vel_estimate = mapper_vel_estimate
    return AxisStatus(
        name=name,
        label=label,
        available=axis is not None,
        # Safety/runtime state must never come from the configuration cache.
        # The axis may arm, disarm, or fault between samples without any
        # configuration change.
        current_state=current_state,
        active_errors=_get(axis, "active_errors"),
        disarm_reason=_get(axis, "disarm_reason"),
        pos_estimate=pos_estimate,
        position_source=position_source,
        vel_estimate=vel_estimate,
        position_deg=_axis_turns_to_degrees(label, pos_estimate),
        velocity_deg_per_sec=_axis_turns_to_degrees(label, vel_estimate),
        current=measured_current,
        current_setpoint=current_setpoint,
        is_armed=is_armed,
        drive_serial=config_value("drive_serial", lambda: _get(device, "serial_number")),
        drive_firmware=config_value("drive_firmware", lambda: _version(device, "fw") if device is not None else "unknown"),
        drive_hardware=config_value("drive_hardware", lambda: _version(device, "hw") if device is not None else "unknown"),
        drive_vbus_voltage=config_value("drive_vbus_voltage", lambda: _get_float(device, "vbus_voltage")),
        drive_ibus=config_value("drive_ibus", lambda: _get_float(device, "ibus")),
        position_gain=config_value("position_gain", lambda: _get_path_float(axis, "controller.config.pos_gain")),
        velocity_gain=config_value("velocity_gain", lambda: _get_path_float(axis, "controller.config.vel_gain")),
        velocity_integrator_gain=config_value("velocity_integrator_gain", lambda: _get_path_float(axis, "controller.config.vel_integrator_gain")),
        velocity_integrator_limit=config_value("velocity_integrator_limit", lambda: _get_path_float(axis, "controller.config.vel_integrator_limit")),
        velocity_integrator_decay_gain=config_value("velocity_integrator_decay_gain", lambda: _get_path_float(axis, "controller.config.vel_integrator_decay_gain")),
        velocity_limit=config_value("velocity_limit", lambda: _turns_to_degrees(_get_path_float(axis, "controller.config.vel_limit"))),
        velocity_limit_tolerance=config_value("velocity_limit_tolerance", lambda: _get_path_float(axis, "controller.config.vel_limit_tolerance")),
        velocity_ramp_rate=config_value("velocity_ramp_rate", lambda: _turns_to_degrees(_get_path_float(axis, "controller.config.vel_ramp_rate"))),
        torque_ramp_rate=config_value("torque_ramp_rate", lambda: _get_path_float(axis, "controller.config.torque_ramp_rate")),
        control_mode=config_value("control_mode", lambda: _get_path_int(axis, "controller.config.control_mode")),
        input_mode=config_value("input_mode", lambda: _get_path_int(axis, "controller.config.input_mode")),
        trajectory_done=_get_path_bool(axis, "controller.trajectory_done"),
        input_pos=config_value("input_pos", lambda: _turns_to_degrees(_get_path_float(axis, "controller.input_pos"))),
        pos_setpoint=config_value("pos_setpoint", lambda: _turns_to_degrees(_get_path_float(axis, "controller.pos_setpoint"))),
        input_vel=_turns_to_degrees(_get_path_float(axis, "controller.input_vel")),
        vel_setpoint=_turns_to_degrees(_get_path_float(axis, "controller.vel_setpoint")),
        torque_setpoint=config_value("torque_setpoint", lambda: _get_path_float(axis, "controller.torque_setpoint")),
        effective_torque_setpoint=config_value("effective_torque_setpoint", lambda: _get_path_float(axis, "controller.effective_torque_setpoint")),
        torque_soft_min=config_value("torque_soft_min", lambda: _get_path_float(axis, "config.torque_soft_min")),
        torque_soft_max=config_value("torque_soft_max", lambda: _get_path_float(axis, "config.torque_soft_max")),
        spinout_electrical_power_threshold=config_value("spinout_electrical_power_threshold", lambda: _get_path_float(axis, "controller.config.spinout_electrical_power_threshold")),
        spinout_mechanical_power_threshold=config_value("spinout_mechanical_power_threshold", lambda: _get_path_float(axis, "controller.config.spinout_mechanical_power_threshold")),
        spinout_electrical_power_bandwidth=config_value("spinout_electrical_power_bandwidth", lambda: _get_path_float(axis, "controller.config.spinout_electrical_power_bandwidth")),
        spinout_mechanical_power_bandwidth=config_value("spinout_mechanical_power_bandwidth", lambda: _get_path_float(axis, "controller.config.spinout_mechanical_power_bandwidth")),
        encoder_bandwidth=config_value("encoder_bandwidth", lambda: _get_path_float(axis, "config.encoder_bandwidth")),
        input_filter_bandwidth=config_value("input_filter_bandwidth", lambda: _get_path_float(axis, "controller.config.input_filter_bandwidth")),
        inertia=config_value("inertia", lambda: _get_path_float(axis, "controller.config.inertia")),
        trap_velocity_limit=config_value("trap_velocity_limit", lambda: _turns_to_degrees(_get_path_float(axis, "trap_traj.config.vel_limit"))),
        trap_accel_limit=config_value("trap_accel_limit", lambda: _turns_to_degrees(_get_path_float(axis, "trap_traj.config.accel_limit"))),
        trap_decel_limit=config_value("trap_decel_limit", lambda: _turns_to_degrees(_get_path_float(axis, "trap_traj.config.decel_limit"))),
    )


def _axis_feedback_turns(label: str, device: Any) -> float | None:
    del label
    axis = _get(device, "axis0")
    mapped = _first_float(
        axis,
        (
            "pos_vel_mapper.pos_abs",
            "load_mapper.pos_abs",
        ),
    )
    if mapped is not None:
        return mapped
    # An absolute SPI encoder is useful for read-only commissioning before
    # commutation calibration makes the axis mapper valid. This value is never
    # used to bypass the ODrive closed-loop/calibration safety checks.
    return _get_path_float(device, "spi_encoder0.raw")


def _axis_feedback_position_source(device: Any) -> str:
    axis = _get(device, "axis0")
    if _first_float(axis, ("pos_vel_mapper.pos_abs", "load_mapper.pos_abs")) is not None:
        return "pos_vel_mapper.pos_abs"
    if _get_path_float(device, "spi_encoder0.raw") is not None:
        return "spi_encoder0.raw"
    return "pos_estimate"


def _ensure_axis_feedback_config(label: str, device: Any) -> None:
    return


def _axis_feedback_turns_per_second(label: str, device: Any) -> float | None:
    return None


def _turns_to_degrees(value: float | None) -> float | None:
    if value is None:
        return None
    return value * TURN_DEGREES


def _axis_turns_to_degrees(label: str, value: float | None) -> float | None:
    if value is None:
        return None
    return _turns_to_degrees(value)


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


def _get_path_int(obj: Any, path: str) -> int | None:
    current = obj
    for part in path.split("."):
        current = _get(current, part)
        if current is None:
            return None
    try:
        return int(current)
    except (TypeError, ValueError):
        return None


def _get_path_bool(obj: Any, path: str) -> bool | None:
    current = obj
    for part in path.split("."):
        current = _get(current, part)
        if current is None:
            return None
    try:
        return bool(current)
    except Exception:
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
