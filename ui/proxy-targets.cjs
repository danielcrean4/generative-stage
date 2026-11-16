// Where the dev server sends /api calls. Defaults: the main API on 8780, the read-only API on 8781.
// To change them, set GENSTAGE_API_TARGET and GENSTAGE_READONLY_TARGET (full addresses, such as
// http://127.0.0.1:4311), or put {"api": "...", "readonly": "..."} in ui/proxy.local.json
// (not committed). The environment wins over the file; either may set just one. The older names
// DF_API_TARGET and DF_READONLY_TARGET are still read, with a note, for one release.
const fs = require('node:fs');
const path = require('node:path');

const DEFAULTS = { api: 'http://127.0.0.1:8780', readonly: 'http://127.0.0.1:8781' };
const LOCAL_FILE = path.join(__dirname, 'proxy.local.json');

function readLocal(file) {
  if (!fs.existsSync(file)) return {};
  let raw;
  try {
    raw = JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch (error) {
    throw new Error(`${file}: not valid JSON (${error.message})`);
  }
  if (raw === null || typeof raw !== 'object' || Array.isArray(raw)) {
    throw new Error(`${file}: expected a JSON object`);
  }
  for (const key of Object.keys(raw)) {
    if (!(key in DEFAULTS)) throw new Error(`${file}: unknown key '${key}' (known: api, readonly)`);
  }
  return raw;
}

function check(source, name, value) {
  let url;
  try {
    url = new URL(value);
  } catch {
    throw new Error(`${source}: ${name} must be a full address such as http://127.0.0.1:8780`);
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') {
    throw new Error(`${source}: ${name} must start with http:// or https://`);
  }
  return url.origin;
}

function fromEnvironment(env, key) {
  const name = `GENSTAGE_${key.toUpperCase()}_TARGET`;
  const old = `DF_${key.toUpperCase()}_TARGET`;
  if (env[name]) return [name, env[name]];
  if (env[old]) {
    console.warn(`note: ${old} is deprecated and will stop working; set ${name} instead`);
    return [old, env[old]];
  }
  return [name, undefined];
}

function proxyTargets(env = process.env, file = LOCAL_FILE) {
  const local = readLocal(file);
  const targets = {};
  for (const key of Object.keys(DEFAULTS)) {
    const [name, value] = fromEnvironment(env, key);
    if (value) targets[key] = check('environment', name, value);
    else if (local[key] !== undefined) targets[key] = check(file, key, local[key]);
    else targets[key] = DEFAULTS[key];
  }
  return targets;
}

function proxyConfig(targets) {
  const entry = (target) => ({
    target,
    secure: false,
    changeOrigin: true,
    headers: { Origin: target },
  });
  // The read-only path comes first: the proxy takes the first matching path.
  return { '/api/ro': entry(targets.readonly), '/api': entry(targets.api) };
}

module.exports = { DEFAULTS, proxyTargets, proxyConfig };
