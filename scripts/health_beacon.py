#!/usr/bin/env python3
"""Drive IRIV DO-0 as a mount telemetry healthy beacon."""

from __future__ import annotations

import argparse
import json
import logging
import signal
import socket
import ssl
import threading
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import urlopen

import RPi.GPIO as GPIO

LOG = logging.getLogger("health-beacon")
DO0_BCM_PIN = 23
BLINK_SECONDS = 0.5
HEALTHY_PULSE_SECONDS = 0.2
HEALTHY_PAUSE_SECONDS = 2.0
STATUS_POLL_SECONDS = 0.2
LED_TICK_SECONDS = 0.02
INTERNET_CHECK_SECONDS = 2.0
INTERNET_CONFIRMATIONS = 3
RAPID_BLINK_SECONDS = 0.1
MODE_HEALTHY = "healthy"
MODE_THERMAL_MISSING = "thermal_missing"
MODE_VISIBLE_MISSING = "visible_missing"
MODE_AZIMUTH_ERROR = "azimuth_error"
MODE_ALTITUDE_ERROR = "altitude_error"
MODE_INTERNET_ERROR = "internet_error"
MODE_NETWORK_DISCONNECTED = "network_disconnected"
MODE_OFF = "off"
SETTINGS_PATH = Path(__file__).resolve().parents[1] / "AppSetting.JSON"
BEACON_STATE_PATH = Path("/run/fire-detector/health-beacon.json")

BEACON_LABELS = {
    MODE_HEALTHY: ("SYSTEM READY", "Healthy pulse"),
    MODE_OFF: ("SYSTEM NOT READY", "1 flash"),
    MODE_THERMAL_MISSING: ("THERMAL CAMERA OFFLINE", "2 flashes"),
    MODE_VISIBLE_MISSING: ("VISIBLE CAMERA OFFLINE", "3 flashes"),
    MODE_AZIMUTH_ERROR: ("AZIMUTH FAULT", "4 flashes"),
    MODE_ALTITUDE_ERROR: ("ALTITUDE FAULT", "5 flashes"),
    MODE_INTERNET_ERROR: ("TELEMETRY OFFLINE", "6 flashes"),
    MODE_NETWORK_DISCONNECTED: ("INTERNET OFFLINE", "100 ms rapid blink"),
}


def beacon_label(mode: str, reason: str) -> str:
    if mode != MODE_OFF:
        return BEACON_LABELS.get(mode, ("STATUS UNKNOWN", "LED off"))[0]
    reason_labels = (
        ("both camera", "BOTH CAMERAS OFFLINE"),
        ("not in hardware mode", "HARDWARE MODE OFF"),
        ("telemetry is disconnected", "MOUNT DISCONNECTED"),
        ("drive health or bus power", "DRIVE POWER NOT READY"),
        ("axis telemetry", "AXIS DATA MISSING"),
        ("sensor cannot be read", "AZ SENSOR UNREADABLE"),
        ("telemetry check failed", "STATUS CHECK FAILED"),
    )
    lowered_reason = reason.lower()
    for fragment, label in reason_labels:
        if fragment in lowered_reason:
            return label
    return BEACON_LABELS[MODE_OFF][0]


def write_beacon_state(mode: str, reason: str) -> None:
    _, pattern = BEACON_LABELS.get(mode, ("STATUS UNKNOWN", "LED off"))
    payload = {
        "mode": mode,
        "label": beacon_label(mode, reason),
        "pattern": pattern,
        "reason": reason,
        "updated_at": time.time(),
    }
    temporary_path = BEACON_STATE_PATH.with_suffix(".tmp")
    temporary_path.write_text(json.dumps(payload), encoding="utf-8")
    temporary_path.replace(BEACON_STATE_PATH)


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
    remote = settings.get("mount_agent", {}).get("remote", {})
    host = str(remote.get("host") or "").strip()
    if not host:
        raise RuntimeError("telemetry server host is not configured")
    return host, int(remote.get("port") or 15001)


def telemetry_endpoint_reachable(timeout: float) -> bool:
    try:
        with socket.create_connection(telemetry_endpoint(), timeout=timeout):
            return True
    except (OSError, ValueError, json.JSONDecodeError):
        return False


def fire_detector_server_url() -> tuple[str, str]:
    settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    remote = settings.get("mount_agent", {}).get("remote", {})
    upload_url = str(remote.get("media_upload_url") or "").strip()
    parsed = urlsplit(upload_url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("Fire Detector media server URL is not configured")
    return f"{parsed.scheme}://{parsed.netloc}/", str(remote.get("ca_file") or "").strip()


def internet_reachable(timeout: float) -> bool:
    """Treat an HTTPS response from the configured Fire Detector server as online."""
    try:
        server_url, ca_file = fire_detector_server_url()
        context = ssl.create_default_context(cafile=ca_file or None)
        with urlopen(server_url, timeout=timeout, context=context) as response:
            # Any valid HTTP response proves the configured server is reachable.
            return 100 <= response.status <= 599
    except HTTPError:
        # 401/403/404 still prove that the HTTPS server answered us.
        return True
    except (OSError, ValueError, json.JSONDecodeError):
        return False


def beacon_state(status: dict[str, Any], cameras: dict[str, Any],
                 telemetry_connected: bool = True,
                 internet_connected: bool = True) -> tuple[str, str]:
    if not internet_connected:
        return MODE_NETWORK_DISCONNECTED, "internet connection is unavailable"
    if not telemetry_connected:
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
    if not visible_ok and not thermal_ok:
        return MODE_OFF, "both camera streams are missing"
    return MODE_HEALTHY, "all required hardware is ready"


def health_reason(status: dict[str, Any], cameras: dict[str, Any]) -> str | None:
    mode, reason = beacon_state(status, cameras)
    return None if mode == MODE_HEALTHY else reason


def pattern_output(mode: str, elapsed: float) -> bool:
    if mode == MODE_NETWORK_DISCONNECTED:
        return int(elapsed / RAPID_BLINK_SECONDS) % 2 == 0
    if mode == MODE_HEALTHY:
        phase = elapsed % (HEALTHY_PULSE_SECONDS + HEALTHY_PAUSE_SECONDS)
        return phase < HEALTHY_PULSE_SECONDS
    flash_counts = {
        # Keep the indicator visibly alive for general not-ready states. The
        # specific component failures retain their two-through-six flash codes.
        MODE_OFF: 1,
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


def monitor_status(
    stopped: threading.Event,
    base_url: str,
    request_timeout: float,
    publish: Any,
) -> None:
    """Poll telemetry away from the timing-sensitive GPIO driver loop."""
    telemetry_connected = True
    telemetry_failures = 0
    telemetry_successes = 0
    internet_connected = True
    internet_failures = 0
    internet_successes = 0
    next_internet_check = 0.0

    while not stopped.is_set():
        now = time.monotonic()
        if now >= next_internet_check:
            if telemetry_endpoint_reachable(request_timeout):
                telemetry_successes += 1
                telemetry_failures = 0
                if telemetry_successes >= INTERNET_CONFIRMATIONS:
                    telemetry_connected = True
            else:
                telemetry_failures += 1
                telemetry_successes = 0
                if telemetry_failures >= INTERNET_CONFIRMATIONS:
                    telemetry_connected = False

            if internet_reachable(request_timeout):
                internet_successes += 1
                internet_failures = 0
                if internet_successes >= INTERNET_CONFIRMATIONS:
                    internet_connected = True
            else:
                internet_failures += 1
                internet_successes = 0
                if internet_failures >= INTERNET_CONFIRMATIONS:
                    internet_connected = False
            next_internet_check = now + INTERNET_CHECK_SECONDS

        try:
            status = fetch_json(f"{base_url}/api/status", request_timeout)
            cameras = fetch_json(f"{base_url}/api/camera-stream", request_timeout)
            mode, reason = beacon_state(
                status, cameras, telemetry_connected, internet_connected
            )
        except Exception as exc:
            mode = MODE_OFF
            reason = f"telemetry check failed: {exc}"
        publish(mode, reason)
        stopped.wait(STATUS_POLL_SECONDS)


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
    last_reason: str | None = None
    pattern_started = time.monotonic()
    state_lock = threading.Lock()
    current_state = [MODE_OFF, "waiting for the first telemetry sample"]
    last_state_write = 0.0
    last_written_state: tuple[str, str] | None = None

    def publish(mode: str, reason: str) -> None:
        nonlocal last_state_write, last_written_state
        with state_lock:
            current_state[:] = [mode, reason]
        now = time.monotonic()
        signature = (mode, reason)
        if signature != last_written_state or now - last_state_write >= 1.0:
            try:
                write_beacon_state(mode, reason)
                last_state_write = now
                last_written_state = signature
            except OSError as exc:
                LOG.warning("cannot publish beacon status: %s", exc)

    monitor = threading.Thread(
        target=monitor_status,
        args=(stopped, args.base_url, args.request_timeout, publish),
        name="beacon-status-monitor",
        daemon=True,
    )
    monitor.start()
    next_tick = time.monotonic()

    try:
        while not stopped.is_set():
            now = time.monotonic()
            with state_lock:
                mode, reason = current_state
            if mode != last_mode:
                pattern_started = now
                LOG.info("beacon mode=%s: %s", mode, reason)
                last_mode = mode
            elif reason != last_reason:
                LOG.info("beacon mode=%s: %s", mode, reason)
            last_reason = reason

            desired_output = pattern_output(mode, now - pattern_started)
            if desired_output != output:
                output = desired_output
                GPIO.output(DO0_BCM_PIN, GPIO.HIGH if output else GPIO.LOW)
            next_tick += LED_TICK_SECONDS
            if next_tick <= now:
                next_tick = now + LED_TICK_SECONDS
            stopped.wait(max(0.0, next_tick - time.monotonic()))
    finally:
        stopped.set()
        monitor.join(timeout=max(args.request_timeout, 0.5))
        GPIO.output(DO0_BCM_PIN, GPIO.LOW)
        GPIO.cleanup(DO0_BCM_PIN)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
