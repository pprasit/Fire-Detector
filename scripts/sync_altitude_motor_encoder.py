#!/usr/bin/env python3
"""Copy hardware-level motor/encoder configuration from Azimuth to Altitude.

Calibration results and direction signs that are unique to a physical motor
installation are intentionally not copied. Both axes are forced to IDLE and
this script never requests a calibration or closed-loop state.
"""

from __future__ import annotations

import argparse
import json
import math
from time import monotonic, sleep
from typing import Any

import odrive


AZIMUTH_SERIAL_DEC = "59898476770354"
ALTITUDE_SERIAL_DEC = "59812575523890"
AXIS_STATE_IDLE = 1

COPY_PATHS = (
    # Motor model and electrical operating limits.
    "axis0.config.motor.motor_type",
    "axis0.config.motor.pole_pairs",
    "axis0.config.motor.torque_constant",
    "axis0.config.motor.calibration_current",
    "axis0.config.motor.resistance_calib_max_voltage",
    "axis0.config.motor.current_soft_max",
    "axis0.config.motor.current_hard_max",
    "axis0.config.motor.current_control_bandwidth",
    "axis0.config.motor.current_slew_rate_limit",
    "axis0.config.motor.bEMF_FF_enable",
    "axis0.config.motor.dI_dt_FF_enable",
    "axis0.config.motor.wL_FF_enable",
    "axis0.config.motor.fw_enable",
    "axis0.config.motor.fw_fb_bandwidth",
    "axis0.config.motor.fw_mod_setpoint",
    "axis0.config.motor.power_torque_report_filter_bandwidth",
    # Axis torque limits and calibration profile.
    "axis0.config.torque_soft_min",
    "axis0.config.torque_soft_max",
    "axis0.config.calibration_lockin.current",
    "axis0.config.calibration_lockin.vel",
    "axis0.config.calibration_lockin.accel",
    "axis0.config.calibration_lockin.ramp_distance",
    "axis0.config.calibration_lockin.ramp_time",
    "axis0.config.calib_range",
    "axis0.config.calib_scan_distance",
    "axis0.config.calib_scan_vel",
    # Encoder selection and physical encoder mode.
    "axis0.config.load_encoder",
    "axis0.config.commutation_encoder",
    "axis0.config.encoder_bandwidth",
    "spi_encoder0.config.mode",
    # Generic mapper geometry. Installation-specific commutation offset excluded.
    "axis0.pos_vel_mapper.config.circular_output_range",
    "axis0.pos_vel_mapper.config.scale",
    "axis0.pos_vel_mapper.config.offset",
    "axis0.pos_vel_mapper.config.offset_valid",
    "axis0.commutation_mapper.config.circular",
    "axis0.commutation_mapper.config.circular_output_range",
)

# This only becomes persistently true after the physical commutation
# calibration establishes a valid mapper. It must not fail hardware sync.
POST_CALIBRATION_PATHS = ("axis0.pos_vel_mapper.config.circular",)

INVALIDATE_PATHS = (
    "axis0.config.motor.phase_resistance_valid",
    "axis0.config.motor.phase_inductance_valid",
    "axis0.config.motor.motor_model_l_dq_valid",
    "axis0.commutation_mapper.config.offset_valid",
)


def get_path(root: Any, path: str) -> Any:
    value = root
    for part in path.split("."):
        value = getattr(value, part)
    return value


def set_path(root: Any, path: str, value: Any) -> None:
    parts = path.split(".")
    target = root
    for part in parts[:-1]:
        target = getattr(target, part)
    setattr(target, parts[-1], value)


def connect(serial_dec: str, timeout: float = 12.0) -> Any:
    serial_hex = f"{int(serial_dec):012X}"
    device = odrive.find_any(serial_number=serial_hex, timeout=timeout)
    if str(int(device.serial_number)) != serial_dec:
        raise RuntimeError(f"Connected to unexpected ODrive serial {device.serial_number}.")
    device.axis0.requested_state = AXIS_STATE_IDLE
    device.axis0.controller.input_vel = 0.0
    device.axis0.controller.input_torque = 0.0
    return device


def serializable(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    return value


def snapshot(device: Any) -> dict[str, Any]:
    paths = COPY_PATHS + INVALIDATE_PATHS + POST_CALIBRATION_PATHS + (
        "axis0.config.motor.phase_resistance",
        "axis0.config.motor.phase_inductance",
        "axis0.commutation_mapper.config.offset",
    )
    return {path: serializable(get_path(device, path)) for path in paths}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Write and save the Altitude Drive.")
    args = parser.parse_args()

    azimuth = connect(AZIMUTH_SERIAL_DEC)
    altitude = connect(ALTITUDE_SERIAL_DEC)
    before = snapshot(altitude)
    source = snapshot(azimuth)
    changes = {
        path: {"before": before[path], "after": source[path]}
        for path in COPY_PATHS
        if before[path] != source[path]
    }
    for path in INVALIDATE_PATHS:
        if before[path] is not False:
            changes[path] = {"before": before[path], "after": False}

    print(json.dumps({"apply": args.apply, "changes": changes}, indent=2, sort_keys=True))
    if not args.apply:
        print("Dry run only. Re-run with --apply to write the Altitude Drive.")
        return 0

    # Reassert IDLE immediately before modifying configuration.
    azimuth.axis0.requested_state = AXIS_STATE_IDLE
    altitude.axis0.requested_state = AXIS_STATE_IDLE
    for path in COPY_PATHS:
        set_path(altitude, path, get_path(azimuth, path))
    for path in INVALIDATE_PATHS:
        set_path(altitude, path, False)

    for path in COPY_PATHS:
        actual = get_path(altitude, path)
        expected = get_path(azimuth, path)
        if isinstance(expected, float):
            if not math.isclose(float(actual), expected, rel_tol=1e-6, abs_tol=1e-8):
                raise RuntimeError(f"Readback mismatch for {path}: {actual!r} != {expected!r}")
        elif actual != expected:
            raise RuntimeError(f"Readback mismatch for {path}: {actual!r} != {expected!r}")

    try:
        altitude.save_configuration()
    except Exception:
        # Fibre disconnect during flash/reboot is expected.
        pass

    deadline = monotonic() + 20.0
    verified = None
    while monotonic() < deadline:
        sleep(0.5)
        try:
            verified = connect(ALTITUDE_SERIAL_DEC, timeout=2.0)
            break
        except Exception:
            continue
    if verified is None:
        raise RuntimeError("Altitude Drive did not reconnect after save_configuration().")

    after = snapshot(verified)
    for path in COPY_PATHS:
        expected = source[path]
        actual = after[path]
        if isinstance(expected, float) and isinstance(actual, float):
            matches = math.isclose(actual, expected, rel_tol=1e-6, abs_tol=1e-8)
        else:
            matches = actual == expected
        if not matches:
            raise RuntimeError(f"Persistent readback mismatch for {path}: {actual!r} != {expected!r}")
    for path in INVALIDATE_PATHS:
        if after[path] is not False:
            raise RuntimeError(f"{path} unexpectedly remained valid.")

    print(json.dumps({"saved": True, "serial": ALTITUDE_SERIAL_DEC, "after": after}, indent=2, sort_keys=True))
    print("Altitude hardware parameters saved. Motor/commutation calibration remains intentionally invalid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
