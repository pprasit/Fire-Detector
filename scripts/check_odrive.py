#!/usr/bin/env python3
"""Check USB connectivity to an ODrive controller."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from fire_detector.odrive_connection import ODriveConnectionError, connect, read_status


def main() -> int:
    parser = argparse.ArgumentParser(description="Check ODrive USB connection.")
    parser.add_argument("--timeout", type=float, default=10.0, help="Seconds to wait for ODrive.")
    parser.add_argument("--serial-number", help="Optional ODrive serial number filter.")
    args = parser.parse_args()

    try:
        device = connect(timeout=args.timeout, serial_number=args.serial_number)
        status = read_status(device)
    except ODriveConnectionError as exc:
        print(f"ODrive connection failed: {exc}", file=sys.stderr)
        return 1

    print("ODrive connected")
    print(f"  serial_number: {status.serial_number}")
    print(f"  firmware:      {status.firmware_version}")
    print(f"  hardware:      {status.hardware_version}")
    print(f"  vbus_voltage:  {_format_float(status.vbus_voltage)} V")
    print(f"  ibus:          {_format_float(status.ibus)} A")
    print(f"  axis0_state:   {status.axis0_state}")
    print(f"  axis0_errors:  {status.axis0_active_errors}")
    print(f"  axis0_disarm:  {status.axis0_disarm_reason}")

    if not status.has_bus_power:
        print()
        print("Warning: DC bus voltage is low. USB is connected, but the ODrive")
        print("does not appear to have motor power on the DC bus.")

    return 0


def _format_float(value: float | None) -> str:
    if value is None:
        return "unknown"
    return f"{value:.3f}"


if __name__ == "__main__":
    raise SystemExit(main())

