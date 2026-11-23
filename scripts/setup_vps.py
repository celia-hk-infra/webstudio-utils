#!/usr/bin/env python3
"""Install an isolated Docker HTTPS egress proxy on Ubuntu (run as root)."""
import argparse
import fcntl
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import platform
import re
import secrets
import shutil
import time
import socket
import subprocess
import tarfile
import tempfile
import urllib.request

VERSION = '3.3.3'
STATE = Path('/etc/webstudio-egress')
# Multi-platform manifests, verified against Docker Hub; amd64 and arm64 supported.
GOST_IMAGE = 'busybox:1.37.0@sha256:a7dbc319b1438115a207e11930dc4bb3e643dcb3ec0bdd694bb36cd8fad289ec'
CERTBOT_IMAGE = 'certbot/certbot:v5.4.0@sha256:c23159d30afdd9c97960578aa4654f5901de6cae394958f894074dedd55e599d'
NETWORK = 'webstudio-egress'
CONTAINER = 'webstudio-egress'
LABEL = 'org.webstudio-utils.egress=managed'
SERVICE = 'gost-egress.service'


def run(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def endpoint(value):
    try:
        address = ipaddress.ip_address(value)
        if address.version != 4 or not address.is_global:
            raise ValueError('Use a public IPv4 address for this installer')
        return str(address), True
    except ValueError:
        if re.fullmatch(r'[0-9.]+', value) or ':' in value:
            raise ValueError('Use a public IPv4 address') from None
    value = value.lower()
    if (len(value) > 253 or '.' not in value or
            not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', x)
                    for x in value.split('.'))):
        raise ValueError('Enter a valid DNS hostname or public IPv4 address')
    return value, False


def detect_public_ip():
    """Suggest the VPS's direct public IPv4, without inheriting a proxy route."""
    try:
        result = subprocess.run(
            ['curl', '-q', '-4', '--fail', '--silent', '--show-error',
             '--noproxy', '*', '--connect-timeout', '5', '--max-time', '10',
             'https://ifconfig.me/ip'],
            capture_output=True, text=True, timeout=12, check=False)
        if result.returncode:
            return None
        address = ipaddress.IPv4Address(result.stdout.strip())
        return str(address) if address.is_global else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def select_address(explicit=None):
    if explicit is not None:
        return endpoint(explicit)[0]
    detected = detect_public_ip()
    if detected:
        print(f'Detected public IP: {detected}')
        value = input('Press Enter to use it, or enter another IP/hostname: ').strip() or detected
    else:
        print('Could not detect a public IPv4 address; enter it manually.')
        value = input('Proxy public IPv4 address or hostname: ').strip()
    return endpoint(value)[0]


def atomic(path, value, mode=0o600):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix='.staged-')
    try:
        with os.fdopen(fd, 'w') as output:
            output.write(value)
        os.chmod(temp, mode)
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def load_deployment(directory, host):
    path = directory / 'deployment.json'
    if path.exists():
        data = json.loads(path.read_text())
        if data.get('host') != host:
            raise ValueError('Existing deployment uses a different address; refusing to replace it')
        if data.get('username') != 'codexproxy' or not re.fullmatch(r'[a-f0-9]{48}', data.get('password', '')):
            raise ValueError('Invalid saved deployment credentials')
        return data
    if any((directory / name).exists() for name in ('gost.json', 'client-url')):
        raise ValueError('Incomplete existing configuration; refusing to replace credentials')
    data = dict(host=host, username='codexproxy', password=secrets.token_hex(24))
    atomic(path, json.dumps(data) + '\n')
    return data


def gost_config(data):
    cert = '/etc/letsencrypt/live/webstudio-egress'
    return {'services': [{'name': 'webstudio-egress', 'addr': ':8443',
        'handler': {'type': 'http', 'auth': {
            'username': data['username'], 'password': data['password']}},
        'listener': {'type': 'tls', 'tls': {
            'certFile': cert + '/fullchain.pem', 'keyFile': cert + '/privkey.pem'}}}]}


def certificate_args(host, email):
    host, is_ip = endpoint(host)
    args = ['certonly', '--standalone', '--non-interactive', '--agree-tos',
            '--http-01-port', '8080', '--email', email, '--cert-name', 'webstudio-egress', '--keep-until-expiring']
    return args + (['--preferred-profile', 'shortlived', '--ip-address', host]
                   if is_ip else ['-d', host])


def install_gost():
    arch = {'x86_64': 'amd64', 'aarch64': 'arm64'}.get(platform.machine())
    if not arch:
        raise ValueError('Only amd64 and arm64 VPSs are supported')
    target = STATE / 'bin/gost'
    target.parent.mkdir(parents=True, exist_ok=True)
    manifest = STATE / 'bin/verified.json'
    if target.exists() and manifest.exists():
        saved = json.loads(manifest.read_text())
        if (saved.get('version') == VERSION and saved.get('arch') == arch and
                saved.get('sha256') == hashlib.sha256(target.read_bytes()).hexdigest()):
            return
    asset = f'gost_{VERSION}_linux_{arch}.tar.gz'
    base = f'https://github.com/go-gost/gost/releases/download/v{VERSION}/'
    with tempfile.TemporaryDirectory() as temp:
        archive = Path(temp) / asset
        with urllib.request.urlopen(base + 'checksums.txt', timeout=60) as response:
            checksums = response.read().decode()
        expected = next((line.split()[0] for line in checksums.splitlines()
                         if len(line.split()) == 2 and line.split()[1].lstrip('*') == asset), None)
        if not expected or not re.fullmatch(r'[a-fA-F0-9]{64}', expected):
            raise ValueError('GOST release checksum missing')
        run(['curl', '-q', '-fLsS', '--retry', '3', '--max-time', '600',
             '-o', str(archive), base + asset])
        if hashlib.sha256(archive.read_bytes()).hexdigest() != expected.lower():
            raise ValueError('GOST checksum mismatch')
        with tarfile.open(archive) as bundle:
            member = bundle.getmember('gost')
            if not member.isfile():
                raise ValueError('Invalid GOST archive member')
            binary = Path(temp) / 'gost'
            binary.write_bytes(bundle.extractfile(member).read())
        run(['install', '-m', '755', str(binary), str(target)])
        atomic(manifest, json.dumps({'version': VERSION, 'arch': arch,
               'sha256': hashlib.sha256(binary.read_bytes()).hexdigest()}) + '\n')


def probe(url, authenticated=True):
    # Proxy credentials only enter curl over stdin, never its argv or logs.
    env = os.environ.copy()
    for name in list(env):
        if name.lower() in ('http_proxy', 'https_proxy', 'all_proxy', 'no_proxy'):
            env.pop(name)
    result = subprocess.run(['curl', '-q', '--config', '-', '--silent',
        '--connect-timeout', '10', '--max-time', '30', '--output', '/dev/null',
        '--write-out', '%{http_connect}', 'https://api.ipify.org'],
        input=f'proxy = "{url}"\n' + ('fail\n' if authenticated else ''),
        text=True, capture_output=True, env=env)
    if authenticated:
        if result.returncode or result.stdout != '200':
            raise RuntimeError('Authenticated HTTPS proxy check failed; check network and service logs')
    elif result.stdout != '407':
        raise RuntimeError('Proxy did not reject unauthenticated CONNECT with 407')


def container_base(name):
    return ['docker', 'run', '--rm', '--name', name, '--label', LABEL,
            '--network', NETWORK, '--user', '0:0', '--read-only', '--cap-drop', 'ALL',
            '--security-opt', 'no-new-privileges=true', '--pids-limit', '128',
            '--log-opt', 'max-size=10m', '--log-opt', 'max-file=3',
            '--tmpfs', '/tmp:rw,noexec,nosuid,size=64m']


def certbot_command(args):
    return container_base('webstudio-egress-certbot') + [
        '--publish', '0.0.0.0:80:8080',
        '--mount', f'type=bind,src={STATE}/letsencrypt,dst=/etc/letsencrypt',
        '--tmpfs', '/var/lib/letsencrypt:rw,nosuid,size=64m',
        '--tmpfs', '/var/log/letsencrypt:rw,nosuid,size=32m',
        CERTBOT_IMAGE] + args


def proxy_command():
    cert = 'letsencrypt'
    args = container_base(CONTAINER) + ['--publish', '0.0.0.0:443:8443']
    for source, destination in (
            ('bin/gost', '/usr/local/bin/gost'), ('gost.json', '/etc/gost.json'),
            (cert + '/live/webstudio-egress', '/etc/letsencrypt/live/webstudio-egress'),
            (cert + '/archive/webstudio-egress', '/etc/letsencrypt/archive/webstudio-egress')):
        args += ['--mount', f'type=bind,src={STATE}/{source},dst={destination},readonly']
    return args + [GOST_IMAGE, '/usr/local/bin/gost', '-C', '/etc/gost.json']


def certificate_digest():
    return hashlib.sha256((STATE / 'letsencrypt/live/webstudio-egress/fullchain.pem').read_bytes()).hexdigest()


def renew(dry_run=False):
    args = ['renew', '--cert-name', 'webstudio-egress', '--quiet']
    if dry_run:
        args.append('--dry-run')
    run(certbot_command(args))
    if not dry_run:
        digest = certificate_digest()
        marker = STATE / 'loaded-certificate'
        # Keep retrying a failed restart even when the next renewal has no new cert.
        if not marker.exists() or marker.read_text().strip() != digest:
            run(['systemctl', 'restart', SERVICE])
            run(['systemctl', 'is-active', '--quiet', SERVICE])
            atomic(marker, digest + '\n')


def ensure_network():
    result = subprocess.run(['docker', 'network', 'inspect', NETWORK], capture_output=True, text=True)
    if result.returncode == 0:
        network = json.loads(result.stdout)[0]
        if (network.get('Labels') or {}).get('org.webstudio-utils.egress') != 'managed':
            raise ValueError('Docker network webstudio-egress already exists and is not managed by this installer')
        if network.get('Driver') != 'bridge':
            raise ValueError('Managed Docker network must use the bridge driver')
    else:
        run(['docker', 'network', 'create', '--driver', 'bridge', '--label', LABEL, NETWORK])


def check_container_names(unit_exists):
    for name in (CONTAINER, 'webstudio-egress-certbot'):
        result = subprocess.run(['docker', 'container', 'inspect', name], capture_output=True, text=True)
        if result.returncode:
            continue
        existing = json.loads(result.stdout)[0]
        labels = existing.get('Config', {}).get('Labels') or {}
        if labels.get('org.webstudio-utils.egress') != 'managed':
            raise ValueError(f'Container {name} belongs to another deployment; refusing to replace it')
        if name != CONTAINER or not unit_exists:
            raise ValueError(f'Existing container {name} must be inspected before retrying setup')


def proxy_unit():
    # Paths and image references are controlled constants; no credentials in argv.
    return """# Managed by webstudio-utils (Docker)
[Unit]
Description=WebStudio HTTPS egress container
Requires=docker.service
After=docker.service network-online.target
PartOf=docker.service
[Service]
ExecStart=""" + ' '.join(proxy_command()) + """
ExecStop=/usr/bin/docker stop --time 15 webstudio-egress
Restart=always
RestartSec=5
TimeoutStopSec=30
[Install]
WantedBy=multi-user.target
"""


def install(host, email):
    host, _ = endpoint(host)
    if os.geteuid() != 0:
        raise ValueError('Run this installer with sudo or as root')
    release = Path('/etc/os-release').read_text()
    if not re.search(r'^ID=(["\']?)ubuntu\1$', release, re.M) or not Path('/run/systemd/system').is_dir():
        raise ValueError('This installer requires Ubuntu with systemd')
    version = re.search(r'^VERSION_ID="?([0-9]+)', release, re.M)
    if not version or int(version.group(1)) < 22:
        raise ValueError('Ubuntu 22.04 or newer is required')
    unit = Path('/etc/systemd/system') / SERVICE
    if unit.exists() and '# Managed by webstudio-utils (Docker)' not in unit.read_text():
        raise ValueError('Existing native or unrelated gost-egress service found; automatic migration is not supported')
    if not unit.exists() and subprocess.run(['systemctl', 'cat', SERVICE],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
        raise ValueError('An existing gost-egress service is not managed by this installer')
    # Port 80 must stay available for future standalone HTTP-01 renewals.
    for port in (80, 443):
        with socket.socket() as sock:
            try:
                sock.bind(('0.0.0.0', port))
            except OSError:
                if port == 443 and unit.exists() and subprocess.run(
                        ['systemctl', 'is-active', '--quiet', SERVICE]).returncode == 0:
                    continue
                raise ValueError(f'Port {port} is occupied; this installer requires a standalone VPS')
    socket.getaddrinfo(host, 443)
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    STATE.chmod(0o700)
    data = load_deployment(STATE, host)
    print('Installing Docker runtime. Cloud firewall must allow TCP 80/443.', flush=True)
    print('Docker publishes ports outside normal UFW INPUT rules; review cloud and DOCKER-USER restrictions.', flush=True)
    run(['apt-get', 'update'])
    packages = ['ca-certificates', 'curl']
    if not shutil.which('docker'):
        packages.append('docker.io')
    run(['apt-get', 'install', '-y'] + packages)
    run(['systemctl', 'enable', '--now', 'docker.service'])
    run(['docker', 'info'], stdout=subprocess.DEVNULL)
    check_container_names(unit.exists())
    ensure_network()
    for image in (GOST_IMAGE, CERTBOT_IMAGE):
        run(['docker', 'pull', image])
    install_gost()
    (STATE / 'letsencrypt').mkdir(mode=0o700, exist_ok=True)
    # No third-party host certbot or GOST service is installed.
    run(certbot_command(certificate_args(host, email)))
    atomic(STATE / 'gost.json', json.dumps(gost_config(data)) + '\n')
    url = f'https://{data["username"]}:{data["password"]}@{host}:443'
    atomic(STATE / 'client-url', url + '\n')
    atomic(STATE / 'manager.py', Path(__file__).read_text(), 0o700)
    atomic(unit, proxy_unit(), 0o644)
    atomic('/etc/systemd/system/webstudio-certbot.service', f"""# Managed by webstudio-utils (Docker)
[Unit]
Description=Renew WebStudio proxy certificate in a container
Requires=docker.service
After=docker.service
[Service]
Type=oneshot
ExecStart=/usr/bin/python3 {STATE}/manager.py --renew
""", 0o644)
    atomic('/etc/systemd/system/webstudio-certbot.timer', """# Managed by webstudio-utils (Docker)
[Unit]
Description=Check WebStudio certificate renewal twice daily
[Timer]
OnCalendar=*-*-* 00,12:00:00
RandomizedDelaySec=3600
Persistent=true
[Install]
WantedBy=timers.target
""", 0o644)
    run(['systemctl', 'daemon-reload'])
    run(['systemctl', 'enable', SERVICE])
    run(['systemctl', 'restart', SERVICE])
    # Enable renewal before live tests so a transient check failure cannot leave
    # a running short-lived certificate without its renewal schedule.
    run(['systemctl', 'enable', '--now', 'webstudio-certbot.timer'])
    renew(dry_run=True)
    for attempt in range(5):
        try:
            probe(f'https://{host}:443', authenticated=False)
            probe(url)
            break
        except RuntimeError:
            if attempt == 4:
                raise
            time.sleep(1)
    atomic(STATE / 'loaded-certificate', certificate_digest() + '\n')
    print(f'Proxy ready: {host}:443\nPrivate client URL: {STATE}/client-url')
    print('On WebStudio: ./setup_tools.sh --agents codex --official --skip-vscode --direct-egress')
    print(f'Read the private URL with sudo cat {STATE}/client-url and paste it at the hidden prompt.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--address', help='Public IPv4 or hostname; otherwise detect and confirm interactively')
    parser.add_argument('--email', help='Certificate contact email')
    parser.add_argument('--agree-tos', action='store_true', help="Accept Let's Encrypt subscriber agreement")
    parser.add_argument('--renew', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.renew:
        if os.geteuid() != 0:
            parser.error('Run renewal as root')
        with open('/run/lock/webstudio-egress-setup.lock', 'w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            renew()
        return
    host = select_address(args.address)
    email = args.email or input('Certificate contact email: ').strip()
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
        parser.error('Enter a valid email address')
    if not args.agree_tos:
        answer = input("Accept Let's Encrypt subscriber agreement (https://letsencrypt.org/repository/)? [y/N] ")
        if answer.lower() not in ('y', 'yes'):
            parser.error('Certificate issuance requires acceptance')
    if os.geteuid() != 0:
        parser.error('Run with sudo or as root')
    with open('/run/lock/webstudio-egress-setup.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        install(host, email)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, tarfile.TarError, subprocess.CalledProcessError) as error:
        # No command containing credentials is ever executed.
        raise SystemExit(f'VPS setup failed: {error}')
