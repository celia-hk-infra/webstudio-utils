import json
import io
import hashlib
import tarfile
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import setup_vps as server
import provision_vps as client
import direct_egress as direct


class VpsSetupTests(unittest.TestCase):
    def test_endpoint_validation(self):
        self.assertEqual(server.endpoint('8.8.8.8'), ('8.8.8.8', True))
        self.assertEqual(server.endpoint('Proxy.Example.org'), ('proxy.example.org', False))
        for host in ('127.0.0.1', '10.0.0.1', '999.1.1.1', 'host;id', '-host.example',
                     'a/b.example', '::1', 'https://example.org', '*.example.org'):
            with self.subTest(host=host), self.assertRaises(ValueError):
                server.endpoint(host)

    def test_detect_ip_uses_direct_ipv4_and_rejects_invalid_responses(self):
        for body, expected in [('8.8.8.8\n', '8.8.8.8'), ('10.0.0.1', None),
                               ('<html>error</html>', None), ('2001:4860:4860::8888', None)]:
            with self.subTest(body=body), patch.object(server.subprocess, 'run',
                    return_value=subprocess.CompletedProcess([], 0, body)) as run:
                self.assertEqual(server.detect_public_ip(), expected)
                command = run.call_args.args[0]
                self.assertIn('-4', command)
                self.assertEqual(command[command.index('--noproxy') + 1], '*')
        for error in (FileNotFoundError(), subprocess.TimeoutExpired('curl', 12)):
            with patch.object(server.subprocess, 'run', side_effect=error):
                self.assertIsNone(server.detect_public_ip())
        with patch.object(server.subprocess, 'run', return_value=subprocess.CompletedProcess([], 22, '8.8.8.8')):
            self.assertIsNone(server.detect_public_ip())

    def test_detected_ip_is_confirmed_or_overridden(self):
        with patch.object(server, 'detect_public_ip', return_value='8.8.8.8'), \
                patch('builtins.input', return_value='') as prompt, patch('builtins.print'):
            self.assertEqual(server.select_address(), '8.8.8.8')
            self.assertIn('Press Enter', prompt.call_args.args[0])
        with patch.object(server, 'detect_public_ip', return_value='8.8.8.8'), \
                patch('builtins.input', return_value='proxy.example.org'), patch('builtins.print'):
            self.assertEqual(server.select_address(), 'proxy.example.org')
        with patch.object(server, 'detect_public_ip', return_value=None), \
                patch('builtins.input', return_value='1.1.1.1'), patch('builtins.print'):
            self.assertEqual(server.select_address(), '1.1.1.1')
        with patch.object(server, 'detect_public_ip') as detect, patch('builtins.input') as prompt:
            self.assertEqual(server.select_address('proxy.example.org'), 'proxy.example.org')
            detect.assert_not_called()
            prompt.assert_not_called()

    def test_credentials_survive_rerun_and_address_change_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            first = server.load_deployment(directory, '8.8.8.8')
            second = server.load_deployment(directory, '8.8.8.8')
            self.assertEqual(first, second)
            self.assertEqual((directory / 'deployment.json').stat().st_mode & 0o777, 0o600)
            with self.assertRaises(ValueError):
                server.load_deployment(directory, '1.1.1.1')
            self.assertEqual(json.loads((directory / 'deployment.json').read_text()), first)

    def test_partial_config_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            (directory / 'client-url').write_text('existing')
            with self.assertRaises(ValueError):
                server.load_deployment(directory, '8.8.8.8')
            self.assertEqual((directory / 'client-url').read_text(), 'existing')

    def test_certificate_and_listener_security(self):
        args = server.certificate_args('8.8.8.8', 'user@example.org')
        self.assertIn('--ip-address', args)
        self.assertIn('shortlived', args)
        self.assertNotIn('--staging', args)
        self.assertNotIn('--ip-address', server.certificate_args('proxy.example.org', 'a@b.org'))
        config = server.gost_config(dict(username='user', password='secret'))['services'][0]
        self.assertEqual(config['listener']['type'], 'tls')
        self.assertEqual(config['handler']['auth']['password'], 'secret')
        self.assertTrue(config['listener']['tls']['keyFile'].endswith('/privkey.pem'))
        chain = direct.gost_config('https://user:secret@8.8.8.8:443', 9999)
        tls = chain['chains'][0]['hops'][0]['nodes'][0]['dialer']['tls']
        self.assertEqual(tls, {'secure': True, 'serverName': '8.8.8.8'})

    def test_probe_never_puts_credentials_in_argv_and_requires_407(self):
        with patch.object(server.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '200')) as run:
            server.probe('https://user:secret@8.8.8.8:443')
            self.assertNotIn('secret', str(run.call_args.args))
            self.assertIn('secret', run.call_args.kwargs['input'])
            with self.assertRaises(RuntimeError):
                server.probe('https://8.8.8.8:443', authenticated=False)
        with patch.object(server.subprocess, 'run', return_value=subprocess.CompletedProcess([], 56, '407')):
            server.probe('https://8.8.8.8:443', authenticated=False)

    @patch.object(client, 'ssh_binary', return_value='/usr/bin/ssh')
    def test_ssh_verifies_host_and_disables_agent_forwarding(self, _):
        args = client.ssh_command('8.8.8.8', 'ubuntu', 22, '/key', '/known-hosts')
        self.assertIn('StrictHostKeyChecking=ask', args)
        self.assertIn('ForwardAgent=no', args)
        self.assertIn('IdentitiesOnly=yes', args)
        self.assertNotIn('-A', args)
        for user in ('-oProxyCommand=x', 'ubuntu;id'):
            with self.assertRaises(ValueError):
                client.ssh_command('8.8.8.8', user, 22, '/key', '/known-hosts')

    def test_remote_upload_fetch_and_cleanup(self):
        secret = 'https://codexproxy:secret@8.8.8.8:443'
        calls = []
        def fake(ssh, command, **kwargs):
            calls.append((command, kwargs))
            output = '/tmp/webstudio-vps.abcdefghij\n' if command[0] == 'mktemp' else ''
            if command[-1] == '/etc/webstudio-egress/client-url':
                output = secret + '\n'
            return subprocess.CompletedProcess([], 0, output)
        with patch.object(client, 'remote', side_effect=fake), patch.object(client, 'probe') as probe, \
                patch.object(client.subprocess, 'run') as cleanup:
            result = client.provision(['ssh', 'ubuntu@8.8.8.8'], '8.8.8.8', 'a@b.org', True)
        self.assertEqual(result, secret)
        probe.assert_called_once_with(secret)
        self.assertNotIn('secret', str([c[0] for c in calls]))
        self.assertIn('sudo', calls[0][0])
        self.assertIn(b'def install(', calls[2][1]['input'])
        self.assertIn('rm -rf', cleanup.call_args.args[0][-1])

    def test_gost_download_checksum_precedes_install(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        state = patch.object(server, 'STATE', Path(temp.name))
        state.start()
        self.addCleanup(state.stop)
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode='w:gz') as bundle:
            member = tarfile.TarInfo('gost')
            member.size = 6
            bundle.addfile(member, io.BytesIO(b'binary'))
        payload = archive.getvalue()
        checksum = hashlib.sha256(payload).hexdigest()
        installed = []
        def run(args, **kwargs):
            if args[0] == 'curl':
                Path(args[args.index('-o') + 1]).write_bytes(payload)
            elif args[0] == 'install':
                installed.append(Path(args[-2]).read_bytes())
            return subprocess.CompletedProcess(args, 0, '')
        with patch.object(server.platform, 'machine', return_value='aarch64'), \
                patch.object(server, 'run', side_effect=run), \
                patch.object(server.urllib.request, 'urlopen', return_value=io.BytesIO(
                    (checksum + '  gost_3.3.3_linux_arm64.tar.gz\n').encode())):
            server.install_gost()
        self.assertEqual(installed, [b'binary'])
        installed.clear()
        with patch.object(server.platform, 'machine', return_value='aarch64'), \
                patch.object(server, 'run', side_effect=run), \
                patch.object(server.urllib.request, 'urlopen', return_value=io.BytesIO(
                    ('0' * 64 + '  gost_3.3.3_linux_arm64.tar.gz\n').encode())):
            with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                server.install_gost()
        self.assertEqual(installed, [])

    def test_container_isolation_and_mounts(self):
        proxy = server.proxy_command()
        certbot = server.certbot_command(server.certificate_args('8.8.8.8', 'a@b.org'))
        for args in (proxy, certbot):
            self.assertIn('--read-only', args)
            self.assertIn('ALL', args)
            self.assertIn('no-new-privileges=true', args)
            self.assertNotIn('--privileged', args)
            self.assertNotIn('host', args)
            self.assertNotIn('docker.sock', str(args))
        self.assertIn('0.0.0.0:443:8443', proxy)
        self.assertIn('0.0.0.0:80:8080', certbot)
        self.assertNotIn('0.0.0.0:80:8080', proxy)
        mounts = [proxy[i + 1] for i, arg in enumerate(proxy) if arg == '--mount']
        self.assertTrue(all(mount.endswith(',readonly') for mount in mounts))
        self.assertNotIn('/accounts', str(proxy))
        self.assertIn('@sha256:', server.GOST_IMAGE)
        self.assertIn('@sha256:', server.CERTBOT_IMAGE)
        self.assertEqual(server.gost_config(dict(username='x', password='y'))['services'][0]['addr'], ':8443')

    def test_renewal_restarts_only_for_unloaded_certificate_and_retries_failure(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(server, 'STATE', Path(temp)), \
                patch.object(server, 'certificate_digest', return_value='new-cert'), \
                patch.object(server, 'run') as run:
            marker = Path(temp) / 'loaded-certificate'
            marker.write_text('old-cert')
            run.side_effect = [None, subprocess.CalledProcessError(1, 'systemctl')]
            with self.assertRaises(subprocess.CalledProcessError):
                server.renew()
            self.assertEqual(marker.read_text(), 'old-cert')
            run.reset_mock(side_effect=True)
            server.renew()
            self.assertEqual(marker.read_text(), 'new-cert\n')
            self.assertTrue(any(call.args[0][:2] == ['systemctl', 'restart'] for call in run.call_args_list))
            run.reset_mock()
            server.renew()
            self.assertEqual(run.call_count, 1)
            server.renew(dry_run=True)
            self.assertIn('--dry-run', run.call_args.args[0])
            self.assertEqual(marker.read_text(), 'new-cert\n')

    def test_container_and_network_conflicts_are_preserved(self):
        unrelated = json.dumps([{'Config': {'Labels': {}}}])
        with patch.object(server.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, unrelated)):
            with self.assertRaisesRegex(ValueError, 'another deployment'):
                server.check_container_names(False)
        network = json.dumps([{'Driver': 'bridge', 'Labels': {}}])
        with patch.object(server.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, network)):
            with self.assertRaisesRegex(ValueError, 'not managed'):
                server.ensure_network()

    def test_remote_failure_still_cleans_up(self):
        with patch.object(client, 'remote', side_effect=[
                subprocess.CompletedProcess([], 0),
                subprocess.CompletedProcess([], 0, '/tmp/webstudio-vps.abcdefghij\n'),
                subprocess.CalledProcessError(1, 'ssh')]), \
                patch.object(client.subprocess, 'run') as cleanup, patch.object(client, 'probe') as probe:
            with self.assertRaises(subprocess.CalledProcessError):
                client.provision(['ssh', 'root@8.8.8.8'], '8.8.8.8', 'a@b.org', True)
            cleanup.assert_called_once()
            probe.assert_not_called()


if __name__ == '__main__':
    unittest.main()
