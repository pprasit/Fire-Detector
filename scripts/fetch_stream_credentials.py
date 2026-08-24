#!/usr/bin/env python3
"""Fetch short-lived MediaMTX publisher credentials without logging secrets."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import base64
import json
import os
from pathlib import Path
import ssl
import tempfile
import urllib.error
import urllib.request


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SETTINGS_PATH = PROJECT_ROOT / "AppSetting.JSON"
CREDENTIAL_PATH = Path("/run/fire-detector-stream/publisher.env")
API_PATH = "/api/v1/stream/publisher-credentials"
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def main() -> int:
    remote = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))["mount_agent"]["remote"]
    device_id = str(remote["device_id"])
    timestamp = utc_now()
    canonical = "\n".join((device_id, "GET", API_PATH, timestamp, EMPTY_SHA256))
    secret = Path(str(remote["secret_file"])).read_bytes().strip()
    signature = hmac.new(secret, canonical.encode("utf-8"), hashlib.sha256).hexdigest()
    base_url = str(remote["media_upload_url"]).split("/api/", 1)[0].rstrip("/")
    request = urllib.request.Request(base_url + API_PATH, method="GET", headers={
        "X-Narit-Device-Id": device_id,
        "X-Narit-Timestamp": timestamp,
        "X-Narit-Body-SHA256": EMPTY_SHA256,
        "X-Narit-Signature": signature,
    })
    context = ssl.create_default_context(cafile=str(remote["ca_file"]))
    try:
        with urllib.request.urlopen(request, context=context, timeout=10) as response:
            payload = json.loads(response.read())
            status = response.status
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Publisher credential endpoint returned HTTP {exc.code}.") from exc

    if status != 200:
        raise RuntimeError(f"Publisher credential endpoint returned HTTP {status}.")
    if payload.get("device_id") != device_id:
        raise RuntimeError("Publisher credential response device_id mismatch.")
    if not all(isinstance(payload.get(field), str) and payload[field] for field in ("username", "password")):
        raise RuntimeError("Publisher credential response is incomplete.")
    paths = payload.get("paths")
    if not isinstance(paths, dict) or not all(isinstance(paths.get(camera), str) for camera in ("thermal", "visible")):
        raise RuntimeError("Publisher credential response does not contain both stream paths.")

    CREDENTIAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".publisher-credentials.", dir=CREDENTIAL_PATH.parent)
    try:
        os.fchmod(fd, 0o600)
        encoded = {
            "PUBLISHER_USERNAME_B64": base64.b64encode(payload["username"].encode()).decode(),
            "PUBLISHER_PASSWORD_B64": base64.b64encode(payload["password"].encode()).decode(),
            "THERMAL_PATH_B64": base64.b64encode(paths["thermal"].encode()).decode(),
            "VISIBLE_PATH_B64": base64.b64encode(paths["visible"].encode()).decode(),
        }
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            for name, value in encoded.items():
                output.write(f"{name}={value}\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, CREDENTIAL_PATH)
        os.chmod(CREDENTIAL_PATH, 0o600)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print(f"Publisher credential endpoint HTTP {status}; credentials stored securely.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
