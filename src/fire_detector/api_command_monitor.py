"""In-memory timing traces for commands entering the Mount Agent protocol."""

from __future__ import annotations

from collections import deque
from contextvars import ContextVar, Token
from dataclasses import dataclass
from datetime import datetime, timezone
import math
from threading import Lock
from time import monotonic
from typing import Any


_CURRENT_TRACE_ID: ContextVar[int | None] = ContextVar("api_command_trace_id", default=None)
_REDACTED_KEY_PARTS = (
    "authorization",
    "control_lease",
    "credential",
    "lease_id",
    "password",
    "secret",
    "token",
)


def current_api_command_trace_id() -> int | None:
    """Return the trace attached to the current protocol-dispatch context."""

    return _CURRENT_TRACE_ID.get()


@dataclass(frozen=True)
class CommandTraceHandle:
    trace_id: int
    started_at: float
    context_token: Token[int | None]


class ApiCommandMonitor:
    """Keep a bounded, thread-safe command timeline for diagnostics.

    This store is intentionally memory-only. Reading it never touches ODrive
    hardware, and command payload credentials are redacted before storage.
    """

    def __init__(self, capacity: int = 300) -> None:
        self._capacity = max(20, int(capacity))
        self._events: deque[dict[str, Any]] = deque(maxlen=self._capacity)
        self._lock = Lock()
        self._next_trace_id = 0
        self._revision = 0

    def begin(self, message: dict[str, Any], context: dict[str, Any]) -> CommandTraceHandle:
        started_at = monotonic()
        with self._lock:
            self._next_trace_id += 1
            trace_id = self._next_trace_id
            if len(self._events) == self._events.maxlen:
                self._events.popleft()
            self._events.append({
                "trace_id": trace_id,
                "received_at": _timestamp(),
                "source": str(context.get("source") or "unknown")[:80],
                "action": str(message.get("action") or "<missing>")[:160],
                "message_id": str(message.get("message_id") or message.get("id") or "")[:180],
                "automatic": (
                    str(context.get("source") or "") == "web-api-console"
                    and str(message.get("action") or "") == "mount.get_status"
                    and str(message.get("message_id") or "").startswith("poll-")
                ),
                "params": _safe_value(message.get("params") if isinstance(message.get("params"), dict) else {}),
                "state": "running",
                "ok": None,
                "policy_ms": None,
                "queue_wait_ms": None,
                "execution_ms": None,
                "total_ms": None,
                "manager_action": None,
                "manager_sequence": None,
                "safety_priority": False,
                "error_code": None,
                "error_message": None,
            })
            self._revision += 1
        token = _CURRENT_TRACE_ID.set(trace_id)
        return CommandTraceHandle(trace_id, started_at, token)

    def mark_dispatch_started(self, handle: CommandTraceHandle) -> None:
        self._update(handle.trace_id, policy_ms=_milliseconds(monotonic() - handle.started_at))

    def record_motion_timing(
        self,
        trace_id: int | None,
        *,
        manager_sequence: int,
        manager_action: str,
        queue_wait_ms: float,
        execution_ms: float,
        ok: bool,
        safety_priority: bool = False,
        superseded: bool = False,
    ) -> None:
        if trace_id is None:
            return
        values: dict[str, Any] = {
            "manager_sequence": int(manager_sequence),
            "manager_action": str(manager_action),
            "queue_wait_ms": _finite_ms(queue_wait_ms),
            "execution_ms": _finite_ms(execution_ms),
            "safety_priority": bool(safety_priority),
        }
        if not ok and superseded:
            values.update(error_code="SUPERSEDED_BY_STOP", error_message="Superseded by a safety stop")
        self._update(trace_id, **values)

    def finish(self, handle: CommandTraceHandle, response: dict[str, Any] | None) -> None:
        try:
            ok = bool(response and response.get("ok") is True)
            error = response.get("error") if isinstance(response, dict) else None
            error = error if isinstance(error, dict) else {}
            self._update(
                handle.trace_id,
                completed_at=_timestamp(),
                state="ok" if ok else "error",
                ok=ok,
                total_ms=_milliseconds(monotonic() - handle.started_at),
                error_code=str(error.get("code") or "") or None,
                error_message=str(error.get("message") or "")[:300] or None,
            )
        finally:
            _CURRENT_TRACE_ID.reset(handle.context_token)

    def snapshot(
        self,
        *,
        after_revision: int = 0,
        limit: int = 100,
        include_automatic: bool = True,
    ) -> dict[str, Any]:
        limit = max(1, min(int(limit), self._capacity))
        with self._lock:
            revision = self._revision
            changed = int(after_revision) != revision
            if not changed:
                events: list[dict[str, Any]] = []
            else:
                selected = (
                    list(self._events)
                    if include_automatic
                    else [event for event in self._events if not event.get("automatic")]
                )
                events = [dict(event) for event in selected[-limit:]]
            running = sum(event.get("state") == "running" for event in self._events)
        return {
            "revision": revision,
            "changed": changed,
            "capacity": self._capacity,
            "running": running,
            "events": events,
        }

    def clear(self) -> dict[str, Any]:
        with self._lock:
            self._events.clear()
            self._revision += 1
            revision = self._revision
        return {"cleared": True, "revision": revision}

    def _update(self, trace_id: int, **values: Any) -> None:
        with self._lock:
            for event in reversed(self._events):
                if event.get("trace_id") == trace_id:
                    event.update(values)
                    self._revision += 1
                    return


def _safe_value(value: Any, depth: int = 0) -> Any:
    if depth >= 4:
        return "<max-depth>"
    if value is None or isinstance(value, (bool, int, str)):
        return value[:500] if isinstance(value, str) else value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 40:
                safe["<truncated>"] = f"{len(value) - index} more fields"
                break
            name = str(key)[:120]
            lowered = name.lower()
            safe[name] = "<redacted>" if any(part in lowered for part in _REDACTED_KEY_PARTS) else _safe_value(item, depth + 1)
        return safe
    if isinstance(value, (list, tuple)):
        return [_safe_value(item, depth + 1) for item in list(value)[:40]]
    return repr(value)[:500]


def _milliseconds(seconds: float) -> float:
    return round(max(0.0, float(seconds) * 1000.0), 3)


def _finite_ms(value: float) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(max(0.0, number), 3) if math.isfinite(number) else None


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
