import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    'station_doctor', Path(__file__).parents[1] / 'scripts/station_doctor.py')
doctor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(doctor)


class StationDoctorTests(unittest.TestCase):
    def test_usb_inventory_distinguishes_odrive_and_reports_missing_serial(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            for name, vendor, product in [('drive', '1209', '0d32'), ('hub', '1d6b', '0002')]:
                device = base / name
                device.mkdir()
                (device / 'idVendor').write_text(vendor)
                (device / 'idProduct').write_text(product)
            devices = doctor.usb_inventory(base)
        self.assertTrue(devices[0]['odrive'])
        self.assertFalse(devices[1]['odrive'])
        self.assertEqual(devices[0]['serial'], '')

    def test_unconfigured_station_is_not_ready_and_never_prints_camera_secrets(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'AppSetting.JSON').write_text(json.dumps({
                'simulation_mode': {'enabled': True}, 'drive_serials': {}}))
            (root / 'camera_runtime').mkdir()
            (root / 'camera_runtime/system_settings.json').write_text(json.dumps({
                'cameras': {'thermal': {'password': 'test-private-value'}}}))
            output = io.StringIO()
            with patch.object(doctor, 'ROOT', root), patch('sys.argv', ['doctor']), patch('sys.stdout', output):
                code = doctor.main()
        self.assertEqual(code, 1)
        self.assertNotIn('test-private-value', output.getvalue())
        self.assertFalse(json.loads(output.getvalue())['ready_for_acceptance'])
