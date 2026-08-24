#!/usr/bin/env python3
"""Safely synchronize Station configuration from NARIT Fire Watch Server."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import hmac
import json
import logging
import math
import os
from pathlib import Path
import ssl
import sys
import tempfile
import time
from typing import Any
import urllib.error
import urllib.request


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SETTINGS_PATH = PROJECT_ROOT / "AppSetting.JSON"
STATE_PATH = PROJECT_ROOT / "data" / "station_configuration" / "state.json"
ACTIVE_PATH = PROJECT_ROOT / "data" / "station_configuration" / "active.json"
LOCAL_API = "http://127.0.0.1:8000"
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
LOGGER = logging.getLogger("configuration-worker")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def atomic_json_write(path: Path, payload: dict[str, Any]) -> None:
    """Durably replace a JSON file without exposing a partial configuration."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(payload, output, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else dict(default)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return dict(default)


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def _object(value: Any, field: str, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    missing, extra = keys - value.keys(), value.keys() - keys
    if missing:
        raise ValueError(f"{field} is missing {sorted(missing)[0]}")
    if extra:
        raise ValueError(f"{field} contains unsupported field {sorted(extra)[0]}")
    return value


class ConfigurationWorker:
    def __init__(self, poll_seconds: float = 3.0, timeout: float = 8.0) -> None:
        self.settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        remote = self.settings["mount_agent"]["remote"]
        self.device_id = str(remote["device_id"])
        configured_url = str(remote.get("media_upload_url") or "https://100.102.91.123:8443")
        self.base_url = configured_url.split("/api/", 1)[0].rstrip("/")
        self.secret = Path(str(remote["secret_file"])).read_bytes().strip()
        if not self.secret:
            raise RuntimeError("The configured shared-secret file is empty.")
        self.context = ssl.create_default_context(cafile=str(remote["ca_file"]))
        self.poll_seconds = max(2.0, min(float(poll_seconds), 5.0))
        self.timeout = max(2.0, min(float(timeout), 10.0))
        self.state = read_json(STATE_PATH, {"applied_revision": None, "acked_revision": None})
        active = read_json(ACTIVE_PATH, {})
        active_revision = active.get("revision")
        if isinstance(active_revision, int) and not isinstance(active_revision, bool):
            current = self.state.get("applied_revision")
            self.state["applied_revision"] = max(active_revision, current if isinstance(current, int) else -1)

    @property
    def configuration_path(self) -> str:
        return f"/api/v1/stations/{self.device_id}/configuration"

    @property
    def ack_path(self) -> str:
        return f"{self.configuration_path}/ack"

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
        request = urllib.request.Request(self.base_url + path, data=body or None, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, context=self.context, timeout=self.timeout) as response:
                raw = response.read()
                try:
                    payload = json.loads(raw) if raw else {}
                except json.JSONDecodeError as exc:
                    raise RuntimeError("Configuration API returned invalid JSON") from exc
                if not isinstance(payload, dict):
                    raise RuntimeError("Configuration API response must be a JSON object")
                return response.status, payload
        except urllib.error.HTTPError as exc:
            raw_detail = exc.read()
            detail = (raw_detail.decode("utf-8", errors="replace") if isinstance(raw_detail, bytes)
                      else str(raw_detail))[:500]
            raise RuntimeError(f"Configuration API HTTP {exc.code}: {detail}") from exc

    def drive_limits(self) -> dict[str, dict[str, float]]:
        request = urllib.request.Request(LOCAL_API + "/api/status", method="GET")
        with urllib.request.urlopen(request, timeout=5) as response:
            status = json.loads(response.read())
        result: dict[str, dict[str, float]] = {}
        for label in ("Azimuth", "Altitude"):
            axis = next((item for item in status.get("axes", []) if item.get("label") == label), None)
            if not axis or not axis.get("available"):
                raise ValueError(f"{label} drive limits are unavailable")
            result[label] = {
                "speed": min(_number(axis.get("trap_velocity_limit"), f"{label} drive velocity limit"),
                             _number(axis.get("velocity_limit"), f"{label} controller velocity limit")),
                "acceleration": _number(axis.get("trap_accel_limit"), f"{label} drive acceleration limit"),
            }
        return result

    def validate(self, candidate: Any) -> dict[str, Any]:
        config = _object(candidate, "configuration", {
            "device_id", "revision", "station_name", "location", "motion_limits", "updated_at"
        })
        if not isinstance(config["device_id"], str) or config["device_id"] != self.device_id:
            raise ValueError("device_id does not match this Station")
        revision = config["revision"]
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            raise ValueError("revision must be a non-negative integer")
        name = config["station_name"]
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 128:
            raise ValueError("station_name must be a non-empty string of at most 128 characters")
        location = _object(config["location"], "location", {"latitude", "longitude"})
        latitude = _number(location["latitude"], "latitude")
        longitude = _number(location["longitude"], "longitude")
        if not -90 <= latitude <= 90:
            raise ValueError("latitude must be within WGS84 range -90 to 90")
        if not -180 <= longitude <= 180:
            raise ValueError("longitude must be within WGS84 range -180 to 180")
        updated_at = config["updated_at"]
        if not isinstance(updated_at, str) or not updated_at.endswith("Z"):
            raise ValueError("updated_at must be a UTC ISO-8601 string")
        try:
            datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("updated_at must be a valid UTC ISO-8601 string") from exc

        names = {
            "azimuth_min_deg", "azimuth_max_deg", "altitude_min_deg", "altitude_max_deg",
            "azimuth_speed_max_deg_s", "altitude_speed_max_deg_s",
            "azimuth_acceleration_deg_s2", "altitude_acceleration_deg_s2",
        }
        remote_limits = _object(config["motion_limits"], "motion_limits", names)
        values = {key: _number(remote_limits[key], key) for key in names}
        if values["azimuth_min_deg"] >= values["azimuth_max_deg"]:
            raise ValueError("azimuth_min_deg must be less than azimuth_max_deg")
        if values["altitude_min_deg"] >= values["altitude_max_deg"]:
            raise ValueError("altitude_min_deg must be less than altitude_max_deg")
        for key in names - {"azimuth_min_deg", "azimuth_max_deg", "altitude_min_deg", "altitude_max_deg"}:
            if values[key] <= 0:
                raise ValueError(f"{key} must be greater than zero")

        local = self.settings["motion_limits"]
        bounds = (
            ("azimuth_min_deg", float(local["azimuth_ccw_limit_deg"]), "local absolute encoder"),
            ("azimuth_max_deg", float(local["azimuth_cw_limit_deg"]), "local absolute encoder"),
            ("altitude_min_deg", float(local["altitude_lower_limit_deg"]), "local mechanical"),
            ("altitude_max_deg", float(local["altitude_upper_limit_deg"]), "local mechanical"),
        )
        for key, hard, label in bounds:
            if (key.endswith("min_deg") and values[key] < hard) or (key.endswith("max_deg") and values[key] > hard):
                raise ValueError(f"{key} exceeds {label} limit")
        drive = self.drive_limits()
        local_speed = _number(local["slew_rate_deg_per_sec"], "local slew rate")
        for axis, label in (("azimuth", "Azimuth"), ("altitude", "Altitude")):
            speed_key, acceleration_key = f"{axis}_speed_max_deg_s", f"{axis}_acceleration_deg_s2"
            if values[speed_key] > min(local_speed, drive[label]["speed"]):
                raise ValueError(f"{speed_key} exceeds local or drive limit")
            if values[acceleration_key] > drive[label]["acceleration"]:
                raise ValueError(f"{acceleration_key} exceeds drive limit")

        return {
            "device_id": self.device_id,
            "revision": revision,
            "station_name": name.strip(),
            "location": {"latitude": latitude, "longitude": longitude, "datum": "WGS84"},
            "motion_limits": values,
            "updated_at": updated_at,
            "applied_at": utc_now(),
        }

    def acknowledge(self, revision: int, status: str, message: str) -> int:
        body = json.dumps({"revision": revision, "status": status, "message": message},
                          separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
        http_status, _ = self.signed_request("POST", self.ack_path, body)
        return http_status

    def _save_state(self) -> None:
        atomic_json_write(STATE_PATH, self.state)

    def run_once(self) -> None:
        http_status, response = self.signed_request("GET", self.configuration_path)
        candidate = response.get("configuration")
        if candidate is None:
            LOGGER.info("Received configuration response HTTP %s with no configuration", http_status)
            return
        revision = candidate.get("revision") if isinstance(candidate, dict) else None
        LOGGER.info("Received Station configuration revision=%r", revision)
        if isinstance(revision, bool) or not isinstance(revision, int):
            LOGGER.warning("Rejected Station configuration with invalid revision")
            return
        applied = self.state.get("applied_revision")
        if isinstance(applied, int) and revision <= applied:
            if revision == applied and self.state.get("acked_revision") != revision:
                status = self.acknowledge(revision, "applied", "configuration applied successfully")
                self.state.update({"acked_revision": revision, "ack_http_status": status, "acked_at": utc_now()})
                self._save_state()
                LOGGER.info("Retried ACK Station configuration revision=%s HTTP %s", revision, status)
                return
            LOGGER.info("Skipped Station configuration revision=%s; applied_revision=%s", revision, applied)
            return
        try:
            active = self.validate(candidate)
            atomic_json_write(ACTIVE_PATH, active)
        except Exception as exc:
            message = str(exc)
            LOGGER.warning("Rejected Station configuration revision=%s: %s", revision, message)
            LOGGER.info("Rollback revision=%s: last-known-good configuration retained", revision)
            self.state.update({"last_rejected_revision": revision, "last_error": message, "last_error_at": utc_now()})
            self._save_state()
            try:
                self.acknowledge(revision, "rejected", message)
            except Exception as ack_exc:
                LOGGER.error("Rejected configuration ACK failed revision=%s: %s", revision, ack_exc)
            return
        self.state.update({"applied_revision": revision, "acked_revision": None, "last_error": None,
                           "applied_at": active["applied_at"]})
        self._save_state()
        LOGGER.info("Applied Station configuration revision=%s atomically", revision)
        status = self.acknowledge(revision, "applied", "configuration applied successfully")
        self.state.update({"acked_revision": revision, "ack_http_status": status, "acked_at": utc_now()})
        self._save_state()
        LOGGER.info("ACK Station configuration revision=%s HTTP %s", revision, status)

    def run(self) -> None:
        LOGGER.info("Configuration worker started api=%s%s poll=%.1fs", self.base_url,
                    self.configuration_path, self.poll_seconds)
        while True:
            try:
                self.run_once()
            except Exception as exc:
                LOGGER.error("Configuration sync failed; last-known-good retained: %s", exc)
            time.sleep(self.poll_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--poll-seconds", type=float, default=3.0)
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    worker = ConfigurationWorker(args.poll_seconds, args.timeout)
    worker.run_once() if args.once else worker.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
