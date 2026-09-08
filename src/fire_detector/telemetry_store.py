"""Low-overhead SQLite storage for rolling mount telemetry reports."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
from statistics import median
import subprocess
from threading import Event, Lock, Thread
from time import monotonic, sleep, time
from typing import Any, Callable

# Production monitoring is passive. An active 5 MB download + 1 MB upload test
# can saturate a degraded 4G link and interfere with RTSP, so capacity tests are
# started explicitly through the dashboard/API only.
NETWORK_SPEED_TEST_INTERVAL_SEC = None
NETWORK_USAGE_HISTORY_SEC = 15 * 60
MANUAL_CAPACITY_MAX_AGE_SEC = 6 * 60 * 60
POWER_SAMPLE_INTERVAL_SEC = 1.0
SYSTEM_HEALTH_SAMPLE_INTERVAL_SEC = 5.0
VCGENCMD_PATH = Path("/usr/bin/vcgencmd")
PMIC_ADC_PATTERN = re.compile(
    r"^\s*(?P<rail>\S+)_(?P<kind>[AV])\s+(?:current|volt)\(\d+\)="
    r"(?P<value>[-+0-9.eE]+)[AV]\s*$"
)


class TelemetryStore:
    """Sample a monitor at 10 Hz and persist samples in batched transactions."""

    def __init__(
        self,
        database_path: Path,
        snapshot_provider: Callable[[], dict[str, Any]],
        *,
        sample_interval_sec: float = 0.1,
        flush_interval_sec: float = 5.0,
        retention_hours: int | None = None,
    ) -> None:
        self.database_path = database_path
        self._snapshot_provider = snapshot_provider
        self._sample_interval = max(0.1, sample_interval_sec)
        self._flush_interval = max(1.0, flush_interval_sec)
        self._retention_sec = (
            max(24, int(retention_hours)) * 3600
            if retention_hours is not None
            else None
        )
        self._pending: deque[tuple[Any, ...]] = deque()
        self._pending_power: deque[tuple[Any, ...]] = deque()
        self._pending_system_health: deque[tuple[Any, ...]] = deque()
        self._pending_network_usage: deque[tuple[Any, ...]] = deque()
        self._pending_lock = Lock()
        self._stop = Event()
        self._thread: Thread | None = None
        self._network_thread: Thread | None = None
        self._network_live_thread: Thread | None = None
        self._network_live_lock = Lock()
        self._capacity_test_lock = Lock()
        self._capacity_test_thread: Thread | None = None
        self._capacity_test_state: dict[str, Any] = {
            "status": "idle", "started_ms": None, "completed_ms": None,
            "interface": None, "latency_ms": None,
            "download_mbps": None, "upload_mbps": None, "error": None,
        }
        self._network_live: dict[str, Any] = {
            "interface": None, "download_mbps": None, "upload_mbps": None,
            "sample_window_ms": None, "captured_ms": None,
        }
        self._network_usage_history: deque[tuple[int, str, float, float]] = deque()
        self._network_capacity_history: deque[tuple[int, str, float, float]] = deque()
        self._next_power_sample_at = 0.0
        self._next_system_health_sample_at = 0.0
        self._previous_cpu_times: tuple[int, int] | None = None
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

    def network_report(self, hours: int = 168, buckets: int = 2016) -> dict[str, Any]:
        hours = min(168, max(1, int(hours)))
        buckets = min(5000, max(24, int(buckets)))
        now_ms = int(time() * 1000)
        start_ms = now_ms - hours * 3600 * 1000
        bucket_ms = max(1000, (now_ms - start_ms) // buckets)
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
            usage_rows = connection.execute("""
                SELECT ((captured_ms - ?) / ?) AS bucket,
                       MAX(captured_ms), AVG(download_mbps), AVG(upload_mbps), MAX(interface)
                FROM network_usage_metrics
                WHERE captured_ms >= ?
                GROUP BY bucket ORDER BY bucket
            """, (start_ms, bucket_ms, start_ms)).fetchall()
            usage_average = connection.execute("""
                SELECT AVG(download_mbps), AVG(upload_mbps)
                FROM network_usage_metrics WHERE captured_ms >= ?
            """, (start_ms,)).fetchone()
        capacity_points = [{
            "time_ms": r[0], "latency_ms": r[1], "download_mbps": r[2],
            "upload_mbps": r[3], "online": bool(r[4]), "interface": r[5],
        } for r in rows if r[2] is not None or r[3] is not None]
        usage_points = [{
            "time_ms": row[1],
            "download_mbps": row[2], "upload_mbps": row[3], "interface": row[4],
        } for row in usage_rows]
        free_points: list[dict[str, Any]] = []
        capacity_index = 0
        latest_capacity_by_interface: dict[str, dict[str, Any]] = {}
        for usage in usage_points:
            while (capacity_index < len(capacity_points)
                   and capacity_points[capacity_index]["time_ms"] <= usage["time_ms"]):
                capacity = capacity_points[capacity_index]
                if capacity.get("interface"):
                    latest_capacity_by_interface[str(capacity["interface"])] = capacity
                capacity_index += 1
            latest_capacity = latest_capacity_by_interface.get(str(usage.get("interface")))
            if latest_capacity is None:
                continue
            free_points.append({
                "time_ms": usage["time_ms"],
                "download_mbps": max(
                    0.0,
                    float(latest_capacity.get("download_mbps") or 0.0)
                    - float(usage.get("download_mbps") or 0.0),
                ),
                "upload_mbps": max(
                    0.0,
                    float(latest_capacity.get("upload_mbps") or 0.0)
                    - float(usage.get("upload_mbps") or 0.0),
                ),
                "interface": usage.get("interface"),
            })

        def latest(points: list[dict[str, Any]]) -> dict[str, Any] | None:
            return points[-1] if points else None

        def point_average(points: list[dict[str, Any]]) -> dict[str, float | None]:
            def average_key(key: str) -> float | None:
                values = [float(point[key]) for point in points if point.get(key) is not None]
                return sum(values) / len(values) if values else None
            return {"download_mbps": average_key("download_mbps"),
                    "upload_mbps": average_key("upload_mbps")}

        latest_speed = latest(capacity_points)
        usage_average_payload = {
            "download_mbps": usage_average[0] if usage_average else None,
            "upload_mbps": usage_average[1] if usage_average else None,
        }
        return {"from_ms": start_ms, "to_ms": now_ms, "hours": hours,
                "bucket_ms": bucket_ms,
                "points": capacity_points, "latest": latest_speed,
                "average": {"download_mbps": average[0] if average else None,
                            "upload_mbps": average[1] if average else None},
                "series": {
                    "capacity": {"points": capacity_points, "latest": latest_speed,
                                 "average": {"download_mbps": average[0] if average else None,
                                             "upload_mbps": average[1] if average else None}},
                    "used": {"points": usage_points, "latest": latest(usage_points),
                             "average": usage_average_payload},
                    "free": {"points": free_points, "latest": latest(free_points),
                             "average": point_average(free_points)},
                }}

    def power_report(
        self,
        hours: int = 24,
        buckets: int = 288,
        interval_sec: int = 5,
        max_points: int = 5000,
    ) -> dict[str, Any]:
        """Return five-second device power averages and estimated energy use."""
        hours = min(168, max(1, int(hours)))
        buckets = min(1008, max(24, int(buckets)))
        interval_sec = min(300, max(1, int(interval_sec)))
        max_points = min(10000, max(100, int(max_points), buckets))
        now_ms = int(time() * 1000)
        start_ms = now_ms - hours * 3600 * 1000
        requested_bucket_ms = interval_sec * 1000

        def positive(column: str) -> str:
            return f"CASE WHEN {column} > 0 THEN {column} ELSE 0 END"

        with self._connect(read_only=True) as connection:
            earliest = connection.execute("""
                SELECT MIN(captured_ms) FROM power_metrics
                WHERE captured_ms >= ?
                  AND (az_power_w IS NOT NULL OR alt_power_w IS NOT NULL OR pi_power_w IS NOT NULL)
            """, (start_ms,)).fetchone()
            earliest_ms = earliest[0] if earliest and earliest[0] is not None else now_ms
            aligned_earliest_ms = (int(earliest_ms) // requested_bucket_ms) * requested_bucket_ms
            # Show at least one minute on a new installation, then expand with
            # the collected history until the full requested rolling window is visible.
            visible_start_ms = min(aligned_earliest_ms, now_ms - 60_000)
            plot_start_ms = max(
                start_ms,
                (visible_start_ms // requested_bucket_ms) * requested_bucket_ms,
            )
            visible_span_ms = max(requested_bucket_ms, now_ms - plot_start_ms)
            bucket_multiple = max(
                1,
                math.ceil(visible_span_ms / (requested_bucket_ms * max_points)),
            )
            bucket_ms = requested_bucket_ms * bucket_multiple
            rows = connection.execute(f"""
                SELECT ((captured_ms - ?) / ?) AS bucket,
                       AVG({positive('az_power_w')}),
                       AVG({positive('alt_power_w')}),
                       AVG({positive('pi_power_w')}),
                       AVG({positive('total_power_w')})
                FROM power_metrics
                WHERE captured_ms >= ?
                  AND (az_power_w IS NOT NULL OR alt_power_w IS NOT NULL OR pi_power_w IS NOT NULL)
                GROUP BY bucket ORDER BY bucket
            """, (plot_start_ms, bucket_ms, plot_start_ms)).fetchall()
            latest_time = connection.execute("""
                SELECT MAX(captured_ms) FROM power_metrics
                WHERE captured_ms >= ?
                  AND (az_power_w IS NOT NULL OR alt_power_w IS NOT NULL OR pi_power_w IS NOT NULL)
            """, (start_ms,)).fetchone()
            latest_ms = latest_time[0] if latest_time and latest_time[0] is not None else None
            latest = connection.execute(f"""
                SELECT AVG(az_voltage_v), AVG(az_current_a), AVG({positive('az_power_w')}),
                       AVG(alt_voltage_v), AVG(alt_current_a), AVG({positive('alt_power_w')}),
                       AVG(pi_voltage_v), AVG(pi_current_a), AVG({positive('pi_power_w')}),
                       AVG({positive('total_power_w')})
                FROM power_metrics
                WHERE captured_ms > ? AND captured_ms <= ?
            """, (latest_ms - requested_bucket_ms, latest_ms)).fetchone() if latest_ms is not None else None
            summary = connection.execute(f"""
                SELECT AVG({positive('az_power_w')}),
                       AVG({positive('alt_power_w')}),
                       AVG({positive('pi_power_w')}),
                       AVG({positive('total_power_w')}),
                       MAX({positive('total_power_w')}), COUNT(*),
                       SUM({positive('az_power_w')}) * ? / 3600000.0,
                       SUM({positive('alt_power_w')}) * ? / 3600000.0,
                       SUM({positive('pi_power_w')}) * ? / 3600000.0,
                       SUM({positive('total_power_w')}) * ? / 3600000.0
                FROM power_metrics WHERE captured_ms >= ?
            """, (
                POWER_SAMPLE_INTERVAL_SEC,
                POWER_SAMPLE_INTERVAL_SEC,
                POWER_SAMPLE_INTERVAL_SEC,
                POWER_SAMPLE_INTERVAL_SEC,
                start_ms,
            )).fetchone()

        points = [{
            "time_ms": plot_start_ms + int(row[0]) * bucket_ms,
            "azimuth_power_w": row[1],
            "altitude_power_w": row[2],
            "raspberry_pi_power_w": row[3],
            "total_power_w": row[4],
        } for row in rows]
        latest_payload = ({
            "time_ms": latest_ms,
            "azimuth": {"voltage_v": latest[0], "current_a": latest[1], "power_w": latest[2]},
            "altitude": {"voltage_v": latest[3], "current_a": latest[4], "power_w": latest[5]},
            "raspberry_pi": {
                "voltage_v": latest[6],
                "estimated_current_a": latest[7],
                "power_w": latest[8],
                "source": "PMIC internal rails",
            },
            "total_power_w": latest[9],
        } if latest is not None and latest[9] is not None else None)
        return {
            "from_ms": plot_start_ms,
            "to_ms": now_ms,
            "window_from_ms": start_ms,
            "hours": hours,
            "bucket_ms": bucket_ms,
            "requested_interval_ms": requested_bucket_ms,
            "resolution_reduced": bucket_ms > requested_bucket_ms,
            "sample_interval_ms": round(POWER_SAMPLE_INTERVAL_SEC * 1000),
            "calculation": (
                f"{interval_sec}-second average of positive Vbus x Ibus per drive, "
                "plus Raspberry Pi PMIC internal rail power"
            ),
            "raspberry_pi_measurement": {
                "source": "vcgencmd pmic_read_adc",
                "scope": "PMIC internal rails; excludes direct 5V and some USB/carrier loads",
                "estimated": True,
            },
            "points": points,
            "latest": latest_payload,
            "average": {
                "azimuth_power_w": summary[0] if summary else None,
                "altitude_power_w": summary[1] if summary else None,
                "raspberry_pi_power_w": summary[2] if summary else None,
                "total_power_w": summary[3] if summary else None,
            },
            "peak_total_power_w": summary[4] if summary else None,
            "sample_count": summary[5] if summary else 0,
            "energy": {
                "azimuth_kwh": summary[6] if summary else None,
                "altitude_kwh": summary[7] if summary else None,
                "raspberry_pi_kwh": summary[8] if summary else None,
                "total_kwh": summary[9] if summary else None,
                "azimuth_wh": summary[6] * 1000.0 if summary and summary[6] is not None else None,
                "altitude_wh": summary[7] * 1000.0 if summary and summary[7] is not None else None,
                "raspberry_pi_wh": summary[8] * 1000.0 if summary and summary[8] is not None else None,
                "total_wh": summary[9] * 1000.0 if summary and summary[9] is not None else None,
            },
        }

    def system_health_report(self, hours: int = 24, buckets: int = 288) -> dict[str, Any]:
        """Return rolling controller resource and thermal health history."""
        hours = min(168, max(1, int(hours)))
        buckets = min(1440, max(24, int(buckets)))
        now_ms = int(time() * 1000)
        start_ms = now_ms - hours * 3600 * 1000
        bucket_ms = max(1000, (now_ms - start_ms) // buckets)
        metric_columns = {
            "storage": "storage_percent",
            "cpu": "cpu_percent",
            "memory": "memory_percent",
            "temperature": "cpu_temp_c",
            "load": "load_1m_percent",
            "swap": "swap_percent",
        }
        point_columns = list(metric_columns.values())
        with self._connect(read_only=True) as connection:
            rows = connection.execute(f"""
                SELECT ((captured_ms - ?) / ?) AS bucket,
                       {', '.join(f'AVG({column})' for column in point_columns)}
                FROM system_health_metrics
                WHERE captured_ms >= ?
                GROUP BY bucket ORDER BY bucket
            """, (start_ms, bucket_ms, start_ms)).fetchall()
            latest = connection.execute("""
                SELECT captured_ms,
                       storage_total_bytes, storage_used_bytes, storage_percent,
                       cpu_percent,
                       memory_total_bytes, memory_used_bytes, memory_percent,
                       cpu_temp_c, load_1m_percent,
                       swap_total_bytes, swap_used_bytes, swap_percent, uptime_sec
                FROM system_health_metrics
                WHERE captured_ms >= ?
                ORDER BY captured_ms DESC LIMIT 1
            """, (start_ms,)).fetchone()
            summaries = {
                name: connection.execute(
                    f"SELECT AVG({column}), MAX({column}) FROM system_health_metrics "
                    f"WHERE captured_ms >= ? AND {column} IS NOT NULL",
                    (start_ms,),
                ).fetchone()
                for name, column in metric_columns.items()
            }
            sample_count_row = connection.execute(
                "SELECT COUNT(*) FROM system_health_metrics WHERE captured_ms >= ?",
                (start_ms,),
            ).fetchone()

        points = [
            {
                "time_ms": start_ms + int(row[0]) * bucket_ms,
                **{column: row[index + 1] for index, column in enumerate(point_columns)},
            }
            for row in rows
        ]
        latest_payload = None if latest is None else {
            "time_ms": latest[0],
            "storage_total_bytes": latest[1],
            "storage_used_bytes": latest[2],
            "storage_percent": latest[3],
            "cpu_percent": latest[4],
            "memory_total_bytes": latest[5],
            "memory_used_bytes": latest[6],
            "memory_percent": latest[7],
            "cpu_temp_c": latest[8],
            "load_1m_percent": latest[9],
            "swap_total_bytes": latest[10],
            "swap_used_bytes": latest[11],
            "swap_percent": latest[12],
            "uptime_sec": latest[13],
        }
        return {
            "from_ms": start_ms,
            "to_ms": now_ms,
            "hours": hours,
            "bucket_ms": bucket_ms,
            "sample_interval_ms": round(SYSTEM_HEALTH_SAMPLE_INTERVAL_SEC * 1000),
            "sample_count": sample_count_row[0] if sample_count_row else 0,
            "points": points,
            "latest": latest_payload,
            "metrics": {
                name: {
                    "average": summary[0] if summary else None,
                    "peak": summary[1] if summary else None,
                }
                for name, summary in summaries.items()
            },
        }

    def network_live(self) -> dict[str, Any]:
        """Return passive interface throughput sampled over the last second."""
        with self._network_live_lock:
            return dict(self._network_live)

    def network_capacity_test_status(self) -> dict[str, Any]:
        with self._capacity_test_lock:
            return dict(self._capacity_test_state)

    def start_network_capacity_test(self) -> tuple[bool, dict[str, Any]]:
        """Start one operator-requested active test in a background thread."""
        with self._capacity_test_lock:
            if self._capacity_test_state["status"] == "running":
                return False, dict(self._capacity_test_state)
            self._capacity_test_state = {
                "status": "running", "started_ms": int(time() * 1000),
                "completed_ms": None, "interface": self._default_network_interface(),
                "latency_ms": None, "download_mbps": None,
                "upload_mbps": None, "error": None,
            }
            self._capacity_test_thread = Thread(
                target=self._run_network_capacity_test,
                name="manual-network-capacity-test",
                daemon=True,
            )
            self._capacity_test_thread.start()
            return True, dict(self._capacity_test_state)

    def _run_network_capacity_test(self) -> None:
        interface = self._default_network_interface()
        latency, download, upload = self._measure_network(True)
        captured_ms = int(time() * 1000)
        error = None
        if latency is None or download is None or upload is None:
            error = "capacity probe did not return a complete result"
        try:
            with self._connect() as connection:
                connection.execute(
                    """INSERT OR REPLACE INTO network_metrics
                       (captured_ms, latency_ms, download_mbps, upload_mbps,
                        online, interface, source)
                       VALUES (?, ?, ?, ?, ?, ?, 'manual')""",
                    (captured_ms, latency, download, upload, int(latency is not None), interface),
                )
        except sqlite3.Error as exc:
            error = f"cannot store capacity result: {exc}"
        if interface is not None and download is not None and upload is not None:
            with self._network_live_lock:
                self._network_capacity_history.append(
                    (captured_ms, interface, float(download), float(upload))
                )
        with self._capacity_test_lock:
            self._capacity_test_state = {
                "status": "failed" if error else "complete",
                "started_ms": self._capacity_test_state.get("started_ms"),
                "completed_ms": captured_ms, "interface": interface,
                "latency_ms": latency, "download_mbps": download,
                "upload_mbps": upload, "error": error,
            }

    def _load_network_capacity_history(self) -> None:
        cutoff_ms = int((time() - MANUAL_CAPACITY_MAX_AGE_SEC) * 1000)
        try:
            with self._connect(read_only=True) as connection:
                rows = connection.execute("""
                    SELECT captured_ms, interface, download_mbps, upload_mbps
                    FROM network_metrics
                    WHERE captured_ms >= ? AND interface IS NOT NULL
                      AND source = 'manual'
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
                cutoff_ms = captured_ms - NETWORK_USAGE_HISTORY_SEC * 1000
                capacity_cutoff_ms = captured_ms - MANUAL_CAPACITY_MAX_AGE_SEC * 1000
                if (interface is not None and live["download_mbps"] is not None
                        and live["upload_mbps"] is not None):
                    usage_row = (
                        captured_ms, interface, float(live["download_mbps"]),
                        float(live["upload_mbps"]),
                    )
                    self._network_usage_history.append(usage_row)
                    with self._pending_lock:
                        self._pending_network_usage.append(usage_row)
                while self._network_usage_history and self._network_usage_history[0][0] < cutoff_ms:
                    self._network_usage_history.popleft()
                while (self._network_capacity_history
                       and self._network_capacity_history[0][0] < capacity_cutoff_ms):
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
                    "estimated_download_mbps": (
                        tested_down if tested_down is not None else observed_down
                    ),
                    "estimated_upload_mbps": (
                        tested_up if tested_up is not None else observed_up
                    ),
                    "capacity_sample_count": len(capacity_samples),
                    "capacity_source": "manual" if capacity_samples else "observed_peak",
                    "capacity_age_sec": (
                        max(0.0, (captured_ms - capacity_samples[-1][0]) / 1000.0)
                        if capacity_samples else None
                    ),
                    "capacity_max_age_sec": MANUAL_CAPACITY_MAX_AGE_SEC,
                    "history_window_sec": NETWORK_USAGE_HISTORY_SEC,
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
        while not self._stop.is_set():
            now = monotonic()
            if now >= next_probe:
                interface = self._default_network_interface()
                latency, download, upload = self._measure_network(False)
                try:
                    with self._connect() as connection:
                        connection.execute(
                            """INSERT OR REPLACE INTO network_metrics
                               (captured_ms, latency_ms, download_mbps, upload_mbps,
                                online, interface, source)
                               VALUES (?, ?, ?, ?, ?, ?, 'passive')""",
                            (int(time() * 1000), latency, download, upload,
                             int(latency is not None), interface),
                        )
                except sqlite3.Error:
                    pass
                next_probe = now + 60.0
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
            captured_ms = int(time() * 1000)
            row = (captured_ms, *self._axis_values(azimuth), *self._axis_values(altitude))
            with self._pending_lock:
                self._pending.append(row)
                now = monotonic()
                if now >= self._next_power_sample_at:
                    az_power = self._power_axis_values(azimuth)
                    alt_power = self._power_axis_values(altitude)
                    pi_power = self._raspberry_pi_power_values()
                    if any(values[2] is not None for values in (az_power, alt_power, pi_power)):
                        total_power = sum(
                            max(0.0, value)
                            for value in (az_power[2], alt_power[2], pi_power[2])
                            if value is not None
                        )
                        self._pending_power.append((
                            captured_ms, *az_power, *alt_power, *pi_power, total_power,
                        ))
                    self._next_power_sample_at = now + POWER_SAMPLE_INTERVAL_SEC
                if now >= self._next_system_health_sample_at:
                    self._pending_system_health.append((
                        captured_ms, *self._system_health_values(),
                    ))
                    self._next_system_health_sample_at = (
                        now + SYSTEM_HEALTH_SAMPLE_INTERVAL_SEC
                    )
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

    @staticmethod
    def _power_axis_values(
        axis: dict[str, Any],
    ) -> tuple[float | None, float | None, float | None]:
        def finite(key: str) -> float | None:
            try:
                value = float(axis.get(key))
                return value if math.isfinite(value) else None
            except (TypeError, ValueError):
                return None

        voltage = finite("drive_vbus_voltage")
        current = finite("drive_ibus")
        power = voltage * current if voltage is not None and current is not None else None
        return voltage, current, power

    @classmethod
    def _raspberry_pi_power_values(
        cls,
    ) -> tuple[float | None, float | None, float | None]:
        """Estimate CM5 internal-rail power from the PMIC ADC telemetry."""
        if not VCGENCMD_PATH.exists():
            return None, None, None
        try:
            result = subprocess.run(
                [str(VCGENCMD_PATH), "pmic_read_adc"],
                capture_output=True,
                text=True,
                timeout=1.0,
                check=True,
            )
        except (OSError, subprocess.SubprocessError):
            return None, None, None
        return cls._parse_pmic_adc(result.stdout)

    @staticmethod
    def _parse_pmic_adc(
        output: str,
    ) -> tuple[float | None, float | None, float | None]:
        currents: dict[str, float] = {}
        voltages: dict[str, float] = {}
        for line in output.splitlines():
            match = PMIC_ADC_PATTERN.match(line)
            if match is None:
                continue
            try:
                value = float(match.group("value"))
            except ValueError:
                continue
            if not math.isfinite(value):
                continue
            target = currents if match.group("kind") == "A" else voltages
            target[match.group("rail")] = value
        power_w = sum(
            max(0.0, current) * voltages[rail]
            for rail, current in currents.items()
            if rail in voltages and voltages[rail] > 0
        )
        if power_w <= 0:
            return voltages.get("EXT5V"), None, None
        input_voltage_v = voltages.get("EXT5V")
        equivalent_current_a = (
            power_w / input_voltage_v
            if input_voltage_v is not None and input_voltage_v > 0
            else None
        )
        return input_voltage_v, equivalent_current_a, power_w

    def _system_health_values(self) -> tuple[Any, ...]:
        """Read lightweight Linux controller metrics without extra dependencies."""
        storage_total: int | None = None
        storage_used: int | None = None
        storage_percent: float | None = None
        try:
            storage = shutil.disk_usage(self.database_path.parent)
            storage_total = storage.total
            storage_used = storage.used
            storage_percent = (
                storage.used * 100.0 / storage.total if storage.total > 0 else None
            )
        except OSError:
            pass

        cpu_percent: float | None = None
        try:
            fields = Path("/proc/stat").read_text(encoding="utf-8").splitlines()[0].split()
            counters = [int(value) for value in fields[1:]]
            total = sum(counters)
            idle = counters[3] + (counters[4] if len(counters) > 4 else 0)
            if self._previous_cpu_times is not None:
                previous_total, previous_idle = self._previous_cpu_times
                total_delta = total - previous_total
                idle_delta = idle - previous_idle
                if total_delta > 0:
                    cpu_percent = min(100.0, max(0.0, 100.0 * (total_delta - idle_delta) / total_delta))
            self._previous_cpu_times = (total, idle)
        except (OSError, ValueError, IndexError):
            pass

        memory_total: int | None = None
        memory_used: int | None = None
        memory_percent: float | None = None
        swap_total: int | None = None
        swap_used: int | None = None
        swap_percent: float | None = None
        try:
            memory_info: dict[str, int] = {}
            for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
                key, separator, value = line.partition(":")
                if not separator:
                    continue
                memory_info[key] = int(value.strip().split()[0]) * 1024
            memory_total = memory_info.get("MemTotal")
            memory_available = memory_info.get("MemAvailable")
            if memory_total is not None and memory_available is not None:
                memory_used = max(0, memory_total - memory_available)
                memory_percent = memory_used * 100.0 / memory_total if memory_total else None
            swap_total = memory_info.get("SwapTotal")
            swap_free = memory_info.get("SwapFree")
            if swap_total is not None and swap_free is not None:
                swap_used = max(0, swap_total - swap_free)
                swap_percent = swap_used * 100.0 / swap_total if swap_total else 0.0
        except (OSError, ValueError, IndexError):
            pass

        cpu_temp_c: float | None = None
        thermal_zones = sorted(Path("/sys/class/thermal").glob("thermal_zone*"))
        preferred_zones: list[Path] = []
        other_zones: list[Path] = []
        for zone in thermal_zones:
            try:
                zone_type = (zone / "type").read_text(encoding="utf-8").strip().lower()
            except OSError:
                zone_type = ""
            (preferred_zones if "cpu" in zone_type or "soc" in zone_type else other_zones).append(zone)
        for zone in [*preferred_zones, *other_zones]:
            try:
                raw_temperature = float((zone / "temp").read_text(encoding="utf-8").strip())
                cpu_temp_c = raw_temperature / 1000.0 if raw_temperature > 1000 else raw_temperature
                if math.isfinite(cpu_temp_c):
                    break
                cpu_temp_c = None
            except (OSError, ValueError):
                continue

        load_1m_percent: float | None = None
        try:
            cpu_count = os.cpu_count() or 1
            load_1m_percent = max(0.0, os.getloadavg()[0] * 100.0 / cpu_count)
        except (OSError, AttributeError):
            pass

        uptime_sec: float | None = None
        try:
            uptime_sec = float(Path("/proc/uptime").read_text(encoding="utf-8").split()[0])
        except (OSError, ValueError, IndexError):
            pass

        return (
            storage_total, storage_used, storage_percent,
            cpu_percent,
            memory_total, memory_used, memory_percent,
            cpu_temp_c, load_1m_percent,
            swap_total, swap_used, swap_percent,
            uptime_sec,
        )

    def _flush(self) -> None:
        with self._pending_lock:
            rows = list(self._pending)
            power_rows = list(self._pending_power)
            system_health_rows = list(self._pending_system_health)
            network_usage_rows = list(self._pending_network_usage)
            self._pending.clear()
            self._pending_power.clear()
            self._pending_system_health.clear()
            self._pending_network_usage.clear()
        if not rows and not power_rows and not system_health_rows and not network_usage_rows:
            return
        try:
            with self._connect() as connection:
                if rows:
                    connection.executemany(
                        "INSERT OR REPLACE INTO telemetry VALUES (?, ?, ?, ?, ?, ?, ?)", rows,
                    )
                if power_rows:
                    connection.executemany(
                        """INSERT OR REPLACE INTO power_metrics
                           (captured_ms, az_voltage_v, az_current_a, az_power_w,
                            alt_voltage_v, alt_current_a, alt_power_w,
                            pi_voltage_v, pi_current_a, pi_power_w, total_power_w)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        power_rows,
                    )
                if system_health_rows:
                    connection.executemany(
                        """INSERT OR REPLACE INTO system_health_metrics
                           (captured_ms,
                            storage_total_bytes, storage_used_bytes, storage_percent,
                            cpu_percent,
                            memory_total_bytes, memory_used_bytes, memory_percent,
                            cpu_temp_c, load_1m_percent,
                            swap_total_bytes, swap_used_bytes, swap_percent, uptime_sec)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        system_health_rows,
                    )
                if network_usage_rows:
                    connection.executemany(
                        """INSERT OR REPLACE INTO network_usage_metrics
                           (captured_ms, interface, download_mbps, upload_mbps)
                           VALUES (?, ?, ?, ?)""",
                        network_usage_rows,
                    )
                now = monotonic()
                if self._retention_sec is not None and now >= self._next_cleanup_at:
                    cutoff = int(time() * 1000) - self._retention_sec * 1000
                    connection.execute("DELETE FROM telemetry WHERE captured_ms < ?", (cutoff,))
                    connection.execute("DELETE FROM power_metrics WHERE captured_ms < ?", (cutoff,))
                    connection.execute(
                        "DELETE FROM system_health_metrics WHERE captured_ms < ?", (cutoff,),
                    )
                    connection.execute(
                        "DELETE FROM network_usage_metrics WHERE captured_ms < ?", (cutoff,),
                    )
                    self._next_cleanup_at = now + 3600.0
        except sqlite3.Error:
            with self._pending_lock:
                self._pending.extendleft(reversed(rows[-5000:]))
                self._pending_power.extendleft(reversed(power_rows[-5000:]))
                self._pending_system_health.extendleft(reversed(system_health_rows[-5000:]))
                self._pending_network_usage.extendleft(reversed(network_usage_rows[-5000:]))

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
                    interface TEXT, source TEXT
                ) WITHOUT ROWID
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS power_metrics (
                    captured_ms INTEGER PRIMARY KEY,
                    az_voltage_v REAL, az_current_a REAL, az_power_w REAL,
                    alt_voltage_v REAL, alt_current_a REAL, alt_power_w REAL,
                    pi_voltage_v REAL, pi_current_a REAL, pi_power_w REAL,
                    total_power_w REAL
                ) WITHOUT ROWID
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS network_usage_metrics (
                    captured_ms INTEGER PRIMARY KEY,
                    interface TEXT,
                    download_mbps REAL,
                    upload_mbps REAL
                ) WITHOUT ROWID
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS system_health_metrics (
                    captured_ms INTEGER PRIMARY KEY,
                    storage_total_bytes INTEGER,
                    storage_used_bytes INTEGER,
                    storage_percent REAL,
                    cpu_percent REAL,
                    memory_total_bytes INTEGER,
                    memory_used_bytes INTEGER,
                    memory_percent REAL,
                    cpu_temp_c REAL,
                    load_1m_percent REAL,
                    swap_total_bytes INTEGER,
                    swap_used_bytes INTEGER,
                    swap_percent REAL,
                    uptime_sec REAL
                ) WITHOUT ROWID
            """)
            power_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(power_metrics)")
            }
            for column in ("pi_voltage_v", "pi_current_a", "pi_power_w"):
                if column not in power_columns:
                    connection.execute(f"ALTER TABLE power_metrics ADD COLUMN {column} REAL")
            columns = {row[1] for row in connection.execute("PRAGMA table_info(network_metrics)")}
            if "interface" not in columns:
                connection.execute("ALTER TABLE network_metrics ADD COLUMN interface TEXT")
            if "source" not in columns:
                connection.execute("ALTER TABLE network_metrics ADD COLUMN source TEXT")

    def _connect(self, *, read_only: bool = False) -> sqlite3.Connection:
        if read_only:
            return sqlite3.connect(f"file:{self.database_path}?mode=ro", uri=True, timeout=5.0)
        return sqlite3.connect(self.database_path, timeout=5.0)
