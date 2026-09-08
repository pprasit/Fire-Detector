import unittest

from fire_detector.web_server import _dashboard_variant


class DashboardVariantTests(unittest.TestCase):
    def test_mobile_user_agents_use_mobile_frontend(self):
        self.assertEqual(_dashboard_variant("Mozilla/5.0 (Linux; Android 15; Pixel 8) Mobile"), "mobile")
        self.assertEqual(_dashboard_variant("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)"), "mobile")

    def test_desktop_user_agents_use_desktop_frontend(self):
        self.assertEqual(_dashboard_variant("Mozilla/5.0 (Windows NT 10.0; Win64; x64)"), "desktop")
        self.assertEqual(_dashboard_variant("Mozilla/5.0 (X11; Linux x86_64)"), "desktop")

    def test_client_hint_and_explicit_preview_override(self):
        self.assertEqual(_dashboard_variant("Desktop", "?1"), "mobile")
        self.assertEqual(_dashboard_variant("Android Mobile", "?1", "desktop"), "desktop")
        self.assertEqual(_dashboard_variant("Desktop", "?0", "mobile"), "mobile")


if __name__ == "__main__":
    unittest.main()
