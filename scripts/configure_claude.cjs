// Merge gateway settings and an optional replacement key, preserving preferences.
const fs = require('node:fs');
const path = require('node:path');
const filename = process.argv[2];
const apiKey = process.argv.includes('--key-stdin') ? fs.readFileSync(0, 'utf8') : '';
if (/\s/.test(apiKey)) throw new Error('The API key must not contain whitespace.');
function readJson(file) {
  if (!fs.existsSync(file)) return {};
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch {
    throw new Error(`Could not read valid JSON from ${file}; existing files were left unchanged.`);
  }
}
// Onboarding uses Anthropic's OAuth endpoints, independently of the API URL.
// This installation supplies its own gateway configuration instead.
const stateFilename = path.join(path.dirname(filename), '.claude.json');
const state = readJson(stateFilename);
if (!state || Array.isArray(state) || typeof state !== 'object') {
  throw new Error('Claude state must be a JSON object; existing files were left unchanged.');
}
const settings = readJson(filename);
if (!settings || Array.isArray(settings) || typeof settings !== 'object' ||
    (settings.env !== undefined && (!settings.env || Array.isArray(settings.env) || typeof settings.env !== 'object'))) {
  throw new Error('Claude settings and env must be JSON objects; existing file was left unchanged.');
}
settings.env = { ...settings.env, ANTHROPIC_BASE_URL: 'https://api.openlux.ai', CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY: '1' };
if (apiKey) settings.env.ANTHROPIC_AUTH_TOKEN = apiKey;
// Explicit gateway mode disables model discovery in Claude Code 2.1.322.
delete settings.env.CLAUDE_CODE_USE_GATEWAY;
const temporary = filename + '.tmp-' + process.pid;
fs.writeFileSync(temporary, JSON.stringify(settings, null, 2) + '\n', { mode: 0o600, flag: 'wx' });
fs.renameSync(temporary, filename);
state.hasCompletedOnboarding = true;
const stateTemporary = stateFilename + '.tmp-' + process.pid;
fs.writeFileSync(stateTemporary, JSON.stringify(state, null, 2) + '\n', { mode: 0o600, flag: 'wx' });
fs.renameSync(stateTemporary, stateFilename);
