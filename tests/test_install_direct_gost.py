import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
SPEC = importlib.util.spec_from_file_location('install_direct_gost', ROOT / 'scripts/install_direct_gost.py')
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)
BODY = bytes(range(256)) * 4096


class Origin(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_HEAD(self):
        self.send_response(200)
        self.send_header('Content-Length', str(len(BODY)))
        self.send_header('Accept-Ranges', 'bytes')
        self.end_headers()

    def do_GET(self):
        value = self.headers.get('Range', '')
        if not value.startswith('bytes='):
            self.send_error(400)
            return
        start, end = map(int, value[6:].split('-'))
        self.send_response(206)
        self.send_header('Content-Range', f'bytes {start}-{end}/{len(BODY)}')
        self.send_header('Content-Length', str(end - start + 1))
        self.end_headers()
        self.wfile.write(BODY[start:end + 1])


class VerifiedDownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Origin)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.env = os.environ.copy()
        for name in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY', 'all_proxy'):
            self.env.pop(name, None)
        self.env['NO_PROXY'] = '127.0.0.1,localhost'
        self.env['WEBSTUDIO_LOCAL_DIR'] = self.temp.name
        self.url = f'http://127.0.0.1:{self.server.server_port}/archive'
        self.cache = Path(self.temp.name) / 'cache/archive.tar.gz'

    def test_verified_ranges_publish_archive(self):
        with patch.dict(os.environ, self.env), patch.object(installer, 'BASE', self.url.rsplit('/', 1)[0]), patch.object(installer, 'CHUNK', 64 * 1024):
            path = installer.download_archive('archive', hashlib.sha256(BODY).hexdigest(),
                                              self.cache, self.env)
        self.assertEqual(path.read_bytes(), BODY)

    def test_bad_checksum_never_publishes_archive(self):
        with patch.dict(os.environ, self.env), patch.object(installer, 'BASE', self.url.rsplit('/', 1)[0]), patch.object(installer, 'CHUNK', 64 * 1024):
            with self.assertRaises(RuntimeError):
                installer.download_archive('archive', '0' * 64, self.cache, self.env)
        self.assertFalse(self.cache.exists())


if __name__ == '__main__':
    unittest.main()
