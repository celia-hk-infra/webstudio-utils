import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/direct_egress.py'
SPEC = importlib.util.spec_from_file_location('direct_egress', SCRIPT)
direct = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(direct)


class DirectEgressTests(unittest.TestCase):
    def test_url_requires_authenticated_tls(self):
        for url in ('http://user:pass@host:8443', 'https://host:8443',
                    'https://user:pass@host:8443/path',
                    'https://user:pass@host:99999'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                direct.valid_url(url)

    def test_launcher_uses_direct_proxy_and_keeps_secret_off_output(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            (state / 'bin').mkdir()
            (state / 'egress').mkdir()
            secret = 'test-proxy-secret'
            url = f'https://codexproxy:{secret}@egress.example.org:8443'
            config = state / 'egress/direct-proxy.json'
            config.write_text(json.dumps({'proxy_url': url}))
            config.chmod(0o600)
            real = state / 'bin/codex-real'
            real.write_text('#!/usr/bin/env python3\nimport os\nassert os.environ["HTTPS_PROXY"].startswith("https://codexproxy:")\nprint("routed")\n')
            real.chmod(0o700)
            mock = state / 'curl'
            mock.write_text('#!/usr/bin/env python3\nimport os,sys\nsys.exit(0 if os.environ.get("HTTPS_PROXY", "").startswith("https://codexproxy:") else 1)\n')
            mock.chmod(0o700)
            env = os.environ.copy()
            env.update(WEBSTUDIO_AGENT_STATE_DIR=directory,
                       WEBSTUDIO_GOST_BIN=str(state / 'missing-gost'),
                       WEBSTUDIO_PROVIDER='auto', PATH=f'{directory}:{env["PATH"]}')
            result = subprocess.run(['bash', str(ROOT / 'scripts/agent-launch.sh'), 'codex'],
                                    env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, 'routed\n')
            self.assertNotIn(secret, result.stderr)
            self.assertIn('direct VPS egress', result.stderr)

    def test_configure_saves_private_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'egress/direct-proxy.json'
            url = 'https://user:longsecret@egress.example.org:8443'
            with patch.object(direct.getpass, 'getpass', return_value=url):
                direct.configure(path)
            self.assertEqual(direct.read_url(path), url)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_private_config_required(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'direct-proxy.json'
            path.write_text(json.dumps({'proxy_url': 'https://user:pass@host:8443'}))
            path.chmod(0o644)
            with self.assertRaises(ValueError):
                direct.read_url(path)

    def test_local_gost_chain_verifies_tls_and_keeps_upstream_auth(self):
        config = direct.gost_config('https://user:pass@egress.example.org:443', 12345)
        self.assertEqual(config['services'][0]['addr'], '127.0.0.1:12345')
        node = config['chains'][0]['hops'][0]['nodes'][0]
        self.assertEqual(node['connector']['auth'], {'username': 'user', 'password': 'pass'})
        self.assertEqual(node['dialer']['tls'], {'secure': True, 'serverName': 'egress.example.org'})


if __name__ == '__main__':
    unittest.main()
