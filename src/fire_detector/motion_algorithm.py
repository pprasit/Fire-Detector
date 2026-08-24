"""Pure motion-control calculations, independent of API and transport tasks."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PositionStepInput:
    error_deg: float
    actual_velocity_deg_per_sec: float
    previous_command_deg_per_sec: float
    max_speed_deg_per_sec: float
    gain_per_sec: float
    acceleration_deg_per_sec2: float | None
    interval_sec: float
    position_tolerance_deg: float
    settle_velocity_deg_per_sec: float


@dataclass(frozen=True)
class PositionStepOutput:
    command_velocity_deg_per_sec: float
    settled: bool


class PositionMotionAlgorithm:
    """Generate one deterministic velocity command for a position move."""

    def step(self, control: PositionStepInput) -> PositionStepOutput:
        settled = (
            abs(control.error_deg) <= control.position_tolerance_deg
            and abs(control.actual_velocity_deg_per_sec)
            <= control.settle_velocity_deg_per_sec
        )
        if settled:
            return PositionStepOutput(command_velocity_deg_per_sec=0.0, settled=True)

        max_speed = max(0.0, abs(control.max_speed_deg_per_sec))
        requested = max(
            -max_speed,
            min(max_speed, control.gain_per_sec * control.error_deg),
        )
        acceleration = control.acceleration_deg_per_sec2
        if acceleration is not None and acceleration > 0.0:
            max_change = acceleration * max(0.0, control.interval_sec)
            requested = max(
                control.previous_command_deg_per_sec - max_change,
                min(control.previous_command_deg_per_sec + max_change, requested),
            )
        return PositionStepOutput(
            command_velocity_deg_per_sec=requested,
            settled=False,
        )
