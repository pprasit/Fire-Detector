"""Ownership and dead-man protection for momentary Web UI jog controls."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import math
from threading import Condition, Thread, current_thread
from time import monotonic
from typing import Callable, Mapping


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class _JogLease:
    owner: str
    velocity: float
    deadline: float


class JogCommandRegistry:
    """Arbitrate browser jog ownership and stop an axis if heartbeats cease.

    The first non-zero command is forwarded to the central command manager.
    Repeated commands from the same page renew the dead-man lease without
    writing the same setpoint to hardware again.  Every request carries a
    monotonically increasing page sequence so a late start request cannot
    overtake a newer release request.
    """

    def __init__(
        self,
        on_expire: Callable[[dict[str, float]], object] | None = None,
        *,
        lease_timeout_sec: float = 0.6,
    ) -> None:
        if lease_timeout_sec <= 0:
            raise ValueError("lease_timeout_sec must be greater than zero.")
        self._condition = Condition()
        self._leases: dict[str, _JogLease] = {}
        self._last_sequences: dict[tuple[str, str], int] = {}
        self._on_expire = on_expire
        self._lease_timeout_sec = float(lease_timeout_sec)
        self._closed = False
        self._thread: Thread | None = None
        if on_expire is not None:
            self._thread = Thread(target=self._watchdog_loop, name="jog-deadman", daemon=True)
            self._thread.start()

    def arbitrate(
        self,
        client_id: str,
        velocities: Mapping[str, float],
        command_sequence: int,
    ) -> tuple[dict[str, float], dict[str, str]]:
        client_id = client_id.strip()
        if not client_id:
            raise ValueError("X-Motion-Client-ID is required for jog commands; reload the dashboard.")
        if isinstance(command_sequence, bool) or command_sequence <= 0:
            raise ValueError("X-Motion-Command-Sequence must be a positive integer; reload the dashboard.")

        accepted: dict[str, float] = {}
        ignored: dict[str, str] = {}
        now = monotonic()
        with self._condition:
            if self._closed:
                raise RuntimeError("Jog command registry is closed.")
            for label, velocity in velocities.items():
                value = float(velocity)
                sequence_key = (client_id, label)
                previous_sequence = self._last_sequences.get(sequence_key, 0)
                if command_sequence <= previous_sequence:
                    ignored[label] = "newer command sequence already received"
                    continue
                self._last_sequences[sequence_key] = command_sequence

                lease = self._leases.get(label)
                if not math.isclose(value, 0.0, abs_tol=1e-12):
                    if lease is not None and lease.owner != client_id:
                        # A held jog is exclusive until its owner releases it
                        # or its dead-man lease expires.  Two open pages must
                        # never alternate opposite setpoints every heartbeat.
                        ignored[label] = lease.owner
                        continue
                    # An identical request is a heartbeat only.  It renews the
                    # lease but does not add another hardware command.
                    unchanged = (
                        lease is not None
                        and math.isclose(lease.velocity, value, rel_tol=0.0, abs_tol=1e-12)
                    )
                    self._leases[label] = _JogLease(
                        owner=client_id,
                        velocity=value,
                        deadline=now + self._lease_timeout_sec,
                    )
                    if not unchanged:
                        accepted[label] = value
                elif lease is None or lease.owner == client_id:
                    self._leases.pop(label, None)
                    accepted[label] = 0.0
                else:
                    ignored[label] = lease.owner
            self._condition.notify_all()
        return accepted, ignored

    def supersede(self, labels: tuple[str, ...] | None = None) -> None:
        with self._condition:
            if labels is None:
                self._leases.clear()
            else:
                for label in labels:
                    self._leases.pop(label, None)
            # Sequence history deliberately remains: a delayed request sent
            # before Stop/Disable must not be able to revive motion afterward.
            self._condition.notify_all()

    def snapshot(self) -> dict[str, str]:
        with self._condition:
            return {label: lease.owner for label, lease in self._leases.items()}

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._leases.clear()
            self._condition.notify_all()
        thread = self._thread
        if thread is not None and thread.is_alive() and current_thread() is not thread:
            thread.join(timeout=1.0)

    def _watchdog_loop(self) -> None:
        while True:
            with self._condition:
                if self._closed:
                    return
                if not self._leases:
                    self._condition.wait()
                    continue
                now = monotonic()
                nearest_deadline = min(lease.deadline for lease in self._leases.values())
                if nearest_deadline > now:
                    self._condition.wait(timeout=nearest_deadline - now)
                    continue

                expired = {
                    label: 0.0
                    for label, lease in self._leases.items()
                    if lease.deadline <= now
                }
                for label in expired:
                    self._leases.pop(label, None)
                if not expired:
                    continue

                # Keep arbitration locked until the zero command completes.
                # Therefore a heartbeat that races the deadline is ordered
                # strictly before or after the dead-man stop, never across it.
                LOGGER.warning("Jog dead-man expired; stopping axes=%s", sorted(expired))
                try:
                    assert self._on_expire is not None
                    self._on_expire(expired)
                except Exception:
                    LOGGER.exception("Jog dead-man could not stop axes=%s", sorted(expired))
