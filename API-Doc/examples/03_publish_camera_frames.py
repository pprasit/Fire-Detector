#!/usr/bin/env python3
"""Publish encoded camera frames over HTTP (simple compatibility example)."""

from __future__ import annotations

import argparse
import http.client
import json
from pathlib import Path
import time


def publish(host: str, port: int, camera: str, frame_path: Path, fps: float) -> None:
    frame = frame_path.read_bytes()
    mime_type = "image/png" if frame_path.suffix.lower() == ".png" else "image/jpeg"
    sequence = 0
    next_frame = time.monotonic()
    while True:
        sequence += 1
        connection = http.client.HTTPConnection(host, port, timeout=5)
        metadata = json.dumps({
            "producer_sequence": sequence,
            "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }, separators=(",", ":"))
        connection.request(
            "POST",
            f"/api/camera-stream/frame/{camera}?source=live",
            frame,
            {"Content-Type": mime_type, "X-Camera-Metadata": metadata},
        )
        response = connection.getresponse()
        body = response.read()
        connection.close()
        if response.status != 202:
            raise RuntimeError(f"Frame rejected: HTTP {response.status}: {body.decode(errors='replace')}")
        next_frame += 1.0 / fps
        time.sleep(max(0.0, next_frame - time.monotonic()))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="192.168.1.105")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--camera", choices=("thermal", "visible"), required=True)
    parser.add_argument("--frame", type=Path, required=True)
    parser.add_argument("--fps", type=float, default=60.0)
    args = parser.parse_args()
    if not 0 < args.fps <= 120:
        parser.error("--fps must be between 0 and 120")
    publish(args.host, args.port, args.camera, args.frame, args.fps)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
