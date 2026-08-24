#!/usr/bin/env python3
"""Generate and ingest simulated fire events over a configurable time window."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import hmac
import http.client
import json
import os
from pathlib import Path
import random
import ssl
import subprocess
import tempfile
import time
from urllib.parse import urlsplit


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SETTINGS = PROJECT_ROOT / "AppSetting.JSON"
MAX_VIDEO_BYTES = 100 * 1024 * 1024


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_config(args: argparse.Namespace) -> tuple[str, str, bytes, str]:
    settings = json.loads(args.settings.read_text(encoding="utf-8"))
    remote = settings.get("mount_agent", {}).get("remote", {})
    device_id = args.device_id or str(remote.get("device_id") or "")
    configured_url = str(remote.get("media_upload_url") or "")
    base_url = args.server or (configured_url.split("/api/", 1)[0] if "/api/" in configured_url else "")
    secret_file = args.secret_file or Path(str(remote.get("secret_file") or ""))
    secret_env = args.secret_env or str(remote.get("secret_env") or "")
    ca_file = args.ca or str(remote.get("ca_file") or "")
    secret = os.environ.get(secret_env, "").encode() if secret_env else b""
    if not secret and secret_file.is_file():
        secret = secret_file.read_bytes().strip()
    if not device_id or not base_url or not secret:
        raise RuntimeError("device_id, server URL, and shared secret must be configured")
    return device_id, base_url.rstrip("/"), secret, ca_file


def signed_headers(device_id: str, secret: bytes, method: str, path: str, body_hash: str) -> dict[str, str]:
    timestamp = utc_now()
    canonical = "\n".join((device_id, method, path, timestamp, body_hash))
    signature = hmac.new(secret, canonical.encode(), hashlib.sha256).hexdigest()
    return {
        "X-Narit-Device-Id": device_id,
        "X-Narit-Timestamp": timestamp,
        "X-Narit-Body-SHA256": body_hash,
        "X-Narit-Signature": signature,
    }


def connection_for(base_url: str, ca_file: str, timeout: float) -> tuple[http.client.HTTPConnection, str]:
    parsed = urlsplit(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError(f"invalid server URL: {base_url}")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    prefix = parsed.path.rstrip("/")
    if parsed.scheme == "https":
        context = ssl.create_default_context(cafile=ca_file or None)
        return http.client.HTTPSConnection(parsed.hostname, port, timeout=timeout, context=context), prefix
    return http.client.HTTPConnection(parsed.hostname, port, timeout=timeout), prefix


def read_response(response: http.client.HTTPResponse) -> object:
    body = response.read()
    if not 200 <= response.status < 300:
        raise RuntimeError(f"server returned HTTP {response.status}: {body[:1000].decode(errors='replace')}")
    return json.loads(body) if body else {}


def upload_video(base_url: str, ca_file: str, device_id: str, secret: bytes,
                 event_id: str, camera: str, video: Path, timeout: float) -> object:
    size = video.stat().st_size
    if size > MAX_VIDEO_BYTES:
        raise ValueError(f"{video} is {size} bytes; simulator limit is {MAX_VIDEO_BYTES} bytes")
    path = f"/api/v1/events/{device_id}/{event_id}/media/{camera}"
    digest = file_sha256(video)
    headers = signed_headers(device_id, secret, "PUT", path, digest)
    headers.update({"Content-Type": "video/mp4", "Content-Length": str(size)})
    connection, prefix = connection_for(base_url, ca_file, timeout)
    try:
        connection.putrequest("PUT", prefix + path)
        for name, value in headers.items():
            connection.putheader(name, value)
        connection.endheaders()
        with video.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                connection.send(chunk)
        return read_response(connection.getresponse())
    finally:
        connection.close()


def finalize_event(base_url: str, ca_file: str, device_id: str, secret: bytes,
                   payload: dict[str, object], timeout: float) -> object:
    path = "/api/v1/events"
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    headers = signed_headers(device_id, secret, "POST", path, hashlib.sha256(body).hexdigest())
    headers.update({"Content-Type": "application/json", "Content-Length": str(len(body))})
    connection, prefix = connection_for(base_url, ca_file, timeout)
    try:
        connection.request("POST", prefix + path, body=body, headers=headers)
        return read_response(connection.getresponse())
    finally:
        connection.close()


def make_video(path: Path, camera: str, duration: int, seed: int) -> None:
    # MPEG-4 is broadly available on Raspberry Pi ffmpeg builds and keeps these clips small.
    source = "smptebars=size=640x512:rate=10" if camera == "thermal" else "testsrc2=size=1280x720:rate=15"
    filters = "format=gray,negate" if camera == "thermal" else "eq=saturation=1.25:contrast=1.08"
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
        "-i", source, "-t", str(duration), "-vf", filters, "-c:v", "mpeg4",
        "-q:v", "5", "-metadata", f"comment=simulated-fire-seed-{seed}",
        "-movflags", "+faststart", str(path),
    ]
    subprocess.run(command, check=True)
    if not path.is_file() or path.stat().st_size > MAX_VIDEO_BYTES:
        raise RuntimeError(f"generated video is missing or exceeds 100 MiB: {path}")


def random_payload(event_id: str, station_id: str, detected_at: str, rng: random.Random,
                   duration_ms: int) -> dict[str, object]:
    azimuth_start = round(rng.uniform(0, 350), 1)
    min_temp = round(rng.uniform(35, 60), 1)
    return {
        "event_id": event_id,
        "station_id": station_id,
        "detected_at": detected_at,
        "latitude": round(18.85421 + rng.uniform(-0.008, 0.008), 6),
        "longitude": round(98.95912 + rng.uniform(-0.008, 0.008), 6),
        "area_m2": round(rng.uniform(100, 2500), 1),
        "confidence": round(rng.uniform(0.72, 0.99), 2),
        "severity": rng.choice(("medium", "high", "critical")),
        "title": "Simulated fire detection",
        "summary": "Station integration exercise",
        "azimuth_start_deg": azimuth_start,
        "azimuth_end_deg": round(min(359.9, azimuth_start + rng.uniform(3, 15)), 1),
        "temperature_min_c": min_temp,
        "temperature_max_c": round(rng.uniform(max(90, min_temp + 25), 220), 1),
        "thermal_duration_ms": duration_ms,
        "visible_duration_ms": duration_ms,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, default=DEFAULT_SETTINGS)
    parser.add_argument("--server", help="Base URL, for example https://receiver:8443")
    parser.add_argument("--device-id")
    parser.add_argument("--station-id")
    parser.add_argument("--secret-file", type=Path)
    parser.add_argument("--secret-env")
    parser.add_argument("--ca", help="Receiver CA certificate")
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--window-sec", type=int, default=15 * 60)
    parser.add_argument("--duration-sec", type=int, default=15)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--dry-run", action="store_true", help="Generate a plan and videos without waiting or sending")
    args = parser.parse_args()
    if args.count < 1 or args.window_sec < 0 or not 1 <= args.duration_sec <= 300:
        parser.error("count must be positive, window-sec non-negative, and duration-sec 1..300")

    rng = random.Random(args.seed)
    device_id, base_url, secret, ca_file = load_config(args)
    station_id = args.station_id or device_id
    offsets = sorted(rng.uniform(0, args.window_sec) for _ in range(args.count))
    started = time.monotonic()
    run_tag = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    with tempfile.TemporaryDirectory(prefix="fire-event-sim-") as temp_name:
        temp_dir = Path(temp_name)
        for index, offset in enumerate(offsets, 1):
            event_id = f"fire-sim-{run_tag}-{index:03d}"
            if not args.dry_run:
                time.sleep(max(0.0, started + offset - time.monotonic()))
            detected_at = utc_now()
            payload = random_payload(event_id, station_id, detected_at, rng, args.duration_sec * 1000)
            videos = {camera: temp_dir / f"{event_id}-{camera}.mp4" for camera in ("thermal", "visible")}
            for camera, video in videos.items():
                make_video(video, camera, args.duration_sec, rng.randrange(2**31))
            print(json.dumps({"status": "prepared", "offset_sec": round(offset, 1), "event": payload,
                              "video_bytes": {k: v.stat().st_size for k, v in videos.items()}}, ensure_ascii=False), flush=True)
            if args.dry_run:
                continue
            for camera, video in videos.items():
                upload_video(base_url, ca_file, device_id, secret, event_id, camera, video, args.timeout)
                print(json.dumps({"status": "uploaded", "event_id": event_id, "camera": camera}), flush=True)
            result = finalize_event(base_url, ca_file, device_id, secret, payload, args.timeout)
            print(json.dumps({"status": "finalized", "event_id": event_id, "response": result}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
