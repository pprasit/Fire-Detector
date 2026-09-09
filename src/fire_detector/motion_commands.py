"""Central command arbitration for all mount-control transports.

REST, Web UI, local IPC, and remote control adapters must call the managed
controller exposed here.  They never own control-loop threads and never write
to a drive directly.
"""

from __future__ import annotations

import logging
from queue import Queue
from threading import Condition, Event, Lock, Thread, current_thread
from time import monotonic
from typing import Any

from fire_detector.api_command_monitor import current_api_command_trace_id


LOGGER = logging.getLogger(__name__)


class MotionCommandSuperseded(ValueError):
    """A queued motion command was invalidated by a later safety stop."""


class _ManagedCall:
    def __init__(
        self,
        sequence: int,
        safety_epoch: int,
        source: str,
        method_name: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        trace_id: int | None,
    ) -> None:
        self.sequence = sequence
        self.safety_epoch = safety_epoch
        self.source = source
        self.method_name = method_name
        self.args = args
        self.kwargs = kwargs
        self.trace_id = trace_id
        self.enqueued_at = monotonic()
        self.done = Event()
        self.result: Any = None
        self.error: Exception | None = None


class MotionCommandManager:
    """Own command ordering while leaving motion design to the controller.

    Ordinary commands execute FIFO on one worker.  A safety-stop command does
    not join that queue: it advances the safety epoch, invalidates pending
    commands, waits only for the current atomic controller call, and executes
    before any later queued command can enter the controller.
    """

    def __init__(self, controller: Any, command_monitor: Any | None = None) -> None:
        self._controller = controller
        self._command_monitor = command_monitor
        self._queue: Queue[_ManagedCall | None] = Queue()
        self._state = Condition(Lock())
        self._execution_lock = Lock()
        self._safety_stop_lock = Lock()
        self._sequence = 0
        self._safety_epoch = 0
        self._stop_active = False
        self._pending_safety_stops = 0
        self._thread = Thread(target=self._run, name="motion-command-manager", daemon=True)
        self._thread.start()

    def submit(self, source: str, method_name: str, *args: Any, **kwargs: Any) -> Any:
        if self._is_safety_stop(method_name, args, kwargs):
            return self._execute_safety_stop(source, method_name, args, kwargs)

        if current_thread() is self._thread:
            return getattr(self._controller, method_name)(*args, **kwargs)

        with self._state:
            self._sequence += 1
            call = _ManagedCall(
                self._sequence,
                self._safety_epoch,
                source,
                method_name,
                args,
                kwargs,
                current_api_command_trace_id(),
            )
        # High-rate velocity control can submit many calls per second. Detailed
        # timing remains available in ApiCommandMonitor without flooding the
        # persistent system journal.
        LOGGER.debug(
            "Motion command accepted sequence=%s epoch=%s source=%s action=%s",
            call.sequence,
            call.safety_epoch,
            source,
            method_name,
        )
        self._queue.put(call)
        call.done.wait()
        if call.error is not None:
            raise call.error
        return call.result

    def close(self) -> None:
        self._queue.put(None)
        if self._thread.is_alive() and current_thread() is not self._thread:
            self._thread.join(timeout=2.0)

    @staticmethod
    def _is_safety_stop(
        method_name: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> bool:
        del kwargs
        if method_name == "stop_motors":
            return True
        if method_name not in {"command_velocities", "set_velocities"} or not args:
            return False
        velocities = args[0]
        if not isinstance(velocities, dict) or not velocities:
            return False
        try:
            return all(abs(float(value)) <= 1e-12 for value in velocities.values())
        except (TypeError, ValueError):
            return False

    def _execute_safety_stop(
        self,
        source: str,
        method_name: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> Any:
        with self._state:
            self._sequence += 1
            sequence = self._sequence
            self._safety_epoch += 1
            safety_epoch = self._safety_epoch
            self._pending_safety_stops += 1
            self._stop_active = True
            self._state.notify_all()

        accepted_at = monotonic()
        started_at: float | None = None
        trace_id = current_api_command_trace_id()
        result: Any = None
        error: BaseException | None = None
        LOGGER.warning(
            "Safety stop accepted sequence=%s epoch=%s source=%s action=%s",
            sequence,
            safety_epoch,
            source,
            method_name,
        )
        try:
            # Cancellation is memory-only and may run immediately, even when
            # the current controller workflow is still inside an atomic call.
            # It lets long calibration/tuning loops release that call so the
            # physical zero command can take the safety-priority hardware slot.
            request_stop = getattr(self._controller, "request_safety_stop", None)
            if callable(request_stop):
                request_stop()
            # This lock is not the normal FIFO queue. It only lets the current
            # atomic controller call finish so no stale write can land after
            # the stop command.
            with self._safety_stop_lock:
                with self._execution_lock:
                    started_at = monotonic()
                    result = getattr(self._controller, method_name)(*args, **kwargs)
            LOGGER.warning(
                "Safety stop finished sequence=%s epoch=%s source=%s action=%s "
                "wait_ms=%.1f elapsed_ms=%.1f",
                sequence,
                safety_epoch,
                source,
                method_name,
                (started_at - accepted_at) * 1000.0,
                (monotonic() - started_at) * 1000.0,
            )
            return result
        except BaseException as exc:
            error = exc
            raise
        finally:
            finished_at = monotonic()
            self._record_motion_timing(
                trace_id,
                manager_sequence=sequence,
                manager_action=method_name,
                queue_wait_ms=((started_at or finished_at) - accepted_at) * 1000.0,
                execution_ms=(finished_at - started_at) * 1000.0 if started_at is not None else 0.0,
                ok=error is None,
                safety_priority=True,
            )
            with self._state:
                self._pending_safety_stops -= 1
                self._stop_active = self._pending_safety_stops > 0
                self._state.notify_all()

    def _run(self) -> None:
        while True:
            call = self._queue.get()
            if call is None:
                self._queue.task_done()
                return
            try:
                self._execute_queued(call)
            finally:
                call.done.set()
                self._queue.task_done()

    def _execute_queued(self, call: _ManagedCall) -> None:
        while True:
            with self._state:
                while self._stop_active:
                    self._state.wait()

            with self._execution_lock:
                with self._state:
                    if self._stop_active:
                        continue
                    if call.safety_epoch != self._safety_epoch:
                        call.error = MotionCommandSuperseded(
                            f"Motion command {call.sequence} was superseded by a safety stop."
                        )
                        LOGGER.warning(
                            "Motion command superseded sequence=%s command_epoch=%s "
                            "current_epoch=%s source=%s action=%s",
                            call.sequence,
                            call.safety_epoch,
                            self._safety_epoch,
                            call.source,
                            call.method_name,
                        )
                        self._record_motion_timing(
                            call.trace_id,
                            manager_sequence=call.sequence,
                            manager_action=call.method_name,
                            queue_wait_ms=(monotonic() - call.enqueued_at) * 1000.0,
                            execution_ms=0.0,
                            ok=False,
                            superseded=True,
                        )
                        return

                started_at = monotonic()
                LOGGER.debug(
                    "Motion command started sequence=%s epoch=%s source=%s action=%s "
                    "queue_wait_ms=%.1f",
                    call.sequence,
                    call.safety_epoch,
                    call.source,
                    call.method_name,
                    (started_at - call.enqueued_at) * 1000.0,
                )
                try:
                    call.result = getattr(self._controller, call.method_name)(
                        *call.args,
                        **call.kwargs,
                    )
                except Exception as exc:
                    call.error = exc
                finally:
                    finished_at = monotonic()
                    log = LOGGER.warning if call.error is not None else LOGGER.debug
                    log(
                        "Motion command finished sequence=%s epoch=%s source=%s action=%s "
                        "elapsed_ms=%.1f ok=%s%s",
                        call.sequence,
                        call.safety_epoch,
                        call.source,
                        call.method_name,
                        (finished_at - started_at) * 1000.0,
                        call.error is None,
                        f" error={call.error}" if call.error is not None else "",
                    )
                    self._record_motion_timing(
                        call.trace_id,
                        manager_sequence=call.sequence,
                        manager_action=call.method_name,
                        queue_wait_ms=(started_at - call.enqueued_at) * 1000.0,
                        execution_ms=(finished_at - started_at) * 1000.0,
                        ok=call.error is None,
                    )
                return

    def _record_motion_timing(self, trace_id: int | None, **values: Any) -> None:
        recorder = getattr(self._command_monitor, "record_motion_timing", None)
        if not callable(recorder):
            return
        try:
            recorder(trace_id, **values)
        except Exception:
            LOGGER.exception("Could not record API command timing trace_id=%s", trace_id)


class ManagedMotionController:
    """Transport-facing facade for the central command manager."""

    MANAGED_METHODS = frozenset({
        "enable_motors",
        "disable_motors",
        "set_axis_enabled",
        "stop_motors",
        "goto_positions",
        "set_velocities",
        "command_velocities",
        "start_motor_calibration",
        "stop_motor_calibration",
        "start_sine_velocity_test",
        "stop_sine_velocity_test",
        "update_tuning",
        "save_configuration",
        "flash_motion_limits",
        "reload_configuration",
        "auto_tune_axis",
    })

    def __init__(self, controller: Any, manager: MotionCommandManager, source: str) -> None:
        self._controller = controller
        self._manager = manager
        self._source = source

    def __getattr__(self, name: str) -> Any:
        attribute = getattr(self._controller, name)
        if name not in self.MANAGED_METHODS or not callable(attribute):
            return attribute

        def managed_call(*args: Any, **kwargs: Any) -> Any:
            return self._manager.submit(self._source, name, *args, **kwargs)

        return managed_call
