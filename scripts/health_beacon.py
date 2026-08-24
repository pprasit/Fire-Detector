#!/usr/bin/env python3
"""Drive IRIV DO-0 as a mount telemetry healthy beacon."""

from __future__ import annotations

import argparse
import json
import logging
import signal
import socket
import threading
import time
from pathlib import Path
from typing import Any
from urllib.request import urlopen

import RPi.GPIO as GPIO

LOG = logging.getLogger("health-beacon")
DO0_BCM_PIN = 23
BLINK_SECONDS = 0.5
HEALTHY_PULSE_SECONDS = 0.2
HEALTHY_PAUSE_SECONDS = 2.0
POLL_SECONDS = 0.2
MODE_HEALTHY = "healthy"
MODE_THERMAL_MISSING = "thermal_missing"
MODE_VISIBLE_MISSING = "visible_missing"
MODE_AZIMUTH_ERROR = "azimuth_error"
MODE_ALTITUDE_ERROR = "altitude_error"
MODE_INTERNET_ERROR = "internet_error"
MODE_OFF = "off"
SETTINGS_PATH = Path(__file__).resolve().parents[1] / "AppSetting.JSON"


def fetch_json(url: str, timeout: float) -> dict[str, Any]:
    with urlopen(url, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"{url} returned HTTP {response.status}")
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise RuntimeError(f"{url} did not return a JSON object")
    return payload


def telemetry_endpoint() -> tuple[str, int]:
    settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    host = str(settings.get("mount_agent", {}).get("remote", {}).get("host") or "").strip()
    if not host:
        raise RuntimeError("telemetry server host is not configured")
    return host, 8765


def telemetry_endpoint_reachable(timeout: float) -> bool:
    try:
        with socket.create_connection(telemetry_endpoint(), timeout=timeout):
            return True
    except (OSError, ValueError, json.JSONDecodeError):
        return False


def beacon_state(status: dict[str, Any], cameras: dict[str, Any],
                 internet_connected: bool = True) -> tuple[str, str]:
    if not internet_connected:
        return MODE_INTERNET_ERROR, "telemetry/control server is unreachable"
    if status.get("run_mode") != "hardware" or status.get("simulation_mode") is not False:
        return MODE_OFF, "mount is not in hardware mode"
    if status.get("connected") is not True:
        return MODE_OFF, "mount telemetry is disconnected"
    if status.get("health") != "ready" or status.get("has_bus_power") is not True:
        return MODE_OFF, "drive health or bus power is not ready"

    axes = status.get("axes")
    if not isinstance(axes, list):
        return MODE_OFF, "axis telemetry is missing"
    by_label = {axis.get("label"): axis for axis in axes if isinstance(axis, dict)}
    for label, error_mode in (("Altitude", MODE_ALTITUDE_ERROR), ("Azimuth", MODE_AZIMUTH_ERROR)):
        axis = by_label.get(label)
        if not axis or axis.get("available") is not True:
            return error_mode, f"{label.lower()} drive is unavailable"
        if axis.get("active_errors") != 0:
            return error_mode, f"{label.lower()} drive reports an active error"

    sensors = status.get("azimuth_sensors")
    if isinstance(sensors, dict):
        for side in ("cw", "ccw"):
            if sensors.get(f"{side}_pin") is not None and sensors.get(f"{side}_error") is not None:
                return MODE_OFF, f"azimuth {side} sensor cannot be read"

    live = cameras.get("sources", {}).get("live", {})
    per_camera = live.get("cameras")
    if isinstance(per_camera, dict):
        thermal_ok = per_camera.get("thermal", {}).get("connected") is True
        visible_ok = per_camera.get("visible", {}).get("connected") is True
    else:
        streams = set(live.get("streams") or []) if live.get("connected") is True else set()
        thermal_ok = "thermal" in streams
        visible_ok = "visible" in streams
    if visible_ok and not thermal_ok:
        return MODE_THERMAL_MISSING, "thermal camera telemetry is missing; visible camera is ready"
    if thermal_ok and not visible_ok:
        return MODE_VISIBLE_MISSING, "visible camera telemetry is missing; thermal camera is ready"
    if not visible_ok:
        return MODE_OFF, "visible camera telemetry is missing"
    if not thermal_ok:
        return MODE_OFF, "thermal camera telemetry is missing"
    return MODE_HEALTHY, "all required hardware is ready"


def health_reason(status: dict[str, Any], cameras: dict[str, Any]) -> str | None:
    mode, reason = beacon_state(status, cameras)
    return None if mode == MODE_HEALTHY else reason


def pattern_output(mode: str, elapsed: float) -> bool:
    if mode == MODE_HEALTHY:
        phase = elapsed % (HEALTHY_PULSE_SECONDS + HEALTHY_PAUSE_SECONDS)
        return phase < HEALTHY_PULSE_SECONDS
    flash_counts = {
        MODE_THERMAL_MISSING: 2,
        MODE_VISIBLE_MISSING: 3,
        MODE_AZIMUTH_ERROR: 4,
        MODE_ALTITUDE_ERROR: 5,
        MODE_INTERNET_ERROR: 6,
    }
    count = flash_counts.get(mode)
    if count is not None:
        phase = elapsed % (count + 1.5)
        return any(index <= phase < index + BLINK_SECONDS for index in range(count))
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--request-timeout", type=float, default=0.5)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    stopped = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stopped.set())
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(DO0_BCM_PIN, GPIO.OUT, initial=GPIO.LOW)
    output = False
    last_mode: str | None = None
    pattern_started = time.monotonic()
    internet_connected = False
    next_internet_check = 0.0

    try:
        while not stopped.is_set():
            now = time.monotonic()
            if now >= next_internet_check:
                internet_connected = telemetry_endpoint_reachable(args.request_timeout)
                next_internet_check = now + 2.0
            try:
                status = fetch_json(f"{args.base_url}/api/status", args.request_timeout)
                cameras = fetch_json(f"{args.base_url}/api/camera-stream", args.request_timeout)
                mode, reason = beacon_state(status, cameras, internet_connected)
            except Exception as exc:
                mode = MODE_OFF
                reason = f"telemetry check failed: {exc}"

            now = time.monotonic()
            if mode != last_mode:
                pattern_started = now
                LOG.info("beacon mode=%s: %s", mode, reason)
                last_mode = mode

            desired_output = pattern_output(mode, now - pattern_started)
            if desired_output != output:
                output = desired_output
                GPIO.output(DO0_BCM_PIN, GPIO.HIGH if output else GPIO.LOW)
            stopped.wait(POLL_SECONDS)
    finally:
        GPIO.output(DO0_BCM_PIN, GPIO.LOW)
        GPIO.cleanup(DO0_BCM_PIN)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
