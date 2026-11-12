// Remove settings owned by the OpenLux setup when returning to official login.
const fs = require('node:fs');
const path = require('node:path');
const [agent, directory] = process.argv.slice(2);
const file = path.join(directory, agent === 'codex' ? 'config.toml' : 'settings.json');
if (!fs.existsSync(file)) process.exit(0);
if (agent === 'codex') {
  let inTable = false;
  let removed = false;
  const content = fs.readFileSync(file, 'utf8').split('\n').filter(line => {
    if (/^\s*\[/.test(line)) inTable = true;
    if (!inTable && /^\s*openai_base_url\s*=\s*["']https:\/\/api\.openlux\.ai\/v1["']/.test(line)) {
      removed = true;
      return false;
    }
    return true;
  }).join('\n');
  if (removed) {
    fs.writeFileSync(file, content);
    const auth = path.join(directory, 'auth.json');
    if (fs.existsSync(auth)) {
      const data = JSON.parse(fs.readFileSync(auth, 'utf8'));
      if (data.auth_mode === 'apikey' || data.OPENAI_API_KEY) {
        delete data.OPENAI_API_KEY;
        if (data.auth_mode === 'apikey') delete data.auth_mode;
        fs.writeFileSync(auth, JSON.stringify(data, null, 2) + '\n', { mode: 0o600 });
      }
    }
  }
} else {
  const settings = JSON.parse(fs.readFileSync(file, 'utf8'));
  if (settings.env?.ANTHROPIC_BASE_URL === 'https://api.openlux.ai') {
    for (const key of ['ANTHROPIC_BASE_URL', 'ANTHROPIC_AUTH_TOKEN', 'CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY', 'CLAUDE_CODE_USE_GATEWAY']) delete settings.env[key];
    fs.writeFileSync(file, JSON.stringify(settings, null, 2) + '\n');
    const stateFile = path.join(directory, '.claude.json');
    if (fs.existsSync(stateFile)) {
      const state = JSON.parse(fs.readFileSync(stateFile, 'utf8'));
      delete state.hasCompletedOnboarding;
      fs.writeFileSync(stateFile, JSON.stringify(state, null, 2) + '\n');
    }
  }
}
