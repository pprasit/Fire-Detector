from pathlib import Path
import tempfile
from threading import Event
from time import time
import unittest
from unittest.mock import patch

from fire_detector.telemetry_store import (
    MANUAL_CAPACITY_MAX_AGE_SEC,
    POWER_SAMPLE_INTERVAL_SEC,
    SYSTEM_HEALTH_SAMPLE_INTERVAL_SEC,
    TelemetryStore,
)


class TelemetryStorePowerTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "telemetry.sqlite3"

    def tearDown(self):
        self.temporary_directory.cleanup()

    @staticmethod
    def snapshot():
        return {
            "axes": [
                {
                    "label": "Azimuth",
                    "position_deg": 10.0,
                    "velocity_deg_per_sec": 2.0,
                    "current": 3.0,
                    "drive_vbus_voltage": 48.0,
                    "drive_ibus": 2.0,
                },
                {
                    "label": "Altitude",
                    "position_deg": 20.0,
                    "velocity_deg_per_sec": 1.0,
                    "current": 4.0,
                    "drive_vbus_voltage": 50.0,
                    "drive_ibus": -1.0,
                },
            ]
        }

    def test_captures_drive_power_and_excludes_regeneration_from_consumption(self):
        store = TelemetryStore(self.database_path, self.snapshot)
        store._initialize()

        with patch.object(store, "_raspberry_pi_power_values", return_value=(None, None, None)):
            store._capture()
        store._flush()
        report = store.power_report()

        self.assertEqual(report["sample_interval_ms"], POWER_SAMPLE_INTERVAL_SEC * 1000)
        self.assertEqual(report["sample_count"], 1)
        self.assertAlmostEqual(report["latest"]["azimuth"]["power_w"], 96.0)
        self.assertEqual(report["latest"]["altitude"]["power_w"], 0)
        self.assertAlmostEqual(report["latest"]["total_power_w"], 96.0)
        self.assertAlmostEqual(report["energy"]["total_kwh"], 96.0 / 3_600_000.0)
        self.assertAlmostEqual(report["energy"]["total_wh"], 96.0 / 3600.0)
        self.assertAlmostEqual(report["points"][0]["azimuth_power_w"], 96.0)
        self.assertEqual(report["points"][0]["altitude_power_w"], 0)

    def test_empty_power_report_has_no_latest_sample(self):
        store = TelemetryStore(self.database_path, lambda: {"axes": []})
        store._initialize()

        report = store.power_report()

        self.assertIsNone(report["latest"])
        self.assertEqual(report["points"], [])
        self.assertEqual(report["sample_count"], 0)

    def test_raspberry_pi_power_is_stored_and_included_in_total(self):
        store = TelemetryStore(self.database_path, self.snapshot)
        store._initialize()

        with patch.object(
            store,
            "_raspberry_pi_power_values",
            return_value=(5.1, 0.5, 2.55),
        ):
            store._capture()
        store._flush()
        report = store.power_report()

        self.assertAlmostEqual(report["latest"]["raspberry_pi"]["power_w"], 2.55)
        self.assertAlmostEqual(report["latest"]["total_power_w"], 98.55)
        self.assertAlmostEqual(report["points"][0]["raspberry_pi_power_w"], 2.55)
        self.assertAlmostEqual(report["energy"]["raspberry_pi_wh"], 2.55 / 3600.0)

    def test_power_report_groups_samples_into_five_second_averages(self):
        store = TelemetryStore(self.database_path, lambda: {"axes": []})
        store._initialize()
        base_ms = (int(time() * 1000) // 5000) * 5000 - 15_000
        rows = [
            (base_ms + 1000, 48.0, 1.0, 10.0, 48.0, 0.0, 0.0, 10.0),
            (base_ms + 2000, 48.0, 1.0, 20.0, 48.0, 0.0, 0.0, 20.0),
            (base_ms + 6000, 48.0, 1.0, 30.0, 48.0, 0.0, 0.0, 30.0),
            (base_ms + 7000, 48.0, 1.0, 50.0, 48.0, 0.0, 0.0, 50.0),
        ]
        with store._connect() as connection:
            connection.executemany(
                """INSERT INTO power_metrics
                   (captured_ms, az_voltage_v, az_current_a, az_power_w,
                    alt_voltage_v, alt_current_a, alt_power_w, total_power_w)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                rows,
            )

        report = store.power_report(interval_sec=5)

        populated = [point for point in report["points"] if point["total_power_w"] is not None]
        self.assertEqual(report["requested_interval_ms"], 5000)
        self.assertEqual(report["bucket_ms"], 5000)
        self.assertEqual([point["total_power_w"] for point in populated], [15.0, 40.0])
        self.assertAlmostEqual(report["latest"]["total_power_w"], 40.0)

    def test_parses_raspberry_pi_pmic_rail_power(self):
        voltage, current, power = TelemetryStore._parse_pmic_adc("""
           3V3_SYS_A current(1)=0.10000000A
           VDD_CORE_A current(7)=1.00000000A
           3V3_SYS_V volt(9)=3.30000000V
           VDD_CORE_V volt(15)=0.80000000V
           EXT5V_V volt(24)=5.10000000V
        """)

        self.assertAlmostEqual(voltage, 5.1)
        self.assertAlmostEqual(power, 1.13)
        self.assertAlmostEqual(current, 1.13 / 5.1)

    def test_network_report_returns_capacity_used_and_free_series(self):
        store = TelemetryStore(self.database_path, lambda: {"axes": []})
        store._initialize()
        base_ms = int(time() * 1000) - 10_000
        with store._connect() as connection:
            connection.execute(
                """INSERT INTO network_metrics
                   (captured_ms, latency_ms, download_mbps, upload_mbps, online, interface)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (base_ms, 12.0, 100.0, 40.0, 1, "eth0"),
            )
            connection.executemany(
                """INSERT INTO network_usage_metrics
                   (captured_ms, interface, download_mbps, upload_mbps)
                   VALUES (?, ?, ?, ?)""",
                [
                    (base_ms + 1000, "eth0", 25.0, 5.0),
                    (base_ms + 2000, "eth0", 35.0, 7.0),
                ],
            )

        report = store.network_report(hours=1, buckets=3600)

        self.assertEqual(report["series"]["capacity"]["latest"]["download_mbps"], 100.0)
        self.assertAlmostEqual(report["series"]["used"]["average"]["download_mbps"], 30.0)
        self.assertEqual(report["series"]["used"]["latest"]["upload_mbps"], 7.0)
        self.assertEqual(report["series"]["free"]["latest"]["download_mbps"], 65.0)
        self.assertEqual(report["series"]["free"]["latest"]["upload_mbps"], 33.0)

    def test_manual_capacity_test_persists_complete_result(self):
        store = TelemetryStore(self.database_path, lambda: {"axes": []})
        store._initialize()

        with patch.object(store, "_measure_network", return_value=(25.0, 12.5, 3.5)):
            started, initial = store.start_network_capacity_test()
            self.assertTrue(started)
            self.assertEqual(initial["status"], "running")
            store._capacity_test_thread.join(timeout=2.0)

        status = store.network_capacity_test_status()
        self.assertEqual(status["status"], "complete")
        self.assertEqual(status["download_mbps"], 12.5)
        self.assertEqual(status["upload_mbps"], 3.5)
        with store._connect(read_only=True) as connection:
            stored = connection.execute(
                "SELECT latency_ms, download_mbps, upload_mbps, source FROM network_metrics"
            ).fetchone()
        self.assertEqual(stored, (25.0, 12.5, 3.5, "manual"))

    def test_manual_capacity_test_does_not_start_twice(self):
        store = TelemetryStore(self.database_path, lambda: {"axes": []})
        store._initialize()
        release = Event()

        def measure(_run_speed):
            release.wait(timeout=2.0)
            return 10.0, 5.0, 2.0

        with patch.object(store, "_measure_network", side_effect=measure):
            first, _ = store.start_network_capacity_test()
            second, state = store.start_network_capacity_test()
            self.assertTrue(first)
            self.assertFalse(second)
            self.assertEqual(state["status"], "running")
            release.set()
            store._capacity_test_thread.join(timeout=2.0)

    def test_recent_manual_capacity_survives_dashboard_restart(self):
        store = TelemetryStore(self.database_path, lambda: {"axes": []})
        store._initialize()
        captured_ms = int((time() - MANUAL_CAPACITY_MAX_AGE_SEC / 2) * 1000)
        with store._connect() as connection:
            connection.execute(
                """INSERT INTO network_metrics
                   (captured_ms, latency_ms, download_mbps, upload_mbps,
                    online, interface, source)
                   VALUES (?, ?, ?, ?, ?, ?, 'manual')""",
                (captured_ms, 25.0, 12.5, 3.5, 1, "eth0"),
            )

        store._load_network_capacity_history()

        self.assertEqual(
            list(store._network_capacity_history),
            [(captured_ms, "eth0", 12.5, 3.5)],
        )

    def test_captures_and_reports_controller_health_metrics(self):
        store = TelemetryStore(self.database_path, self.snapshot)
        store._initialize()
        health_values = (
            1_000_000, 250_000, 25.0,
            40.0,
            2_000_000, 1_000_000, 50.0,
            55.0, 20.0,
            100_000, 10_000, 10.0,
            12_345.0,
        )

        with (
            patch.object(store, "_raspberry_pi_power_values", return_value=(None, None, None)),
            patch.object(store, "_system_health_values", return_value=health_values),
        ):
            store._capture()
        store._flush()
        report = store.system_health_report()

        self.assertEqual(
            report["sample_interval_ms"],
            SYSTEM_HEALTH_SAMPLE_INTERVAL_SEC * 1000,
        )
        self.assertEqual(report["sample_count"], 1)
        self.assertEqual(report["latest"]["storage_percent"], 25.0)
        self.assertEqual(report["latest"]["cpu_percent"], 40.0)
        self.assertEqual(report["latest"]["memory_percent"], 50.0)
        self.assertEqual(report["latest"]["cpu_temp_c"], 55.0)
        self.assertEqual(report["latest"]["uptime_sec"], 12_345.0)
        self.assertEqual(report["metrics"]["temperature"]["peak"], 55.0)
        self.assertEqual(report["points"][0]["swap_percent"], 10.0)

    def test_empty_controller_health_report_is_safe(self):
        store = TelemetryStore(self.database_path, lambda: {"axes": []})
        store._initialize()

        report = store.system_health_report()

        self.assertIsNone(report["latest"])
        self.assertEqual(report["points"], [])
        self.assertEqual(report["sample_count"], 0)

    def test_default_store_keeps_unconfirmed_history_for_backup(self):
        store = TelemetryStore(self.database_path, self.snapshot)
        store._initialize()
        old_ms = int((time() - 10 * 24 * 3600) * 1000)
        with store._connect() as connection:
            connection.execute(
                "INSERT INTO telemetry VALUES (?, ?, ?, ?, ?, ?, ?)",
                (old_ms, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0),
            )

        with (
            patch.object(store, "_raspberry_pi_power_values", return_value=(None, None, None)),
            patch.object(store, "_system_health_values", return_value=(None,) * 13),
        ):
            store._capture()
        store._flush()

        with store._connect(read_only=True) as connection:
            retained = connection.execute(
                "SELECT COUNT(*) FROM telemetry WHERE captured_ms = ?", (old_ms,),
            ).fetchone()[0]
        self.assertEqual(retained, 1)


if __name__ == "__main__":
    unittest.main()
