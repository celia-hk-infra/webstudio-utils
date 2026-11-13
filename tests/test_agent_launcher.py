import os
from pathlib import Path
import subprocess
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[1]
class LauncherTests(unittest.TestCase):
    def run_agent(self, args, backup=False, egress=False):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d); (p/'bin').mkdir()
            real=p/'bin/codex-real'
            real.write_text('#!/bin/bash\nprintf "%s\\n" "$CODEX_HOME" "$@"\n'); real.chmod(0o700)
            if backup:
                q=p/'providers/openlux';q.mkdir(parents=True);(q/'codex.ready').touch()
            if egress:
                q=p/'egress';q.mkdir();(q/'connection.env').write_text('invalid')
            env=dict(os.environ,WEBSTUDIO_AGENT_STATE_DIR=d,WEBSTUDIO_PROVIDER='auto')
            return subprocess.run(['bash',str(ROOT/'scripts/agent-launch.sh'),'codex']+args,env=env,capture_output=True,text=True)
    def test_official_embedded(self):
        r=self.run_agent([]);self.assertEqual(r.returncode,0);self.assertIn('/.codex\n--no-daemon',r.stdout)
    def test_login_no_tui_flag(self):
        r=self.run_agent(['login','status']);self.assertNotIn('--no-daemon',r.stdout)
    def test_openlux_isolated(self):
        r=self.run_agent(['--provider','openlux'],backup=True);self.assertEqual(r.returncode,0);self.assertIn('/providers/openlux/codex',r.stdout)
    def test_no_unattended_fallback(self):
        r=self.run_agent([],backup=True,egress=True);self.assertNotEqual(r.returncode,0);self.assertEqual(r.stdout,'')
    def test_help_offline(self):
        r=self.run_agent(['--help'],egress=True);self.assertEqual(r.returncode,0)

    def test_migrate_keeps_private_backup_and_other_settings(self):
        import json
        with tempfile.TemporaryDirectory() as d:
            p=Path(d); q=p/'.codex';q.mkdir()
            (q/'config.toml').write_text('openai_base_url = "https://api.openlux.ai/v1"\nmodel = "example"\n')
            (q/'auth.json').write_text(json.dumps({'auth_mode':'apikey','OPENAI_API_KEY':'fake-test-key'}))
            r=subprocess.run(['node',str(ROOT/'scripts/migrate_agent_providers.cjs'),d,'codex'],capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stderr)
            self.assertIn('example',(q/'config.toml').read_text())
            self.assertNotIn('fake-test-key',(q/'auth.json').read_text())
            self.assertEqual(json.loads((p/'providers/openlux/codex/auth.json').read_text())['OPENAI_API_KEY'],'fake-test-key')
            self.assertEqual(len(list(p.glob('.provider-migration-*'))),1)
