"""Run with python -m unittest discover -s tests -v; no downloads or real keys."""
import errno
import json
import os
from pathlib import Path
import pty
import re
import select
import signal
import shutil
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
KEY = 'test-openlux-secret'
ANSI = re.compile(rb'\x1b\[[0-9;?]*[A-Za-z]')
DOWN = b'\x1b[B'


class Terminal:
    def __init__(self, command, env):
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.execvpe('bash', ['bash', '--noprofile', '--norc', '-c', command], env)
        self.output = b''
        self.status = None

    def expect(self, text):
        end = time.monotonic() + 10
        while text.encode() not in ANSI.sub(b'', self.output):
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
        self.tunnel = self.root / 'container-work/.webstudio-tunnel'
        self.home = self.root / 'home'
        self.home.mkdir()
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith(('WEBSTUDIO_', 'ANTHROPIC_', 'CLAUDE_', 'OPENLUX_', 'CODEX_', 'GH_', 'GITHUB_', 'VSCODE_'))}
        self.env.update(HOME=str(self.home), WEBSTUDIO_PERSIST_ROOT=str(self.persist),
                        WEBSTUDIO_LOCAL_DIR=str(self.local), WEBSTUDIO_TUNNEL_DIR=str(self.tunnel), TERM='xterm')
        self.executable(self.persist / 'tools/tmux/bin/tmux', '#!/bin/sh\nexit 0\n')
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

    def run_setup(self, agents='both', key=KEY, success=True, provider='--openlux'):
        env = self.env.copy()
        if key is not None:
            env['OPENLUX_API_KEY'] = key
        result = subprocess.run(['bash', str(ROOT / 'setup_tools.sh'), '--agents', agents, '--skip-vscode', provider],
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

    def mock_github_auth(self):
        self.executable(self.persist / 'tools/gh/2.103.3/bin/gh', '''#!/usr/bin/env python3
import os, pathlib, sys
state = pathlib.Path(os.environ['GH_CONFIG_DIR'])
args = sys.argv[1:]
with (state / 'calls').open('a') as log:
    log.write(' '.join(args) + '\\n')
if args[:2] == ['auth', 'status']:
    sys.exit(0 if (state / 'hosts.yml').exists() or os.environ.get('GH_TOKEN') else 1)
if args[:2] == ['auth', 'login']:
    assert '--web' in args and '--insecure-storage' in args
    if os.environ.get('TEST_GH_LOGIN_FAIL'):
        sys.exit(1)
    (state / 'hosts.yml').write_text('test credential')
if args[:2] == ['auth', 'setup-git']:
    (pathlib.Path.home() / '.gitconfig').write_text('test credential helper')
''')

    def test_github_login_survives_new_home(self):
        self.mock_github_auth()
        terminal = self.terminal(f'bash "{ROOT}/setup_tools.sh" --agents none --skip-vscode')
        terminal.expect('Which optional tools should be installed?')
        terminal.send(b'\r')
        terminal.expect('GitHub authentication ready')
        self.assertEqual(terminal.finish(), 0)
        credentials = self.state / 'gh/hosts.yml'
        self.assertEqual(credentials.stat().st_mode & 0o777, 0o600)
        self.assertEqual(credentials.parent.stat().st_mode & 0o777, 0o700)
        replacement = self.root / 'replacement-home'
        replacement.mkdir()
        self.env['HOME'] = str(replacement)
        self.run_setup(agents='none', key=None)
        calls = (self.state / 'gh/calls').read_text()
        self.assertEqual(calls.count('auth login'), 1)
        self.assertEqual(calls.count('auth setup-git'), 2)
        self.assertTrue((replacement / '.gitconfig').exists())
        self.assertTrue((self.state / '.setup-complete').exists())

    def test_github_unattended_requires_auth_or_explicit_skip(self):
        self.mock_github_auth()
        result = self.run_setup(agents='none', key=None, success=False)
        self.assertIn('GitHub login required', result.stderr)
        self.assertNotIn('auth login', (self.state / 'gh/calls').read_text())
        result = subprocess.run(['bash', str(ROOT / 'setup_tools.sh'), '--agents', 'none',
                                 '--skip-vscode', '--skip-gh-auth'], env=self.env, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.env['GH_TOKEN'] = 'test-github-token'
        self.run_setup(agents='none', key=None)
        self.assertTrue((self.home / '.gitconfig').exists())
        self.assertFalse((self.state / 'gh/hosts.yml').exists())

    def test_github_login_failure_stops_setup(self):
        self.mock_github_auth()
        self.env['TEST_GH_LOGIN_FAIL'] = '1'
        terminal = self.terminal(f'bash "{ROOT}/setup_tools.sh" --agents none --skip-vscode')
        terminal.expect('Which optional tools should be installed?')
        terminal.send(b'\r')
        terminal.expect('Sign in to GitHub.')
        self.assertNotEqual(terminal.finish(), 0)
        self.assertFalse((self.home / '.gitconfig').exists())
        self.assertFalse((self.state / '.setup-complete').exists())

    def test_optional_tools_none_skips_install_and_auth(self):
        shutil.rmtree(self.persist / 'tools/tmux')
        shutil.rmtree(self.persist / 'tools/gh')
        terminal = self.terminal(f'bash "{ROOT}/setup_tools.sh" --agents none --skip-vscode')
        terminal.expect('Which optional tools should be installed?')
        terminal.send(b'a\r')
        terminal.expect('Setup complete')
        self.assertEqual(terminal.finish(), 0)
        self.assertFalse((self.persist / 'tools/tmux').exists())
        self.assertFalse((self.persist / 'tools/gh').exists())
        self.assertFalse((self.home / '.gitconfig').exists())

    def test_optional_tools_cli_selections(self):
        for flags, gh_selected, tmux_selected in [
            (['--tools', 'none'], False, False),
            (['--tools', 'gh'], True, False),
            (['--tools', 'tmux'], False, True),
            (['--skip-gh', '--skip-tmux'], False, False),
        ]:
            result = subprocess.run(['bash', str(ROOT / 'setup_tools.sh'), '--agents', 'none',
                                     '--skip-vscode', *flags], env=self.env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual('GitHub CLI' in result.stdout, gh_selected)
            self.assertEqual(str(self.persist / 'tools/tmux/bin/tmux') in result.stdout, tmux_selected)

    def test_tmux_install_and_reuse(self):
        (self.persist / 'tools/tmux/bin/tmux').unlink()
        conda = self.root / 'conda'
        self.executable(conda, '''#!/usr/bin/env python3
import pathlib, sys
prefix = pathlib.Path(sys.argv[sys.argv.index('--prefix') + 1])
(prefix / 'conda-called').touch()
binary = prefix / 'bin/tmux'
binary.write_text('#!/bin/sh\\nexit 0\\n')
binary.chmod(0o700)
''')
        self.env['CONDA_EXE'] = str(conda)
        self.run_setup(agents='none', key=None)
        self.assertTrue((self.persist / 'tools/tmux/conda-called').exists())
        conda.unlink()
        self.run_setup(agents='none', key=None)
        result = subprocess.run(['bash', '-c', f'source "{ROOT}/shell/init.sh"; command -v tmux'],
                                env=self.env, text=True, capture_output=True)
        self.assertEqual(result.stdout.strip(), str(self.persist / 'tools/tmux/bin/tmux'))

    def test_init_decline_and_noninteractive_guidance(self):
        terminal = self.terminal(f'source "{ROOT}/shell/init.sh"; echo SHELL_ALIVE')
        terminal.expect('Run tools setup now?')
        terminal.send(b'n\r')
        terminal.expect('SHELL_ALIVE')
        self.assertEqual(terminal.finish(), 0)
        self.assertFalse(self.local.exists())
        result = subprocess.run(['bash', '-c', f'source "{ROOT}/shell/init.sh"'],
                                env=self.env, text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('setup_tools.sh', result.stderr)

    def test_tunnel_prompt_and_init_accept(self):
        repo = self.mock_tunnel_repo()
        self.env['OPENLUX_API_KEY'] = KEY
        terminal = self.terminal(f'source "{repo}/shell/init.sh"; printf "LOADED:%s" "$CODEX_HOME"')
        terminal.expect('Run tools setup now?')
        terminal.send(b'y\r')
        terminal.expect('Anthropic Claude Code')
        terminal.send(b'\r')
        terminal.expect('Which optional tools should be installed?')
        terminal.send(b'\r')
        terminal.expect('VS Code tunnel name')
        terminal.send(b'\r')
        terminal.expect('Start the VS Code tunnel when setup finishes?')
        terminal.send(b'\r')
        terminal.expect('Configure personal egress now?')
        terminal.send(b'n\r')
        terminal.expect('Configure OpenLux as an optional backup?')
        terminal.send(b'y\r')
        terminal.expect('LOADED:' + str(self.state / '.codex'))
        self.assertEqual(terminal.finish(), 0)
        calls = self.persist / 'tunnel-calls'
        self.assertEqual(calls.read_text().splitlines(), ['--install-only', '--background'])
        self.assertTrue((self.state / '.setup-complete').exists())
        self.assertRegex((self.tunnel / 'name').read_text(), r'^webstudio-[0-9a-f]{10}\n$')
        terminal = self.terminal(f'bash "{repo}/setup_tools.sh" --agents none')
        terminal.expect('Which optional tools should be installed?')
        terminal.send(b'\r')
        terminal.expect('VS Code tunnel name')
        terminal.send(b'\r')
        terminal.expect('Start the VS Code tunnel when setup finishes?')
        terminal.send(DOWN + DOWN + b'\r')
        terminal.expect('start_vscode_tunnel.sh --background')
        self.assertEqual(terminal.finish(), 0)
        self.assertEqual(calls.read_text().splitlines(), ['--install-only', '--background', '--install-only'])
        for flags, expected in [([], ['--install-only']), (['--start-tunnel'], ['--install-only', '--background']),
                                (['--start-tunnel=foreground'], ['--install-only', 'started']),
                                (['--no-start-tunnel'], ['--install-only'])]:
            calls.write_text('')
            result = subprocess.run(['bash', str(repo / 'setup_tools.sh'), '--agents', 'none', *flags],
                                    env=self.env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(calls.read_text().splitlines(), expected)
        (self.state / '.setup-complete').unlink()
        terminal = self.terminal(f'source "{repo}/shell/init.sh"')
        terminal.expect('Run tools setup now?')
        terminal.send(b'n\r')
        self.assertEqual(terminal.finish(), 0)


    def test_menu_navigation_toggle_and_cancel(self):
        prefix = (f'set -eu; source "{ROOT}/scripts/ui.sh"; ui_setup; source "{ROOT}/scripts/setup_prompts.sh"; '
                  'skip_codex=0; skip_claude=0; ')
        terminal = self.terminal(prefix + 'choose_agents; printf "RESULT:%s:%s" "$skip_codex" "$skip_claude"')
        terminal.expect('Anthropic Claude Code')
        terminal.send(b'\x1b[B \x1b[A \x1b[B \r')
        terminal.expect('RESULT:1:0')
        self.assertEqual(terminal.finish(), 0)
        terminal = self.terminal(prefix + 'choose_agents; printf "RESULT:%s:%s" "$skip_codex" "$skip_claude"')
        terminal.expect('Anthropic Claude Code')
        terminal.send(b'a\r')
        terminal.expect('None (tools only)')
        terminal.expect('RESULT:1:1')
        self.assertEqual(terminal.finish(), 0)
        cancel = self.terminal(prefix + 'choose_agents; printf UNEXPECTED')
        cancel.expect('Anthropic Claude Code')
        cancel.send(b'q')
        cancel.expect('Setup cancelled.')
        self.assertEqual(cancel.finish(), 130)
        self.assertNotIn(b'UNEXPECTED', cancel.output)

    def test_interactive_setup_hides_key(self):
        terminal = self.terminal(f'bash "{ROOT}/setup_tools.sh" --skip-vscode')
        terminal.expect('Anthropic Claude Code')
        terminal.send(b'\r')
        terminal.expect('Which optional tools should be installed?')
        terminal.send(b'\r')
        terminal.expect('Configure personal egress now?')
        terminal.send(b'n\r')
        terminal.expect('Configure OpenLux as an optional backup?')
        terminal.send(b'y\r')
        terminal.expect('OpenLux API key (input hidden)')
        terminal.send(b'\r')
        terminal.expect('A key is required')
        terminal.send(KEY.encode() + b'\r')
        terminal.expect(f'Saved for the selected agents ({len(KEY)} characters)')
        terminal.expect('Setup complete')
        self.assertEqual(terminal.finish(), 0)
        self.assertNotIn(KEY.encode(), terminal.output)
        self.assert_credentials()

    def mock_tunnel_repo(self):
        repo = self.root / 'repo'
        shutil.copytree(ROOT, repo, ignore=shutil.ignore_patterns('.git', '__pycache__'))
        self.executable(repo / 'scripts/start_vscode_tunnel.sh', '''#!/bin/sh
printf '%s\\n' "${1:-started}" >> "$WEBSTUDIO_PERSIST_ROOT/tunnel-calls"
''')
        return repo

    def test_init_offers_new_or_stopped_tunnel(self):
        repo = self.mock_tunnel_repo()
        self.state.mkdir(parents=True, exist_ok=True)
        (self.state / '.setup-complete').write_text(str(repo))
        self.executable(self.persist / 'tools/tmux/bin/tmux', '#!/bin/sh\nexit 1\n')
        for saved, prompt in [(None, 'Create and start a VS Code tunnel'),
                              ('saved-name', 'Resume VS Code tunnel saved-name')]:
            if saved:
                self.tunnel.mkdir(parents=True, exist_ok=True)
                (self.tunnel / 'name').write_text(saved)
            terminal = self.terminal(f'source "{repo}/shell/init.sh"; echo READY')
            terminal.expect(prompt)
            terminal.send(b'y\r')
            terminal.expect('READY')
            self.assertEqual(terminal.finish(), 0)
        self.assertEqual((self.persist / 'tunnel-calls').read_text().splitlines(),
                         ['--background', '--background'])

    def test_fresh_tunnel_name_prompt(self):
        terminal = self.terminal(
            f'source "{ROOT}/scripts/tunnel_config.sh"; webstudio_ensure_tunnel_name')
        terminal.expect('VS Code tunnel name')
        terminal.send(b'-invalid\r')
        terminal.expect('Use up to 20')
        terminal.send(b'my-container\r')
        self.assertEqual(terminal.finish(), 0)
        self.assertEqual((self.tunnel / 'name').read_text(), 'my-container\n')

    def test_init_skips_connected_tunnel_prompt(self):
        repo = self.mock_tunnel_repo()
        self.state.mkdir(parents=True, exist_ok=True)
        (self.state / '.setup-complete').write_text(str(repo))
        self.executable(self.local / 'vscode/bin/code',
                        '''#!/bin/sh
echo '{"tunnel":{"tunnel":"Connected"}}'
''')
        terminal = self.terminal(f'source "{repo}/shell/init.sh"; echo READY')
        terminal.expect('already connected')
        terminal.expect('READY')
        self.assertEqual(terminal.finish(), 0)
        self.assertFalse((self.persist / 'tunnel-calls').exists())

    def test_tunnel_name_prompt_validates_input(self):
        name_file = self.tunnel / 'name'
        repo = self.mock_tunnel_repo()
        terminal = self.terminal(f'bash "{repo}/setup_tools.sh" --agents none --no-start-tunnel')
        terminal.expect('Which optional tools should be installed?')
        terminal.send(b'\r')
        terminal.expect('VS Code tunnel name')
        terminal.expect('webstudio-')
        # Invalid characters are rejected, input stops at 20, and a leading hyphen cannot be submitted.
        terminal.send(b'-')
        terminal.send(b'\r')
        terminal.expect('must start with a letter or digit')
        terminal.send(b'\x7fmy_box.' + b'x' * 30 + b'\r')
        terminal.expect('VS Code tunnel name')
        terminal.expect('mybox' + 'x' * 15)
        terminal.expect('Setup complete')
        self.assertEqual(terminal.finish(), 0)
        self.assertEqual(name_file.read_text(), 'mybox' + 'x' * 15 + '\n')
        result = subprocess.run(['bash', str(ROOT / 'setup_tools.sh'), '--agents', 'none', '--tunnel-name',
                                 'a' * 21], env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('up to 20 characters', result.stderr)

    def test_background_tunnel_lifecycle(self):
        real_tmux = shutil.which('tmux') or '/home/ma-user/work/dataset/demo-user/tools/tmux/bin/tmux'
        if not os.access(real_tmux, os.X_OK):
            self.skipTest('tmux is not installed')
        tmux = self.persist / 'tools/tmux/bin/tmux'
        tmux.unlink()
        tmux.symlink_to(real_tmux)
        self.env.pop('TMUX', None)
        self.env['TMUX_TMPDIR'] = str(self.root)
        self.addCleanup(subprocess.run, [real_tmux, 'kill-server'], env=self.env, capture_output=True)
        vscode = self.root / 'vscode'
        for runtime_file in ('runtime/bin/patchelf', 'runtime/lib/libstdc++.so.6'):
            self.executable(vscode / runtime_file, '')
        self.executable(vscode / 'local/bin/code', '''#!/usr/bin/env bash
for ((i = 1; i < $#; i++)); do
  next=$((i + 1))
  [[ ${!i} == --cli-data-dir ]] && data=${!next}
  [[ ${!i} == --name ]] && name=${!next}
done
case "$1 ${2:-}" in
  'tunnel user')
    if [[ $3 == show ]]; then [[ -f $data/token ]]; exit; fi
    echo 'use code TEST-CODE'; touch "$data/token"; exit 0 ;;
  'tunnel status')
    if [[ -f $data/connected ]]; then echo '{"tunnel":{"tunnel":"Connected"}}'; else echo '{"tunnel":null}'; fi
    exit 0 ;;
  'tunnel kill') rm -f "$data/connected"; exit 0 ;;
esac
if [[ $1 == tunnel ]]; then
  trap 'rm -f "$data/connected"; exit 0' HUP TERM
  echo "  Open: https://vscode.dev/tunnel/$name$PWD"
  touch "$data/connected"
  while :; do sleep 0.1; done
fi
echo 'code 1.0.0'
''')
        self.env.update(VSCODE_INSTALL_DIR=str(vscode), VSCODE_LOCAL_DIR=str(vscode / 'local'))
        self.tunnel.mkdir(parents=True)
        self.env['WEBSTUDIO_TUNNEL_NAME'] = 'test-name'
        self.local.mkdir()
        self.state.mkdir(parents=True, exist_ok=True)
        (self.state / '.setup-complete').write_text(f'{ROOT}\n')
        script = str(ROOT / 'scripts/start_vscode_tunnel.sh')
        terminal = self.terminal(f'cd "{self.root}" && bash "{script}" --background')
        terminal.expect('use code TEST-CODE')
        terminal.expect('VS Code tunnel is running in the background')
        terminal.expect(f'https://vscode.dev/tunnel/test-name{self.root}')
        self.assertEqual(terminal.finish(), 0)

        def run(*args):
            return subprocess.run(['bash', script, *args], env=self.env, text=True, capture_output=True)
        status = run('--status')
        self.assertEqual(status.returncode, 0, status.stdout + status.stderr)
        self.assertIn('tmux attach -t vscode-tunnel', status.stdout)
        again = run('--background')
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertIn('already running', again.stdout)
        self.assertEqual(run('--stop').returncode, 0)
        self.assertNotEqual(subprocess.run([real_tmux, 'has-session', '-t', '=vscode-tunnel'],
                                           env=self.env, capture_output=True).returncode, 0)
        self.assertEqual(run('--status').returncode, 1)

    def assert_credentials(self):
        codex = self.state / 'providers/openlux/codex/auth.json'
        claude = self.state / 'providers/openlux/claude/settings.json'
        self.assertEqual(json.loads(codex.read_text())['OPENAI_API_KEY'], KEY)
        data = json.loads(claude.read_text())
        self.assertEqual(data['env']['ANTHROPIC_AUTH_TOKEN'], KEY)
        self.assertEqual(data['env']['ANTHROPIC_BASE_URL'], 'https://api.openlux.ai')
        self.assertTrue(json.loads((claude.parent / '.claude.json').read_text())['hasCompletedOnboarding'])
        for path in (codex, claude, claude.parent / '.claude.json'):
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_tunnel_identity_is_container_local(self):
        self.run_setup(agents='none', key=None)
        original = (self.tunnel / 'name').read_text()
        other = self.root / 'other-container/.webstudio-tunnel'
        env = dict(self.env, WEBSTUDIO_TUNNEL_DIR=str(other))
        command = (f'source "{ROOT}/shell/init.sh" && '
                   f'source "{ROOT}/scripts/tunnel_config.sh" && webstudio_ensure_tunnel_name')
        result = subprocess.run(['bash', '-c', command], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotEqual(original, (other / 'name').read_text())
        self.assertEqual(original, (self.tunnel / 'name').read_text())
        self.assertFalse((self.persist / '.webstudio-tunnel').exists())
        saved = (other / 'name').read_text()
        subprocess.run(['bash', '-c', command], env=env, check=True, capture_output=True)
        self.assertEqual(saved, (other / 'name').read_text())
        env['WEBSTUDIO_TUNNEL_NAME'] = 'container-b'
        subprocess.run(['bash', '-c', command], env=env, check=True, capture_output=True)
        self.assertEqual((other / 'name').read_text(), 'container-b\n')

    def test_replacement_container_only_needs_init(self):
        self.run_setup()
        shutil.rmtree(self.local)
        shutil.rmtree(self.home)
        self.home.mkdir()
        result = subprocess.run(
            ['bash', '-c', f'source "{ROOT}/shell/init.sh" && command -v codex && command -v claude'],
            env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(self.state / 'bin/codex'), result.stdout)
        self.assertTrue((self.home / '.codex').is_symlink())
        self.assertFalse(self.local.exists())

    def test_both_and_rerun_preserve_preferences(self):
        self.run_setup()
        self.assert_credentials()
        settings = self.state / 'providers/openlux/claude/settings.json'
        data = json.loads(settings.read_text())
        data['model'] = 'user-model'
        settings.write_text(json.dumps(data))
        config = self.state / 'providers/openlux/codex/config.toml'
        config.write_text(config.read_text() + '\n[projects."/example"]\ntrust_level = "trusted"\n')
        self.run_setup(key=None)
        self.assert_credentials()
        self.assertEqual(json.loads(settings.read_text())['model'], 'user-model')
        self.assertEqual(config.read_text().count('openai_base_url ='), 1)
        self.assertEqual(config.read_text().count('cli_auth_credentials_store ='), 1)
        self.assertIn('[projects."/example"]', config.read_text())
        terminal = self.terminal(f'bash "{ROOT}/setup_tools.sh" --agents both --skip-vscode')
        terminal.expect('Which optional tools should be installed?')
        terminal.send(b'\r')
        terminal.expect('Configure personal egress now?')
        terminal.send(b'n\r')
        terminal.expect('Configure OpenLux as an optional backup?')
        terminal.send(b'y\r')
        terminal.expect('Enter keeps saved credentials')
        terminal.send(b'\r')
        terminal.expect('Setup complete')
        self.assertEqual(terminal.finish(), 0)
        self.assert_credentials()

    def test_official_fresh_and_after_openlux(self):
        self.run_setup(key=None, provider='--official')
        self.assertFalse((self.state / '.codex/auth.json').exists())
        self.assertFalse((self.state / '.claude/settings.json').exists())
        self.run_setup()
        self.run_setup(key=None, provider='--official')
        self.assertFalse((self.state / '.codex/auth.json').exists())
        self.assertFalse((self.state / '.claude/settings.json').exists())
        self.assert_credentials()

    def test_missing_key_fails_after_install(self):
        result = self.run_setup(key=None, success=False)
        self.assertIn('Set OPENLUX_API_KEY', result.stderr)
        self.assertTrue((self.state / 'bin/codex-real').exists())

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
        settings = self.state / 'providers/openlux/claude/settings.json'
        before = settings.read_bytes()
        state = settings.parent / '.claude.json'
        state.write_text('{"secret":"' + KEY + '", BROKEN')
        result = subprocess.run(['node', str(ROOT / 'scripts/configure_claude.cjs'), str(settings), '--key-stdin'],
                                input='replacement', text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(KEY, result.stderr)
        self.assertEqual(settings.read_bytes(), before)


    def test_stale_hook_removed_from_startup_files(self):
        """init.sh prunes hooks from other clones so they don't re-trigger setup."""
        # Simulate a home that previously ran setup from a different clone.
        stale = str(self.root / 'old-clone/shell/init.sh')
        current = str(ROOT / 'shell/init.sh')
        for f in (self.home / '.bashrc', self.home / '.bash_profile'):
            f.write_text(
                f'export A=1\n'
                f'source {stale} # webstudio shell init\n'
                f'alias x=y\n'
            )
        # Write the setup marker pointing at ROOT (the current clone).
        self.local.mkdir(parents=True, exist_ok=True)
        self.state.mkdir(parents=True, exist_ok=True)
        (self.state / '.setup-complete').write_text(str(ROOT) + '\n')
        (self.state / '.setup-complete').chmod(0o600)
        # Sourcing init.sh should succeed and clean up the stale hook.
        result = subprocess.run(
            ['bash', '-c', f'source "{current}"; echo OK'],
            env=self.env, text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('OK', result.stdout)
        for path in (self.home / '.bashrc', self.home / '.bash_profile'):
            contents = path.read_text()
            self.assertNotIn(stale, contents, f'stale hook still in {path.name}')
            self.assertIn(f'source {current} # webstudio shell init', contents)
            # Unrelated lines must be preserved.
            self.assertIn('export A=1', contents)
            self.assertIn('alias x=y', contents)

    def test_stale_hook_not_added_twice(self):
        """Running init.sh a second time does not duplicate the hook."""
        self.local.mkdir(parents=True, exist_ok=True)
        self.state.mkdir(parents=True, exist_ok=True)
        (self.state / '.setup-complete').write_text(str(ROOT) + '\n')
        (self.state / '.setup-complete').chmod(0o600)
        current = str(ROOT / 'shell/init.sh')
        for _ in range(2):
            subprocess.run(
                ['bash', '-c', f'source "{current}"'],
                env=self.env, check=True, capture_output=True,
            )
        for path in (self.home / '.bashrc', self.home / '.bash_profile'):
            count = path.read_text().count(f'source {current} # webstudio shell init')
            self.assertEqual(count, 1, f'hook duplicated in {path.name}')


if __name__ == '__main__':
    unittest.main()
