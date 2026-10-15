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
from typing import Any

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
RTSP_SOCKET_BUFFER_BYTES = 64 * 1024
RTSP_IO_TIMEOUT_US = 3 * 1_000_000
# Live observation must prefer a gap over stale video.  A congested TCP
# publisher is replaced before its ordered send queue can become seconds old.
RTSP_SEND_QUEUE_LIMIT_BYTES = 64 * 1024
RTSP_SEND_QUEUE_RECOVERY_BYTES = 16 * 1024
RTSP_QUEUE_POLL_SECONDS = 0.5
RTSP_QUEUE_FAILURE_LIMIT = 2
PROGRESS_STALL_SECONDS = 3.0
PUBLISHER_START_GRACE_SECONDS = 5.0
RECONNECT_BACKOFF_MIN_SECONDS = 2.0
RECONNECT_BACKOFF_MAX_SECONDS = 60.0
RECONNECT_STABLE_RESET_SECONDS = 60.0
CAPACITY_RECHECK_SECONDS = 15.0
ADAPTIVE_UPGRADE_STABLE_SECONDS = 180.0
LOCAL_NETWORK_THROUGHPUT_URL = "http://127.0.0.1:8000/api/network/throughput"
FRAME_RATE_STEPS = (15, 12, 10, 8, 5, 3)
TARGET_FRAME_RATE = FRAME_RATE_STEPS[0]
UPLOAD_UTILIZATION_LIMIT = 0.80
CONTROL_RESERVE_KBPS = 150.0
STREAM_POLICY_STATE_DIR = Path("/run/fire-detector")
CAMERA_STATUS_URL = "http://127.0.0.1:8000/api/camera-stream"


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


def write_stream_health_state(camera: str, payload: dict[str, Any]) -> None:
    """Atomically expose per-camera publisher progress without credentials."""
    state = {"camera": camera, **payload, "updated_at": time.time()}
    try:
        STREAM_POLICY_STATE_DIR.mkdir(parents=True, exist_ok=True)
        target = STREAM_POLICY_STATE_DIR / f"stream-health-{camera}.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, separators=(",", ":")), encoding="utf-8")
        temporary.replace(target)
    except OSError:
        return


def camera_capture_health(camera: str, timeout: float = 1.0) -> dict[str, Any]:
    """Check actual latest-frame progress in the Station pool, not camera flags alone."""
    try:
        request = urllib.request.Request(CAMERA_STATUS_URL, headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
        state = payload["sources"]["live"]["cameras"][camera]
        age_ms = float(state["age_ms"])
        return {
            "fresh": bool(state.get("connected")) and age_ms < 5_000,
            "age_ms": round(age_ms, 1),
            "sequence": int(state["sequence"]),
        }
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return {"fresh": False, "age_ms": None, "sequence": None}


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


def rtsp_socket_stats(pid: int) -> dict[str, int] | None:
    """Return actual RTSP/TCP session queue and cumulative sent bytes for FFmpeg."""
    try:
        result = subprocess.run(
            [
                "ss", "-Htinp", "dst", SERVER_HOST,
                "dport", "=", f":{SERVER_PORT}",
            ],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    lines = result.stdout.splitlines()
    for index, line in enumerate(lines):
        if re.search(rf"\bpid={pid},", line):
            fields = line.split()
            if len(fields) >= 3:
                try:
                    stats = {"send_queue_bytes": int(fields[2]), "bytes_sent": 0}
                except ValueError:
                    return None
                detail = lines[index + 1] if index + 1 < len(lines) else ""
                match = re.search(r"\bbytes_sent:(\d+)", detail)
                if match:
                    stats["bytes_sent"] = int(match.group(1))
                return stats
    return None


def rtsp_send_queue_bytes(pid: int) -> int | None:
    """Compatibility wrapper used by policy tests and callers."""
    stats = rtsp_socket_stats(pid)
    return None if stats is None else stats["send_queue_bytes"]


class ProgressTracker:
    """Thread-safe FFmpeg encoded-frame progress."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.frames = 0
        self.last_frame_at: float | None = None

    def update(self, key: str, value: str) -> None:
        if key != "frame":
            return
        try:
            frames = int(value)
        except ValueError:
            return
        with self._lock:
            if frames > self.frames:
                self.frames = frames
                self.last_frame_at = time.time()

    def snapshot(self) -> tuple[int, float | None]:
        with self._lock:
            return self.frames, self.last_frame_at


def read_ffmpeg_progress(stream: Any, tracker: ProgressTracker) -> None:
    for raw_line in stream:
        key, separator, value = raw_line.strip().partition("=")
        if separator:
            tracker.update(key, value)


def publisher_stall_reason(
    uptime: float,
    progress_age: float,
    capture_fresh: bool,
) -> str | None:
    if uptime < PUBLISHER_START_GRACE_SECONDS or progress_age < PROGRESS_STALL_SECONDS:
        return None
    return "output_stall" if capture_fresh else "capture_stall"


def monitor_rtsp_policy(
    process: subprocess.Popen[str],
    stopped: threading.Event,
    action: dict[str, str | int | None],
    frame_rate: int,
    profile: str,
    initial_capacity_limit: int,
    progress: ProgressTracker,
) -> None:
    """Adapt policy and replace a publisher when frames or network bytes stall."""
    consecutive_over_limit = 0
    started = time.monotonic()
    stable_since = started
    last_progress = started
    last_frames = 0
    last_bytes_sent = 0
    capacity_limit = initial_capacity_limit
    next_capacity_check = 0.0
    while process.poll() is None and not stopped.wait(RTSP_QUEUE_POLL_SECONDS):
        now = time.monotonic()
        if now >= next_capacity_check:
            capacity_limit = recommended_frame_rate(measured_upload_capacity(), profile)
            next_capacity_check = now + CAPACITY_RECHECK_SECONDS
        socket_stats = rtsp_socket_stats(process.pid)
        queued = None if socket_stats is None else socket_stats["send_queue_bytes"]
        bytes_sent = 0 if socket_stats is None else socket_stats["bytes_sent"]
        frames, last_frame_at = progress.snapshot()
        if frames > last_frames or bytes_sent > last_bytes_sent:
            last_progress = now
        last_frames = max(last_frames, frames)
        last_bytes_sent = max(last_bytes_sent, bytes_sent)
        capture = camera_capture_health(str(action.get("camera") or "unknown"))
        progress_age = now - last_progress
        write_stream_health_state(str(action.get("camera") or "unknown"), {
            "state": "publishing" if socket_stats is not None else "connecting",
            "publisher_pid": process.pid,
            "rtsp_session_active": socket_stats is not None,
            "encoded_frames": frames,
            "bytes_sent": bytes_sent,
            "send_queue_bytes": queued,
            "last_frame_at": last_frame_at,
            "progress_age_seconds": round(progress_age, 1),
            "capture": capture,
        })
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
        stall_reason = publisher_stall_reason(now - started, progress_age, capture["fresh"])
        if stall_reason is not None:
            reason = stall_reason
            action.update(reason=reason, target_frame_rate=frame_rate)
            sys.stderr.write(
                f"{camera_label(action)} watchdog: no encoded-frame or RTSP-byte progress "
                f"for {progress_age:.1f}s; restarting {reason.replace('_', ' ')} pipeline.\n"
            )
            sys.stderr.flush()
            process.terminate()
            return
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


def camera_label(action: dict[str, str | int | None]) -> str:
    return str(action.get("camera") or "unknown").capitalize()


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
        "-stats_period", "1", "-progress", "pipe:1",
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
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert process.stderr is not None
    assert process.stdout is not None
    progress = ProgressTracker()
    progress_reader = threading.Thread(
        target=read_ffmpeg_progress,
        args=(process.stdout, progress),
        name=f"{camera}-ffmpeg-progress",
        daemon=True,
    )
    progress_reader.start()
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
            progress,
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
        progress_reader.join(timeout=1.0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera", required=True, choices=tuple(STREAMS))
    parser.add_argument("--profile", choices=tuple(STREAM_PROFILES), default=None)
    parser.add_argument("--once", action="store_true", help=argparse.SUPPRESS)
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
    backoff = RECONNECT_BACKOFF_MIN_SECONDS
    reconnects = 0
    while True:
        started = time.monotonic()
        write_stream_health_state(camera, {
            "state": "fetching_credentials",
            "reconnects": reconnects,
            "rtsp_session_active": False,
        })
        try:
            capacity_limit = recommended_frame_rate(measured_upload_capacity(), profile)
            return_code, action = run_publisher(camera, profile, frame_rate, capacity_limit)
        except Exception as exc:
            # Exception messages are deliberately endpoint/status only; request headers and
            # credential material are never logged.
            sys.stderr.write(
                f"{camera.capitalize()} publisher setup failed: {exc}; retrying in {backoff:.0f}s.\n"
            )
            sys.stderr.flush()
            write_stream_health_state(camera, {
                "state": "credential_retry",
                "reconnects": reconnects,
                "rtsp_session_active": False,
                "retry_in_seconds": backoff,
                "error": type(exc).__name__,
            })
            if args.once:
                return 1
            time.sleep(backoff)
            backoff = min(backoff * 2, RECONNECT_BACKOFF_MAX_SECONDS)
            reconnects += 1
            continue
        reason = action.get("reason")
        if args.once:
            return return_code
        uptime = time.monotonic() - started
        if uptime >= RECONNECT_STABLE_RESET_SECONDS:
            backoff = RECONNECT_BACKOFF_MIN_SECONDS
        sys.stderr.write(
            f"{camera.capitalize()} publisher exited code={return_code} reason={reason or 'process_exit'}; "
            f"requesting fresh credentials and retrying in {backoff:.0f}s.\n"
        )
        sys.stderr.flush()
        write_stream_health_state(camera, {
            "state": "reconnecting",
            "reconnects": reconnects,
            "rtsp_session_active": False,
            "last_exit_code": return_code,
            "reason": reason or "process_exit",
            "retry_in_seconds": backoff,
        })
        target_frame_rate = int(action.get("target_frame_rate") or frame_rate)
        frame_rate = target_frame_rate
        if reason == "backlog" and frame_rate == FRAME_RATE_STEPS[-1]:
            sys.stderr.write("Adaptive policy reached minimum 3 FPS; reconnecting with a clean queue.\n")
            sys.stderr.flush()
        time.sleep(backoff)
        backoff = min(backoff * 2, RECONNECT_BACKOFF_MAX_SECONDS)
        reconnects += 1


if __name__ == "__main__":
    raise SystemExit(main())
