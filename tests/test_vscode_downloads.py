import concurrent.futures
import hashlib
import http.server
import importlib.util
from pathlib import Path
import re
import tempfile
import threading
import unittest

spec = importlib.util.spec_from_file_location('downloads', Path(__file__).resolve().parents[1] / 'scripts/vscode_downloads.py')
downloads = importlib.util.module_from_spec(spec)
spec.loader.exec_module(downloads)
ROUTE = '/commit:' + 'a' * 40 + '/server-linux-x64/stable'


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.payload = b'archive-test-data' * 10000
        self.ranges = []
        self.bad_hash = False
        self.ignore_range = False
        self.bad_range = False
        self.offline = False
        test = self

        class Origin(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_HEAD(self):
                if test.offline:
                    raise AssertionError('A cached request must not contact upstream')
                self.send_response(200)
                self.send_header('Content-Length', str(len(test.payload)))
                self.send_header('x-sha256', '0' * 64 if test.bad_hash else hashlib.sha256(test.payload).hexdigest())
                self.end_headers()

            def do_GET(self):
                value = self.headers.get('Range')
                test.ranges.append(value)
                if value and not test.ignore_range:
                    start, end = map(int, re.fullmatch(r'bytes=(\d+)-(\d+)', value).groups())
                    content = test.payload[start:end + 1]
                    self.send_response(206)
                    if test.bad_range:
                        start += 1
                    self.send_header('Content-Range', f'bytes {start}-{end}/{len(test.payload)}')
                else:
                    content = test.payload
                    self.send_response(200)
                self.send_header('Content-Length', str(len(content)))
                self.end_headers()
                self.wfile.write(content)

        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Origin)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.cache = downloads.Cache(self.root / 'persistent', self.root / 'local', workers=4,
                                     upstream=f'http://127.0.0.1:{self.server.server_port}')
        old_chunk = downloads.CHUNK
        downloads.CHUNK = 32768
        self.addCleanup(setattr, downloads, 'CHUNK', old_chunk)

    def test_parallel_download_deduplication_and_offline_restart(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            paths = list(pool.map(self.cache.archive, [ROUTE, ROUTE]))
        self.assertEqual(paths[0].read_bytes(), self.payload)
        self.assertEqual(len(self.ranges), 6)
        self.offline = True
        fresh = downloads.Cache(self.cache.cache, self.root / 'new-container')
        self.assertEqual(fresh.archive(ROUTE).read_bytes(), self.payload)

    def test_checksum_failure_never_publishes(self):
        self.bad_hash = True
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            self.cache.archive(ROUTE)
        self.assertFalse(list(self.cache.cache.glob('*.tar.gz')))

    def test_corrupt_cache_is_repaired(self):
        archive = self.cache.archive(ROUTE)
        archive.write_bytes(b'corrupt')
        self.assertEqual(self.cache.archive(ROUTE).read_bytes(), self.payload)

    def test_range_fallback_and_wrong_offsets(self):
        self.bad_range = True
        with self.assertRaisesRegex(ValueError, 'Invalid range'):
            self.cache.archive(ROUTE)
        self.bad_range = False
        self.ignore_range = True
        self.assertEqual(self.cache.archive(ROUTE).read_bytes(), self.payload)
        self.assertIsNone(self.ranges[-1])

    def test_proxy_serves_requested_commit_and_rejects_unknown_paths(self):
        import urllib.request
        import urllib.error
        proxy = http.server.ThreadingHTTPServer(('127.0.0.1', 0), downloads.handler(self.cache))
        threading.Thread(target=proxy.serve_forever, daemon=True).start()
        self.addCleanup(proxy.server_close)
        self.addCleanup(proxy.shutdown)
        base = f'http://127.0.0.1:{proxy.server_port}'
        with urllib.request.urlopen(base + ROUTE) as response:
            self.assertEqual(response.read(), self.payload)
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(base + '/../../etc/passwd')
        self.assertEqual(caught.exception.code, 404)

    def test_migration_refuses_a_running_editor(self):
        import subprocess
        import sys
        old, target = self.root / 'server-data', self.root / 'persistent-data'
        old.mkdir()
        process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)',
                                    '/test/server-main.js', '--server-data-dir=' + str(old)])
        try:
            with self.assertRaisesRegex(RuntimeError, 'still uses'):
                downloads.migrate_data(old, target)
            self.assertFalse(target.exists())
        finally:
            process.terminate()
            process.wait()

    def test_data_migration_survives_local_removal_and_preserves_conflicts(self):
        old, target = self.root / 'server-data', self.root / 'persistent-data'
        (old / 'extensions').mkdir(parents=True)
        (old / 'extensions/example').write_text('extension')
        (old / 'settings.json').write_text('settings')
        downloads.migrate_data(old, target)
        self.assertTrue(old.is_symlink())
        self.assertEqual((target / 'settings.json').read_text(), 'settings')
        old.unlink()
        downloads.migrate_data(old, target)
        self.assertEqual((target / 'extensions/example').read_text(), 'extension')
        old.mkdir()
        (old / 'settings.json').write_text('different')
        with self.assertRaisesRegex(RuntimeError, 'Both'):
            downloads.migrate_data(old, target)
        self.assertEqual((old / 'settings.json').read_text(), 'different')
        self.assertEqual((target / 'settings.json').read_text(), 'settings')


if __name__ == '__main__':
    unittest.main()
