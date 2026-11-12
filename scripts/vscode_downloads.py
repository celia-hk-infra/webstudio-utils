#!/usr/bin/env python3
"""Loopback update service: verified parallel downloads and a persistent cache.

The CLI's VSCODE_CLI_UPDATE_URL hook handles arbitrary client commits without
patching VS Code or guessing which desktop version will connect next.
"""
import argparse
import concurrent.futures
import fcntl
import hashlib
import http.server
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import urllib.parse

UPSTREAM = 'https://update.code.visualstudio.com'
DOWNLOAD = re.compile(r'/commit:([0-9a-f]{40})/([a-z0-9-]+)/(stable|insider|exploration)')
METADATA = re.compile(r'/api/(?:latest/[a-z0-9-]+|versions/[0-9.]+/[a-z0-9-]+)/(?:stable|insider|exploration)')
CHUNK = 4 * 1024 * 1024


def log(message):
    print('[VS Code downloads] ' + message, flush=True)


def digest(path):
    value = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def headers(path):
    # Include redirect headers: Microsoft publishes x-sha256 on the redirect.
    result = {}
    for line in Path(path).read_text().splitlines():
        if ':' in line:
            key, value = line.split(':', 1)
            result[key.lower()] = value.strip()
    return result


class RangeUnsupported(Exception):
    pass


class Cache:
    def __init__(self, cache, local, workers=32, upstream=UPSTREAM):
        self.cache, self.local = Path(cache), Path(local)
        self.workers, self.upstream = workers, upstream.rstrip('/')
        self.curl = '/usr/bin/curl' if Path('/usr/bin/curl').exists() else shutil.which('curl')
        self.cache.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.local.mkdir(parents=True, exist_ok=True, mode=0o700)

    def curl_request(self, url, *options):
        return subprocess.check_output([
            self.curl, '--fail', '--silent', '--show-error', '--location',
            '--retry', '2', '--connect-timeout', '15', '--max-time', '120',
            *map(str, options), url,
        ], text=True)

    def archive(self, route):
        match = DOWNLOAD.fullmatch(route)
        if not match:
            raise ValueError('Unsupported download path')
        key = '-'.join(match.groups())
        archive = self.cache / (key + '.tar.gz')
        checksum = self.cache / (key + '.sha256')
        # Local locks coordinate all clients in this container. Across containers,
        # atomic publication permits duplicate downloads but never partial reads.
        with open(self.local / (key + '.lock'), 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if archive.is_file() and checksum.is_file():
                expected = checksum.read_text().strip()
                if re.fullmatch('[0-9a-f]{64}', expected) and digest(archive) == expected:
                    log('Cache hit: ' + key)
                    return archive
                log('Invalid cached archive; downloading again: ' + key)
            with tempfile.TemporaryDirectory(prefix='download-', dir=self.local) as temp:
                temp = Path(temp)
                url = self.curl_request(self.upstream + route, '--head',
                                        '--dump-header', temp / 'headers', '--output', os.devnull,
                                        '--write-out', '%{url_effective}').strip()
                info = headers(temp / 'headers')
                expected = info.get('x-sha256', '').lower()
                if not re.fullmatch('[0-9a-f]{64}', expected):
                    raise ValueError('Microsoft did not supply a SHA-256 checksum; refusing unverified download')
                size = int(info['content-length'])
                if size <= 0:
                    raise ValueError('Invalid download size')
                started = time.monotonic()
                log(f'Downloading {key}: {size / 1e6:.1f} MB, {self.workers} connections')
                completed = 0
                progress_lock = threading.Lock()

                def part(start, length=CHUNK):
                    nonlocal completed
                    end = min(start + length, size) - 1
                    dest, head = temp / str(start), temp / (str(start) + '.headers')
                    status = self.curl_request(url, '--range', f'{start}-{end}',
                                               '--dump-header', head, '--output', dest,
                                               '--write-out', '%{http_code}')
                    if status == '200':
                        raise RangeUnsupported()
                    if (status != '206' or headers(head).get('content-range') != f'bytes {start}-{end}/{size}'
                            or dest.stat().st_size != end - start + 1):
                        raise ValueError('Invalid range response')
                    with progress_lock:
                        completed += end - start + 1
                        if completed == size or completed // (16 * 1024 * 1024) != (completed - (end - start + 1)) // (16 * 1024 * 1024):
                            log(f'{key}: {completed / 1e6:.1f}/{size / 1e6:.1f} MB')
                    return dest

                assembled = temp / 'archive'
                try:
                    # Probe once before fan-out, avoiding many full downloads if
                    # an intermediary silently ignores HTTP Range.
                    probe_size = min(CHUNK, 64 * 1024)
                    first = part(0, probe_size)
                    with concurrent.futures.ThreadPoolExecutor(max_workers=self.workers) as pool:
                        parts = [first] + list(pool.map(part, range(probe_size, size, CHUNK)))
                    with open(assembled, 'wb') as output:
                        for chunk in parts:
                            with open(chunk, 'rb') as source:
                                shutil.copyfileobj(source, output)
                except RangeUnsupported:
                    log('Range requests unsupported; using a verified single download')
                    self.curl_request(url, '--max-time', '1800', '--output', assembled)
                if assembled.stat().st_size != size or digest(assembled) != expected:
                    raise ValueError('Downloaded archive failed SHA-256 verification')
                self.publish(assembled, archive)
                (temp / 'checksum').write_text(expected + '\n')
                self.publish(temp / 'checksum', checksum)
                log(f'Verified and cached {key} in {time.monotonic() - started:.1f}s')
                return archive

    def publish(self, source, target):
        fd, name = tempfile.mkstemp(prefix='.partial-', dir=self.cache)
        try:
            with os.fdopen(fd, 'wb') as output, open(source, 'rb') as stream:
                shutil.copyfileobj(stream, output)
            os.replace(name, target)
        finally:
            if os.path.exists(name):
                os.unlink(name)


def handler(cache):
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            route = urllib.parse.urlsplit(self.path).path
            try:
                if DOWNLOAD.fullmatch(route):
                    path = cache.archive(route)
                    self.send_response(200)
                    self.send_header('Content-Length', str(path.stat().st_size))
                    self.send_header('Content-Type', 'application/octet-stream')
                    self.end_headers()
                    with open(path, 'rb') as source:
                        shutil.copyfileobj(source, self.wfile)
                elif METADATA.fullmatch(route):
                    data = cache.curl_request(cache.upstream + route).encode()
                    self.send_response(200)
                    self.send_header('Content-Length', str(len(data)))
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(data)
                else:
                    self.send_error(404)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as error:
                log(f'{route}: {error}')
                self.send_error(502, 'VS Code download failed; see tunnel log')
    return Handler


def migrate_data(old, target):
    old, target = Path(old), Path(target)
    if old.is_dir() and not old.is_symlink():
        for process in Path('/proc').glob('[0-9]*/cmdline'):
            try:
                arguments = process.read_bytes().split(b'\0')
            except (FileNotFoundError, PermissionError, ProcessLookupError):
                continue
            editor = any(arg.endswith((b'/server-main.js', b'/bin/code-server')) for arg in arguments)
            if editor and any(str(old).encode() in arg for arg in arguments):
                raise RuntimeError(f'Editor process {process.parent.name} still uses {old}; close it before migrating')
        if target.exists():
            raise RuntimeError(f'Both {old} and {target} exist; merge their editor data before starting')
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.TemporaryDirectory(prefix='.vscode-data-', dir=target.parent) as temp:
            stage = Path(temp) / 'data'
            shutil.copytree(old, stage, symlinks=True)
            os.replace(stage, target)
        # Keep the original as a recovery copy. The legacy path points to the
        # persistent location so an old cached server command cannot lose data.
        backup = old.with_name(old.name + '.before-persistent-' + str(time.time_ns()))
        old.rename(backup)
        old.symlink_to(target, target_is_directory=True)
        log(f'Editor data migrated to {target}; backup: {backup}')
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    target.chmod(0o700)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', required=True)
    parser.add_argument('--local', required=True)
    parser.add_argument('--workers', type=int, default=32, choices=range(1, 33))
    parser.add_argument('--prefetch', action='store_true')
    parser.add_argument('--migrate-data', nargs=2, metavar=('OLD', 'PERSISTENT'))
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    os.umask(0o077)
    cache = Cache(args.cache, args.local, args.workers)
    if args.migrate_data:
        migrate_data(*args.migrate_data)
    if args.prefetch:
        import json
        version = json.loads(cache.curl_request(UPSTREAM + '/api/latest/server-linux-x64/stable'))['version']
        cache.archive(f'/commit:{version}/server-linux-x64/stable')
        return
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command:
        return
    # Keep the port stable across tunnel restarts: detached agent supervisors
    # inherit this URL and may remain alive after the tunnel process exits.
    port_file = cache.local / 'port'
    port = int(port_file.read_text()) if port_file.exists() else 0
    server = http.server.ThreadingHTTPServer(('127.0.0.1', port), handler(cache))
    port_file.write_text(str(server.server_port))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    env = os.environ.copy()
    env['VSCODE_CLI_UPDATE_URL'] = f'http://127.0.0.1:{server.server_port}'
    for name in ('NO_PROXY', 'no_proxy'):
        env[name] = ','.join(filter(None, [env.get(name), '127.0.0.1', 'localhost']))
    log('Parallel downloads enabled; archive cache: ' + str(cache.cache))
    child = subprocess.Popen(command, env=env)
    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, lambda sig, frame: child.send_signal(sig) if child.poll() is None else None)
    try:
        return child.wait()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    raise SystemExit(main())
