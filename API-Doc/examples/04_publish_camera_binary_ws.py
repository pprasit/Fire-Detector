#!/usr/bin/env python3
"""Publish encoded frames over the recommended persistent binary WebSocket."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import struct
import time

from websockets.sync.client import connect


def make_message(camera: str, payload: bytes, mime_type: str, sequence: int) -> bytes:
    header = json.dumps({
        "camera": camera,
        "mime_type": mime_type,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "metadata": {
            "producer_sequence": sequence,
            "captured_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        },
    }, separators=(",", ":")).encode("utf-8")
    return struct.pack(">I", len(header)) + header + payload


def publish(url: str, camera: str, frame_path: Path, fps: float) -> None:
    payload = frame_path.read_bytes()
    mime_type = "image/png" if frame_path.suffix.lower() == ".png" else "image/jpeg"
    interval = 1.0 / fps
    sequence = 0
    while True:
        try:
            # JPEG/PNG is already compressed. WebSocket compression wastes CPU
            # and can prevent high-resolution streams from sustaining 60 FPS.
            with connect(url, open_timeout=5, close_timeout=2, max_size=None, compression=None) as socket:
                next_frame = time.monotonic()
                while True:
                    sequence += 1
                    socket.send(make_message(camera, payload, mime_type, sequence))
                    next_frame += interval
                    time.sleep(max(0.0, next_frame - time.monotonic()))
        except (OSError, TimeoutError) as exc:
            print(f"camera relay unavailable ({exc}); reconnecting", flush=True)
            time.sleep(1.0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="ws://192.168.1.105:8000/ws/camera-stream?role=producer&source=live")
    parser.add_argument("--camera", choices=("thermal", "visible"), required=True)
    parser.add_argument("--frame", type=Path, required=True)
    parser.add_argument("--fps", type=float, default=60.0)
    args = parser.parse_args()
    if not 0 < args.fps <= 120:
        parser.error("--fps must be between 0 and 120")
    publish(args.url, args.camera, args.frame, args.fps)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
