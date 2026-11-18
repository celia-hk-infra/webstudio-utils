#!/usr/bin/env python3
"""Per-directory HKSTP setup and launchers; never source WebStudio shell init."""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time

from egress_supervisor import supervise

REPO = Path(__file__).resolve().parent.parent
VERSION = '0.166.0'


def run(args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def private_dir(path):
    if path.is_symlink():
        raise ValueError('Expected a real directory: ' + str(path))
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)
    if path.stat().st_mode & 0o777 != 0o700:
        raise ValueError('Filesystem must support mode 700: ' + str(path))


def atomic_write(path, content, mode=0o600):
    if path.is_symlink():
        raise ValueError('Refusing to replace a symlink: ' + str(path))
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, mode)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextmanager
def locked(path, blocking=True):
    with path.open('a') as stream:
        os.chmod(path, 0o600)
        fcntl.flock(stream, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        yield


def identity(root):
    return hashlib.sha256(os.fsencode(root)).hexdigest()[:20]


def alias_line(root, name):
    # Bash aliases are expanded as shell text: quote both the path and the value.
    return 'alias {}={}\n'.format(name, shlex.quote(shlex.quote(str(root / 'bin/codex'))))


def update_alias(root, name, write=False):
    home = Path.home()
    rc = home / '.bashrc'
    if rc.is_symlink():
        if not rc.exists():
            raise ValueError('Repair the broken ~/.bashrc symlink before setup.')
        rc = rc.resolve()
    begin = '# BEGIN hkstp ' + identity(root)
    end = '# END hkstp ' + identity(root)
    with locked(home / '.hkstp-aliases.lock'):
        text = rc.read_text() if rc.exists() else ''
        pattern = re.compile(r'^' + re.escape(begin) + r'\n.*?^' + re.escape(end) + r'\n?', re.M | re.S)
        own = pattern.findall(text)
        if len(own) > 1 or ((begin in text or end in text) and not own):
            raise ValueError('Malformed HKSTP alias block in ~/.bashrc; repair it before setup.')
        other = pattern.sub('', text)
        # Check the common Bash alias files without executing shared startup code.
        sources = [('~/.bashrc', other)]
        aliases = home / '.bash_aliases'
        if aliases.is_file():
            sources.append(('~/.bash_aliases', aliases.read_text()))
        for source, content in sources:
            if re.search(r'(?<![\w-])' + re.escape(name) + r'\s*(?:=|\(\s*\))', content):
                raise ValueError('Command name already defined in ' + source + ': ' + name)
        if shutil.which(name):
            raise ValueError('Command name already exists on PATH: ' + name)
        if write:
            block = begin + '\n' + alias_line(root, name) + end + '\n'
            updated = pattern.sub(lambda _: block, text) if own else text + ('\n' if text else '') + block
            if updated != text:
                # Preserve existing permissions and the target of a .bashrc symlink.
                atomic_write(rc, updated, rc.stat().st_mode & 0o777 if rc.exists() else 0o600)


def connection(repo, path):
    spec = importlib.util.spec_from_file_location('hkstp_connection', repo / 'vendor/codex-local-egress/connection.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        return module.parse(path.read_text())
    except (OSError, ValueError):
        raise ValueError('Missing or invalid connection.env; credentials were not displayed.') from None


def clean_env(config, root):
    env = os.environ.copy()
    for key in list(env):
        if key in ('BASH_ENV', 'ENV') or key.startswith(('OPENAI_', 'CODEX_', 'WEBSTUDIO_', 'DEVTUNNELS_')) or key.lower() in (
                'http_proxy', 'https_proxy', 'all_proxy', 'no_proxy'):
            env.pop(key)
    env.update(CODEX_HOME=str(root / '.hkstp/codex'),
               EGRESS_STATE_DIR=str(root / '.hkstp/egress'),
               DEVTUNNELS_USER_STATE_DIR=str(root / '.hkstp/egress/.devtunnel'),
               PATH=os.pathsep.join(config['paths'] + [env.get('PATH', '/usr/bin:/bin')]))
    return env


class Instance:
    def __init__(self, root):
        self.root = root.resolve()
        self.state = self.root / '.hkstp'
        self.config = json.loads((self.state / 'instance.json').read_text())
        self.repo = Path(self.config['repo'])
        self.egress = self.state / 'egress'
        self.remote = self.repo / 'vendor/codex-local-egress/remote.sh'
        self.env = clean_env(self.config, self.root)
        self.tmux = [self.config['tmux'], '-f', '/dev/null', '-L', 'hkstp-' + identity(self.root)]

    def tm(self, *args, **kwargs):
        return subprocess.run(self.tmux + list(args), env=self.env, **kwargs)

    def running(self):
        return self.tm('has-session', '-t', '=egress', stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL).returncode == 0

    def healthy(self):
        try:
            return subprocess.run(['bash', str(self.remote), 'check'], env=self.env,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                  timeout=8).returncode == 0
        except subprocess.TimeoutExpired:
            return False

    def login(self, provider=None):
        args = ['bash', self.remote, 'devtunnel', 'login']
        if provider:
            args.append(provider)
        run(args, env=self.env)

    def authenticated(self):
        result = subprocess.run(['devtunnel', 'user', 'show'], env=self.env,
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30)
        return result.returncode == 0 and not re.search(
            r'Not logged in|Login token expired|Previously logged in', result.stdout)

    def start(self):
        with locked(self.egress / '.control.lock'):
            if self.running() and self.healthy():
                return
            if not self.running():
                values = connection(self.repo, self.egress / 'connection.env')
                check_port(int(values['PROXY_PORT']))
                if not self.authenticated():
                    raise ValueError('Dev Tunnels login required. Run {} --egress login.'.format(self.config['name']))
                command = shlex.join([sys.executable, '-u', str(self.repo / 'scripts/hkstp.py'),
                                      'supervise', str(self.root)])
                command += ' >>' + shlex.quote(str(self.egress / 'supervisor.log')) + ' 2>&1'
                self.tm('new-session', '-d', '-s', 'egress', command, check=True)
            for _ in range(20):
                if self.running() and self.healthy():
                    return
                time.sleep(1)
        raise ValueError('Egress is not ready. Keep the laptop/VPS host running; inspect {} --egress logs.'.format(self.config['name']))

    def stop(self):
        with locked(self.egress / '.control.lock'):
            if self.running():
                self.tm('send-keys', '-t', '=egress:0.0', 'C-c', check=True)
                for _ in range(100):
                    if not self.running():
                        return
                    time.sleep(.1)
                raise ValueError('Egress did not stop cleanly. Inspect its log before changing configuration.')

    def supervise(self):
        values = connection(self.repo, self.egress / 'connection.env')
        # Hold a per-port lock for the entire supervisor lifetime, including retries.
        ports = Path('/tmp') / ('hkstp-egress-' + str(os.getuid()))
        private_dir(ports)
        with locked(ports / (values['PROXY_PORT'] + '.lock'), blocking=False):
            check_port(int(values['PROXY_PORT']))
            os.environ.clear()
            os.environ.update(self.env)
            stopped = threading.Event()
            for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
                signal.signal(sig, lambda *_: stopped.set())
            supervise(['bash', str(self.remote)], stopped)

    def launch(self, args):
        if args[:1] == ['--egress']:
            action = args[1:]
            if action == ['start']:
                self.start()
            elif action == ['stop']:
                self.stop()
            elif action == ['restart']:
                self.stop()
                self.start()
            elif action == ['status']:
                healthy = self.running() and self.healthy()
                print('Egress ready' if healthy else 'Egress unavailable')
                print('Background session: tmux -L hkstp-{} (session: egress)'.format(identity(self.root)))
                print('Log: ' + str(self.egress / 'supervisor.log'))
                return 0 if healthy else 1
            elif action == ['logs']:
                log = self.egress / 'supervisor.log'
                print(log.read_text()[-16000:] if log.exists() else 'No egress log yet.')
            elif action[:1] == ['login'] and len(action) <= 2:
                self.login(action[1] if len(action) == 2 else None)
            else:
                raise ValueError('--egress expects start, stop, restart, status, logs, or login [github|microsoft].')
            return 0
        if args not in (['--help'], ['-h'], ['--version'], ['-V']):
            self.start()
            # A background Codex server can retain an old proxy after egress is
            # reconfigured. Keep interactive work in the launched environment.
            command = ['bash', str(self.remote), 'exec', '--', self.config['codex'], '--no-daemon']
        else:
            command = [self.config['codex']]
        os.execvpe(command[0], command + args, self.env)


def check_port(port):
    with socket.socket() as sock:
        try:
            sock.bind(('127.0.0.1', port))
        except OSError:
            raise ValueError('Egress port {} is already occupied. Do not stop another person\'s tunnel. '
                             'On your host, stop local.sh, move connection.env aside, restart local.sh '
                             'to generate a new tunnel/port, then import the new file here.'.format(port)) from None


def download(url, target):
    run(['curl', '--fail', '--location', '--silent', '--show-error', '--retry', '3',
         '--connect-timeout', '15', '--max-time', '180', url, '-o', target])


def install_tools(root, version):
    tools = root / 'tools'
    tools.mkdir(exist_ok=True)
    paths = []
    # Reuse system Node/npm. If absent, install the current Node 22 LTS archive,
    # checking the SHA-256 published alongside it before extraction.
    node_root = tools / 'node'
    if (node_root / 'bin/npm').is_file():
        paths.append(str(node_root / 'bin'))
    elif not (shutil.which('node') and shutil.which('npm')):
        arch = {'x86_64': 'x64', 'aarch64': 'arm64'}.get(os.uname().machine)
        if not arch:
            raise ValueError('Install Node.js and npm for this architecture before setup.')
        with tempfile.TemporaryDirectory(prefix='.node-', dir=tools) as tmp:
            stage = Path(tmp)
            base = 'https://nodejs.org/dist/latest-v22.x/'
            download(base + 'SHASUMS256.txt', stage / 'checksums')
            matches = re.findall(r'^([0-9a-f]{64})\s+(node-v[\d.]+-linux-' + arch + r'\.tar\.xz)$',
                                 (stage / 'checksums').read_text(), re.M)
            if len(matches) != 1:
                raise ValueError('Could not identify the Node.js archive.')
            digest, name = matches[0]
            download(base + name, stage / name)
            if hashlib.sha256((stage / name).read_bytes()).hexdigest() != digest:
                raise ValueError('Node.js archive checksum mismatch.')
            run(['tar', '-xJf', stage / name, '-C', stage])
            (stage / name[:-len('.tar.xz')]).rename(node_root)
        paths.append(str(node_root / 'bin'))
    else:
        paths.extend(dict.fromkeys(str(Path(shutil.which(tool)).parent) for tool in ('node', 'npm')))
    tmux = str(tools / 'tmux/bin/tmux') if (tools / 'tmux/bin/tmux').is_file() else shutil.which('tmux')
    if not tmux:
        conda = shutil.which('conda') or os.environ.get('CONDA_EXE')
        if not conda:
            raise ValueError('Install tmux, or provide Conda via CONDA_EXE so setup can install tools/tmux.')
        run([conda, 'create', '--yes', '--prefix', tools / 'tmux', '--override-channels', '-c', 'conda-forge', 'tmux'])
        tmux = str(tools / 'tmux/bin/tmux')
    paths.append(str(Path(tmux).parent))
    dev = tools / 'devtunnel/bin'
    if not (dev / 'devtunnel').is_file() and not shutil.which('devtunnel'):
        arch = {'x86_64': 'linux-x64', 'aarch64': 'linux-arm64'}.get(os.uname().machine)
        if not arch:
            raise ValueError('Install Microsoft Dev Tunnels for this architecture before setup.')
        dev.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.download-', dir=dev) as tmp:
            binary = Path(tmp) / 'devtunnel'
            download('https://aka.ms/TunnelsCliDownload/' + arch, binary)
            binary.chmod(0o700)
            run([binary, '--version'])
            binary.rename(dev / 'devtunnel')
    paths.append(str(dev if (dev / 'devtunnel').is_file() else Path(shutil.which('devtunnel')).parent))
    env = os.environ.copy()
    env['PATH'] = os.pathsep.join(paths + [env.get('PATH', '')])
    env['npm_config_cache'] = str(root / '.hkstp/npm-cache')
    target = tools / 'codex' / version
    codex = target / 'node_modules/.bin/codex'
    if not codex.is_file():
        if target.exists():
            raise ValueError('Incomplete Codex installation; move aside and rerun: ' + str(target))
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.install-', dir=target.parent) as tmp:
            run(['npm', 'install', '--registry', 'https://registry.npmjs.org', '--prefix', tmp,
                 '--no-save', '--no-audit', '--no-fund', '@openai/codex@' + version], env=env)
            if not (Path(tmp) / 'node_modules/.bin/codex').is_file():
                raise ValueError('Codex installation did not produce a CLI.')
            Path(tmp).rename(target)
    run([codex, '--version'], env=clean_env({'paths': paths}, root))
    return {'paths': paths, 'tmux': tmux, 'codex': str(codex)}


def configure_codex(state):
    path = state / 'codex/config.toml'
    text = path.read_text() if path.exists() else ''
    # Retain all user preferences, replacing only the top-level credential store.
    table = re.search(r'^[ \t]*\[', text, re.M)
    top, rest = (text[:table.start()], text[table.start():]) if table else (text, '')
    top = re.sub(r'^[ \t]*cli_auth_credentials_store\s*=.*\n?', '', top, flags=re.M)
    atomic_write(path, 'cli_auth_credentials_store = "file"\n' + top + rest)


def setup(argv):
    parser = argparse.ArgumentParser(prog='setup-hkstp.sh', description='Set up personal official Codex + egress on HKSTP; no WebStudio shell hooks.')
    parser.add_argument('--root', type=Path, default=REPO.parent, help='Person directory (default: repository parent)')
    parser.add_argument('--name', help='Shared Bash shortcut, e.g. bob-codex')
    parser.add_argument('--connection', type=Path, help='connection.env from your laptop/VPS')
    parser.add_argument('--provider', choices=('github', 'microsoft'), help='Dev Tunnels login provider')
    parser.add_argument('--codex-version', default=VERSION, help='Pinned official npm release (default: %(default)s)')
    parser.add_argument('--defer-egress', action='store_true', help='Install only; configure/login/start egress on a later run')
    parser.add_argument('--skip-login', action='store_true', help='Skip official Codex device login')
    args = parser.parse_args(argv)
    if not re.fullmatch(r'\d+\.\d+\.\d+', args.codex_version):
        parser.error('--codex-version must be a numeric release')
    for tool in ('bash', 'git', 'curl'):
        if not shutil.which(tool):
            raise ValueError('Install the required system dependency first: ' + tool)
    root = args.root.expanduser().resolve()
    if root == Path.home().resolve() or root == REPO or REPO in root.parents:
        raise ValueError('Choose a person directory outside the Git checkout, not the shared Linux home.')
    root.mkdir(parents=True, exist_ok=True)
    state = root / '.hkstp'
    private_dir(state)
    with locked(state / '.setup.lock'):
        saved = json.loads((state / 'instance.json').read_text()) if (state / 'instance.json').exists() else {}
        name = args.name or saved.get('name')
        if not name and sys.stdin.isatty():
            print('Choose a personal alias for Codex. For example, bob-codex will launch\n'
                  'Codex with your own login, history and egress from any project directory.\n'
                  'This shortcut will be added to the shared ~/.bashrc; choose a unique name.')
            name = input('Your Codex alias (must end in -codex, e.g. bob-codex): ').strip()
        if not name or not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_-]*-codex', name):
            raise ValueError('Provide --name NAME-codex, for example --name bob-codex.')
        if saved and saved['name'] != name:
            raise ValueError('This directory already uses ' + saved['name'] + '; keep that name when rerunning setup.')
        update_alias(root, name)
        for relative in ('codex', 'egress', 'egress/.devtunnel'):
            private_dir(state / relative)
        launcher = root / 'bin/codex'
        body = '#!/usr/bin/env bash\nset -euo pipefail\nset +xv\nexec ' + shlex.join([
            sys.executable, str(REPO / 'scripts/hkstp.py'), 'launch', str(root)]) + ' "$@"\n'
        if launcher.exists() and not saved:
            raise ValueError('Existing bin/codex is not managed by HKSTP; choose another root.')
        run(['git', '-C', REPO, 'submodule', 'update', '--init', '--', 'vendor/codex-local-egress'])
        incoming = None
        if args.connection:
            connection(REPO, args.connection.expanduser())
            incoming = args.connection.expanduser().read_text()
        target = state / 'egress/connection.env'
        if not args.defer_egress and not incoming and not target.exists():
            if not sys.stdin.isatty():
                raise ValueError('Provide --connection FILE, or use --defer-egress for installation only.')
            print('On your laptop/VPS, run bash scripts/start_egress_host.sh and keep it running.\n'
                  'See README.en.md for host dependencies. Copy its connection.env here.')
            source = Path(input('Path to connection.env: ').strip()).expanduser()
            connection(REPO, source)
            incoming = source.read_text()
        config = install_tools(root, args.codex_version)
        config.update(repo=str(REPO), name=name)
        # Do not replace connection settings while this person's supervisor runs.
        with locked(state / 'egress/.control.lock'):
            if incoming is not None and (not target.exists() or target.read_text() != incoming):
                if saved and Instance(root).running():
                    raise ValueError('Stop your egress before replacing connection.env: ' + name + ' --egress stop')
                atomic_write(target, incoming)
            atomic_write(state / 'instance.json', json.dumps(config, indent=2) + '\n')
            configure_codex(state)
            launcher.parent.mkdir(exist_ok=True)
            atomic_write(launcher, body, 0o700)
        update_alias(root, name, write=True)
        print('Shortcut saved for new Bash terminals. It is not active in this terminal yet.\n'
              'After setup finishes, run:\n' + alias_line(root, name).rstrip(), flush=True)
        instance = Instance(root)
        if args.defer_egress:
            print('Installed; egress and Codex login deferred. Rerun without --defer-egress when ready.')
            return 0
        if not instance.authenticated():
            instance.login(args.provider)
        instance.start()
        authenticated = subprocess.run([str(launcher), 'login', 'status'], env=instance.env,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
        if not authenticated and not args.skip_login:
            if sys.stdin.isatty() and input('Sign in to official Codex now? [Y/n] ').strip().lower() in ('n', 'no'):
                print('Login deferred. Run: ' + name + ' login --device-auth')
            else:
                run([launcher, 'login', '--device-auth'], env=instance.env)
                run([launcher, 'login', 'status'], env=instance.env)
        elif not authenticated:
            print('Login deferred. Run: ' + name + ' login --device-auth')
        print('Egress ready. Run {} or {} resume. Manage it with {} --egress status|stop|start|logs.'.format(name, name, name))
        print('Activate the shortcut in this terminal:\n' + alias_line(root, name).rstrip())
    return 0


def main():
    os.umask(0o077)
    try:
        if len(sys.argv) < 2 or sys.argv[1] == 'setup':
            return setup(sys.argv[2:])
        instance = Instance(Path(sys.argv[2]))
        if sys.argv[1] == 'supervise':
            instance.supervise()
            return 0
        if sys.argv[1] == 'launch':
            return instance.launch(sys.argv[3:])
        raise ValueError('Unknown HKSTP operation')
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print('HKSTP: ' + str(error), file=sys.stderr)
        return 1
    except EOFError:
        print('HKSTP: Input ended before setup was complete. Rerun when ready.', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__':
    sys.exit(main())
