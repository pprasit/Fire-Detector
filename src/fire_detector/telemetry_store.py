"""Low-overhead SQLite storage for rolling mount telemetry reports."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import math
from pathlib import Path
import sqlite3
from statistics import median
import subprocess
from threading import Event, Lock, Thread
from time import monotonic, sleep, time
from typing import Any, Callable

NETWORK_SPEED_TEST_INTERVAL_SEC = 300.0


class TelemetryStore:
    """Sample a monitor at 10 Hz and persist samples in batched transactions."""

    def __init__(
        self,
        database_path: Path,
        snapshot_provider: Callable[[], dict[str, Any]],
        *,
        sample_interval_sec: float = 0.1,
        flush_interval_sec: float = 5.0,
        retention_hours: int = 168,
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
        self._network_thread: Thread | None = None
        self._network_live_thread: Thread | None = None
        self._network_live_lock = Lock()
        self._network_live: dict[str, Any] = {
            "interface": None, "download_mbps": None, "upload_mbps": None,
            "sample_window_ms": None, "captured_ms": None,
        }
        self._network_usage_history: deque[tuple[int, str, float, float]] = deque()
        self._network_capacity_history: deque[tuple[int, str, float, float]] = deque()
        self._next_cleanup_at = 0.0

    def start(self) -> None:
        if self._thread is not None:
            return
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()
        self._load_network_capacity_history()
        self._thread = Thread(target=self._run, name="telemetry-sqlite-writer", daemon=True)
        self._thread.start()
        self._network_thread = Thread(target=self._network_run, name="network-metrics-writer", daemon=True)
        self._network_thread.start()
        self._network_live_thread = Thread(
            target=self._network_live_run, name="network-throughput-sampler", daemon=True,
        )
        self._network_live_thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self._flush_interval + 2.0)
        if self._network_thread is not None:
            self._network_thread.join(timeout=2.0)
        if self._network_live_thread is not None:
            self._network_live_thread.join(timeout=2.0)
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

    def network_report(self, hours: int = 168) -> dict[str, Any]:
        hours = min(168, max(1, int(hours)))
        now_ms = int(time() * 1000)
        start_ms = now_ms - hours * 3600 * 1000
        with self._connect(read_only=True) as connection:
            rows = connection.execute("""
                SELECT captured_ms, latency_ms, download_mbps, upload_mbps, online, interface
                FROM network_metrics WHERE captured_ms >= ? ORDER BY captured_ms
            """, (start_ms,)).fetchall()
            average = connection.execute("""
                SELECT AVG(download_mbps), AVG(upload_mbps)
                FROM network_metrics
                WHERE captured_ms >= ? AND download_mbps IS NOT NULL
            """, (start_ms,)).fetchone()
        points = [{"time_ms": r[0], "latency_ms": r[1], "download_mbps": r[2],
                   "upload_mbps": r[3], "online": bool(r[4]), "interface": r[5]} for r in rows]
        latest_speed = next((p for p in reversed(points) if p["download_mbps"] is not None), None)
        return {"from_ms": start_ms, "to_ms": now_ms, "hours": hours,
                "points": points, "latest": latest_speed,
                "average": {"download_mbps": average[0] if average else None,
                            "upload_mbps": average[1] if average else None}}

    def network_live(self) -> dict[str, Any]:
        """Return passive interface throughput sampled over the last second."""
        with self._network_live_lock:
            return dict(self._network_live)

    def _load_network_capacity_history(self) -> None:
        cutoff_ms = int((time() - 900.0) * 1000)
        try:
            with self._connect(read_only=True) as connection:
                rows = connection.execute("""
                    SELECT captured_ms, interface, download_mbps, upload_mbps
                    FROM network_metrics
                    WHERE captured_ms >= ? AND interface IS NOT NULL
                      AND download_mbps IS NOT NULL AND upload_mbps IS NOT NULL
                    ORDER BY captured_ms
                """, (cutoff_ms,)).fetchall()
            with self._network_live_lock:
                self._network_capacity_history.extend(
                    (int(row[0]), str(row[1]), float(row[2]), float(row[3])) for row in rows
                )
        except (sqlite3.Error, TypeError, ValueError):
            return

    def _network_live_run(self) -> None:
        previous: tuple[str, int, int, float] | None = None
        while not self._stop.is_set():
            sampled_at = monotonic()
            interface = self._default_network_interface()
            counters = self._network_counters(interface) if interface else None
            live: dict[str, Any] = {
                "interface": interface, "download_mbps": None, "upload_mbps": None,
                "sample_window_ms": None, "captured_ms": int(time() * 1000),
            }
            if counters is not None and previous is not None and previous[0] == interface:
                elapsed = sampled_at - previous[3]
                if elapsed > 0:
                    live.update({
                        "download_mbps": max(0, counters[0] - previous[1]) * 8 / elapsed / 1_000_000,
                        "upload_mbps": max(0, counters[1] - previous[2]) * 8 / elapsed / 1_000_000,
                        "sample_window_ms": round(elapsed * 1000),
                    })
            if counters is not None and interface is not None:
                previous = (interface, counters[0], counters[1], sampled_at)
            else:
                previous = None
            with self._network_live_lock:
                captured_ms = int(live["captured_ms"])
                cutoff_ms = captured_ms - 900_000
                if (interface is not None and live["download_mbps"] is not None
                        and live["upload_mbps"] is not None):
                    self._network_usage_history.append((
                        captured_ms, interface, float(live["download_mbps"]),
                        float(live["upload_mbps"]),
                    ))
                while self._network_usage_history and self._network_usage_history[0][0] < cutoff_ms:
                    self._network_usage_history.popleft()
                while self._network_capacity_history and self._network_capacity_history[0][0] < cutoff_ms:
                    self._network_capacity_history.popleft()
                capacity_samples = [
                    row for row in self._network_capacity_history if row[1] == interface
                ]
                usage_samples = [row for row in self._network_usage_history if row[1] == interface]
                tested_down = median(row[2] for row in capacity_samples) if capacity_samples else None
                tested_up = median(row[3] for row in capacity_samples) if capacity_samples else None
                observed_down = max((row[2] for row in usage_samples), default=None)
                observed_up = max((row[3] for row in usage_samples), default=None)
                live.update({
                    "estimated_download_mbps": max(
                        value for value in (tested_down, observed_down) if value is not None
                    ) if tested_down is not None or observed_down is not None else None,
                    "estimated_upload_mbps": max(
                        value for value in (tested_up, observed_up) if value is not None
                    ) if tested_up is not None or observed_up is not None else None,
                    "capacity_sample_count": len(capacity_samples),
                    "history_window_sec": 900,
                })
                self._network_live = live
            self._stop.wait(1.0)

    @staticmethod
    def _default_network_interface() -> str | None:
        """Find the lowest-metric active IPv4 default route without spawning a process."""
        try:
            candidates: list[tuple[int, str]] = []
            for line in Path("/proc/net/route").read_text(encoding="ascii").splitlines()[1:]:
                fields = line.split()
                if len(fields) >= 8 and fields[1] == "00000000" and int(fields[3], 16) & 1:
                    candidates.append((int(fields[6]), fields[0]))
            return min(candidates)[1] if candidates else None
        except (OSError, ValueError, IndexError):
            return None

    @staticmethod
    def _network_counters(interface: str) -> tuple[int, int] | None:
        if not interface or "/" in interface or interface in {".", ".."}:
            return None
        base = Path("/sys/class/net") / interface / "statistics"
        try:
            return (int((base / "rx_bytes").read_text()), int((base / "tx_bytes").read_text()))
        except (OSError, ValueError):
            return None

    def _network_run(self) -> None:
        next_probe = monotonic()
        next_speed = next_probe
        speed_interface: str | None = None
        while not self._stop.is_set():
            now = monotonic()
            if now >= next_probe:
                interface = self._default_network_interface()
                run_speed = now >= next_speed or interface != speed_interface
                latency, download, upload = self._measure_network(run_speed)
                try:
                    with self._connect() as connection:
                        connection.execute(
                            """INSERT OR REPLACE INTO network_metrics
                               (captured_ms, latency_ms, download_mbps, upload_mbps, online, interface)
                               VALUES (?, ?, ?, ?, ?, ?)""",
                            (int(time() * 1000), latency, download, upload,
                             int(latency is not None), interface),
                        )
                except sqlite3.Error:
                    pass
                next_probe = now + 60.0
                if run_speed:
                    next_speed = now + NETWORK_SPEED_TEST_INTERVAL_SEC
                    speed_interface = interface
                    if (interface is not None and download is not None and upload is not None):
                        with self._network_live_lock:
                            self._network_capacity_history.append(
                                (int(time() * 1000), interface, float(download), float(upload))
                            )
            self._stop.wait(max(0.2, next_probe - monotonic()))

    @staticmethod
    def _measure_network(run_speed: bool) -> tuple[float | None, float | None, float | None]:
        def curl(args: list[str], payload: bytes | None = None) -> tuple[float, float] | None:
            for family in ("-6", "-4"):
                try:
                    result = subprocess.run(
                        ["curl", family, "-sS", "-o", "/dev/null", "--connect-timeout", "5",
                         "--max-time", "30", "-w", "%{time_appconnect} %{speed_download} %{speed_upload}", *args],
                        input=payload, capture_output=True, timeout=35, check=True,
                    )
                    tls, down, up = (float(value) for value in result.stdout.decode().split())
                    return tls * 1000.0, (up if payload is not None else down) * 8.0 / 1_000_000.0
                except (OSError, ValueError, subprocess.SubprocessError):
                    continue
            return None
        probe = curl(["https://speed.cloudflare.com/__down?bytes=1"])
        if probe is None:
            return None, None, None
        latency = probe[0]
        if not run_speed:
            return latency, None, None
        down = curl(["https://speed.cloudflare.com/__down?bytes=5000000"])
        upload = curl(["-X", "POST", "--data-binary", "@-", "https://speed.cloudflare.com/__up"], b"0" * 1000000)
        return latency, down[1] if down else None, upload[1] if upload else None

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
            connection.execute("""
                CREATE TABLE IF NOT EXISTS network_metrics (
                    captured_ms INTEGER PRIMARY KEY, latency_ms REAL,
                    download_mbps REAL, upload_mbps REAL, online INTEGER NOT NULL,
                    interface TEXT
                ) WITHOUT ROWID
            """)
            columns = {row[1] for row in connection.execute("PRAGMA table_info(network_metrics)")}
            if "interface" not in columns:
                connection.execute("ALTER TABLE network_metrics ADD COLUMN interface TEXT")

    def _connect(self, *, read_only: bool = False) -> sqlite3.Connection:
        if read_only:
            return sqlite3.connect(f"file:{self.database_path}?mode=ro", uri=True, timeout=5.0)
        return sqlite3.connect(self.database_path, timeout=5.0)
