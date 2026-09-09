import unittest
from threading import Event

from fire_detector.jog_commands import JogCommandRegistry


class JogCommandRegistryTests(unittest.TestCase):
    def test_missing_client_id_is_rejected(self):
        with self.assertRaises(ValueError):
            JogCommandRegistry().arbitrate("", {"Azimuth": 5.0}, 1)

    def test_live_owner_cannot_be_overridden_by_another_page(self):
        registry = JogCommandRegistry()
        self.assertEqual(registry.arbitrate("old", {"Azimuth": 5.0}, 1)[0], {"Azimuth": 5.0})
        accepted, ignored = registry.arbitrate("new", {"Azimuth": -5.0}, 1)
        self.assertEqual(accepted, {})
        self.assertEqual(ignored, {"Azimuth": "old"})

        accepted, ignored = registry.arbitrate("old", {"Azimuth": 0.0}, 2)

        self.assertEqual(accepted, {"Azimuth": 0.0})
        self.assertEqual(ignored, {})
        self.assertEqual(registry.snapshot(), {})

    def test_owner_can_stop_and_explicit_motion_can_supersede(self):
        registry = JogCommandRegistry()
        registry.arbitrate("page", {"Azimuth": 5.0, "Altitude": 2.0}, 1)
        self.assertEqual(registry.arbitrate("page", {"Azimuth": 0.0}, 2)[0], {"Azimuth": 0.0})
        registry.supersede(("Altitude",))
        self.assertEqual(registry.snapshot(), {})

    def test_heartbeat_renews_lease_without_rewriting_hardware(self):
        registry = JogCommandRegistry()
        self.assertEqual(registry.arbitrate("page", {"Azimuth": 5.0}, 1)[0], {"Azimuth": 5.0})
        self.assertEqual(registry.arbitrate("page", {"Azimuth": 5.0}, 2)[0], {})
        self.assertEqual(registry.snapshot(), {"Azimuth": "page"})

    def test_late_start_cannot_overtake_release(self):
        registry = JogCommandRegistry()
        self.assertEqual(registry.arbitrate("page", {"Azimuth": 0.0}, 2)[0], {"Azimuth": 0.0})
        accepted, ignored = registry.arbitrate("page", {"Azimuth": 5.0}, 1)
        self.assertEqual(accepted, {})
        self.assertIn("Azimuth", ignored)
        self.assertEqual(registry.snapshot(), {})

    def test_deadman_stops_axis_when_heartbeat_ceases(self):
        expired = []
        stopped = Event()

        def on_expire(command):
            expired.append(command)
            stopped.set()

        registry = JogCommandRegistry(on_expire, lease_timeout_sec=0.05)
        try:
            registry.arbitrate("page", {"Azimuth": 5.0}, 1)
            self.assertTrue(stopped.wait(0.5))
            self.assertEqual(expired, [{"Azimuth": 0.0}])
            self.assertEqual(registry.snapshot(), {})
        finally:
            registry.close()


if __name__ == "__main__":
    unittest.main()
