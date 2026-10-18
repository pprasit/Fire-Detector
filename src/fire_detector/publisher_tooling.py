"""Pinned, authenticated publisher tooling download (never stores credentials)."""
import hashlib
import os
from pathlib import Path
import ssl
import tempfile
import urllib.request

ARCHIVE_SHA256 = 'defea22dc88c1657901643a486a6f4f791fcf78aad3c3536001117505b1adfe7'
TOOLING_SHA256 = '494d3880e0b01a0b159b78e0312f9ec52998857f492a78c3f2258c09f9c475ab'
PUBLIC_KEY = b'-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEAhkJmPmiaNR+9d1uafwFWPbgtRidodSENzBmkixDd9Gg=\n-----END PUBLIC KEY-----\n'
PUBLIC_KEY_SHA256 = '076d6e62b57659cf421defec7d524bde92448c931ee9cb68c506360bbbeebfaa'


def download(directory, origin, cookie, ca=None):
    directory = Path(directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = directory / 'publisher-tooling.tar.gz'
    if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == ARCHIVE_SHA256:
        return target
    request = urllib.request.Request(origin + '/api/updates/builds/tooling', headers={
        'Cookie': cookie, 'Accept': 'application/gzip',
        'User-Agent': 'Mozilla/5.0 (compatible; NARITStationPublisher/1.0)'})
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=ca)))
    temporary = None
    try:
        with opener.open(request, timeout=60) as response, tempfile.NamedTemporaryFile(dir=directory, delete=False) as stream:
            temporary = Path(stream.name)
            os.chmod(temporary, 0o600)
            digest, size = hashlib.sha256(), 0
            while chunk := response.read(262144):
                size += len(chunk)
                if size > 32 * 1024 * 1024:
                    raise ValueError('tooling_archive_too_large')
                digest.update(chunk)
                stream.write(chunk)
            if digest.hexdigest() != ARCHIVE_SHA256:
                raise ValueError('tooling_checksum_mismatch')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        return target
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
