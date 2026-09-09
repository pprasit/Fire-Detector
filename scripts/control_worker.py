#!/usr/bin/env python3
"""Persistent safety-first WebSocket mount control worker."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import hmac
import itertools
import json
import logging
import math
import os
from pathlib import Path
import random
import secrets
import signal
import ssl
import time
from typing import Any
import urllib.parse
import urllib.error
import urllib.request

import websockets


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SETTINGS_PATH = PROJECT_ROOT / "AppSetting.JSON"
STATE_PATH = PROJECT_ROOT / "data" / "control" / "state.json"
LOCAL_API = "http://127.0.0.1:8000"
CONTROL_PATH = "/control/v1"
LOGGER = logging.getLogger("control-worker")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_utc(value: Any) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("expires_at must be a UTC ISO-8601 timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("expires_at must include a timezone")
    return parsed.astimezone(timezone.utc)


def atomic_state(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class LocalMount:
    def __init__(self, settings: dict[str, Any], *, motion_enabled: bool) -> None:
        self.settings = settings
        self.motion_enabled = motion_enabled
        self.local_speed_limit = float(settings["motion_limits"]["slew_rate_deg_per_sec"])
        self._jog_client_id = f"control-worker-{os.getpid()}-{secrets.token_hex(8)}"
        self._jog_sequence = 0
        self._jog_heartbeat_task: asyncio.Task[None] | None = None

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        body = json.dumps(payload, separators=(",", ":")).encode() if payload is not None else None
        request = urllib.request.Request(
            LOCAL_API + path,
            data=body,
            method=method,
            headers={
                **({"Content-Type": "application/json"} if body else {}),
                **(headers or {}),
            },
        )
        with urllib.request.urlopen(request, timeout=3.0) as response:
            result = json.loads(response.read())
        if result.get("ok") is False:
            raise RuntimeError(str(result.get("error") or "local mount request failed"))
        return result

    async def stop(self) -> None:
        heartbeat = self._jog_heartbeat_task
        self._jog_heartbeat_task = None
        if heartbeat is not None and heartbeat is not asyncio.current_task():
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
        await asyncio.to_thread(self.request, "POST", "/api/motors/stop", {})

    def _jog_request(self, payload: dict[str, float]) -> dict[str, Any]:
        self._jog_sequence += 1
        return self.request(
            "POST",
            "/api/motors/velocity-command",
            payload,
            {
                "X-Motion-Client-ID": self._jog_client_id,
                "X-Motion-Command-Sequence": str(self._jog_sequence),
            },
        )

    async def _jog_heartbeat(self, payload: dict[str, float]) -> None:
        try:
            while True:
                await asyncio.sleep(0.2)
                await asyncio.to_thread(self._jog_request, payload)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            # The server-side 0.6 s dead-man remains the final authority if
            # this process or its local HTTP link becomes unhealthy.
            LOGGER.error("Local Jog heartbeat failed; server dead-man will stop motion: %s", exc)

    async def status(self) -> dict[str, Any]:
        return await asyncio.to_thread(self.request, "GET", "/api/status")

    @staticmethod
    def axes_by_label(status: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {
            str(axis.get("label")): axis
            for axis in status.get("axes", [])
            if isinstance(axis, dict)
        }

    async def enable(self, axes: list[str], move_after_enable: bool) -> None:
        if axes != ["azimuth", "altitude"] and set(axes) != {"azimuth", "altitude"}:
            raise RuntimeError("ENABLE requires both azimuth and altitude axes")
        if move_after_enable:
            raise RuntimeError("move_after_enable must be false")
        status = await self.status()
        if not status.get("connected") or status.get("health") != "ready" or not status.get("has_bus_power"):
            raise RuntimeError("mount is not connected, ready, and powered")
        if status.get("e_stop_active") is True:
            raise RuntimeError("E-stop is active")
        if status.get("interlocks_ok") is False:
            raise RuntimeError("mount interlock is not satisfied")
        # CW/CCW GPIOs are region selectors for absolute-position unwrapping,
        # not motion limit switches. Software limits below are enforced by the
        # Station motion layer using the absolute encoder position.
        axes_status = self.axes_by_label(status)
        for label in ("Azimuth", "Altitude"):
            axis = axes_status.get(label)
            if not axis or not axis.get("available"):
                raise RuntimeError(f"{label} axis is unavailable")
            if axis.get("active_errors") or axis.get("disarm_reason"):
                raise RuntimeError(f"{label} drive reports an active error")
        try:
            await asyncio.to_thread(self.request, "POST", "/api/motors/enable", {})
            confirmed = self.axes_by_label(await self.status())
            if not all(confirmed.get(label, {}).get("is_armed") is True for label in ("Azimuth", "Altitude")):
                raise RuntimeError("partial arm prevented; both axes returned to disabled state")
        except Exception:
            await self.stop()
            await asyncio.to_thread(self.request, "POST", "/api/motors/disable", {})
            raise

    async def disable(self) -> None:
        await self.stop()
        await asyncio.to_thread(self.request, "POST", "/api/motors/disable", {})
        confirmed = self.axes_by_label(await self.status())
        if not all(confirmed.get(label, {}).get("is_armed") is False for label in ("Azimuth", "Altitude")):
            await self.stop()
            raise RuntimeError("could not confirm both axes disabled")

    async def preflight(self) -> dict[str, Any]:
        status = await self.status()
        if not status.get("connected") or status.get("health") != "ready" or not status.get("has_bus_power"):
            raise RuntimeError("mount is not connected, ready, and powered")
        # Region sensor state is intentionally not an enable interlock. It
        # selects the absolute-encoder branch and remains active during valid
        # motion in that region.
        for label in ("Azimuth", "Altitude"):
            axis = next((item for item in status.get("axes", []) if item.get("label") == label), None)
            if not axis or not axis.get("available") or not axis.get("is_armed"):
                raise RuntimeError(f"{label} axis is unavailable or disarmed")
            if axis.get("active_errors") or axis.get("disarm_reason"):
                raise RuntimeError(f"{label} drive reports an error")
        return status

    def effective_speeds(self, status: dict[str, Any], azimuth_server: float, altitude_server: float) -> dict[str, float]:
        hardware = {
            str(axis.get("label")): float(axis.get("velocity_limit") or self.local_speed_limit)
            for axis in status.get("axes", [])
            if isinstance(axis, dict)
        }
        return {
            "Azimuth": min(azimuth_server, self.local_speed_limit, hardware.get("Azimuth", self.local_speed_limit)),
            "Altitude": min(altitude_server, self.local_speed_limit, hardware.get("Altitude", self.local_speed_limit)),
        }

    async def jog(self, azimuth: int, altitude: int, azimuth_limit: float, altitude_limit: float) -> dict[str, float]:
        if not self.motion_enabled:
            raise RuntimeError("motion disabled during commissioning")
        status = await self.preflight()
        speeds = self.effective_speeds(status, azimuth_limit, altitude_limit)
        payload = {
            "Azimuth": azimuth * speeds["Azimuth"],
            "Altitude": altitude * speeds["Altitude"],
        }
        previous_heartbeat = self._jog_heartbeat_task
        self._jog_heartbeat_task = None
        if previous_heartbeat is not None:
            previous_heartbeat.cancel()
            await asyncio.gather(previous_heartbeat, return_exceptions=True)
        await asyncio.to_thread(self._jog_request, payload)
        self._jog_heartbeat_task = asyncio.create_task(self._jog_heartbeat(payload))
        return speeds

    async def goto_angles(self, azimuth: float, altitude: float, azimuth_limit: float, altitude_limit: float) -> dict[str, float]:
        if not self.motion_enabled:
            raise RuntimeError("motion disabled during commissioning")
        status = await self.preflight()
        speeds = self.effective_speeds(status, azimuth_limit, altitude_limit)
        await asyncio.to_thread(
            self.request,
            "POST",
            "/api/motors/goto",
            {"Azimuth": azimuth, "Altitude": altitude, "velocity_target_deg_per_sec": min(speeds.values())},
        )
        return speeds

    async def goto_location(self, latitude: float, longitude: float, azimuth_limit: float, altitude_limit: float) -> dict[str, float]:
        query = urllib.parse.urlencode({"lat": latitude, "lon": longitude})
        result = await asyncio.to_thread(self.request, "GET", f"/api/pointing/sample?{query}")
        sample = result.get("sample") or {}
        azimuth = sample.get("device_azimuth_deg")
        altitude = sample.get("altitude_deg")
        if azimuth is None or altitude is None or not sample.get("inside_dem"):
            raise RuntimeError("trusted terrain elevation is unavailable for target")
        return await self.goto_angles(float(azimuth), float(altitude), azimuth_limit, altitude_limit)


class ControlWorker:
    def __init__(self, *, motion_enabled: bool = False, watchdog_seconds: float = 0.45) -> None:
        self.settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        remote = self.settings["mount_agent"]["remote"]
        self.device_id = str(remote["device_id"])
        self.secret = Path(str(remote["secret_file"])).read_bytes().strip()
        if not self.secret:
            raise RuntimeError("configured shared-secret file is empty")
        self.ca_file = str(remote["ca_file"])
        self.url = f"wss://{remote['host']}:8765{CONTROL_PATH}"
        self.ssl_context = ssl.create_default_context(cafile=self.ca_file)
        self.mount = LocalMount(self.settings, motion_enabled=motion_enabled)
        self.watchdog_seconds = watchdog_seconds
        try:
            persisted = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            self.last_sequence = int(persisted.get("last_sequence", -1))
        except (FileNotFoundError, ValueError, TypeError, json.JSONDecodeError, OSError):
            self.last_sequence = -1
        self.jog_deadline = 0.0
        self.jog_task: asyncio.Task[None] | None = None
        self.active_jog: tuple[int, str] | None = None
        self.command_epoch = 0
        self.queue_counter = itertools.count()
        self.shutdown = asyncio.Event()
        self.last_capabilities_response: dict[str, Any] = {}
        self.last_capabilities_http_status: int | None = None
        self.ack_cache: dict[int, dict[str, str]] = {}

    def authentication(self) -> dict[str, Any]:
        timestamp = utc_now()
        nonce = secrets.token_urlsafe(24)
        canonical = "\n".join((self.device_id, "WEBSOCKET", CONTROL_PATH, timestamp, nonce))
        signature = hmac.new(self.secret, canonical.encode(), hashlib.sha256).hexdigest()
        return {
            "type": "authenticate",
            "device_id": self.device_id,
            "timestamp": timestamp,
            "nonce": nonce,
            "signature": signature,
        }

    async def safe_stop(self, reason: str) -> None:
        self.jog_deadline = 0.0
        self.active_jog = None
        if self.jog_task is not None and self.jog_task is not asyncio.current_task():
            self.jog_task.cancel()
        self.jog_task = None
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                await self.mount.stop()
                LOGGER.info("Safe STOP complete reason=%s", reason)
                return
            except Exception as exc:
                last_error = exc
                LOGGER.error("Safe STOP attempt %s failed reason=%s: %s", attempt + 1, reason, exc)
                await asyncio.sleep(0.05)
        raise RuntimeError(f"unable to stop mount after 3 attempts: {last_error}")

    def signed_request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
        body = json.dumps(payload, separators=(",", ":")).encode() if payload is not None else b""
        timestamp = utc_now()
        body_hash = hashlib.sha256(body).hexdigest()
        canonical = "\n".join((self.device_id, method, path, timestamp, body_hash))
        signature = hmac.new(self.secret, canonical.encode(), hashlib.sha256).hexdigest()
        request = urllib.request.Request(
            self.url.split(CONTROL_PATH, 1)[0].replace("wss://", "https://").replace(":8765", ":8443") + path,
            data=body if body else None,
            method=method,
            headers={
                "X-Narit-Device-Id": self.device_id,
                "X-Narit-Timestamp": timestamp,
                "X-Narit-Body-SHA256": body_hash,
                "X-Narit-Signature": signature,
                **({"Content-Type": "application/json"} if body else {}),
            },
        )
        try:
            with urllib.request.urlopen(request, context=self.ssl_context, timeout=8) as response:
                if response.status < 200 or response.status >= 300:
                    raise RuntimeError(f"signed endpoint returned HTTP {response.status}")
                raw = response.read()
                return response.status, json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"signed endpoint returned HTTP {exc.code}: {detail}") from exc

    async def publish_capabilities(self) -> None:
        limits = self.settings["motion_limits"]
        payload = {
            "azimuth_min_deg": float(limits["azimuth_ccw_limit_deg"]),
            "azimuth_max_deg": float(limits["azimuth_cw_limit_deg"]),
            "altitude_min_deg": float(limits["altitude_lower_limit_deg"]),
            "altitude_max_deg": float(limits["altitude_upper_limit_deg"]),
            "altitude_speed_max_deg_s": float(limits["slew_rate_deg_per_sec"]),
            "close_up_duration_max_s": 120,
            "pan_speed_max_deg_s": float(limits["slew_rate_deg_per_sec"]),
            "thermal_zoom_max_x": 5.0,
            "thermal_zoom_min_x": 1.0,
            "visible_zoom_max_x": 5.0,
            "visible_zoom_min_x": 1.0,
        }
        path = f"/api/v1/missions/{self.device_id}/capabilities"
        status, response = await asyncio.to_thread(self.signed_request, "POST", path, payload)
        self.last_capabilities_http_status = status
        self.last_capabilities_response = response
        LOGGER.info("Capabilities synchronized HTTP %s: %s", status, response)

    async def capabilities_loop(self) -> None:
        last_mtime = SETTINGS_PATH.stat().st_mtime_ns
        last_success = 0.0
        backoff = 1.0
        while not self.shutdown.is_set():
            current_mtime = SETTINGS_PATH.stat().st_mtime_ns
            due = time.monotonic() - last_success >= 300.0
            changed = current_mtime != last_mtime
            if due or changed:
                try:
                    if changed:
                        self.settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
                        self.mount.settings = self.settings
                        self.mount.local_speed_limit = float(self.settings["motion_limits"]["slew_rate_deg_per_sec"])
                    await self.publish_capabilities()
                    last_success = time.monotonic()
                    last_mtime = current_mtime
                    backoff = 1.0
                except Exception as exc:
                    LOGGER.warning("Capabilities synchronization failed: %s; retrying", exc)
                    try:
                        await asyncio.wait_for(self.shutdown.wait(), timeout=backoff + random.uniform(0, 0.25))
                    except asyncio.TimeoutError:
                        pass
                    backoff = min(300.0, backoff * 2.0)
                    continue
            try:
                await asyncio.wait_for(self.shutdown.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                pass

    @staticmethod
    def command_speed_limits(message: dict[str, Any]) -> tuple[float, float]:
        fallback = 20.0
        command = message.get("command") if isinstance(message.get("command"), dict) else {}
        azimuth = message.get("azimuth_speed_limit_deg_s", command.get("azimuth_speed_limit_deg_s"))
        altitude = message.get("altitude_speed_limit_deg_s", command.get("altitude_speed_limit_deg_s"))
        if azimuth is None or altitude is None:
            LOGGER.warning("Motion command missing speed limit fields; applying migration cap 20 deg/s")
        try:
            values = (float(azimuth if azimuth is not None else fallback), float(altitude if altitude is not None else fallback))
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid motion speed limit") from exc
        if any(not math.isfinite(value) or value <= 0 for value in values):
            raise ValueError("motion speed limits must be finite and positive")
        return min(fallback, values[0]), min(fallback, values[1])

    def arm_jog_watchdog(self, sequence: int, hold_id: str) -> None:
        if self.jog_task is not None and self.jog_task is not asyncio.current_task():
            self.jog_task.cancel()
        self.active_jog = (sequence, hold_id)
        self.jog_deadline = time.monotonic() + self.watchdog_seconds
        self.jog_task = asyncio.create_task(self._jog_watchdog(sequence, hold_id))

    def renew_jog_watchdog(self, message: dict[str, Any]) -> None:
        sequence = message.get("sequence")
        hold_id = message.get("hold_id")
        if message.get("protocol_version") != 1 or self.active_jog != (sequence, hold_id):
            LOGGER.info("Ignored unmatched Jog keepalive sequence=%s", sequence)
            return
        self.arm_jog_watchdog(sequence, hold_id)

    async def _jog_watchdog(self, sequence: int, hold_id: str) -> None:
        try:
            await asyncio.sleep(self.watchdog_seconds)
            if self.active_jog == (sequence, hold_id) and time.monotonic() >= self.jog_deadline:
                await self.safe_stop(f"jog_deadman_sequence_{sequence}")
        except asyncio.CancelledError:
            return

    async def ack(
        self,
        ack_queue: asyncio.PriorityQueue[tuple[int, int, dict[str, Any]]],
        sequence: int,
        state: str,
        message: str,
        *,
        urgent: bool = False,
    ) -> None:
        payload = {"type": "ack", "sequence": sequence, "state": state, "message": message[:240]}
        if sequence > self.last_sequence:
            self.last_sequence = sequence
            atomic_state(STATE_PATH, {"last_sequence": sequence, "updated_at": utc_now()})
        self.ack_cache[sequence] = {"state": state, "message": message[:240]}
        if len(self.ack_cache) > 256:
            self.ack_cache.pop(min(self.ack_cache))
        await ack_queue.put((0 if urgent else 10, next(self.queue_counter), payload))

    async def handle_command(
        self,
        ack_queue: asyncio.PriorityQueue[tuple[int, int, dict[str, Any]]],
        message: dict[str, Any],
    ) -> None:
        sequence = message.get("sequence")
        if not isinstance(sequence, int):
            raise ValueError("mount_command sequence must be an integer")
        if message.get("protocol_version") != 1:
            await self.ack(ack_queue, sequence, "rejected", "unsupported protocol_version")
            return
        if message.get("station_id") != self.device_id:
            await self.ack(ack_queue, sequence, "rejected", "station_id mismatch")
            return
        if sequence <= self.last_sequence:
            cached = self.ack_cache.get(sequence)
            if cached:
                await self.ack(ack_queue, sequence, cached["state"], cached["message"])
                LOGGER.info("Replayed cached ACK sequence=%s", sequence)
            else:
                await self.ack(ack_queue, sequence, "rejected", "old or duplicate sequence")
                LOGGER.info("Rejected replay sequence=%s last_sequence=%s", sequence, self.last_sequence)
            return
        command_type = message.get("command_type")
        command = message.get("command") or {}
        try:
            if command_type == "enable":
                expires_at = parse_utc(message.get("expires_at"))
                if expires_at <= datetime.now(timezone.utc):
                    await self.ack(ack_queue, sequence, "rejected", f"{command_type} command expired")
                    return
            if command_type == "enable":
                axes = command.get("axes")
                if not isinstance(axes, list) or not all(isinstance(axis, str) for axis in axes):
                    raise ValueError("ENABLE axes must be a list")
                await self.mount.enable([axis.lower() for axis in axes], command.get("move_after_enable") is True)
                await self.ack(ack_queue, sequence, "completed", "both axes enabled; no motion commanded")
                return
            if command_type == "disable":
                await self.mount.disable()
                await self.ack(ack_queue, sequence, "completed", "both axes stopped and disabled")
                return
            if command_type == "stop":
                await self.safe_stop(f"server_stop_sequence_{sequence}")
                await self.ack(ack_queue, sequence, "stopped", "motors stopped", urgent=True)
                return
            if command_type == "jog":
                hold_id = command.get("hold_id")
                if not isinstance(hold_id, str) or not hold_id:
                    raise ValueError("jog hold_id is required")
                azimuth = int(command.get("azimuth_direction", 0))
                altitude = int(command.get("altitude_direction", 0))
                if azimuth not in (-1, 0, 1) or altitude not in (-1, 0, 1) or (azimuth == 0 and altitude == 0):
                    raise ValueError("invalid jog direction")
                epoch = self.command_epoch
                azimuth_limit, altitude_limit = self.command_speed_limits(message)
                speeds = await self.mount.jog(azimuth, altitude, azimuth_limit, altitude_limit)
                if epoch != self.command_epoch:
                    await self.safe_stop(f"jog_superseded_sequence_{sequence}")
                    await self.ack(ack_queue, sequence, "stopped", "jog superseded by STOP")
                    return
                self.arm_jog_watchdog(sequence, hold_id)
                await self.ack(ack_queue, sequence, "accepted", f"jog active az={speeds['Azimuth']:g} alt={speeds['Altitude']:g} deg/s")
                return
            if command_type == "goto_angles":
                azimuth_limit, altitude_limit = self.command_speed_limits(message)
                await self.mount.goto_angles(float(command["azimuth_deg"]), float(command["altitude_deg"]), azimuth_limit, altitude_limit)
                await self.ack(ack_queue, sequence, "moving", "goto angles started")
                return
            if command_type == "goto_location":
                azimuth_limit, altitude_limit = self.command_speed_limits(message)
                await self.mount.goto_location(float(command["latitude"]), float(command["longitude"]), azimuth_limit, altitude_limit)
                await self.ack(ack_queue, sequence, "moving", "goto location started")
                return
            raise ValueError(f"unsupported command_type: {command_type!r}")
        except Exception as exc:
            LOGGER.warning("Command rejected sequence=%s command_type=%s reason=%s", sequence, command_type, exc)
            await self.safe_stop(f"rejected_sequence_{sequence}")
            await self.ack(ack_queue, sequence, "rejected", str(exc))

    async def motor_executor(
        self,
        command_queue: asyncio.PriorityQueue[tuple[int, int, dict[str, Any]]],
        ack_queue: asyncio.PriorityQueue[tuple[int, int, dict[str, Any]]],
    ) -> None:
        while True:
            _, _, message = await command_queue.get()
            try:
                await self.handle_command(ack_queue, message)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                sequence = message.get("sequence")
                LOGGER.warning("Motor executor rejected malformed command: %s", exc)
                await self.safe_stop("motor_executor_error")
                if isinstance(sequence, int):
                    await self.ack(ack_queue, sequence, "rejected", str(exc))
            finally:
                command_queue.task_done()

    async def ack_writer(
        self,
        websocket: Any,
        ack_queue: asyncio.PriorityQueue[tuple[int, int, dict[str, Any]]],
    ) -> None:
        while True:
            _, _, payload = await ack_queue.get()
            try:
                await websocket.send(json.dumps(payload, separators=(",", ":")))
            finally:
                ack_queue.task_done()

    async def urgent_stop(
        self,
        ack_queue: asyncio.PriorityQueue[tuple[int, int, dict[str, Any]]],
        message: dict[str, Any] | None,
        reason: str,
    ) -> None:
        self.command_epoch += 1
        await self.safe_stop(reason)
        if message is not None and isinstance(message.get("sequence"), int):
            await self.ack(ack_queue, int(message["sequence"]), "stopped", "motors stopped", urgent=True)

    async def session(self) -> None:
        authenticated = False
        async with websockets.connect(
            self.url,
            ssl=self.ssl_context,
            compression=None,
            max_size=16384,
            open_timeout=10,
            ping_interval=10,
            ping_timeout=5,
            close_timeout=3,
        ) as websocket:
            await asyncio.wait_for(websocket.send(json.dumps(self.authentication(), separators=(",", ":"))), timeout=5)
            LOGGER.info("WebSocket connected; authentication sent device_id=%s", self.device_id)
            command_queue: asyncio.PriorityQueue[tuple[int, int, dict[str, Any]]] = asyncio.PriorityQueue()
            ack_queue: asyncio.PriorityQueue[tuple[int, int, dict[str, Any]]] = asyncio.PriorityQueue()
            executor = asyncio.create_task(self.motor_executor(command_queue, ack_queue), name="motor-executor")
            writer = asyncio.create_task(self.ack_writer(websocket, ack_queue), name="ack-writer")
            urgent_tasks: set[asyncio.Task[None]] = set()
            try:
                while not self.shutdown.is_set():
                    try:
                        raw = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                    except asyncio.TimeoutError:
                        continue
                    message = json.loads(raw)
                    if not isinstance(message, dict):
                        raise ValueError("message must be a JSON object")
                    if message.get("type") == "safe_stop":
                        reason = str(message.get("reason") or "server_safe_stop")
                        if reason == "connection_established":
                            # A lost authenticated session already stops the mount
                            # in this method's finally block.  Stopping again when
                            # its replacement connects interrupts motion that was
                            # subsequently started from another local controller.
                            LOGGER.info("Ignored redundant server safe STOP reason=%s", reason)
                        else:
                            task = asyncio.create_task(self.urgent_stop(
                                ack_queue, None, reason
                            ))
                            urgent_tasks.add(task)
                            task.add_done_callback(urgent_tasks.discard)
                    elif message.get("type") == "authenticated":
                        authenticated = True
                        LOGGER.info("WebSocket authentication accepted")
                    elif message.get("type") == "jog_keepalive":
                        self.renew_jog_watchdog(message)
                    elif message.get("type") == "mount_command":
                        if message.get("command_type") == "stop":
                            task = asyncio.create_task(self.urgent_stop(
                                ack_queue, message, f"server_stop_sequence_{message.get('sequence')}"
                            ))
                            urgent_tasks.add(task)
                            task.add_done_callback(urgent_tasks.discard)
                        else:
                            await command_queue.put((10, next(self.queue_counter), message))
            finally:
                executor.cancel()
                writer.cancel()
                for task in urgent_tasks:
                    task.cancel()
                await asyncio.gather(executor, writer, *urgent_tasks, return_exceptions=True)
                if authenticated:
                    await self.safe_stop("authenticated_session_ended")

    async def run(self) -> None:
        backoff = 1.0
        capabilities_task = asyncio.create_task(self.capabilities_loop())
        try:
            while not self.shutdown.is_set():
                try:
                    await self.session()
                    backoff = 1.0
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    LOGGER.warning("Control connection unavailable: %s; reconnecting", exc)
                    try:
                        await asyncio.wait_for(self.shutdown.wait(), timeout=backoff + random.uniform(0, 0.25))
                    except asyncio.TimeoutError:
                        pass
                    backoff = min(30.0, backoff * 2.0)
        finally:
            capabilities_task.cancel()
            await self.safe_stop("worker_shutdown")


async def async_main(args: argparse.Namespace) -> None:
    worker = ControlWorker(motion_enabled=args.enable_motion, watchdog_seconds=args.watchdog_seconds)
    loop = asyncio.get_running_loop()
    for name in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(name, worker.shutdown.set)
    await worker.run()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enable-motion", action="store_true", help="allow validated Jog/Goto commands")
    parser.add_argument("--watchdog-seconds", type=float, default=0.45)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(async_main(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
