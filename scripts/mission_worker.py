#!/usr/bin/env python3
"""Poll, validate, apply, and acknowledge Server Mission Control revisions."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import random
import ssl
import tempfile
import time
from typing import Any
import urllib.error
import urllib.request


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SETTINGS_PATH = PROJECT_ROOT / "AppSetting.JSON"
STATE_PATH = PROJECT_ROOT / "data" / "mission" / "state.json"
CAMERA_STATE_PATH = PROJECT_ROOT / "data" / "mission" / "camera.json"
LOCAL_API = "http://127.0.0.1:8000"
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
SIMULATED_VISIBLE_ZOOM = (1.0, 5.0)
SIMULATED_THERMAL_ZOOM = (1.0, 5.0)
LOGGER = logging.getLogger("mission-worker")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def atomic_json_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(payload, output, separators=(",", ":"), ensure_ascii=False)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else dict(default)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return dict(default)


class MissionWorker:
    def __init__(self, poll_seconds: float = 3.0, timeout: float = 8.0) -> None:
        settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        self.settings = settings
        remote = settings["mount_agent"]["remote"]
        self.device_id = str(remote["device_id"])
        configured_url = str(remote["media_upload_url"])
        self.base_url = configured_url.split("/api/", 1)[0].rstrip("/")
        self.ca_file = str(remote["ca_file"])
        self.secret = Path(str(remote["secret_file"])).read_bytes().strip()
        if not self.secret:
            raise RuntimeError("The configured shared-secret file is empty.")
        self.context = ssl.create_default_context(cafile=self.ca_file)
        self.poll_seconds = max(2.0, min(poll_seconds, 5.0))
        self.timeout = max(5.0, min(timeout, 10.0))
        self.state = read_json(STATE_PATH, {"applied_revision": None, "acked_revision": None})
        self.survey_target: float | None = None

    @property
    def mission_path(self) -> str:
        return f"/api/v1/missions/{self.device_id}"

    @property
    def ack_path(self) -> str:
        return f"{self.mission_path}/ack"

    def signed_request(self, method: str, path: str, body: bytes = b"") -> tuple[int, dict[str, Any]]:
        timestamp = utc_now()
        body_hash = hashlib.sha256(body).hexdigest()
        canonical = "\n".join((self.device_id, method, path, timestamp, body_hash))
        signature = hmac.new(self.secret, canonical.encode("utf-8"), hashlib.sha256).hexdigest()
        headers = {
            "X-Narit-Device-Id": self.device_id,
            "X-Narit-Timestamp": timestamp,
            "X-Narit-Body-SHA256": body_hash,
            "X-Narit-Signature": signature,
        }
        if body:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.base_url + path, data=body if body else None, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, context=self.context, timeout=self.timeout) as response:
                raw = response.read()
                return response.status, json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1000]
            raise RuntimeError(f"Mission API HTTP {exc.code}: {detail}") from exc

    def local_request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = json.dumps(payload, separators=(",", ":")).encode() if payload is not None else None
        headers = {"Content-Type": "application/json"} if body else {}
        request = urllib.request.Request(LOCAL_API + path, data=body, method=method, headers=headers)
        with urllib.request.urlopen(request, timeout=5) as response:
            result = json.loads(response.read())
        if result.get("ok") is False:
            raise RuntimeError(str(result.get("error") or "Local control request failed."))
        return result

    def validate_zoom(self, label: str, value: Any, limits: tuple[float, float]) -> float:
        try:
            zoom = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} zoom must be numeric.") from exc
        if not limits[0] <= zoom <= limits[1]:
            raise ValueError(f"{label} zoom {zoom:g}x exceeds simulated camera capability {limits[0]:g}x–{limits[1]:g}x.")
        return zoom

    def configure_cameras(self, visible_zoom: Any, thermal_zoom: Any, revision: int, mode: str) -> dict[str, float]:
        visible = self.validate_zoom("Visible", visible_zoom, SIMULATED_VISIBLE_ZOOM)
        thermal = self.validate_zoom("Thermal", thermal_zoom, SIMULATED_THERMAL_ZOOM)
        atomic_json_write(CAMERA_STATE_PATH, {
            "revision": revision,
            "mode": mode,
            "visible_zoom_x": visible,
            "thermal_zoom_x": thermal,
            "updated_at": utc_now(),
        })
        return {"visible_zoom_x": visible, "thermal_zoom_x": thermal}

    def mount_preflight(self, start: float, end: float, speed: float) -> dict[str, Any]:
        limits = self.settings["motion_limits"]
        lower = float(limits["azimuth_ccw_limit_deg"])
        upper = float(limits["azimuth_cw_limit_deg"])
        max_speed = float(limits["slew_rate_deg_per_sec"])
        if not lower <= start <= upper or not lower <= end <= upper:
            raise ValueError(f"Survey range {start:g}°–{end:g}° exceeds Azimuth software limits {lower:g}°–{upper:g}°.")
        if speed <= 0 or speed > max_speed:
            raise ValueError(f"Survey speed {speed:g}°/s is outside 0–{max_speed:g}°/s.")
        status = self.local_request("GET", "/api/status")
        if not status.get("connected") or status.get("health") != "ready" or not status.get("has_bus_power"):
            raise RuntimeError("Mount is not connected, ready, and powered.")
        # CW/CCW are absolute-encoder region sensors, not end stops. The
        # configured Azimuth software limits are validated above and enforced
        # continuously by the Station motion layer.
        axis = next((item for item in status.get("axes", []) if item.get("label") == "Azimuth"), None)
        if not axis or not axis.get("available") or axis.get("active_errors") or axis.get("disarm_reason"):
            raise RuntimeError("Azimuth axis is unavailable or faulted.")
        if status.get("emergency_stop"):
            raise RuntimeError("Emergency stop is active.")
        return status

    def apply_survey(self, mission: dict[str, Any], revision: int) -> dict[str, Any]:
        survey = mission.get("survey") or {}
        start = float(survey["azimuth_start_deg"])
        end = float(survey["azimuth_end_deg"])
        speed = float(survey["pan_speed_deg_s"])
        self.mount_preflight(start, end, speed)
        cameras = self.configure_cameras(survey.get("visible_zoom_x"), survey.get("thermal_zoom_x"), revision, "survey")
        self.local_request("POST", "/api/motors/enable/Azimuth")
        self.local_request("POST", "/api/motors/goto", {"Azimuth": start, "velocity_target_deg_per_sec": speed})
        self.survey_target = start
        return {"motor": f"Survey commanded {start:g}°–{end:g}° at {speed:g}°/s", "cameras": cameras}

    def maintain_survey(self, mission: dict[str, Any]) -> None:
        survey = mission["survey"]
        start, end = float(survey["azimuth_start_deg"]), float(survey["azimuth_end_deg"])
        speed = float(survey["pan_speed_deg_s"])
        status = self.mount_preflight(start, end, speed)
        axis = next(item for item in status["axes"] if item.get("label") == "Azimuth")
        if not axis.get("is_armed"):
            raise RuntimeError("Azimuth disarmed while Survey was active.")
        if axis.get("trajectory_done"):
            target = end if self.survey_target != end else start
            self.local_request("POST", "/api/motors/goto", {"Azimuth": target, "velocity_target_deg_per_sec": speed})
            self.survey_target = target

    def apply_close_up(self, mission: dict[str, Any], revision: int) -> dict[str, Any]:
        close_up = mission.get("close_up") or {}
        duration = max(1, min(int(close_up["duration_s"]), 120))
        cameras = self.configure_cameras(close_up.get("visible_zoom_x"), close_up.get("thermal_zoom_x"), revision, "close_up")
        self.local_request("POST", "/api/camera-recording/start", {"source_phase_sec": 0})
        time.sleep(duration)
        self.local_request("POST", "/api/camera-recording/stop")
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            result = self.local_request("GET", "/api/camera-recording")
            if result.get("status") == "archived":
                return {"motor": "No motion requested", "cameras": cameras, "incident_id": result.get("incident_id")}
            if result.get("status") == "error":
                raise RuntimeError(f"Close-up archive failed: {result.get('message')}")
            time.sleep(1)
        raise TimeoutError("Close-up recording did not archive within 240 seconds.")

    def apply(self, mission: dict[str, Any]) -> dict[str, Any]:
        revision = int(mission["revision"])
        if mission.get("station_id") != self.device_id:
            raise ValueError("Mission station_id does not match this device.")
        mode = mission.get("active_mode")
        if mode == "survey":
            return self.apply_survey(mission, revision)
        if mode == "close_up":
            return self.apply_close_up(mission, revision)
        raise ValueError(f"Unsupported active_mode: {mode!r}")

    def acknowledge(self, revision: int) -> int:
        body = json.dumps({"revision": revision, "message": "applied"}, separators=(",", ":")).encode()
        status, _ = self.signed_request("POST", self.ack_path, body)
        return status

    def run_once(self) -> None:
        http_status, response = self.signed_request("GET", self.mission_path)
        mission = response.get("mission")
        if not isinstance(mission, dict):
            LOGGER.info("Mission GET HTTP %s: no active mission", http_status)
            return
        revision = int(mission["revision"])
        mode = str(mission.get("active_mode"))
        if self.state.get("applied_revision") != revision:
            result = self.apply(mission)
            self.state.update({
                "applied_revision": revision,
                "acked_revision": None,
                "mission": mission,
                "apply_result": result,
                "applied_at": utc_now(),
                "last_error": None,
            })
            atomic_json_write(STATE_PATH, self.state)
            LOGGER.info("Applied Mission revision=%s mode=%s result=%s", revision, mode, result)
        if self.state.get("acked_revision") != revision:
            ack_status = self.acknowledge(revision)
            self.state.update({"acked_revision": revision, "ack_http_status": ack_status, "acked_at": utc_now()})
            atomic_json_write(STATE_PATH, self.state)
            LOGGER.info("ACK Mission revision=%s HTTP %s", revision, ack_status)
        if mode == "survey":
            self.maintain_survey(mission)

    def run(self) -> None:
        backoff = self.poll_seconds
        LOGGER.info("Mission worker started api=%s%s poll=%.1fs", self.base_url, self.mission_path, self.poll_seconds)
        while True:
            try:
                self.run_once()
                backoff = self.poll_seconds
            except Exception as exc:
                self.state["last_error"] = str(exc)
                self.state["last_error_at"] = utc_now()
                atomic_json_write(STATE_PATH, self.state)
                LOGGER.error("Mission cycle failed; safe state retained: %s", exc)
                backoff = min(60.0, max(self.poll_seconds, backoff * 2.0 + random.uniform(0, 0.5)))
            time.sleep(backoff)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--poll-seconds", type=float, default=3.0)
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    worker = MissionWorker(args.poll_seconds, args.timeout)
    if args.once:
        worker.run_once()
    else:
        worker.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
