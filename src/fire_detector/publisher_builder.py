"""Add station-origin headers around the immutable Server build/sign helper.

The upstream tooling and signed manifest schema remain unchanged. Station ID is
origin metadata, not authentication; Server must bind it to the logged-in owner.
"""
from __future__ import annotations

import hashlib
import http.client
import os
from pathlib import Path
import re
import sys
from types import SimpleNamespace
from urllib.parse import urlsplit


def station_connection(base, station_id, origin):
    if not isinstance(station_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", station_id):
        raise ValueError("invalid_source_station_id")
    parsed = urlsplit(origin)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.path not in ('', '/') or parsed.query or parsed.fragment:
        raise ValueError('invalid_server_origin')
    expected_host, expected_port = parsed.hostname, parsed.port or 443

    class StationConnection(base):
        def putrequest(self, method, url, *args, **kwargs):
            super().putrequest(method, url, *args, **kwargs)
            if self.host == expected_host and self.port == expected_port and url.startswith('/api/updates/'):
                self.putheader('X-Narit-Station-ID', station_id)

    return StationConnection


def main():
    helper = Path(sys.argv[1]).resolve()
    if hashlib.sha256(helper.read_bytes()).hexdigest() != '6c78267a5e761d1c00eff151229a2f6e8da3718d7e6c103208854fd6bf3747a4':
        raise ValueError('unsupported_publisher_helper_revision')
    connection_type = station_connection(http.client.HTTPSConnection,
        os.environ.get('FIRE_UPDATE_STATION_ID'), os.environ['FIRE_UPDATE_SERVER'])
    sys.path.insert(0, str(helper.parent))
    from update_system import build_helper
    # Scope the adapter to this helper. Python 3.11 HTTPSConnection uses its
    # module's class name in super(); replacing the global class recurses.
    build_helper.http = SimpleNamespace(client=SimpleNamespace(HTTPSConnection=connection_type))
    sys.argv = [str(helper), *sys.argv[2:]]
    build_helper.main()


if __name__ == '__main__':
    main()
