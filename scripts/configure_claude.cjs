// Merge the gateway setting without replacing credentials or other preferences.
const fs = require('node:fs');
const filename = process.argv[2];
const settings = fs.existsSync(filename) ? JSON.parse(fs.readFileSync(filename, 'utf8')) : {};
if (!settings || Array.isArray(settings) || typeof settings !== 'object' ||
    (settings.env !== undefined && (!settings.env || Array.isArray(settings.env) || typeof settings.env !== 'object'))) {
  throw new Error('Claude settings and env must be JSON objects; existing file was left unchanged.');
}
settings.env = { ...settings.env, ANTHROPIC_BASE_URL: 'https://api.openlux.ai', CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY: '1' };
// Explicit gateway mode disables model discovery in Claude Code 2.1.322.
delete settings.env.CLAUDE_CODE_USE_GATEWAY;
const temporary = filename + '.tmp-' + process.pid;
fs.writeFileSync(temporary, JSON.stringify(settings, null, 2) + '\n', { mode: 0o600, flag: 'wx' });
fs.renameSync(temporary, filename);
