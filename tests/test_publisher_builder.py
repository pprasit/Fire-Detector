import http.client
import unittest
from pathlib import Path
from types import ModuleType
import sys
import tempfile
from unittest.mock import patch

from fire_detector import publisher_builder

from fire_detector.publisher_builder import station_connection


class RecordingSocket:
    def __init__(self):
        self.data = bytearray()

    def sendall(self, value):
        self.data.extend(value)


class StationOriginHeadersTests(unittest.TestCase):
    def connection(self, host='server.example'):
        connection_type = station_connection(http.client.HTTPSConnection, 'station-alpha', 'https://server.example')
        connection = connection_type(host)
        connection.sock = RecordingSocket()
        return connection

    def test_signing_upload_header_is_sent_with_real_http_request(self):
        connection = self.connection()
        connection.putrequest('POST', '/api/updates/builds')
        connection.putheader('Content-Length', '3')
        connection.endheaders()
        connection.send(b'abc')
        wire = bytes(connection.sock.data)
        self.assertEqual(wire.count(b'X-Narit-Station-ID: station-alpha\r\n'), 1)
        self.assertTrue(wire.endswith(b'abc'))

    def test_helper_status_requests_keep_the_same_origin_metadata(self):
        connection = self.connection()
        connection.request('GET', '/api/updates/builds/info')
        self.assertIn(b'X-Narit-Station-ID: station-alpha\r\n', connection.sock.data)

    def test_origin_metadata_is_not_added_to_other_hosts_or_authentication(self):
        for host, path in [('other.example', '/api/updates/builds'), ('server.example', '/api/auth/login')]:
            connection = self.connection(host)
            connection.request('POST', path, body=b'{}')
            self.assertNotIn(b'X-Narit-Station-ID', connection.sock.data)

    def test_real_adapter_entrypoint_preserves_the_global_https_class(self):
        original = http.client.HTTPSConnection
        helper_module = ModuleType('update_system.build_helper')
        package = ModuleType('update_system')
        package.build_helper = helper_module
        captured = []
        def run_helper():
            self.assertIs(http.client.HTTPSConnection, original)
            connection = helper_module.http.client.HTTPSConnection('server.example')
            connection.sock = RecordingSocket()
            connection.request('GET', '/api/updates/builds/info')
            captured.append(bytes(connection.sock.data))
        helper_module.main = run_helper
        with tempfile.TemporaryDirectory() as temporary:
            helper = Path(temporary) / 'build-signed-release'
            helper.write_text('# fixture launcher')
            with (patch.dict(sys.modules, {'update_system': package}),
                  patch.object(sys, 'argv', ['adapter', str(helper), '--source', temporary]),
                  patch.object(sys, 'path', list(sys.path)),
                  patch.dict('os.environ', {'FIRE_UPDATE_STATION_ID': 'station-alpha', 'FIRE_UPDATE_SERVER': 'https://server.example'}),
                  patch.object(publisher_builder.hashlib, 'sha256') as digest):
                digest.return_value.hexdigest.return_value = '6c78267a5e761d1c00eff151229a2f6e8da3718d7e6c103208854fd6bf3747a4'
                publisher_builder.main()
        self.assertEqual(len(captured), 1)
        self.assertIn(b'X-Narit-Station-ID: station-alpha\r\n', captured[0])
        self.assertIs(http.client.HTTPSConnection, original)

    def test_invalid_station_id_cannot_inject_an_http_header(self):
        for station_id in ('', None, '../station', 'station\r\nInjected: yes'):
            with self.assertRaises(ValueError):
                station_connection(http.client.HTTPSConnection, station_id, 'https://server.example')
