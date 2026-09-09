"""Secure local and remote JSON interfaces for the Fire Detector mount.

The local interface is an NDJSON protocol over a Unix domain socket. The
remote interface is an outbound TLS client so a field device behind CGNAT
never needs to expose a public control port.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import ipaddress
import json
import logging
import math
import os
from pathlib import Path
import secrets
import select
import socket
import ssl
import struct
import tempfile
from threading import Event, Lock, Thread
from time import monotonic, sleep
from typing import Any, Callable
import urllib.parse
import urllib.request
from queue import Empty, Queue


LOGGER = logging.getLogger(__name__)
PROTOCOL_VERSION = "1.0"
DEFAULT_LOCAL_SOCKET = "/run/fire-detector/mount-agent.sock"
MAX_MESSAGE_BYTES = 64 * 1024
DEFAULT_HEARTBEAT_SEC = 15.0
DEFAULT_TELEMETRY_SEC = 1.0
MAX_COMMANDS_PER_SECOND = 20
MAX_TERRAIN_BYTES = 128 * 1024 * 1024
TAILSCALE_IPV4_NETWORK = ipaddress.ip_network("100.64.0.0/10")
DEFAULT_BACKUP_API_PORT = 8000
STATION_CONFIG_STATE_PATH = Path(__file__).resolve().parents[2] / ".station_config_sync.json"
STATION_CONFIG_FIELDS = frozenset({
    "station_name", "latitude", "longitude", "elevation_above_ground_m",
    "horizontal_fov_deg", "vertical_fov_deg", "azimuth_north_offset_deg",
    "visible_camera", "thermal_camera",
})
MUTATING_PREFIXES = ("mount.", "axis.", "pointing.", "calibration.", "tuning.")
LEASE_EXEMPT_ACTIONS = {
    "mount.stop",
    "mount.disable",
    "axis.stop",
    "axis.disable",
    "system.hello",
    "system.get_info",
    "system.get_health",
    "system.get_capabilities",
    "system.ping",
    "mount.get_status",
    "subscribe",
    "unsubscribe",
}


class ProtocolError(ValueError):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


@dataclass
class ControlLease:
    lease_id: str
    owner: str
    expires_at: float
    lease_ms: int


class ControlLeaseManager:
    def __init__(self) -> None:
        self._lock = Lock()
        self._lease: ControlLease | None = None

    def acquire(self, owner: str, lease_ms: int) -> dict[str, Any]:
        lease_ms = max(500, min(int(lease_ms), 30_000))
        with self._lock:
            now = monotonic()
            if self._lease is not None and self._lease.expires_at > now and self._lease.owner != owner:
                raise ProtocolError("CONTROL_LEASE_BUSY", "Another client currently controls the mount.")
            self._lease = ControlLease(
                lease_id=secrets.token_urlsafe(18),
                owner=owner,
                expires_at=now + lease_ms / 1000.0,
                lease_ms=lease_ms,
            )
            return self._payload(self._lease)

    def renew(self, owner: str, lease_id: str) -> dict[str, Any]:
        with self._lock:
            lease = self._valid_lease()
            if lease is None or lease.owner != owner or not hmac.compare_digest(lease.lease_id, lease_id):
                raise ProtocolError("CONTROL_LEASE_INVALID", "The control lease is missing, expired, or owned by another client.")
            lease.expires_at = monotonic() + lease.lease_ms / 1000.0
            return self._payload(lease)

    def release(self, owner: str, lease_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            lease = self._valid_lease()
            if lease is None:
                self._lease = None
                return {"released": False}
            if lease.owner != owner:
                raise ProtocolError("CONTROL_LEASE_INVALID", "The control lease is owned by another client.")
            if lease_id and not hmac.compare_digest(lease.lease_id, lease_id):
                raise ProtocolError("CONTROL_LEASE_INVALID", "The control lease ID is invalid.")
            self._lease = None
            return {"released": True}

    def require(self, owner: str, lease_id: str | None) -> None:
        with self._lock:
            lease = self._valid_lease()
            if lease is None or lease.owner != owner or not lease_id or not hmac.compare_digest(lease.lease_id, lease_id):
                raise ProtocolError("CONTROL_LEASE_REQUIRED", "Acquire and maintain a control lease before sending this command.")

    def release_owner(self, owner: str) -> None:
        with self._lock:
            if self._lease is not None and self._lease.owner == owner:
                self._lease = None

    def _valid_lease(self) -> ControlLease | None:
        if self._lease is not None and self._lease.expires_at <= monotonic():
            self._lease = None
        return self._lease

    @staticmethod
    def _payload(lease: ControlLease) -> dict[str, Any]:
        return {
            "lease_id": lease.lease_id,
            "lease_ms": lease.lease_ms,
            "expires_in_ms": max(0, int((lease.expires_at - monotonic()) * 1000)),
        }


class MountAgent:
    def __init__(
        self,
        command_handler: Callable[[str, dict[str, Any], dict[str, Any]], Any],
        telemetry_provider: Callable[[], dict[str, Any]],
        settings_provider: Callable[[], dict[str, Any]],
        terrain_path: Path | None = None,
        terrain_updated: Callable[[], Any] | None = None,
        command_monitor: Any | None = None,
    ) -> None:
        self._command_handler = command_handler
        self._telemetry_provider = telemetry_provider
        self._settings_provider = settings_provider
        self._terrain_path = terrain_path
        self._terrain_updated = terrain_updated
        self._command_monitor = command_monitor
        self._stop = Event()
        self._leases = ControlLeaseManager()
        self._local_thread: Thread | None = None
        self._remote_thread: Thread | None = None
        self._local_socket: socket.socket | None = None
        self._outbound_events: Queue[dict[str, Any]] = Queue(maxsize=128)
        self._camera_telemetry_sequence = 0
        self._station_config_lock = Lock()
        self._station_config_revision = 0
        self._station_config_synced_revision = 0
        self._station_config_changed_fields: list[str] = []
        self._station_config_requests: dict[str, int] = {}
        self._station_config_retry_at = 0.0
        self._station_config_retry_delay = 5.0
        self._load_station_config_sync_state()

    def station_configuration_saved(self, changed_fields: list[str]) -> None:
        """Mark a locally, atomically saved public station configuration for sync.

        This method never sends on the socket itself; the authenticated remote
        session owns all writes so telemetry and configuration NDJSON messages
        cannot interleave.
        """
        fields = sorted(set(changed_fields) & STATION_CONFIG_FIELDS)
        if not fields:
            return
        with self._station_config_lock:
            self._station_config_revision += 1
            self._station_config_changed_fields = fields
            self._save_station_config_sync_state()
            revision = self._station_config_revision
            self._station_config_retry_at = monotonic() + 5.0
            self._station_config_retry_delay = 5.0
        self._enqueue_station_config_changed(revision, fields)

    def _load_station_config_sync_state(self) -> None:
        try:
            state = json.loads(STATION_CONFIG_STATE_PATH.read_text(encoding="utf-8"))
            self._station_config_revision = max(0, int(state.get("revision", 0)))
            self._station_config_synced_revision = max(0, int(state.get("synced_revision", 0)))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            pass

    def _save_station_config_sync_state(self) -> None:
        state = {"revision": self._station_config_revision, "synced_revision": self._station_config_synced_revision}
        fd, temporary = tempfile.mkstemp(prefix=".station-config-sync.", dir=STATION_CONFIG_STATE_PATH.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                json.dump(state, output, sort_keys=True)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, STATION_CONFIG_STATE_PATH)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    def _enqueue_station_config_changed(self, revision: int, fields: list[str]) -> None:
        event = {"type": "station_config_changed", "payload": {"revision": revision, "changed_fields": fields}}
        try:
            self._outbound_events.put_nowait(event)
        except Exception:
            LOGGER.warning("Station configuration sync queue is full; revision %s remains pending.", revision)

    def _retry_station_config_if_due(self) -> None:
        with self._station_config_lock:
            if self._station_config_revision <= self._station_config_synced_revision or monotonic() < self._station_config_retry_at:
                return
            revision = self._station_config_revision
            fields = list(self._station_config_changed_fields)
            delay = self._station_config_retry_delay
            self._station_config_retry_at = monotonic() + delay
            self._station_config_retry_delay = min(delay * 2.0, 60.0)
        self._enqueue_station_config_changed(revision, fields)

    def start(self) -> None:
        settings = self._agent_settings()
        local = settings.get("local", {})
        if local.get("enabled", True):
            self._local_thread = Thread(target=self._run_local_server, name="mount-agent-local", daemon=True)
            self._local_thread.start()
        self._remote_thread = Thread(target=self._run_remote_client, name="mount-agent-remote", daemon=True)
        self._remote_thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._local_socket is not None:
            try:
                self._local_socket.close()
            except OSError:
                pass

    def dispatch_for_session(
        self,
        message: dict[str, Any],
        *,
        source: str,
        owner: str,
    ) -> dict[str, Any]:
        """Dispatch one trusted transport adapter message through protocol policy."""
        response, _ = self._dispatch_message(
            message,
            {"source": source, "owner": owner},
        )
        return response

    def publish_event(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Queue a small Station-originated event for the authenticated receiver."""
        if not event_type or not isinstance(payload, dict):
            raise ProtocolError("INVALID_PARAMETER", "event_type and payload are required.")
        try:
            self._outbound_events.put_nowait({"type": event_type, "payload": payload})
        except Exception as exc:
            raise ProtocolError("EVENT_QUEUE_FULL", "The outbound event queue is full.") from exc
        return {"queued": True, "type": event_type}

    def _agent_settings(self) -> dict[str, Any]:
        settings = self._settings_provider().get("mount_agent", {})
        return settings if isinstance(settings, dict) else {}

    def _run_local_server(self) -> None:
        local = self._agent_settings().get("local", {})
        socket_path = Path(str(local.get("socket_path") or DEFAULT_LOCAL_SOCKET))
        socket_path.parent.mkdir(parents=True, exist_ok=True)
        if socket_path.exists():
            socket_path.unlink()

        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._local_socket = listener
        listener.bind(str(socket_path))
        os.chmod(socket_path, int(str(local.get("mode", "660")), 8))
        listener.listen(8)
        listener.settimeout(1.0)
        LOGGER.info("Mount local control interface listening on %s", socket_path)
        try:
            while not self._stop.is_set():
                try:
                    client, _ = listener.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                Thread(target=self._serve_local_client, args=(client,), name="mount-agent-local-client", daemon=True).start()
        finally:
            try:
                listener.close()
            except OSError:
                pass
            try:
                socket_path.unlink(missing_ok=True)
            except OSError:
                pass

    def _serve_local_client(self, client: socket.socket) -> None:
        peer_pid, peer_uid, peer_gid = _peer_credentials(client)
        allowed_uids = {0, os.geteuid()}
        if peer_uid not in allowed_uids:
            LOGGER.warning("Rejected local mount client uid=%s pid=%s", peer_uid, peer_pid)
            client.close()
            return
        owner = f"local:{peer_uid}:{peer_pid}:{secrets.token_hex(5)}"
        context = {"source": "local", "owner": owner, "uid": peer_uid, "gid": peer_gid, "pid": peer_pid}
        self._serve_session(client, context, require_remote_auth=False)

    def _serve_session(self, connection: socket.socket, context: dict[str, Any], require_remote_auth: bool) -> None:
        del require_remote_auth  # Remote authentication is completed before this common session loop.
        connection.settimeout(0.25)
        buffer = bytearray()
        seen_ids: deque[str] = deque(maxlen=1024)
        seen_set: set[str] = set()
        command_times: deque[float] = deque()
        subscriptions: dict[str, float] = {}
        next_telemetry_at = monotonic()
        try:
            while not self._stop.is_set():
                try:
                    chunk = connection.recv(8192)
                    if not chunk:
                        break
                    buffer.extend(chunk)
                    if len(buffer) > MAX_MESSAGE_BYTES and b"\n" not in buffer:
                        raise ProtocolError("MESSAGE_TOO_LARGE", "Message exceeds the 64 KiB limit.")
                except socket.timeout:
                    chunk = None

                while b"\n" in buffer:
                    raw, _, remainder = buffer.partition(b"\n")
                    buffer = bytearray(remainder)
                    if not raw.strip():
                        continue
                    now = monotonic()
                    while command_times and now - command_times[0] > 1.0:
                        command_times.popleft()
                    if len(command_times) >= MAX_COMMANDS_PER_SECOND:
                        raise ProtocolError("RATE_LIMITED", "Command rate exceeds the session limit.")
                    command_times.append(now)
                    message = _decode_message(raw)
                    message_id = str(message.get("message_id") or message.get("id") or "")
                    if not message_id:
                        raise ProtocolError("MISSING_MESSAGE_ID", "message_id is required.")
                    if message_id in seen_set:
                        _send_json(connection, _response(message, True, {"duplicate": True}))
                        continue
                    if len(seen_ids) == seen_ids.maxlen:
                        seen_set.discard(seen_ids[0])
                    seen_ids.append(message_id)
                    seen_set.add(message_id)
                    response, subscription_update = self._dispatch_message(message, context)
                    if subscription_update is not None:
                        subscriptions = subscription_update
                    _send_json(connection, response)

                now = monotonic()
                if subscriptions and now >= next_telemetry_at:
                    snapshot = self._telemetry_provider()
                    for topic, interval_sec in subscriptions.items():
                        _send_json(connection, _telemetry_event(topic, snapshot))
                        next_telemetry_at = min(next_telemetry_at or now, now + interval_sec)
                    next_telemetry_at = now + min(subscriptions.values())
        except ProtocolError as exc:
            try:
                _send_json(connection, _error_response(None, exc))
            except OSError:
                pass
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            LOGGER.info("Mount agent session ended: %s", exc)
        finally:
            self._leases.release_owner(context["owner"])
            try:
                connection.close()
            except OSError:
                pass

    def _dispatch_message(
        self,
        message: dict[str, Any],
        context: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, float] | None]:
        begin = getattr(self._command_monitor, "begin", None)
        finish = getattr(self._command_monitor, "finish", None)
        handle = None
        if callable(begin):
            try:
                handle = begin(message, context)
            except Exception:
                LOGGER.exception("Could not begin API command trace.")
        response: dict[str, Any] | None = None
        try:
            response, subscription_update = self._dispatch_message_inner(message, context, handle)
            return response, subscription_update
        finally:
            if handle is not None and callable(finish):
                try:
                    finish(handle, response)
                except Exception:
                    LOGGER.exception("Could not finish API command trace.")

    def _dispatch_message_inner(
        self,
        message: dict[str, Any],
        context: dict[str, Any],
        trace_handle: Any | None,
    ) -> tuple[dict[str, Any], dict[str, float] | None]:
        if message.get("version") != PROTOCOL_VERSION:
            return _error_response(message, ProtocolError("UNSUPPORTED_VERSION", "Protocol version 1.0 is required.")), None
        if message.get("type") != "command":
            return _error_response(message, ProtocolError("INVALID_MESSAGE_TYPE", "Expected a command message.")), None
        action = str(message.get("action") or "")
        params = message.get("params")
        if not isinstance(params, dict):
            params = {}
        try:
            _validate_expiry(message)
            mark_dispatch_started = getattr(self._command_monitor, "mark_dispatch_started", None)
            if trace_handle is not None and callable(mark_dispatch_started):
                mark_dispatch_started(trace_handle)
            if action == "camera.publish_frame_ready":
                if context.get("source") != "local":
                    raise ProtocolError("ACTION_NOT_ALLOWED", "Frame notifications may only be published locally.")
                result = self.publish_event("camera.frame_ready", params)
            elif action == "control.acquire":
                result = self._leases.acquire(context["owner"], int(params.get("lease_ms", 5000)))
            elif action == "control.renew":
                result = self._leases.renew(context["owner"], str(params.get("lease_id") or ""))
            elif action == "control.release":
                result = self._leases.release(context["owner"], str(params.get("lease_id") or ""))
            elif action == "subscribe":
                topics = params.get("topics") or ["mount.status"]
                if not isinstance(topics, list) or not all(isinstance(topic, str) for topic in topics):
                    raise ProtocolError("INVALID_PARAMETER", "topics must be an array of strings.")
                interval_ms = max(100, min(int(params.get("interval_ms", 1000)), 60_000))
                subscriptions = {topic: interval_ms / 1000.0 for topic in topics}
                return _response(message, True, {"topics": topics, "interval_ms": interval_ms}), subscriptions
            elif action == "unsubscribe":
                return _response(message, True, {"unsubscribed": True}), {}
            else:
                if action.startswith(MUTATING_PREFIXES) and action not in LEASE_EXEMPT_ACTIONS:
                    self._leases.require(context["owner"], str(message.get("control_lease_id") or params.get("control_lease_id") or ""))
                result = self._command_handler(action, params, context)
            return _response(message, True, result), None
        except ProtocolError as exc:
            return _error_response(message, exc), None
        except ValueError as exc:
            return _error_response(message, ProtocolError("INVALID_PARAMETER", str(exc))), None
        except Exception as exc:
            LOGGER.exception("Mount command %s failed from %s", action, context.get("source"))
            return _error_response(message, ProtocolError("COMMAND_FAILED", str(exc))), None

    def _run_remote_client(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            remote = self._agent_settings().get("remote", {})
            if not remote.get("enabled", False):
                self._stop.wait(2.0)
                continue
            try:
                self._remote_session(remote)
                backoff = 1.0
            except Exception as exc:
                LOGGER.warning("Remote mount protocol disconnected: %s", exc)
                self._stop.wait(backoff)
                backoff = min(backoff * 2.0, 60.0)

    def _remote_session(self, remote: dict[str, Any]) -> None:
        host = str(remote.get("host") or "")
        port = int(remote.get("port") or 0)
        device_id = str(remote.get("device_id") or "")
        if not host or not port or not device_id:
            raise ProtocolError("REMOTE_CONFIG_INVALID", "Remote host, port, and device_id are required.")
        secret = _load_remote_secret(remote)
        context_ssl = ssl.create_default_context(cafile=remote.get("ca_file") or None)
        context_ssl.minimum_version = ssl.TLSVersion.TLSv1_2
        if remote.get("client_cert_file"):
            context_ssl.load_cert_chain(
                certfile=str(remote["client_cert_file"]),
                keyfile=str(remote.get("client_key_file") or remote["client_cert_file"]),
            )
        with socket.create_connection((host, port), timeout=10.0) as raw:
            with context_ssl.wrap_socket(raw, server_hostname=str(remote.get("server_name") or host)) as secure:
                secure.settimeout(10.0)
                _send_json(secure, {
                    "version": PROTOCOL_VERSION,
                    "type": "hello",
                    "message_id": _message_id("hello"),
                    "device_id": device_id,
                    "timestamp": _timestamp(),
                    "payload": {
                        "device_type": "fire-detection-mount",
                        "capabilities": _capabilities(),
                        "services": {
                            "backup_pull_api": _backup_pull_service(remote),
                        },
                        **_station_registration(self._settings_provider()),
                        "terrain": _terrain_registration(self._terrain_path),
                    },
                })
                challenge = _recv_json(secure)
                if challenge.get("type") != "auth_challenge":
                    raise ProtocolError("AUTH_PROTOCOL_ERROR", "Expected auth_challenge from server.")
                nonce = str((challenge.get("payload") or {}).get("nonce") or "")
                if not nonce:
                    raise ProtocolError("AUTH_PROTOCOL_ERROR", "Server challenge did not contain a nonce.")
                auth_timestamp = _timestamp()
                signature = hmac.new(
                    secret,
                    f"{device_id}\n{nonce}\n{auth_timestamp}".encode("utf-8"),
                    hashlib.sha256,
                ).hexdigest()
                _send_json(secure, {
                    "version": PROTOCOL_VERSION,
                    "type": "auth",
                    "message_id": _message_id("auth"),
                    "device_id": device_id,
                    "timestamp": auth_timestamp,
                    "payload": {"nonce": nonce, "signature": signature, "algorithm": "HMAC-SHA256"},
                })
                auth_result = _recv_json(secure)
                if auth_result.get("type") != "auth_result" or not bool((auth_result.get("payload") or {}).get("authenticated")):
                    raise ProtocolError("AUTH_FAILED", "Remote server rejected device authentication.")
                terrain = (auth_result.get("payload") or {}).get("terrain")
                if isinstance(terrain, dict) and terrain.get("download_url"):
                    changed = _synchronize_terrain(
                        terrain,
                        self._terrain_path,
                        remote,
                        context_ssl,
                        self._settings_provider(),
                    )
                    if changed and self._terrain_updated is not None:
                        self._terrain_updated()
                # A short socket timeout also applies to sendall(), which made
                # healthy but briefly back-pressured telemetry links reconnect.
                # Poll read readiness separately and retain a bounded write
                # timeout for fail-fast shutdown when a Receiver stops reading.
                secure.settimeout(5.0)
                owner = f"remote:{device_id}:{secrets.token_hex(5)}"
                LOGGER.info(
                    "Remote mount protocol authenticated for device_id=%s; starting heartbeat every %ss and axis.telemetry every %ss.",
                    device_id,
                    max(2.0, float(remote.get("heartbeat_sec", DEFAULT_HEARTBEAT_SEC))),
                    max(0.1, float(remote.get("telemetry_sec", DEFAULT_TELEMETRY_SEC))),
                )
                with self._station_config_lock:
                    pending_revision = self._station_config_revision
                    pending_fields = list(self._station_config_changed_fields)
                    needs_sync = pending_revision > self._station_config_synced_revision
                if needs_sync:
                    self._enqueue_station_config_changed(pending_revision, pending_fields)
                self._serve_remote_authenticated(secure, {"source": "remote", "owner": owner, "device_id": device_id}, remote)

    def _serve_remote_authenticated(self, secure: socket.socket, context: dict[str, Any], remote: dict[str, Any]) -> None:
        buffer = bytearray()
        seen_ids: deque[str] = deque(maxlen=1024)
        seen_set: set[str] = set()
        command_times: deque[float] = deque()
        heartbeat_sec = max(2.0, float(remote.get("heartbeat_sec", DEFAULT_HEARTBEAT_SEC)))
        telemetry_sec = max(0.1, float(remote.get("telemetry_sec", DEFAULT_TELEMETRY_SEC)))
        next_heartbeat = monotonic()
        next_telemetry = monotonic()
        allowed = set(remote.get("allowed_commands") or _remote_default_commands())
        try:
            while not self._stop.is_set():
                now = monotonic()
                self._retry_station_config_if_due()
                if now >= next_heartbeat:
                    _send_json(secure, {
                        "version": PROTOCOL_VERSION,
                        "type": "heartbeat",
                        "message_id": _message_id("hb"),
                        "device_id": context["device_id"],
                        "timestamp": _timestamp(),
                        "payload": {"sequence_time": monotonic()},
                    })
                    next_heartbeat = now + heartbeat_sec
                if now >= next_telemetry:
                    snapshot = self._telemetry_provider()
                    _send_json(secure, _telemetry_event("axis.telemetry", snapshot, context["device_id"]))
                    camera_telemetry = self._camera_telemetry_event(snapshot, context["device_id"])
                    if camera_telemetry is not None:
                        _send_json(secure, camera_telemetry)
                    next_telemetry = now + telemetry_sec
                self._send_queued_events(secure, context["device_id"])
                readable, _, _ = select.select([secure], [], [], 0.1)
                if not readable and secure.pending() == 0:
                    continue
                chunk = secure.recv(8192)
                if not chunk:
                    raise ConnectionError("Remote server closed the TLS session.")
                buffer.extend(chunk)
                if len(buffer) > MAX_MESSAGE_BYTES and b"\n" not in buffer:
                    raise ProtocolError("MESSAGE_TOO_LARGE", "Remote message exceeds the 64 KiB limit.")
                while b"\n" in buffer:
                    raw, _, remainder = buffer.partition(b"\n")
                    buffer = bytearray(remainder)
                    message = _decode_message(raw)
                    message_type = str(message.get("type") or "")
                    if message_type == "station_config_request":
                        self._send_station_config_snapshot(secure, context["device_id"], message)
                        continue
                    if message_type == "station_config_result":
                        self._handle_station_config_result(message)
                        continue
                    now = monotonic()
                    while command_times and now - command_times[0] > 1.0:
                        command_times.popleft()
                    if len(command_times) >= MAX_COMMANDS_PER_SECOND:
                        _send_json(secure, _error_response(message, ProtocolError("RATE_LIMITED", "Command rate exceeds the session limit.")))
                        continue
                    command_times.append(now)
                    message_id = str(message.get("message_id") or message.get("id") or "")
                    if not message_id:
                        _send_json(secure, _error_response(message, ProtocolError("MISSING_MESSAGE_ID", "message_id is required.")))
                        continue
                    if message_id in seen_set:
                        _send_json(secure, _response(message, True, {"duplicate": True}))
                        continue
                    if len(seen_ids) == seen_ids.maxlen:
                        seen_set.discard(seen_ids[0])
                    seen_ids.append(message_id)
                    seen_set.add(message_id)
                    action = str(message.get("action") or "")
                    if action not in allowed:
                        _send_json(secure, _error_response(message, ProtocolError("ACTION_NOT_ALLOWED", "Command is not permitted for the remote interface.")))
                        continue
                    response, _ = self._dispatch_message(message, context)
                    response["device_id"] = context["device_id"]
                    _send_json(secure, response)
        finally:
            self._leases.release_owner(context["owner"])

    def _send_queued_events(self, secure: socket.socket, device_id: str) -> None:
        for _ in range(16):
            try:
                event = self._outbound_events.get_nowait()
            except Empty:
                return
            _send_json(secure, {
                "version": PROTOCOL_VERSION,
                "type": event["type"],
                "message_id": _message_id("event"),
                "device_id": device_id,
                "timestamp": _timestamp(),
                "payload": event["payload"],
            })
            LOGGER.info("Sent %s event for device_id=%s.", event["type"], device_id)

    def _send_station_config_snapshot(self, secure: socket.socket, device_id: str, request: dict[str, Any]) -> None:
        payload = request.get("payload")
        if not isinstance(payload, dict) or not isinstance(payload.get("request_id"), str):
            raise ProtocolError("INVALID_CONFIG_REQUEST", "station_config_request requires payload.request_id.")
        with self._station_config_lock:
            revision = self._station_config_revision
            self._station_config_requests[payload["request_id"]] = revision
        metadata = _station_config_snapshot(self._settings_provider())
        canonical = json.dumps(metadata, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        _send_json(secure, {
            "version": PROTOCOL_VERSION,
            "type": "station_config_snapshot",
            "message_id": _message_id("station-config-snapshot"),
            "device_id": device_id,
            "timestamp": _timestamp(),
            "payload": {
                "request_id": payload["request_id"],
                "revision": revision,
                "config_hash": hashlib.sha256(canonical).hexdigest(),
                "station_metadata": metadata,
            },
        })

    def _handle_station_config_result(self, message: dict[str, Any]) -> None:
        payload = message.get("payload")
        if not isinstance(payload, dict) or not isinstance(payload.get("request_id"), str):
            return
        with self._station_config_lock:
            revision = self._station_config_requests.pop(payload["request_id"], None)
            if not payload.get("accepted") or revision is None:
                return
            self._station_config_synced_revision = max(self._station_config_synced_revision, revision)
            self._station_config_retry_at = 0.0
            self._station_config_retry_delay = 5.0
            self._save_station_config_sync_state()
        LOGGER.info("Station configuration revision %s synchronized.", self._station_config_synced_revision)

    def _camera_telemetry_event(self, snapshot: dict[str, Any], device_id: str) -> dict[str, Any] | None:
        metadata = self._settings_provider().get("camera_metadata")
        thermal = metadata.get("thermal_camera") if isinstance(metadata, dict) else None
        if not isinstance(thermal, dict):
            return None
        axes = snapshot.get("axes") if isinstance(snapshot, dict) else None
        azimuth: dict[str, Any] = {}
        altitude: dict[str, Any] = {}
        if isinstance(axes, list):
            for axis in axes:
                if not isinstance(axis, dict):
                    continue
                label = str(axis.get("label") or "").lower()
                if label == "azimuth":
                    azimuth = axis
                elif label == "altitude":
                    altitude = axis
        self._camera_telemetry_sequence += 1
        timestamp = _timestamp()
        data = {
            "timestamp_utc": timestamp,
            "sequence": self._camera_telemetry_sequence,
            "azimuth_deg": _number_or_none(azimuth.get("position_deg")),
            "altitude_deg": _number_or_none(altitude.get("position_deg")),
            "azimuth_velocity_deg_per_sec": _number_or_none(azimuth.get("velocity_deg_per_sec")),
            "altitude_velocity_deg_per_sec": _number_or_none(altitude.get("velocity_deg_per_sec")),
            "thermal": {
                "zoom_x": 1.0,
                "horizontal_fov_deg": _number_or_none(thermal.get("horizontal_fov_max_deg")),
                "vertical_fov_deg": _number_or_none(thermal.get("vertical_fov_max_deg")),
                "palette": "iron",
                "simulated": True,
            },
        }
        return {
            "version": PROTOCOL_VERSION,
            "type": "telemetry",
            "message_id": _message_id("camera"),
            "device_id": device_id,
            "timestamp": timestamp,
            "payload": {"topic": "camera.telemetry", "data": data},
        }


def _peer_credentials(client: socket.socket) -> tuple[int, int, int]:
    if not hasattr(socket, "SO_PEERCRED"):
        return (0, os.geteuid(), os.getegid())
    raw = client.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    return struct.unpack("3i", raw)


def _decode_message(raw: bytes) -> dict[str, Any]:
    if len(raw) > MAX_MESSAGE_BYTES:
        raise ProtocolError("MESSAGE_TOO_LARGE", "Message exceeds the 64 KiB limit.")
    try:
        message = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("INVALID_JSON", f"Invalid UTF-8 JSON: {exc}") from exc
    if not isinstance(message, dict):
        raise ProtocolError("INVALID_JSON", "The JSON root must be an object.")
    return message


def _send_json(connection: socket.socket, message: dict[str, Any]) -> None:
    wire = json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n"
    if len(wire) > MAX_MESSAGE_BYTES:
        raise ProtocolError("MESSAGE_TOO_LARGE", "Outgoing message exceeds the 64 KiB limit.")
    connection.sendall(wire)


def _recv_json(connection: socket.socket) -> dict[str, Any]:
    buffer = bytearray()
    while b"\n" not in buffer:
        chunk = connection.recv(8192)
        if not chunk:
            raise ConnectionError("Connection closed while waiting for a protocol message.")
        buffer.extend(chunk)
        if len(buffer) > MAX_MESSAGE_BYTES:
            raise ProtocolError("MESSAGE_TOO_LARGE", "Message exceeds the 64 KiB limit.")
    return _decode_message(bytes(buffer.partition(b"\n")[0]))


def _response(message: dict[str, Any], ok: bool, result: Any) -> dict[str, Any]:
    return {
        "version": PROTOCOL_VERSION,
        "type": "response",
        "message_id": _message_id("rsp"),
        "correlation_id": message.get("message_id") or message.get("id"),
        "action": message.get("action"),
        "timestamp": _timestamp(),
        "ok": ok,
        "result": result,
    }


def _error_response(message: dict[str, Any] | None, error: ProtocolError) -> dict[str, Any]:
    return {
        "version": PROTOCOL_VERSION,
        "type": "response",
        "message_id": _message_id("err"),
        "correlation_id": (message or {}).get("message_id") or (message or {}).get("id"),
        "action": (message or {}).get("action"),
        "timestamp": _timestamp(),
        "ok": False,
        "error": {"code": error.code, "message": str(error), "details": error.details},
    }


def _telemetry_event(topic: str, snapshot: dict[str, Any], device_id: str | None = None) -> dict[str, Any]:
    return {
        "version": PROTOCOL_VERSION,
        "type": "telemetry",
        "message_id": _message_id("tel"),
        "device_id": device_id,
        "timestamp": _timestamp(),
        "payload": {"topic": topic, "data": _topic_payload(topic, snapshot)},
    }


def _topic_payload(topic: str, snapshot: dict[str, Any]) -> Any:
    if topic == "axis.telemetry":
        return {"axes": snapshot.get("axes", []), "connected": snapshot.get("connected")}
    if topic == "sensor.status":
        return {"azimuth_sensors": snapshot.get("azimuth_sensors", {})}
    if topic == "fault":
        return {"events": snapshot.get("drive_error_events", [])}
    if topic == "drive.status":
        return {
            "connected": snapshot.get("connected"),
            "device_serials": snapshot.get("device_serials", []),
            "has_bus_power": snapshot.get("has_bus_power"),
            "health": snapshot.get("health"),
        }
    if topic == "calibration.status":
        return snapshot.get("motor_calibration", {})
    return {
        "connected": snapshot.get("connected"),
        "health": snapshot.get("health"),
        "timestamp": snapshot.get("timestamp"),
        "axes": snapshot.get("axes", []),
    }


def _validate_expiry(message: dict[str, Any]) -> None:
    expires_at = message.get("expires_at")
    if not expires_at:
        return
    try:
        expiry = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProtocolError("INVALID_PARAMETER", "expires_at must be an ISO 8601 timestamp.") from exc
    if expiry.tzinfo is None:
        raise ProtocolError("INVALID_PARAMETER", "expires_at must include a timezone.")
    if expiry.astimezone(timezone.utc) <= datetime.now(timezone.utc):
        raise ProtocolError("COMMAND_EXPIRED", "The command expired before it reached the mount.")


def _backup_pull_service(remote: dict[str, Any]) -> dict[str, Any]:
    """Describe the pull API and advertise the Station's tailnet URL."""
    service: dict[str, Any] = {
        "version": "1.0",
        "base_path": "/api/v1/backups",
        "authentication": "HMAC-SHA256",
        "transport": "tailscale-http",
    }
    try:
        remote_host = str(remote.get("host") or "")
        remote_port = int(remote.get("port") or 1)
        remote_address = ipaddress.ip_address(remote_host)
        if remote_address.version != 4 or remote_address not in TAILSCALE_IPV4_NETWORK:
            return service
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect((remote_host, remote_port))
            local_address = ipaddress.ip_address(probe.getsockname()[0])
        if local_address not in TAILSCALE_IPV4_NETWORK:
            return service
        url = f"http://{local_address}:{DEFAULT_BACKUP_API_PORT}/api/v1/backups"
        service["url"] = url
        service["base_url"] = url
    except (OSError, TypeError, ValueError):
        pass
    return service


def _load_remote_secret(remote: dict[str, Any]) -> bytes:
    secret_file = remote.get("secret_file")
    env_name = str(remote.get("secret_env") or "FIRE_DETECTOR_DEVICE_SECRET")
    if secret_file:
        path = Path(str(secret_file))
        secret = path.read_bytes().strip()
    else:
        secret = os.environ.get(env_name, "").encode("utf-8")
    if len(secret) < 32:
        raise ProtocolError("REMOTE_SECRET_INVALID", "The device secret must contain at least 32 bytes.")
    return secret


def _number_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _capabilities() -> list[str]:
    """Return the actions implemented by the shared command router.

    This list is sent before remote authentication, so keep it aligned with
    ``MountCommandRouter.capabilities``.  The transport-level control and
    subscription actions are included as well.
    """
    return sorted({
        "system.hello", "system.ping", "system.get_info", "system.get_health",
        "system.get_capabilities", "mount.get_status",
        "mount.enable", "mount.disable", "mount.stop", "mount.goto", "mount.set_velocity",
        "axis.enable", "axis.disable", "axis.stop", "axis.goto", "axis.set_velocity",
        "pointing.goto_altaz", "calibration.start", "calibration.stop",
        "calibration.get_status", "tuning.apply", "tuning.save", "subscribe", "unsubscribe",
        "control.acquire", "control.renew", "control.release",
    })


def _station_registration(settings: dict[str, Any]) -> dict[str, Any]:
    """Return stable installation metadata for the receiver's device registry.

    The values are sent only during the initial remote ``hello``.  They are
    installation data, not live GPS telemetry, so ordinary position jitter
    cannot create needless DEM revisions on the receiver.
    """
    station = settings.get("station")
    if not isinstance(station, dict):
        return {}
    try:
        latitude = float(station["latitude"])
        longitude = float(station["longitude"])
        elevation_agl = float(station["elevation_above_ground_m"])
    except (KeyError, TypeError, ValueError):
        return {}
    if (
        not math.isfinite(latitude)
        or not math.isfinite(longitude)
        or not math.isfinite(elevation_agl)
        or not -90.0 <= latitude <= 90.0
        or not -180.0 <= longitude <= 180.0
        or elevation_agl < 0.0
    ):
        return {}
    registration = {
        "latitude": latitude,
        "longitude": longitude,
        "elevation_above_ground_m": elevation_agl,
    }
    try:
        north_offset = float(station.get("azimuth_north_offset_deg", 0.0))
    except (TypeError, ValueError):
        north_offset = 0.0
    if math.isfinite(north_offset) and -360.0 <= north_offset <= 360.0:
        registration["azimuth_north_offset_deg"] = north_offset
    name = str(station.get("name") or "").strip()
    if name:
        registration["station_name"] = name
    camera_metadata = settings.get("camera_metadata")
    if isinstance(camera_metadata, dict):
        for camera_name in ("visible_camera", "thermal_camera"):
            camera = camera_metadata.get(camera_name)
            if isinstance(camera, dict):
                registration[camera_name] = camera
    return registration


def _station_config_snapshot(settings: dict[str, Any]) -> dict[str, Any]:
    """Build the strict allowlisted public snapshot used for receiver sync."""
    station = settings.get("station") if isinstance(settings.get("station"), dict) else {}
    metadata = settings.get("camera_metadata") if isinstance(settings.get("camera_metadata"), dict) else {}
    result: dict[str, Any] = {}
    field_map = {
        "station_name": "name",
        "latitude": "latitude",
        "longitude": "longitude",
        "elevation_above_ground_m": "elevation_above_ground_m",
        "horizontal_fov_deg": "horizontal_fov_deg",
        "vertical_fov_deg": "vertical_fov_deg",
        "azimuth_north_offset_deg": "azimuth_north_offset_deg",
    }
    for output_name, source_name in field_map.items():
        value = station.get(source_name)
        if output_name == "station_name":
            value = str(value or "").strip()
            if value:
                result[output_name] = value
        elif isinstance(value, (int, float)) and math.isfinite(value):
            result[output_name] = float(value)
    camera_fields = {
        "visible_camera": (
            "native_width", "native_height", "horizontal_fov_min_deg", "horizontal_fov_max_deg",
            "vertical_fov_min_deg", "vertical_fov_max_deg",
        ),
        "thermal_camera": ("native_width", "native_height"),
    }
    for camera_name, allowed_fields in camera_fields.items():
        camera = metadata.get(camera_name)
        if not isinstance(camera, dict):
            continue
        safe_camera = {key: camera[key] for key in allowed_fields if isinstance(camera.get(key), (int, float)) and math.isfinite(camera[key])}
        if safe_camera:
            result[camera_name] = safe_camera
    return result


def _terrain_registration(path: Path | None) -> dict[str, Any]:
    """Describe the station's current DEM so the receiver can skip or request sync."""
    if path is None or not path.is_file():
        return {"available": False}
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        stat = path.stat()
    except OSError:
        return {"available": False}
    return {
        "available": True,
        "sha256": digest.hexdigest(),
        "size_bytes": stat.st_size,
        "format": "geotiff",
    }


def _synchronize_terrain(
    manifest: dict[str, Any],
    destination: Path | None,
    remote: dict[str, Any],
    tls_context: ssl.SSLContext,
    settings: dict[str, Any],
) -> bool:
    """Download, verify and atomically install a receiver-provided GeoTIFF."""
    if destination is None:
        raise ProtocolError("TERRAIN_SYNC_DISABLED", "No local terrain destination is configured.")
    expected_sha = str(manifest.get("sha256") or "").lower()
    if len(expected_sha) != 64 or any(char not in "0123456789abcdef" for char in expected_sha):
        raise ProtocolError("TERRAIN_MANIFEST_INVALID", "Terrain manifest must contain a SHA-256 digest.")
    current = _terrain_registration(destination)
    if current.get("sha256") == expected_sha:
        return False

    url = str(manifest.get("download_url") or "")
    parsed = urllib.parse.urlparse(url)
    remote_host = str(remote.get("host") or "").lower()
    if parsed.scheme != "https" or not parsed.hostname or parsed.hostname.lower() != remote_host:
        raise ProtocolError("TERRAIN_URL_REJECTED", "Terrain download must use HTTPS on the configured receiver host.")
    try:
        expected_size = int(manifest.get("size_bytes"))
    except (TypeError, ValueError) as exc:
        raise ProtocolError("TERRAIN_MANIFEST_INVALID", "Terrain size is missing or invalid.") from exc
    if expected_size <= 0 or expected_size > MAX_TERRAIN_BYTES:
        raise ProtocolError("TERRAIN_TOO_LARGE", "Terrain file exceeds the station limit.")

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "FireDetector/1.0"})
        digest = hashlib.sha256()
        received = 0
        with urllib.request.urlopen(request, timeout=120, context=tls_context) as response:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=f".{destination.name}.",
                suffix=".tmp",
                dir=destination.parent,
                delete=False,
            ) as temporary:
                temporary_name = temporary.name
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > expected_size or received > MAX_TERRAIN_BYTES:
                        raise ProtocolError("TERRAIN_SIZE_MISMATCH", "Terrain download is larger than its manifest.")
                    digest.update(chunk)
                    temporary.write(chunk)
                temporary.flush()
                os.fsync(temporary.fileno())
        if received != expected_size or digest.hexdigest() != expected_sha:
            raise ProtocolError("TERRAIN_HASH_MISMATCH", "Terrain download did not match the server manifest.")
        _validate_terrain_file(Path(temporary_name), settings)
        os.replace(temporary_name, destination)
        temporary_name = None
        LOGGER.info("Installed synchronized terrain DEM sha256=%s size=%s.", expected_sha, received)
        return True
    finally:
        if temporary_name:
            try:
                Path(temporary_name).unlink()
            except OSError:
                pass


def _validate_terrain_file(path: Path, settings: dict[str, Any]) -> None:
    from PIL import Image

    try:
        with Image.open(path) as image:
            scale = image.tag_v2.get(33550)
            tiepoint = image.tag_v2.get(33922)
            if image.format != "TIFF" or not scale or not tiepoint or image.width < 2 or image.height < 2:
                raise ValueError
            west = float(tiepoint[3]) - float(tiepoint[0]) * float(scale[0])
            north = float(tiepoint[4]) + float(tiepoint[1]) * float(scale[1])
            east = west + image.width * float(scale[0])
            south = north - image.height * float(scale[1])
    except Exception as exc:
        raise ProtocolError("TERRAIN_INVALID", "Downloaded terrain is not a supported GeoTIFF.") from exc
    station = settings.get("station") if isinstance(settings, dict) else None
    if isinstance(station, dict):
        latitude = _number_or_none(station.get("latitude"))
        longitude = _number_or_none(station.get("longitude"))
        if latitude is not None and longitude is not None and not (south <= latitude <= north and west <= longitude <= east):
            raise ProtocolError("TERRAIN_COVERAGE_INVALID", "Downloaded terrain does not cover the station GPS position.")


def _remote_default_commands() -> list[str]:
    return [
        "system.hello", "system.get_info", "system.get_health", "mount.get_status",
        "control.acquire", "control.renew", "control.release",
        "mount.enable", "mount.disable", "mount.stop", "mount.goto", "mount.set_velocity",
        "axis.enable", "axis.disable", "axis.stop", "axis.goto", "axis.set_velocity",
    ]


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _message_id(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(12)}"
