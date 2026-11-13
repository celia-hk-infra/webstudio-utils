// Migrate only installations explicitly pointing at OpenLux; retain private backups.
const fs = require('fs'), path = require('path'), cp = require('child_process');
const root = process.argv[2];
for (const agent of process.argv.slice(3)) {
  if (!['codex', 'claude'].includes(agent)) throw new Error('Unknown agent');
  const source = path.join(root, '.' + agent);
  const config = path.join(source, agent === 'codex' ? 'config.toml' : 'settings.json');
  if (!fs.existsSync(config)) continue;
  const text = fs.readFileSync(config, 'utf8');
  const legacy = agent === 'codex'
    ? /^openai_base_url\s*=\s*["']https:\/\/api\.openlux\.ai\/v1["']/m.test(text.split(/^\s*\[/m)[0])
    : JSON.parse(text).env?.ANTHROPIC_BASE_URL === 'https://api.openlux.ai';
  if (!legacy) continue;
  const target = path.join(root, 'providers/openlux', agent);
  fs.mkdirSync(target, {recursive:true, mode:0o700});
  const backup = fs.mkdtempSync(path.join(root, '.provider-migration-'));
  for (const name of agent === 'codex' ? ['config.toml', 'auth.json'] : ['settings.json', '.claude.json']) {
    const file = path.join(source, name);
    if (!fs.existsSync(file)) continue;
    fs.copyFileSync(file, path.join(backup, name)); fs.chmodSync(path.join(backup, name), 0o600);
    if (!fs.existsSync(path.join(target, name))) {
      fs.copyFileSync(file, path.join(target, name)); fs.chmodSync(path.join(target, name), 0o600);
    }
  }
  const credentialFile = path.join(target, agent === 'codex' ? 'auth.json' : 'settings.json');
  if (fs.existsSync(credentialFile)) {
    const data = JSON.parse(fs.readFileSync(credentialFile, 'utf8'));
    const key = agent === 'codex' ? data.OPENAI_API_KEY : data.env?.ANTHROPIC_AUTH_TOKEN;
    if (key) fs.writeFileSync(path.join(root, 'providers/openlux', agent + '.ready'), '', {mode:0o600});
  }
  cp.execFileSync(process.execPath, [path.join(__dirname,'restore_official.cjs'), agent, source]);
  console.error(`Migrated ${agent} OpenLux settings; official login may be needed. Private backup: ${backup}`);
}
