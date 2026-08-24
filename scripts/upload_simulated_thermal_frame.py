#!/usr/bin/env python3
"""Upload simulated Station camera frames and notify the receiver."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import hmac
from io import BytesIO
import json
from pathlib import Path
import secrets
import socket
import ssl
import time
import urllib.request
import uuid
import sys

from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from fire_detector.camera_overlay import burn_camera_overlay  # noqa: E402
SETTINGS_PATH = PROJECT_ROOT / "AppSetting.JSON"
DEFAULT_FRAMES = {
    "thermal": PROJECT_ROOT / "data" / "simulated_camera" / "thermal-sip30-150-sample.png",
    "visible": PROJECT_ROOT / "data" / "simulated_camera" / "visible-khao-sok-sample.jpg",
}
LOCAL_SOCKET = "/run/fire-detector/mount-agent.sock"
MISSION_CAMERA_STATE = PROJECT_ROOT / "data" / "mission" / "camera.json"
STREAM_STARTED_MONOTONIC = time.monotonic()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def simulated_zoom_frame(frame_path: Path, camera: str, phase_seconds: float, zoom_override: float | None = None) -> tuple[bytes, int, int, float]:
    """Render the Station-side 1x -> 5x -> 1x digital-zoom simulation."""
    cycle_progress = (phase_seconds % 40.0) / 20.0
    zoom = zoom_override if zoom_override is not None else 1.0 + 4.0 * (cycle_progress if cycle_progress <= 1.0 else 2.0 - cycle_progress)
    with Image.open(frame_path) as source:
        frame = source.convert("RGB")
        source_width, source_height = frame.size
        crop_width = max(2, round(source_width / zoom))
        crop_height = max(2, round(source_height / zoom))
        left = (source_width - crop_width) // 2
        top = (source_height - crop_height) // 2
        width, height = (640, 512) if camera == "thermal" else (1280, 720)
        frame = frame.crop((left, top, left + crop_width, top + crop_height)).resize(
            (width, height), Image.Resampling.LANCZOS,
        )
        frame = burn_camera_overlay(
            frame,
            captured_at=datetime.now(timezone.utc),
            elapsed_sec=time.monotonic() - STREAM_STARTED_MONOTONIC,
            zoom_x=zoom,
        )
    output = BytesIO()
    frame.save(output, format="JPEG", quality=82, optimize=True)
    return output.getvalue(), width, height, zoom


def multipart_body(metadata: bytes, image: bytes, mime_type: str, filename: str) -> tuple[bytes, str]:
    boundary = f"----narit-{secrets.token_hex(16)}"
    chunks = [
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"metadata\"\r\nContent-Type: application/json; charset=utf-8\r\n\r\n".encode(),
        metadata,
        b"\r\n",
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"frame\"; filename=\"{filename}\"\r\nContent-Type: {mime_type}\r\n\r\n".encode(),
        image,
        f"\r\n--{boundary}--\r\n".encode(),
    ]
    return b"".join(chunks), boundary


def notify_mount_agent(payload: dict[str, object]) -> dict[str, object]:
    message = {
        "version": "1.0",
        "type": "command",
        "message_id": str(uuid.uuid4()),
        "action": "camera.publish_frame_ready",
        "params": payload,
    }
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.connect(LOCAL_SOCKET)
        client.sendall(json.dumps(message, separators=(",", ":")).encode() + b"\n")
        response = bytearray()
        while b"\n" not in response:
            chunk = client.recv(8192)
            if not chunk:
                raise ConnectionError("Mount Agent closed the local connection.")
            response.extend(chunk)
    result = json.loads(response.partition(b"\n")[0])
    if not result.get("ok"):
        raise RuntimeError(f"Mount Agent rejected frame notification: {result}")
    return result


def upload_once(camera: str, frame_path: Path, sequence: int) -> dict[str, str]:
    settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    remote = settings["mount_agent"]["remote"]
    upload_url = str(remote.get("media_upload_url") or "")
    secret_path = Path(str(remote.get("secret_file") or ""))
    ca_file = str(remote.get("ca_file") or "")
    device_id = str(remote["device_id"])
    if not upload_url or not secret_path.is_file() or not ca_file:
        raise RuntimeError("media_upload_url, secret_file, and ca_file must be configured.")

    zoom_override = None
    try:
        mission_camera = json.loads(MISSION_CAMERA_STATE.read_text(encoding="utf-8"))
        zoom_override = float(mission_camera[f"{camera}_zoom_x"])
    except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        pass
    image, width, height, zoom = simulated_zoom_frame(frame_path, camera, time.time(), zoom_override)
    if len(image) > 10 * 1024 * 1024:
        raise RuntimeError("Frame exceeds the server's 10 MiB upload limit.")
    expected_size = (640, 512) if camera == "thermal" else (1280, 720)
    if (width, height) != expected_size:
        raise RuntimeError(f"The simulated {camera} frame must be {expected_size[0]}x{expected_size[1]}.")

    timestamp = utc_now()
    frame_id = f"{'th' if camera == 'thermal' else 'vis'}-sim-{sequence:06d}"
    metadata = {
        "device_id": device_id,
        "camera": camera,
        "frame_id": frame_id,
        "storage_mode": "latest",
        "rotation_deg": 0,
        "captured_at_utc": timestamp,
        "width": width,
        "height": height,
        "simulated": True,
        "zoom_x": round(zoom, 3),
    }
    if camera == "thermal":
        metadata.update({
            "horizontal_fov_deg": 14.2,
            "vertical_fov_deg": 11.4,
            "palette": "iron",
            "temperature_measurement": "min_max",
            "temperature_min_c": 24.6,
            "temperature_max_c": 41.2,
        })
    else:
        metadata.update({
            "horizontal_fov_deg": 62.0,
            "vertical_fov_deg": 36.0,
            "focus_position": 0.72,
        })
    metadata_bytes = json.dumps(metadata, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    metadata_sha = sha256_hex(metadata_bytes)
    frame_sha = sha256_hex(image)
    signing_text = "\n".join((device_id, "POST", "/api/v1/media/upload", timestamp, metadata_sha, frame_sha))
    signature = hmac.new(secret_path.read_bytes().strip(), signing_text.encode("utf-8"), hashlib.sha256).hexdigest()
    mime_type = "image/jpeg"
    body, boundary = multipart_body(metadata_bytes, image, mime_type, f"{camera}-latest.jpg")

    request = urllib.request.Request(upload_url, data=body, method="POST", headers={
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "X-Narit-Device-Id": device_id,
        "X-Narit-Timestamp": timestamp,
        "X-Narit-Metadata-SHA256": metadata_sha,
        "X-Narit-Frame-SHA256": frame_sha,
        "X-Narit-Signature": signature,
    })
    context = ssl.create_default_context(cafile=ca_file)
    with urllib.request.urlopen(request, context=context, timeout=30) as response:
        upload_result = json.loads(response.read().decode("utf-8"))
    if upload_result.get("frame_id") != frame_id or upload_result.get("sha256") != frame_sha:
        raise RuntimeError("Server upload response did not match the uploaded frame.")

    notification = dict(metadata)
    notification.update({"mime_type": mime_type, "sha256": frame_sha, "storage_url": upload_result["storage_url"]})
    notify_mount_agent(notification)
    return {"frame_id": frame_id, "storage_url": upload_result["storage_url"], "sha256": frame_sha}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera", choices=("thermal", "visible"), default="thermal")
    parser.add_argument("--frame", type=Path)
    parser.add_argument("--loop", action="store_true", help="Upload continuously using latest-file storage mode.")
    parser.add_argument("--interval", type=float, default=1.0, help="Seconds between frames in --loop mode.")
    args = parser.parse_args()
    if args.interval < 0.2:
        parser.error("--interval must be at least 0.2 seconds.")
    frame_path = args.frame or DEFAULT_FRAMES[args.camera]
    sequence = 1
    while True:
        started = time.monotonic()
        try:
            result = upload_once(args.camera, frame_path, sequence)
            print(json.dumps(result, separators=(",", ":")), flush=True)
            sequence += 1
        except Exception as exc:
            print(f"thermal simulated upload failed: {exc}", flush=True)
        if not args.loop:
            return 0
        time.sleep(max(0.0, args.interval - (time.monotonic() - started)))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
