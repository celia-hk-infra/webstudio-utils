"""HKSTP setup/launch integration with fake tools and loopback-only egress."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TMUX = shutil.which('tmux')


class HkstpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='hkstp-test-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.home = self.base / 'shared-home'
        self.home.mkdir()
        (self.home / '.bashrc').write_text('# existing shared settings\nexport KEEP_ME=yes\n')
        self.repo = self.base / 'repo'
        for name in ('setup-hkstp.sh', 'scripts/hkstp.py', 'scripts/egress_supervisor.py',
                     'vendor/codex-local-egress/remote.sh', 'vendor/codex-local-egress/connection.py',
                     'vendor/codex-local-egress/devtunnel-auth.sh'):
            target = self.repo / name
            target.parent.mkdir(parents=True, exist_ok=True)
            source = ROOT / name
            if not source.exists():
                self.skipTest('Initialize the pinned egress submodule to run HKSTP integration tests')
            shutil.copyfile(source, target)
        self.bin = self.base / 'fake-bin'
        self.bin.mkdir()
        self.env = os.environ.copy()
        self.env.update(HOME=str(self.home), PATH=str(self.bin) + ':/usr/bin:/bin', TERM='xterm')
        for key in ('TMUX', 'BASH_ENV', 'ENV'):
            self.env.pop(key, None)
        self.executable('git', '#!/bin/sh\nexit 0\n')
        self.executable('node', '#!/bin/sh\nexit 0\n')
        self.executable('npm', '#!/bin/sh\necho "Unexpected npm download" >&2\nexit 1\n')
        if not TMUX:
            self.executable('tmux', '#!/bin/sh\nexit 1\n')
        self.executable('devtunnel', '''#!/usr/bin/env python3
import os, pathlib, socket, sys
state = pathlib.Path(os.environ['DEVTUNNELS_USER_STATE_DIR'])
args = sys.argv[1:]
if args == ['user', 'show']:
    print('Logged in' if (state / 'auth').exists() else 'Not logged in')
elif args[:2] == ['user', 'login']:
    (state / 'auth').write_text('test-auth')
elif args[:1] == ['connect']:
    values = dict(line.split('=', 1) for line in (state.parent / 'connection.env').read_text().splitlines())
    with socket.socket() as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(('127.0.0.1', int(values['PROXY_PORT'])))
        server.listen()
        while True:
            conn, _ = server.accept()
            with conn:
                data = conn.recv(4096).decode()
                if data == values['PROXY_AUTH']:
                    conn.sendall(b'ok')
                    conn.recv(1)  # Let the client close first, avoiding server TIME_WAIT.
else:
    sys.exit(2)
''')
        self.executable('curl', '''#!/usr/bin/env python3
import os, socket, urllib.parse
url = urllib.parse.urlparse(os.environ['HTTPS_PROXY'])
with socket.create_connection((url.hostname, url.port), timeout=2) as sock:
    sock.sendall((url.username + ':' + url.password).encode())
    assert sock.recv(10) == b'ok'
''')
        self.roots = []
        self.addCleanup(self.stop_sessions)

    def executable(self, name, content):
        path = self.bin / name
        path.write_text(content)
        path.chmod(0o700)

    def person(self, name):
        root = self.home / name
        codex = root / 'tools/codex/0.166.0/node_modules/.bin/codex'
        codex.parent.mkdir(parents=True)
        codex.write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys
state = pathlib.Path(os.environ['CODEX_HOME'])
if sys.argv[1:] != ['--version']:
    assert sys.argv[1] == '--no-daemon'
    del sys.argv[1]
if sys.argv[1:] == ['--version']:
    print('codex-test')
elif sys.argv[1:3] == ['login', 'status']:
    sys.exit(0 if (state / 'auth.json').exists() else 1)
elif sys.argv[1:3] == ['login', '--device-auth']:
    (state / 'auth.json').write_text('test-official-auth')
else:
    print(json.dumps({'args':sys.argv[1:], 'home':str(state), 'proxy':os.environ['HTTPS_PROXY'],
                     'egress':os.environ['EGRESS_STATE_DIR'], 'api_key':os.environ.get('OPENAI_API_KEY'),
                     'base_url':os.environ.get('OPENAI_BASE_URL')}))
''')
        codex.chmod(0o700)
        self.roots.append(root)
        return root

    def stop_sessions(self):
        if TMUX:
            for root in self.roots:
                digest = hashlib.sha256(os.fsencode(root)).hexdigest()[:20]
                subprocess.run([TMUX, '-L', 'hkstp-' + digest, 'send-keys', '-t', '=egress:0.0', 'C-c'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                launcher = root / 'bin/codex'
                if os.access(launcher, os.X_OK):
                    subprocess.run([str(launcher), '--egress', 'stop'], env=self.env, timeout=15,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def setup(self, root, name, *args, success=True):
        result = subprocess.run(['bash', str(self.repo / 'setup-hkstp.sh'), '--root', str(root),
                                 '--name', name, *map(str, args)], env=self.env,
                                capture_output=True, text=True, timeout=45)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    def connection(self, name, port=None):
        if port is None:
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
        path = self.base / (name + '.env')
        path.write_text('PROXY_PORT={}\nPROXY_AUTH={}:abcdef012345\nTUNNEL_ID={}-tunnel\n'.format(port, name, name))
        return path

    def launch(self, root, *args, env=None, success=True):
        result = subprocess.run([str(root / 'bin/codex'), *args], env=env or self.env,
                                capture_output=True, text=True, timeout=35)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    def test_two_aliases_reruns_and_quoted_paths(self):
        bob = self.person("bob's space $dollar")
        alice = self.person('alice')
        self.setup(bob, 'bob-codex', '--defer-egress')
        self.setup(alice, 'alice-codex', '--defer-egress')
        config = bob / '.hkstp/codex/config.toml'
        config.write_text('model = "user-choice"\n  cli_auth_credentials_store = "keyring"\n  [projects."/example"]\ntrust_level = "trusted"\n')
        (bob / '.hkstp/codex/auth.json').write_text('keep-bob-auth')
        before = (self.home / '.bashrc').read_text()
        self.setup(bob, 'bob-codex', '--defer-egress')
        self.assertEqual((self.home / '.bashrc').read_text(), before)
        self.assertIn('# existing shared settings\nexport KEEP_ME=yes', before)
        self.assertEqual(before.count('alias bob-codex='), 1)
        self.assertIn('alias alice-codex=', before)
        self.assertIn('model = "user-choice"', config.read_text())
        self.assertIn('[projects."/example"]', config.read_text())
        self.assertEqual(config.read_text().count('cli_auth_credentials_store'), 1)
        self.assertEqual((bob / '.hkstp/codex/auth.json').read_text(), 'keep-bob-auth')
        self.assertFalse((self.home / '.codex').exists())
        result = subprocess.run(['bash', '--noprofile', '--norc', '-c',
                                 'shopt -s expand_aliases; source ~/.bashrc\neval "bob-codex --version"'],
                                env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('codex-test', result.stdout)

    def test_alias_collision_preserves_first_person(self):
        bob, alice = self.person('bob'), self.person('alice')
        self.setup(bob, 'bob-codex', '--defer-egress')
        before = (self.home / '.bashrc').read_text()
        result = self.setup(alice, 'bob-codex', '--defer-egress', success=False)
        self.assertIn('already defined', result.stderr)
        self.assertEqual((self.home / '.bashrc').read_text(), before)
        self.assertFalse((alice / 'bin/codex').exists())

    def test_rejects_existing_alias_and_unmanaged_launcher(self):
        bob = self.person('bob')
        (self.home / '.bashrc').write_text('alias bob-codex="echo existing"\n')
        self.setup(bob, 'bob-codex', '--defer-egress', success=False)
        (self.home / '.bashrc').write_text('')
        (bob / 'bin').mkdir()
        (bob / 'bin/codex').write_text('keep this')
        self.setup(bob, 'bob-codex', '--defer-egress', success=False)
        self.assertEqual((bob / 'bin/codex').read_text(), 'keep this')

    def test_rejects_alias_in_bash_aliases(self):
        bob = self.person('bob')
        (self.home / '.bash_aliases').write_text('alias bob-codex="echo existing"\n')
        result = self.setup(bob, 'bob-codex', '--defer-egress', success=False)
        self.assertIn('already defined in ~/.bash_aliases', result.stderr)
        self.assertFalse((bob / 'bin/codex').exists())

    def test_invalid_config_is_not_executed_or_printed(self):
        bob = self.person('bob')
        incoming = self.base / 'invalid.env'
        secret = 'not-for-output'
        incoming.write_text('PROXY_AUTH=$(touch {})\n{}'.format(self.base / 'executed', secret))
        result = self.setup(bob, 'bob-codex', '--connection', incoming, success=False)
        self.assertNotIn(secret, result.stdout + result.stderr)
        self.assertFalse((self.base / 'executed').exists())

    def test_alias_preserves_bashrc_symlink(self):
        target = self.home / 'actual-bashrc'
        (self.home / '.bashrc').rename(target)
        (self.home / '.bashrc').symlink_to(target)
        self.setup(self.person('bob'), 'bob-codex', '--defer-egress')
        self.assertTrue((self.home / '.bashrc').is_symlink())
        self.assertIn('alias bob-codex=', target.read_text())

    def test_missing_egress_never_launches_codex(self):
        bob = self.person('bob')
        self.setup(bob, 'bob-codex', '--defer-egress')
        result = self.launch(bob, 'login', '--device-auth', success=False)
        self.assertIn('invalid connection.env', result.stderr)
        self.assertFalse((bob / '.hkstp/codex/auth.json').exists())

    def test_failed_install_is_not_published_and_can_retry(self):
        bob = self.person('bob')
        self.setup(bob, 'bob-codex', '--defer-egress')
        original = (bob / '.hkstp/instance.json').read_text()
        self.executable('npm', '''#!/usr/bin/env python3
import pathlib, sys
stage = pathlib.Path(sys.argv[sys.argv.index('--prefix') + 1])
(stage / 'partial-download').write_text('not ready')
sys.exit(1)
''')
        self.setup(bob, 'bob-codex', '--defer-egress', '--codex-version', '0.166.1', success=False)
        self.assertFalse((bob / 'tools/codex/0.166.1').exists())
        self.assertEqual((bob / '.hkstp/instance.json').read_text(), original)
        self.executable('npm', '''#!/usr/bin/env python3
import pathlib, sys
stage = pathlib.Path(sys.argv[sys.argv.index('--prefix') + 1])
binary = stage / 'node_modules/.bin/codex'
binary.parent.mkdir(parents=True)
binary.write_text('#!/bin/sh\\necho new-codex-version\\n')
binary.chmod(0o700)
''')
        self.setup(bob, 'bob-codex', '--defer-egress', '--codex-version', '0.166.1')
        self.assertTrue((bob / 'tools/codex/0.166.1/node_modules/.bin/codex').exists())
        self.assertIn('new-codex-version', self.launch(bob, '--version').stdout)

    def test_concurrent_setups_preserve_both_aliases(self):
        bob, alice = self.person('bob'), self.person('alice')
        commands = [subprocess.Popen(['bash', str(self.repo / 'setup-hkstp.sh'), '--root', str(root),
                                      '--name', name, '--defer-egress'], env=self.env,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    for root, name in ((bob, 'bob-codex'), (alice, 'alice-codex'))]
        for process in commands:
            stdout, stderr = process.communicate(timeout=30)
            self.assertEqual(process.returncode, 0, stdout + stderr)
        text = (self.home / '.bashrc').read_text()
        self.assertEqual(text.count('alias bob-codex='), 1)
        self.assertEqual(text.count('alias alice-codex='), 1)

    @unittest.skipUnless(TMUX, 'tmux required for simultaneous egress integration')
    def test_two_live_egress_sessions_and_environment_isolation(self):
        bob, alice = self.person('bob'), self.person('alice')
        self.setup(bob, 'bob-codex', '--connection', self.connection('bob'), '--provider', 'github')
        self.setup(alice, 'alice-codex', '--connection', self.connection('alice'), '--provider', 'microsoft')
        polluted = dict(self.env, CODEX_HOME=str(alice / '.hkstp/codex'), OPENAI_API_KEY='wrong-key',
                        OPENAI_BASE_URL='https://wrong.invalid', HTTPS_PROXY='http://wrong.invalid',
                        EGRESS_STATE_DIR=str(alice / '.hkstp/egress'), DEVTUNNELS_USER_STATE_DIR='/wrong')
        result = json.loads(self.launch(bob, 'resume', 'some session', env=polluted).stdout)
        self.assertEqual(result['home'], str(bob / '.hkstp/codex'))
        self.assertEqual(result['egress'], str(bob / '.hkstp/egress'))
        self.assertIn('bob:abcdef012345@127.0.0.1:', result['proxy'])
        self.assertEqual(result['args'], ['resume', 'some session'])
        self.assertIsNone(result['api_key'])
        self.assertIsNone(result['base_url'])
        for root in (bob, alice):
            self.assertTrue((root / '.hkstp/codex/auth.json').exists())
            self.assertTrue((root / '.hkstp/egress/.devtunnel/auth').exists())
        self.launch(bob, '--egress', 'stop')
        self.launch(bob, '--egress', 'status', success=False)
        self.launch(alice, '--egress', 'status')
        self.launch(bob, 'resume')  # Automatically starts only Bob's connection.
        self.launch(alice, '--egress', 'status')
        self.setup(bob, 'bob-codex', '--connection', self.connection('newbob'), '--skip-login', success=False)
        self.launch(bob, '--egress', 'status')

    @unittest.skipUnless(TMUX, 'tmux required for port collision integration')
    def test_port_collision_does_not_stop_other_tunnel(self):
        bob, alice = self.person('bob'), self.person('alice')
        bob_connection = self.connection('bob')
        port = int(bob_connection.read_text().splitlines()[0].split('=')[1])
        self.setup(bob, 'bob-codex', '--connection', bob_connection, '--provider', 'github')
        result = self.setup(alice, 'alice-codex', '--connection', self.connection('alice', port),
                            '--provider', 'github', success=False)
        self.assertIn('already occupied', result.stderr)
        self.launch(bob, '--egress', 'status')
        self.assertFalse((alice / '.hkstp/codex/auth.json').exists())
