"""Low-overhead SQLite storage for rolling mount telemetry reports."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import math
from pathlib import Path
import sqlite3
from threading import Event, Lock, Thread
from time import monotonic, sleep, time
from typing import Any, Callable


class TelemetryStore:
    """Sample a monitor at 10 Hz and persist samples in batched transactions."""

    def __init__(
        self,
        database_path: Path,
        snapshot_provider: Callable[[], dict[str, Any]],
        *,
        sample_interval_sec: float = 0.1,
        flush_interval_sec: float = 5.0,
        retention_hours: int = 48,
    ) -> None:
        self.database_path = database_path
        self._snapshot_provider = snapshot_provider
        self._sample_interval = max(0.1, sample_interval_sec)
        self._flush_interval = max(1.0, flush_interval_sec)
        self._retention_sec = max(24, retention_hours) * 3600
        self._pending: deque[tuple[Any, ...]] = deque()
        self._pending_lock = Lock()
        self._stop = Event()
        self._thread: Thread | None = None
        self._next_cleanup_at = 0.0

    def start(self) -> None:
        if self._thread is not None:
            return
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()
        self._thread = Thread(target=self._run, name="telemetry-sqlite-writer", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self._flush_interval + 2.0)
        self._flush()

    def report(self, hours: int = 24, buckets: int = 288) -> dict[str, Any]:
        hours = min(168, max(1, int(hours)))
        buckets = min(720, max(24, int(buckets)))
        now_ms = int(time() * 1000)
        start_ms = now_ms - hours * 3600 * 1000
        bucket_ms = max(1, (now_ms - start_ms) // buckets)
        result: dict[str, Any] = {
            "from_ms": start_ms, "to_ms": now_ms, "hours": hours,
            "sample_interval_ms": round(self._sample_interval * 1000), "axes": {},
        }
        with self._connect(read_only=True) as connection:
            for axis, prefix in (("Azimuth", "az"), ("Altitude", "alt")):
                rows = connection.execute(f"""
                    SELECT ((captured_ms - ?) / ?) AS bucket,
                           AVG(ABS({prefix}_current)), AVG(ABS({prefix}_velocity)),
                           MAX(ABS({prefix}_current))
                    FROM telemetry
                    WHERE captured_ms >= ? AND {prefix}_current IS NOT NULL
                    GROUP BY bucket ORDER BY bucket
                """, (start_ms, bucket_ms, start_ms)).fetchall()
                peak = connection.execute(f"""
                    SELECT ABS({prefix}_current), {prefix}_velocity, {prefix}_position, captured_ms
                    FROM telemetry
                    WHERE captured_ms >= ? AND {prefix}_current IS NOT NULL
                    ORDER BY ABS({prefix}_current) DESC LIMIT 1
                """, (start_ms,)).fetchone()
                summary = connection.execute(f"""
                    SELECT AVG(ABS({prefix}_current)), AVG(ABS({prefix}_velocity)), COUNT(*)
                    FROM telemetry WHERE captured_ms >= ? AND {prefix}_current IS NOT NULL
                """, (start_ms,)).fetchone()
                result["axes"][axis] = {
                    "points": [{"time_ms": start_ms + int(row[0]) * bucket_ms,
                                "current_a": row[1], "velocity_deg_per_sec": row[2],
                                "peak_current_a": row[3]} for row in rows],
                    "average_current_a": summary[0] if summary else None,
                    "average_velocity_deg_per_sec": summary[1] if summary else None,
                    "sample_count": summary[2] if summary else 0,
                    "peak": ({"current_a": peak[0], "velocity_deg_per_sec": peak[1],
                              "position_deg": peak[2], "time_ms": peak[3]} if peak else None),
                }
        return result

    def _run(self) -> None:
        next_sample = monotonic()
        next_flush = next_sample + self._flush_interval
        while not self._stop.is_set():
            now = monotonic()
            if now >= next_sample:
                self._capture()
                next_sample += self._sample_interval
                if now - next_sample > self._sample_interval:
                    next_sample = now + self._sample_interval
            if now >= next_flush:
                self._flush()
                next_flush = now + self._flush_interval
            self._stop.wait(max(0.005, min(next_sample, next_flush) - monotonic()))

    def _capture(self) -> None:
        try:
            snapshot = self._snapshot_provider()
            axes = {axis.get("label"): axis for axis in snapshot.get("axes", []) if isinstance(axis, dict)}
            azimuth, altitude = axes.get("Azimuth", {}), axes.get("Altitude", {})
            row = (int(time() * 1000), *self._axis_values(azimuth), *self._axis_values(altitude))
            with self._pending_lock:
                self._pending.append(row)
        except Exception:
            return

    @staticmethod
    def _axis_values(axis: dict[str, Any]) -> tuple[float | None, float | None, float | None]:
        def finite(key: str) -> float | None:
            try:
                value = float(axis.get(key))
                return value if math.isfinite(value) else None
            except (TypeError, ValueError):
                return None
        return finite("position_deg"), finite("velocity_deg_per_sec"), finite("current")

    def _flush(self) -> None:
        with self._pending_lock:
            rows = list(self._pending)
            self._pending.clear()
        if not rows:
            return
        try:
            with self._connect() as connection:
                connection.executemany(
                    "INSERT OR REPLACE INTO telemetry VALUES (?, ?, ?, ?, ?, ?, ?)", rows,
                )
                now = monotonic()
                if now >= self._next_cleanup_at:
                    cutoff = int(time() * 1000) - self._retention_sec * 1000
                    connection.execute("DELETE FROM telemetry WHERE captured_ms < ?", (cutoff,))
                    self._next_cleanup_at = now + 3600.0
        except sqlite3.Error:
            with self._pending_lock:
                self._pending.extendleft(reversed(rows[-5000:]))

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.execute("PRAGMA temp_store=MEMORY")
            connection.execute("""
                CREATE TABLE IF NOT EXISTS telemetry (
                    captured_ms INTEGER PRIMARY KEY,
                    az_position REAL, az_velocity REAL, az_current REAL,
                    alt_position REAL, alt_velocity REAL, alt_current REAL
                ) WITHOUT ROWID
            """)

    def _connect(self, *, read_only: bool = False) -> sqlite3.Connection:
        if read_only:
            return sqlite3.connect(f"file:{self.database_path}?mode=ro", uri=True, timeout=5.0)
        return sqlite3.connect(self.database_path, timeout=5.0)
