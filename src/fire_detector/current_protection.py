"""Deterministic motor-current envelope independent of transport and motion code."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CurrentEnvelopeConfig:
    continuous_current_amp: float = 20.0
    peak_current_amp: float = 40.0
    hard_current_amp: float = 48.0
    peak_duration_sec: float = 2.0
    derating_duration_sec: float = 0.75
    recovery_current_amp: float = 16.0
    recovery_duration_sec: float = 30.0
    torque_constant_nm_per_amp: float = 0.29

    @property
    def continuous_torque_nm(self) -> float:
        return self.continuous_current_amp * self.torque_constant_nm_per_amp

    @property
    def peak_torque_nm(self) -> float:
        return self.peak_current_amp * self.torque_constant_nm_per_amp


@dataclass(frozen=True)
class CurrentEnvelopeOutput:
    allowed_current_amp: float
    torque_limit_nm: float
    phase: str
    peak_used_sec: float
    peak_remaining_sec: float
    recovery_sec: float


class CurrentEnvelope:
    """Allow a short peak, then smoothly return torque to continuous duty.

    This class never changes velocity and never requests a motor stop.  A new
    process starts conservatively at the continuous limit until it has observed
    a complete low-current recovery interval, because pre-restart thermal
    history is unknown.
    """

    def __init__(
        self,
        config: CurrentEnvelopeConfig | None = None,
        *,
        require_startup_recovery: bool = True,
    ) -> None:
        self.config = config or CurrentEnvelopeConfig()
        self._peak_used_sec = self.config.peak_duration_sec if require_startup_recovery else 0.0
        self._derating_elapsed_sec = (
            self.config.derating_duration_sec if require_startup_recovery else 0.0
        )
        self._recovery_sec = 0.0
        self._exhausted = require_startup_recovery

    def step(self, measured_current_amp: float, dt_sec: float) -> CurrentEnvelopeOutput:
        config = self.config
        dt = max(0.0, min(float(dt_sec), 1.0))
        current = abs(float(measured_current_amp))
        newly_exhausted = False

        if current <= config.recovery_current_amp and (
            self._peak_used_sec > 0.0 or self._exhausted
        ):
            self._recovery_sec += dt
            if self._recovery_sec >= config.recovery_duration_sec:
                self._peak_used_sec = 0.0
                self._derating_elapsed_sec = 0.0
                self._recovery_sec = 0.0
                self._exhausted = False
        else:
            self._recovery_sec = 0.0

        if not self._exhausted and current > config.continuous_current_amp:
            self._peak_used_sec = min(
                config.peak_duration_sec,
                self._peak_used_sec + dt,
            )
            if self._peak_used_sec >= config.peak_duration_sec:
                self._exhausted = True
                self._derating_elapsed_sec = 0.0
                newly_exhausted = True

        if self._exhausted:
            if not newly_exhausted:
                self._derating_elapsed_sec = min(
                    config.derating_duration_sec,
                    self._derating_elapsed_sec + dt,
                )
            ratio = (
                1.0
                if config.derating_duration_sec <= 0.0
                else self._derating_elapsed_sec / config.derating_duration_sec
            )
            allowed_current = config.peak_current_amp + (
                config.continuous_current_amp - config.peak_current_amp
            ) * ratio
            phase = "continuous" if ratio >= 1.0 else "derating"
            if self._recovery_sec > 0.0:
                phase = "recovering"
        else:
            allowed_current = config.peak_current_amp
            phase = "peak" if current > config.continuous_current_amp else "ready"

        return CurrentEnvelopeOutput(
            allowed_current_amp=allowed_current,
            torque_limit_nm=allowed_current * config.torque_constant_nm_per_amp,
            phase=phase,
            peak_used_sec=self._peak_used_sec,
            peak_remaining_sec=max(0.0, config.peak_duration_sec - self._peak_used_sec),
            recovery_sec=self._recovery_sec,
        )
