"""Single-owner scheduling primitives for physical hardware I/O.

The queue does not create a thread.  A device-specific owner loop binds itself
and executes every queued callable.  Other tasks can either wait for an atomic
operation or publish a latest-value command that supersedes stale setpoints.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import count
from queue import Empty, PriorityQueue
from threading import Event, Lock, get_ident
from time import monotonic
from typing import Any, Callable


PRIORITY_SAFETY = 0
PRIORITY_CONTROL = 10
PRIORITY_CONFIGURATION = 20


@dataclass
class _HardwareCall:
    callback: Callable[[], Any]
    label: str
    priority: int
    sequence: int
    enqueued_at: float = field(default_factory=monotonic)
    coalesce_key: str | None = None
    coalesce_token: int | None = None
    done: Event = field(default_factory=Event)
    result: Any = None
    error: BaseException | None = None


class HardwareIOQueue:
    """Priority mailbox whose callables are executed by one bound owner."""

    def __init__(self) -> None:
        self._queue: PriorityQueue[tuple[int, int, _HardwareCall]] = PriorityQueue()
        self._sequence = count(1)
        self._owner_ident: int | None = None
        self._state_lock = Lock()
        self._coalesce_tokens: dict[str, int] = {}
        self._executed = 0
        self._superseded = 0
        self._last_wait_ms = 0.0
        self._max_wait_ms = 0.0

    def bind_owner(self) -> None:
        ident = get_ident()
        with self._state_lock:
            if self._owner_ident not in (None, ident):
                raise RuntimeError("Hardware I/O already has a different owner thread.")
            self._owner_ident = ident

    def is_owner(self) -> bool:
        with self._state_lock:
            return self._owner_ident == get_ident()

    def call(
        self,
        callback: Callable[[], Any],
        *,
        label: str,
        priority: int = PRIORITY_CONTROL,
        coalesce_key: str | None = None,
    ) -> Any:
        if self.is_owner():
            return callback()
        task = self._enqueue(callback, label, priority, coalesce_key)
        task.done.wait()
        if task.error is not None:
            raise task.error
        return task.result

    def publish_latest(
        self,
        coalesce_key: str,
        callback: Callable[[], Any],
        *,
        label: str,
        priority: int = PRIORITY_CONTROL,
    ) -> None:
        if self.is_owner():
            callback()
            return
        self._enqueue(callback, label, priority, coalesce_key)

    def take(self, timeout: float | None = None) -> _HardwareCall | None:
        try:
            _, _, task = self._queue.get(timeout=timeout)
            return task
        except Empty:
            return None

    def execute(self, task: _HardwareCall) -> None:
        if not self.is_owner():
            raise RuntimeError("Only the hardware owner may execute I/O tasks.")
        wait_ms = (monotonic() - task.enqueued_at) * 1000.0
        with self._state_lock:
            self._last_wait_ms = wait_ms
            self._max_wait_ms = max(self._max_wait_ms, wait_ms)
            superseded = (
                task.coalesce_key is not None
                and self._coalesce_tokens.get(task.coalesce_key) != task.coalesce_token
            )
            if superseded:
                self._superseded += 1
        try:
            if not superseded:
                task.result = task.callback()
                with self._state_lock:
                    self._executed += 1
        except BaseException as exc:
            task.error = exc
        finally:
            task.done.set()
            self._queue.task_done()

    def stats(self) -> dict[str, Any]:
        with self._state_lock:
            return {
                "single_owner": self._owner_ident is not None,
                "owner_thread_id": self._owner_ident,
                "queue_depth": self._queue.qsize(),
                "executed": self._executed,
                "superseded": self._superseded,
                "last_queue_wait_ms": round(self._last_wait_ms, 3),
                "max_queue_wait_ms": round(self._max_wait_ms, 3),
            }

    def _enqueue(
        self,
        callback: Callable[[], Any],
        label: str,
        priority: int,
        coalesce_key: str | None,
    ) -> _HardwareCall:
        sequence = next(self._sequence)
        token = None
        if coalesce_key is not None:
            with self._state_lock:
                token = self._coalesce_tokens.get(coalesce_key, 0) + 1
                self._coalesce_tokens[coalesce_key] = token
        task = _HardwareCall(
            callback=callback,
            label=label,
            priority=priority,
            sequence=sequence,
            coalesce_key=coalesce_key,
            coalesce_token=token,
        )
        self._queue.put((priority, sequence, task))
        return task
