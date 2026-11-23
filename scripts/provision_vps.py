#!/usr/bin/env python3
"""Install the standalone VPS proxy over verified SSH, then connect WebStudio."""
import argparse
import contextlib
import json
import socket
import tempfile
import time
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

from direct_egress import config_path, save_url, valid_url, run_with_gost, read_url, gost_config, gost_binary
from setup_vps import endpoint, probe


def ssh_binary():
    found = shutil.which('ssh')
    if found:
        return found
    # ModelArts can bundle OpenSSH outside PATH, including multiple distro builds.
    candidates = sorted(Path('/modelarts/authoring/script/entrypoint/deps').glob(
        'ssh_*/bin/ssh'), reverse=True)
    for candidate in candidates:
        if os.access(candidate, os.X_OK):
            result = subprocess.run([str(candidate), '-V'], capture_output=True)
            if result.returncode == 0:
                return str(candidate)
    raise RuntimeError('OpenSSH client missing; install openssh-client or add ssh to PATH')


def ssh_command(host, user, port, key, known_hosts):
    # Only a literal IP is accepted as the SSH destination; no shell interpretation.
    import ipaddress
    ipaddress.ip_address(host)
    if not re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_-]*', user):
        raise ValueError('Invalid SSH username')
    if not 1 <= port <= 65535:
        raise ValueError('Invalid SSH port')
    return [ssh_binary(), '-F', '/dev/null', '-p', str(port), '-i', str(key),
            '-o', 'IdentitiesOnly=yes', '-o', 'ForwardAgent=no',
            '-o', 'StrictHostKeyChecking=ask', '-o', f'UserKnownHostsFile={known_hosts}',
            '-o', 'ConnectTimeout=15', '-o', 'ServerAliveInterval=15',
            '-o', 'ServerAliveCountMax=3', f'{user}@{host}']


def remote(ssh, command, **kwargs):
    return subprocess.run(ssh + [shlex.join(command)], check=True, **kwargs)


def provision(ssh, address, email, agree):
    # Fail before uploading anything if elevation is unavailable. No agent forwarding.
    elevate = [] if ssh[-1].startswith('root@') else ['sudo', '-n']
    remote(ssh, elevate + ['true'])
    result = remote(ssh, ['mktemp', '-d', '/tmp/webstudio-vps.XXXXXXXXXX'],
                    capture_output=True, text=True)
    directory = result.stdout.strip()
    if not re.fullmatch(r'/tmp/webstudio-vps\.[A-Za-z0-9]+', directory):
        raise RuntimeError('Unexpected remote staging path')
    try:
        script = Path(__file__).with_name('setup_vps.py').read_bytes()
        remote(ssh, ['sh', '-c', 'umask 077; cat > "$1/setup_vps.py"', 'sh', directory], input=script)
        args = elevate + ['python3', directory + '/setup_vps.py',
                '--address', address, '--email', email]
        if agree:
            args.append('--agree-tos')
        remote(ssh, args)
        # Capture credentials only in memory, never terminal/setup.log or command arguments.
        result = remote(ssh, elevate + ['cat', '/etc/webstudio-egress/client-url'],
                        capture_output=True, text=True)
        url = valid_url(result.stdout.strip())
        from urllib.parse import urlsplit
        if urlsplit(url).hostname != address or urlsplit(url).port != 443:
            raise RuntimeError('Returned proxy address does not match requested deployment')
        probe(url)
        return url
    finally:
        subprocess.run(ssh + [shlex.join(['rm', '-rf', '--', directory])],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@contextlib.contextmanager
def proxy_bridge(host, port):
    """Carry SSH over an existing verified HTTPS proxy without editor dependencies."""
    with socket.socket() as reserved:
        reserved.bind(('127.0.0.1', 0))
        local_port = reserved.getsockname()[1]
    config = gost_config(read_url(config_path()), local_port)
    service = config['services'][0]
    service['handler']['type'] = 'tcp'
    service['forwarder'] = {'nodes': [{'name': 'ssh', 'addr':
        f'[{host}]:{port}' if ':' in host else f'{host}:{port}'}]}
    with tempfile.TemporaryDirectory(prefix='webstudio-provision-') as directory:
        path = Path(directory) / 'gost.json'
        path.write_text(json.dumps(config))
        path.chmod(0o600)
        process = subprocess.Popen([str(gost_binary()), '-C', str(path)],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(50):
                if process.poll() is not None:
                    raise RuntimeError('SSH proxy bridge exited during startup')
                try:
                    with socket.create_connection(('127.0.0.1', local_port), timeout=0.1):
                        break
                except OSError:
                    time.sleep(0.1)
            else:
                raise RuntimeError('SSH proxy bridge did not start')
            yield local_port
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', help='VPS public IP used for SSH')
    parser.add_argument('--user', help='SSH user with passwordless sudo (or root)')
    parser.add_argument('--port', type=int, default=22)
    parser.add_argument('--identity', help='Local SSH private key path')
    parser.add_argument('--address', help='Proxy public IPv4 or hostname; defaults to --host')
    parser.add_argument('--email', help='Certificate contact email')
    parser.add_argument('--agree-tos', action='store_true')
    parser.add_argument('--via-existing-proxy', action='store_true',
                        help='Carry SSH through the already configured direct HTTPS proxy')
    args = parser.parse_args()
    host = args.host or input('VPS SSH IP: ').strip()
    user = args.user or input('SSH user [root]: ').strip() or 'root'
    key = Path(args.identity or input('SSH private key path: ').strip()).expanduser().resolve()
    if not key.is_file() or key.stat().st_mode & 0o077:
        raise ValueError('SSH private key must exist and be private (chmod 600)')
    address, _ = endpoint(args.address or host)
    email = args.email or input('Certificate contact email: ').strip()
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
        raise ValueError('Enter a valid email address')
    if not args.agree_tos:
        if input("Accept Let's Encrypt subscriber agreement (https://letsencrypt.org/repository/)? [y/N] ").lower() not in ('y', 'yes'):
            raise ValueError('Certificate issuance requires acceptance')
    root = Path(os.environ.get('WEBSTUDIO_PERSIST_ROOT', str(Path(__file__).resolve().parents[2])))
    os.environ.setdefault('WEBSTUDIO_PERSIST_ROOT', str(root))
    os.environ.setdefault('WEBSTUDIO_AGENT_STATE_DIR', str(root / '.webstudio-agent-home'))
    directory = config_path().parent
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)
    print('Verify any new SSH host fingerprint against the VPS console before accepting it.')
    print('Requires Ubuntu, Python 3, passwordless sudo, free ports 80/443, and inbound firewall access.')
    ssh = ssh_command(host, user, args.port, key, directory / 'vps-known-hosts')
    transport = contextlib.nullcontext(None)
    if args.via_existing_proxy:
        transport = proxy_bridge(host, args.port)
    with transport as local_port:
        if local_port is not None:
            ssh = ssh_command('127.0.0.1', user, local_port, key, directory / 'vps-known-hosts')
            ssh[-1:-1] = ['-o', 'HostKeyAlias=' + host]
        url = provision(ssh, address, email, True)
    save_url(config_path(), url)
    subprocess.run([sys.executable, str(Path(__file__).with_name('install_direct_gost.py'))], check=True)
    if run_with_gost(url, ['curl', '-q', '--fail', '--silent', '--show-error',
                          '--connect-timeout', '10', '--max-time', '30',
                          '--output', '/dev/null', 'https://api.ipify.org']):
        raise RuntimeError('Local GOST forwarding check failed')
    print('VPS provisioned and WebStudio direct egress verified. You can now sign in to Codex.')


if __name__ == '__main__':
    try:
        main()
    except subprocess.CalledProcessError:
        raise SystemExit('VPS provisioning command failed; review the preceding output. Existing credentials are preserved.')
    except (OSError, ValueError, RuntimeError) as error:
        raise SystemExit(f'VPS provisioning failed: {error}')
