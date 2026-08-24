#!/usr/bin/env python3
"""Publish a simulated camera stream to MediaMTX without exposing credentials in logs."""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import sys
import urllib.parse


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = Path("/run/fire-detector-stream")
SERVER_HOST = "100.102.91.123"
SERVER_PORT = 8554
SOURCES = {
    "thermal": PROJECT_ROOT / "web" / "static" / "video" / "thermal-zoom-simulation.mp4",
    "visible": PROJECT_ROOT / "web" / "static" / "video" / "visible-zoom-simulation.mp4",
}
STREAMS = {
    "thermal": {"resolution": "640x512", "bitrate": "2M"},
    "visible": {"resolution": "1280x720", "bitrate": "3M"},
}


def sanitized(line: str, secrets: tuple[str, ...]) -> str:
    for secret in secrets:
        if secret:
            line = line.replace(secret, "[REDACTED]")
            line = line.replace(urllib.parse.quote(secret, safe=""), "[REDACTED]")
    return line


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera", required=True, choices=tuple(STREAMS))
    args = parser.parse_args()
    camera = args.camera
    username = base64.b64decode(os.environ["PUBLISHER_USERNAME_B64"], validate=True).decode()
    password = base64.b64decode(os.environ["PUBLISHER_PASSWORD_B64"], validate=True).decode()
    expected_path = f"/iriv-production/{camera}"
    advertised_path = base64.b64decode(os.environ[f"{camera.upper()}_PATH_B64"], validate=True).decode()
    if advertised_path.strip("/") not in (camera, expected_path.strip("/")):
        raise RuntimeError(f"Credential response contains an unexpected {camera} stream path.")
    authority = f"{urllib.parse.quote(username, safe='')}:{urllib.parse.quote(password, safe='')}@{SERVER_HOST}:{SERVER_PORT}"
    publish_url = f"rtsp://{authority}{expected_path}"

    config = STREAMS[camera]
    start_epoch = datetime.now(timezone.utc).timestamp()
    source_phase_sec = start_epoch % 40.0
    overlay_path = RUNTIME_DIR / f"{camera}-overlay.txt"
    overlay_path.write_text(
        "ELAPSED %{pts:hms}\n"
        f"UTC %{{pts:gmtime:{start_epoch:.3f}:%Y-%m-%d %H\\:%M\\:%S}}\n"
        "ZOOM %{expr:1+4*(1-abs(mod(t,40)-20)/20)}x\n"
        f"RES {config['resolution']}",
        encoding="utf-8",
    )
    font = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
    video_filter = (
        f"fps=15,scale={config['resolution']},format=yuv420p,"
        f"drawtext=fontfile={font}:textfile={overlay_path}:fontcolor=white:fontsize=15:"
        "box=1:boxcolor=black@0.36:boxborderw=6:x=10:y=10"
    )
    command = [
        "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "warning",
        "-re", "-stream_loop", "-1", "-ss", f"{source_phase_sec:.3f}", "-i", str(SOURCES[camera]),
        "-an", "-vf", video_filter,
        "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
        "-profile:v", "baseline", "-pix_fmt", "yuv420p", "-r", "15",
        "-bf", "0", "-g", "15", "-keyint_min", "15", "-sc_threshold", "0",
        "-b:v", config["bitrate"], "-maxrate", config["bitrate"], "-bufsize", config["bitrate"],
        "-f", "rtsp", "-rtsp_transport", "tcp", publish_url,
    ]
    print(f"Starting {camera} H.264 publisher to MediaMTX over RTSP/TCP.", flush=True)
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    assert process.stderr is not None
    for line in process.stderr:
        sys.stderr.write(sanitized(line, (username, password, publish_url)))
        sys.stderr.flush()
    return process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
