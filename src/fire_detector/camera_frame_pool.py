"""Central latest-frame pool shared by every camera consumer.

Only an ingest producer writes camera frames.  Dashboard views, metadata
panels, preview profiles, recorders, and outbound publishers must consume the
latest retained frame from this pool instead of opening their own upstream
camera connection.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from threading import Condition, Lock
from time import monotonic
from typing import Any


CAMERA_POOL_PROFILES: dict[str, dict[str, Any]] = {
    "full": {
        "description": "Original encoded frame retained by the ingest pipeline",
        "latest_only": True,
    },
    "pointing": {
        "description": "Low-bandwidth latest-frame preview for Pointing Model",
        "latest_only": True,
        "max_fps": 10,
        "jpeg_quality": 65,
        "dimensions": {
            "thermal": (400, 320),
            "visible": (480, 270),
        },
    },
}


class CameraFramePool:
    """Thread-safe, queue-free store for the newest frame of each camera."""

    sources = ("simulation", "live")
    cameras = ("thermal", "visible")

    def __init__(self) -> None:
        self.lock = Lock()
        self.updated = Condition(self.lock)
        self.frames: dict[tuple[str, str], dict[str, Any]] = {}
        self.images: dict[tuple[str, str], dict[str, Any]] = {}
        self.profile_cache: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.profile_cache_lock = Lock()
        self.sequence = 0
        self.producers: dict[str, dict[str, Any]] = {
            source: {
                "connections": 0,
                "last_frame_at": None,
                "last_frame_monotonic": None,
            }
            for source in self.sources
        }

    def source_connected_locked(self, source: str, *, now: float | None = None) -> bool:
        """Return source health while the caller holds ``lock``."""
        state = self.producers[source]
        last_frame = state.get("last_frame_monotonic")
        current = monotonic() if now is None else now
        return state["connections"] > 0 or (
            isinstance(last_frame, (int, float)) and current - last_frame < 2.0
        )

    def store_locked(
        self,
        source: str,
        camera: str,
        payload: bytes,
        mime_type: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        """Replace a camera's retained frame while the caller holds ``updated``.

        There is deliberately no FIFO: superseded frames are discarded at
        ingest, preventing a slow consumer from accumulating seconds of delay.
        """
        self.sequence += 1
        sequence = self.sequence
        clean_metadata = {**metadata, "simulated": source == "simulation"}
        message = {
            "type": "frame",
            "camera": camera,
            "image": {
                "mime_type": mime_type,
                "data": base64.b64encode(payload).decode("ascii"),
            },
            "metadata": clean_metadata,
            "sequence": sequence,
        }
        self.frames[(source, camera)] = message
        received_monotonic = monotonic()
        self.images[(source, camera)] = {
            "data": payload,
            "mime_type": mime_type,
            "metadata": clean_metadata,
            "sequence": sequence,
            "received_monotonic": received_monotonic,
        }
        now = datetime.now(timezone.utc).isoformat()
        self.producers[source].update(
            last_frame_at=now,
            last_frame_monotonic=received_monotonic,
        )
        self.updated.notify_all()
        return message

    def latest(self, source: str, camera: str) -> dict[str, Any] | None:
        """Copy the newest original frame without exposing mutable pool state."""
        with self.lock:
            stored = self.images.get((source, camera))
            return dict(stored) if stored is not None else None

    def profile_spec(self, profile: str, camera: str) -> dict[str, Any]:
        spec = CAMERA_POOL_PROFILES[profile]
        result = {key: value for key, value in spec.items() if key != "dimensions"}
        dimensions = spec.get("dimensions", {})
        if camera in dimensions:
            result["dimensions"] = tuple(dimensions[camera])
        return result

    def status_locked(self) -> dict[str, Any]:
        """Describe the single-ingest pool contract and current freshness."""
        now = monotonic()
        profiles = {
            name: {
                **{key: value for key, value in spec.items() if key != "dimensions"},
                **(
                    {"dimensions": {camera: list(size) for camera, size in spec["dimensions"].items()}}
                    if "dimensions" in spec else {}
                ),
            }
            for name, spec in CAMERA_POOL_PROFILES.items()
        }
        return {
            "architecture": {
                "mode": "single-ingest-central-latest-frame-pool",
                "upstream_owner": "camera ingest producer only",
                "consumer_rule": "consume station pool endpoints; never connect to camera upstream",
                "retention": "latest frame only",
                "queue_depth_per_camera": 1,
            },
            "profiles": profiles,
            "sources": {
                source: {
                    "connected": self.source_connected_locked(source, now=now),
                    "producer_connections": state["connections"],
                    "last_frame_at": state["last_frame_at"],
                    "streams": sorted(
                        camera for frame_source, camera in self.frames if frame_source == source
                    ),
                    "cameras": {
                        camera: self._camera_status_locked(source, camera, now)
                        for camera in self.cameras
                    },
                }
                for source, state in self.producers.items()
            },
        }

    def _camera_status_locked(self, source: str, camera: str, now: float) -> dict[str, Any]:
        frame = self.images.get((source, camera))
        received = frame.get("received_monotonic") if frame else None
        age_ms = (
            max(0.0, (now - float(received)) * 1000.0)
            if isinstance(received, (int, float)) else None
        )
        return {
            "connected": age_ms is not None and age_ms < 2000.0,
            "sequence": int(frame.get("sequence", 0)) if frame else 0,
            "age_ms": round(age_ms, 1) if age_ms is not None else None,
            "retained_frames": 1 if frame else 0,
        }
