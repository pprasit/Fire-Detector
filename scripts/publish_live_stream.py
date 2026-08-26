#!/usr/bin/env python3
"""Relay a real local camera feed to the remote MediaMTX server."""

from __future__ import annotations

import argparse
import base64
import os
import subprocess
import sys
import urllib.parse


SERVER_HOST = "100.102.91.123"
SERVER_PORT = 8554
LOCAL_STREAM_BASE = "http://127.0.0.1:8000/api/camera-mjpeg/live"
STREAMS = {
    "thermal": {"resolution": "640x512", "bitrate": "2M"},
    "visible": {"resolution": "1920x1080", "bitrate": "4M"},
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
    advertised_path = base64.b64decode(
        os.environ[f"{camera.upper()}_PATH_B64"], validate=True
    ).decode()
    if advertised_path.strip("/") not in (camera, expected_path.strip("/")):
        raise RuntimeError(f"Credential response contains an unexpected {camera} stream path.")

    authority = (
        f"{urllib.parse.quote(username, safe='')}:{urllib.parse.quote(password, safe='')}"
        f"@{SERVER_HOST}:{SERVER_PORT}"
    )
    publish_url = f"rtsp://{authority}{expected_path}"
    config = STREAMS[camera]
    source_url = f"{LOCAL_STREAM_BASE}/{camera}"
    command = [
        "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "warning",
        "-fflags", "nobuffer", "-flags", "low_delay", "-i", source_url,
        "-an", "-vf", f"fps=15,scale={config['resolution']}:force_original_aspect_ratio=decrease,"
        f"pad={config['resolution']}:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
        "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
        "-profile:v", "baseline", "-pix_fmt", "yuv420p", "-r", "15",
        "-bf", "0", "-g", "15", "-keyint_min", "15", "-sc_threshold", "0",
        "-b:v", config["bitrate"], "-maxrate", config["bitrate"],
        "-bufsize", config["bitrate"], "-f", "rtsp", "-rtsp_transport", "tcp", publish_url,
    ]
    print(f"Relaying real {camera} camera frames to MediaMTX over RTSP/TCP.", flush=True)
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    assert process.stderr is not None
    for line in process.stderr:
        sys.stderr.write(sanitized(line, (username, password, publish_url)))
        sys.stderr.flush()
    return process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
