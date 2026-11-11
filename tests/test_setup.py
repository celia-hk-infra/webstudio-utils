"""Run with python -m unittest discover -s tests -v; no downloads or real keys."""
import errno
import json
import os
from pathlib import Path
import pty
import select
import signal
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
KEY = 'test-openlux-secret'


class Terminal:
    def __init__(self, command, env):
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.execvpe('bash', ['bash', '--noprofile', '--norc', '-c', command], env)
        self.output = b''
        self.status = None

    def expect(self, text):
        end = time.monotonic() + 10
        while text.encode() not in self.output:
            if time.monotonic() > end:
                raise AssertionError(f'Terminal did not show {text!r}: {self.output!r}')
            if select.select([self.fd], [], [], 0.1)[0]:
                try:
                    self.output += os.read(self.fd, 65536)
                except OSError as error:
                    if error.errno != errno.EIO:
                        raise
                    raise AssertionError(f'Terminal exited before {text!r}: {self.output!r}')

    def send(self, text):
        os.write(self.fd, text)

    def finish(self):
        end = time.monotonic() + 10
        while time.monotonic() < end:
            pid, status = os.waitpid(self.pid, os.WNOHANG)
            if pid:
                self.status = os.waitstatus_to_exitcode(status)
                return self.status
            time.sleep(0.02)
        raise AssertionError('Terminal did not exit')

    def close(self):
        if self.status is None:
            try:
                os.kill(self.pid, signal.SIGKILL)
                os.waitpid(self.pid, 0)
            except ProcessLookupError:
                pass
        os.close(self.fd)


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='webstudio-setup-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.persist = self.root / 'persist'
        self.state = self.persist / '.webstudio-agent-home'
        self.local = self.root / 'local'
        self.home = self.root / 'home'
        self.home.mkdir()
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith(('WEBSTUDIO_', 'ANTHROPIC_', 'CLAUDE_', 'OPENLUX_', 'CODEX_'))}
        self.env.update(HOME=str(self.home), WEBSTUDIO_PERSIST_ROOT=str(self.persist),
                        WEBSTUDIO_LOCAL_DIR=str(self.local), TERM='xterm')
        self.executable(self.persist / 'tools/gh/2.103.3/bin/gh', '#!/bin/sh\nexit 0\n')
        self.executable(self.persist / 'tools/claude/2.1.322/node_modules/.bin/claude', '#!/bin/sh\nexit 0\n')
        self.executable(self.persist / 'tools/codex/0.166.0/node_modules/.bin/codex', '''#!/usr/bin/env python3
import json, os, pathlib, sys
assert sys.argv[1:] == ['login', '--with-api-key']
assert 'OPENLUX_API_KEY' not in os.environ
p = pathlib.Path(os.environ['CODEX_HOME']) / 'auth.json'
p.write_text(json.dumps({'auth_mode':'apikey', 'OPENAI_API_KEY':sys.stdin.read()}))
''')

    def executable(self, path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        path.chmod(0o700)

    def run_setup(self, agents='both', key=KEY, success=True):
        env = self.env.copy()
        if key is not None:
            env['OPENLUX_API_KEY'] = key
        result = subprocess.run(['bash', str(ROOT / 'setup_container.sh'), '--agents', agents, '--skip-vscode'],
                                env=env, capture_output=True, text=True)
        self.assertNotIn(KEY, result.stdout + result.stderr)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    def terminal(self, script):
        terminal = Terminal(script, self.env)
        self.addCleanup(terminal.close)
        return terminal

    def test_menu_navigation_toggle_and_cancel(self):
        prefix = f'set -eu; source "{ROOT}/scripts/setup_prompts.sh"; skip_codex=0; skip_claude=0; '
        terminal = self.terminal(prefix + 'choose_agents; printf "RESULT:%s:%s" "$skip_codex" "$skip_claude"')
        terminal.expect('[x] Claude Code')
        terminal.send(b'\x1b[B \x1b[A \x1b[B \r')
        terminal.expect('RESULT:1:0')
        self.assertEqual(terminal.finish(), 0)
        cancel = self.terminal(prefix + 'choose_agents; printf UNEXPECTED')
        cancel.expect('[x] Claude Code')
        cancel.send(b'q')
        cancel.expect('Setup cancelled.')
        self.assertEqual(cancel.finish(), 130)
        self.assertNotIn(b'UNEXPECTED', cancel.output)

    def test_interactive_setup_hides_key(self):
        terminal = self.terminal(f'bash "{ROOT}/setup_container.sh" --skip-vscode')
        terminal.expect('[x] Claude Code')
        terminal.send(b'\r')
        terminal.expect('OpenLux API key (input hidden): ')
        terminal.send(b'\r')
        terminal.expect('A key is required')
        terminal.send(KEY.encode() + b'\r')
        terminal.expect('Selected agents are configured.')
        self.assertEqual(terminal.finish(), 0)
        self.assertNotIn(KEY.encode(), terminal.output)
        self.assert_credentials()

    def assert_credentials(self):
        codex = self.state / '.codex/auth.json'
        claude = self.state / '.claude/settings.json'
        self.assertEqual(json.loads(codex.read_text())['OPENAI_API_KEY'], KEY)
        data = json.loads(claude.read_text())
        self.assertEqual(data['env']['ANTHROPIC_AUTH_TOKEN'], KEY)
        self.assertEqual(data['env']['ANTHROPIC_BASE_URL'], 'https://api.openlux.ai')
        self.assertTrue(json.loads((claude.parent / '.claude.json').read_text())['hasCompletedOnboarding'])
        for path in (codex, claude, claude.parent / '.claude.json'):
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_both_and_rerun_preserve_preferences(self):
        self.run_setup()
        self.assert_credentials()
        settings = self.state / '.claude/settings.json'
        data = json.loads(settings.read_text())
        data['model'] = 'user-model'
        settings.write_text(json.dumps(data))
        config = self.state / '.codex/config.toml'
        config.write_text(config.read_text() + '\n[projects."/example"]\ntrust_level = "trusted"\n')
        self.run_setup(key=None)
        self.assert_credentials()
        self.assertEqual(json.loads(settings.read_text())['model'], 'user-model')
        self.assertEqual(config.read_text().count('openai_base_url ='), 1)
        self.assertEqual(config.read_text().count('cli_auth_credentials_store ='), 1)
        self.assertIn('[projects."/example"]', config.read_text())
        terminal = self.terminal(f'bash "{ROOT}/setup_container.sh" --agents both --skip-vscode')
        terminal.expect('Enter keeps saved credentials')
        terminal.send(b'\r')
        terminal.expect('Selected agents are configured.')
        self.assertEqual(terminal.finish(), 0)
        self.assert_credentials()

    def test_missing_key_fails_before_install(self):
        result = self.run_setup(key=None, success=False)
        self.assertIn('Set OPENLUX_API_KEY', result.stderr)
        self.assertFalse(self.local.exists())

    def test_single_agent_and_none(self):
        self.run_setup(agents='none', key=None)
        self.assertFalse((self.state / '.codex/auth.json').exists())
        self.run_setup(agents='claude')
        self.assertFalse((self.state / '.codex/auth.json').exists())
        self.run_setup(agents='codex')
        self.assert_credentials()

    def test_invalid_key_and_invalid_state_preserve_files(self):
        self.run_setup(key='invalid key', success=False)
        self.run_setup()
        settings = self.state / '.claude/settings.json'
        before = settings.read_bytes()
        state = settings.parent / '.claude.json'
        state.write_text('{"secret":"' + KEY + '", BROKEN')
        result = subprocess.run(['node', str(ROOT / 'scripts/configure_claude.cjs'), str(settings), '--key-stdin'],
                                input='replacement', text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(KEY, result.stderr)
        self.assertEqual(settings.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
