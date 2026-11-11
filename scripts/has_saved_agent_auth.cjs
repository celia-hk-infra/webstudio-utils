// Report only presence; never print credential contents.
const fs = require('node:fs');
const path = require('node:path');
const [codexDir, claudeDir, skipCodex, skipClaude] = process.argv.slice(2);
function read(filename) {
  if (!fs.existsSync(filename)) return {};
  return JSON.parse(fs.readFileSync(filename, 'utf8'));
}
function hasKey(value) {
  return typeof value === 'string' && value.length > 0 && !/\s/.test(value);
}
try {
  const codexReady = skipCodex === '1' || hasKey(read(path.join(codexDir, 'auth.json'))?.OPENAI_API_KEY);
  const claudeReady = skipClaude === '1' || hasKey(read(path.join(claudeDir, 'settings.json'))?.env?.ANTHROPIC_AUTH_TOKEN);
  console.log(codexReady && claudeReady);
} catch {
  console.error('Could not read saved agent credentials. Repair invalid JSON before rerunning setup.');
  process.exitCode = 1;
}
