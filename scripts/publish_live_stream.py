#!/usr/bin/env python3
"""Relay a real local camera feed to the remote MediaMTX server."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request

from fetch_stream_credentials import fetch_publisher_credentials


SERVER_HOST = "100.102.91.123"
SERVER_PORT = 8554
LOCAL_STREAM_BASE = "http://127.0.0.1:8000/api/camera-mjpeg/live"
STREAMS = {
    "thermal": {"width": 640, "height": 512},
    "visible": {"width": 1920, "height": 1080},
}
STREAM_PROFILES = {
    # The current NARIT path is relayed by Tailscale DERP and has fallen near
    # 2.3 Mbps under load. This profile favors current frames over old queued
    # frames until a direct Tailscale path or SRT ingest is available.
    "relay": {
        "thermal": {"bitrate": "400k", "buffer_size": "200k"},
        "visible": {
            "width": 1280, "height": 720,
            "bitrate": "800k", "buffer_size": "400k",
        },
    },
    # Leave enough headroom for RTSP/TCP, Tailscale and control telemetry on
    # the measured 4.5 Mbps uplink. Keeping the frame rate and resolution
    # unchanged avoids reintroducing the low-cadence failure seen by NARIT.
    "constrained": {
        "thermal": {"bitrate": "1M", "buffer_size": "500k"},
        "visible": {"bitrate": "2500k", "buffer_size": "1250k"},
    },
    "full": {
        "thermal": {"bitrate": "2M", "buffer_size": "1M"},
        "visible": {"bitrate": "4M", "buffer_size": "2M"},
    },
}
DEFAULT_STREAM_PROFILE = "relay"
RTSP_SOCKET_BUFFER_BYTES = 256 * 1024
RTSP_IO_TIMEOUT_US = 10 * 1_000_000
RTSP_SEND_QUEUE_LIMIT_BYTES = 128 * 1024
RTSP_SEND_QUEUE_RECOVERY_BYTES = 32 * 1024
RTSP_QUEUE_POLL_SECONDS = 2.0
RTSP_QUEUE_FAILURE_LIMIT = 3
CAPACITY_RECHECK_SECONDS = 15.0
ADAPTIVE_UPGRADE_STABLE_SECONDS = 180.0
LOCAL_NETWORK_THROUGHPUT_URL = "http://127.0.0.1:8000/api/network/throughput"
FRAME_RATE_STEPS = (15, 12, 10, 8, 5, 3)
TARGET_FRAME_RATE = FRAME_RATE_STEPS[0]
UPLOAD_UTILIZATION_LIMIT = 0.80
CONTROL_RESERVE_KBPS = 150.0
STREAM_POLICY_STATE_DIR = Path("/run/fire-detector")


def sanitized(line: str, secrets: tuple[str, ...]) -> str:
    for secret in secrets:
        if secret:
            line = line.replace(secret, "[REDACTED]")
            line = line.replace(urllib.parse.quote(secret, safe=""), "[REDACTED]")
    return line


def write_stream_policy_state(
    camera: str,
    profile: str,
    frame_rate: int,
    reason: str,
    queued_bytes: int | None = None,
) -> None:
    """Publish the effective cadence for the upstream camera producer."""
    payload = {
        "camera": camera,
        "profile": profile,
        "frame_rate": frame_rate,
        "reason": reason,
        "queue_bytes": queued_bytes,
        "updated_at": time.time(),
    }
    try:
        STREAM_POLICY_STATE_DIR.mkdir(parents=True, exist_ok=True)
        target = STREAM_POLICY_STATE_DIR / f"stream-policy-{camera}.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        temporary.replace(target)
    except OSError:
        return


def selected_profile(value: str | None = None) -> str:
    profile = (value or os.environ.get("NARIT_STREAM_PROFILE") or DEFAULT_STREAM_PROFILE).strip().lower()
    if profile not in STREAM_PROFILES:
        choices = ", ".join(sorted(STREAM_PROFILES))
        raise ValueError(f"Unknown NARIT stream profile {profile!r}; expected one of: {choices}")
    return profile


def bitrate_kbps(value: str) -> float:
    """Convert an FFmpeg bitrate such as 400k or 2.5M to kbit/s."""
    match = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s*([kKmM]?)\s*", value)
    if match is None:
        raise ValueError(f"Unsupported bitrate value: {value!r}")
    amount = float(match.group(1))
    suffix = match.group(2).lower()
    return amount * (1000.0 if suffix == "m" else 1.0)


def scaled_bitrate(value: str, frame_rate: int) -> str:
    """Scale encoder rate with cadence so a lower FPS also lowers uplink use."""
    return f"{max(1, round(bitrate_kbps(value) * frame_rate / TARGET_FRAME_RATE))}k"


def recommended_frame_rate(upload_mbps: float | None, profile: str) -> int:
    """Select the highest safe cadence using a measured manual upload limit."""
    if upload_mbps is None or upload_mbps <= 0:
        return TARGET_FRAME_RATE
    base_total_kbps = sum(
        bitrate_kbps(str(STREAM_PROFILES[profile][camera]["bitrate"]))
        for camera in STREAMS
    )
    video_budget_kbps = max(
        0.0,
        upload_mbps * 1000.0 * UPLOAD_UTILIZATION_LIMIT - CONTROL_RESERVE_KBPS,
    )
    unconstrained_rate = TARGET_FRAME_RATE * video_budget_kbps / base_total_kbps
    return next(
        (step for step in FRAME_RATE_STEPS if step <= unconstrained_rate),
        FRAME_RATE_STEPS[-1],
    )


def measured_upload_capacity(timeout: float = 2.0) -> float | None:
    """Read a recent operator-run capacity result from the local dashboard."""
    try:
        request = urllib.request.Request(
            LOCAL_NETWORK_THROUGHPUT_URL,
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
        if payload.get("capacity_source") != "manual":
            return None
        value = float(payload["estimated_upload_mbps"])
        return value if value > 0 else None
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


def next_lower_frame_rate(frame_rate: int) -> int:
    try:
        index = FRAME_RATE_STEPS.index(frame_rate)
    except ValueError:
        return FRAME_RATE_STEPS[-1]
    return FRAME_RATE_STEPS[min(index + 1, len(FRAME_RATE_STEPS) - 1)]


def next_higher_frame_rate(frame_rate: int) -> int:
    try:
        index = FRAME_RATE_STEPS.index(frame_rate)
    except ValueError:
        return TARGET_FRAME_RATE
    return FRAME_RATE_STEPS[max(index - 1, 0)]


def adaptive_transition(
    frame_rate: int,
    capacity_limit: int,
    queued_bytes: int | None,
    consecutive_over_limit: int,
    stable_seconds: float,
) -> tuple[str, int] | None:
    """Choose a policy transition with fast decrease and slow recovery."""
    if capacity_limit < frame_rate:
        return "capacity", capacity_limit
    if consecutive_over_limit >= RTSP_QUEUE_FAILURE_LIMIT:
        return "backlog", next_lower_frame_rate(frame_rate)
    if (
        queued_bytes is not None
        and queued_bytes <= RTSP_SEND_QUEUE_RECOVERY_BYTES
        and stable_seconds >= ADAPTIVE_UPGRADE_STABLE_SECONDS
        and frame_rate < capacity_limit
    ):
        return "recovery", min(next_higher_frame_rate(frame_rate), capacity_limit)
    return None


def rtsp_send_queue_bytes(pid: int) -> int | None:
    """Return this FFmpeg process's queued RTSP/TCP bytes, if observable."""
    try:
        result = subprocess.run(
            [
                "ss", "-Htnp", "dst", SERVER_HOST,
                "dport", "=", f":{SERVER_PORT}",
            ],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    for line in result.stdout.splitlines():
        if re.search(rf"\bpid={pid},", line):
            fields = line.split()
            if len(fields) >= 3:
                try:
                    return int(fields[2])
                except ValueError:
                    return None
    return None


def monitor_rtsp_policy(
    process: subprocess.Popen[str],
    stopped: threading.Event,
    action: dict[str, str | int | None],
    frame_rate: int,
    profile: str,
    initial_capacity_limit: int,
) -> None:
    """Adapt one publisher using capacity and bounded RTSP queue hysteresis."""
    consecutive_over_limit = 0
    stable_since = time.monotonic()
    capacity_limit = initial_capacity_limit
    next_capacity_check = 0.0
    while process.poll() is None and not stopped.wait(RTSP_QUEUE_POLL_SECONDS):
        now = time.monotonic()
        if now >= next_capacity_check:
            capacity_limit = recommended_frame_rate(measured_upload_capacity(), profile)
            next_capacity_check = now + CAPACITY_RECHECK_SECONDS
        queued = rtsp_send_queue_bytes(process.pid)
        write_stream_policy_state(
            str(action.get("camera") or "unknown"),
            profile,
            frame_rate,
            "steady",
            queued,
        )
        if queued is None:
            consecutive_over_limit = 0
            stable_since = now
        elif queued > RTSP_SEND_QUEUE_LIMIT_BYTES:
            consecutive_over_limit += 1
            stable_since = now
        else:
            consecutive_over_limit = 0
            if queued > RTSP_SEND_QUEUE_RECOVERY_BYTES:
                stable_since = now
        transition = adaptive_transition(
            frame_rate,
            capacity_limit,
            queued,
            consecutive_over_limit,
            now - stable_since,
        )
        if transition is None:
            continue
        reason, target_frame_rate = transition
        action.update(reason=reason, target_frame_rate=target_frame_rate)
        if reason == "backlog":
            sys.stderr.write(
                f"RTSP send queue remained above {RTSP_SEND_QUEUE_LIMIT_BYTES} bytes; "
                f"reducing from {frame_rate} to {target_frame_rate} FPS.\n"
            )
        elif reason == "capacity":
            sys.stderr.write(
                f"Measured upload policy now limits cadence to {target_frame_rate} FPS; "
                f"reducing from {frame_rate} FPS.\n"
            )
        else:
            sys.stderr.write(
                f"RTSP queue stayed below {RTSP_SEND_QUEUE_RECOVERY_BYTES} bytes for "
                f"{ADAPTIVE_UPGRADE_STABLE_SECONDS:.0f}s; cautiously increasing from "
                f"{frame_rate} to {target_frame_rate} FPS.\n"
            )
        sys.stderr.flush()
        process.terminate()
        return


def run_publisher(
    camera: str,
    profile: str,
    frame_rate: int,
    capacity_limit: int,
) -> tuple[int, dict[str, str | int | None]]:
    """Run one credential-scoped FFmpeg connection."""
    credentials, status = fetch_publisher_credentials()
    username = str(credentials["username"])
    password = str(credentials["password"])
    expected_path = f"/iriv-production/{camera}"
    paths = credentials["paths"]
    if not isinstance(paths, dict):
        raise RuntimeError("Credential response does not contain stream paths.")
    advertised_path = str(paths[camera])
    if advertised_path.strip("/") not in (camera, expected_path.strip("/")):
        raise RuntimeError(f"Credential response contains an unexpected {camera} stream path.")

    authority = (
        f"{urllib.parse.quote(username, safe='')}:{urllib.parse.quote(password, safe='')}"
        f"@{SERVER_HOST}:{SERVER_PORT}"
    )
    publish_url = f"rtsp://{authority}{expected_path}"
    config = {**STREAMS[camera], **STREAM_PROFILES[profile][camera]}
    width = config["width"]
    height = config["height"]
    bitrate = scaled_bitrate(str(config["bitrate"]), frame_rate)
    buffer_size = scaled_bitrate(str(config["buffer_size"]), frame_rate)
    source_url = f"{LOCAL_STREAM_BASE}/{camera}"
    command = [
        "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "warning",
        "-fflags", "nobuffer", "-flags", "low_delay", "-i", source_url,
        "-an", "-vf", f"fps={frame_rate},scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
        "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
        "-profile:v", "baseline", "-pix_fmt", "yuv420p", "-r", str(frame_rate),
        "-bf", "0", "-g", str(frame_rate), "-keyint_min", str(frame_rate), "-sc_threshold", "0",
        "-b:v", bitrate, "-maxrate", bitrate,
        "-bufsize", buffer_size,
        "-flush_packets", "1", "-muxdelay", "0", "-muxpreload", "0",
        "-rw_timeout", str(RTSP_IO_TIMEOUT_US),
        "-buffer_size", str(RTSP_SOCKET_BUFFER_BYTES),
        "-f", "rtsp", "-rtsp_transport", "tcp", publish_url,
    ]
    print(
        f"Publisher credential endpoint HTTP {status}; relaying real {camera} camera "
        f"frames to MediaMTX over bounded RTSP/TCP profile={profile} "
        f"fps={frame_rate} bitrate={bitrate}.",
        flush=True,
    )
    write_stream_policy_state(camera, profile, frame_rate, "publisher_start", 0)
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    assert process.stderr is not None
    watchdog_stopped = threading.Event()
    watchdog_action: dict[str, str | int | None] = {
        "camera": camera,
        "reason": None,
        "target_frame_rate": None,
    }
    watchdog = threading.Thread(
        target=monitor_rtsp_policy,
        args=(
            process,
            watchdog_stopped,
            watchdog_action,
            frame_rate,
            profile,
            capacity_limit,
        ),
        name=f"{camera}-adaptive-stream-policy",
        daemon=True,
    )
    watchdog.start()
    try:
        for line in process.stderr:
            sys.stderr.write(sanitized(line, (username, password, publish_url)))
            sys.stderr.flush()
        return process.wait(), watchdog_action
    finally:
        watchdog_stopped.set()
        watchdog.join(timeout=RTSP_QUEUE_POLL_SECONDS + 0.5)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera", required=True, choices=tuple(STREAMS))
    parser.add_argument("--profile", choices=tuple(STREAM_PROFILES), default=None)
    args = parser.parse_args()
    camera = args.camera
    profile = selected_profile(args.profile)
    upload_capacity = measured_upload_capacity()
    frame_rate = recommended_frame_rate(upload_capacity, profile)
    capacity_label = (
        f"manual upload capacity {upload_capacity:.2f} Mbps"
        if upload_capacity is not None else "no recent manual capacity result"
    )
    print(f"Adaptive stream policy selected {frame_rate} FPS from {capacity_label}.", flush=True)
    while True:
        capacity_limit = recommended_frame_rate(measured_upload_capacity(), profile)
        return_code, action = run_publisher(camera, profile, frame_rate, capacity_limit)
        reason = action.get("reason")
        if reason is None:
            return return_code
        target_frame_rate = int(action.get("target_frame_rate") or frame_rate)
        frame_rate = target_frame_rate
        if reason == "backlog" and frame_rate == FRAME_RATE_STEPS[-1]:
            sys.stderr.write("Adaptive policy reached minimum 3 FPS; reconnecting with a clean queue.\n")
            sys.stderr.flush()


if __name__ == "__main__":
    raise SystemExit(main())
