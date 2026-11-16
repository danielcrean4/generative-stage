// Run with `npm run test:node`. Covers the dev proxy targets and the page title.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { test } = require('node:test');
const { proxyConfig, proxyTargets } = require('./proxy-targets.cjs');

const none = path.join(os.tmpdir(), 'df-no-such-proxy-file.json');

function localFile(content) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'df-proxy-'));
  const file = path.join(dir, 'proxy.local.json');
  fs.writeFileSync(file, content);
  return file;
}

test('defaults are 8780 and 8781', () => {
  assert.deepEqual(proxyTargets({}, none), {
    api: 'http://127.0.0.1:8780',
    readonly: 'http://127.0.0.1:8781',
  });
});

test('environment variables set the targets', () => {
  const env = { GENSTAGE_API_TARGET: 'http://127.0.0.1:4311', GENSTAGE_READONLY_TARGET: 'http://127.0.0.1:4312' };
  assert.deepEqual(proxyTargets(env, none), {
    api: 'http://127.0.0.1:4311',
    readonly: 'http://127.0.0.1:4312',
  });
});

test('the older variable names are still read, and the new ones win', () => {
  const env = { DF_API_TARGET: 'http://127.0.0.1:4311', DF_READONLY_TARGET: 'http://127.0.0.1:4312' };
  assert.deepEqual(proxyTargets(env, none), {
    api: 'http://127.0.0.1:4311',
    readonly: 'http://127.0.0.1:4312',
  });
  env.GENSTAGE_API_TARGET = 'http://127.0.0.1:4313';
  assert.equal(proxyTargets(env, none).api, 'http://127.0.0.1:4313');
});

test('a local file sets one target and the environment wins over it', () => {
  const file = localFile('{"api": "http://127.0.0.1:9000", "readonly": "http://127.0.0.1:9001"}');
  assert.equal(proxyTargets({}, file).api, 'http://127.0.0.1:9000');
  const mixed = proxyTargets({ DF_API_TARGET: 'http://127.0.0.1:9100' }, file);
  assert.deepEqual(mixed, { api: 'http://127.0.0.1:9100', readonly: 'http://127.0.0.1:9001' });
  const partial = proxyTargets({}, localFile('{"readonly": "http://127.0.0.1:9001"}'));
  assert.equal(partial.api, 'http://127.0.0.1:8780');
});

test('bad settings are refused with a message naming the source', () => {
  assert.throws(() => proxyTargets({ DF_API_TARGET: '4311' }, none), /environment: DF_API_TARGET/);
  assert.throws(() => proxyTargets({ DF_API_TARGET: 'ftp://x' }, none), /http:\/\/ or https:\/\//);
  assert.throws(() => proxyTargets({}, localFile('{nope')), /not valid JSON/);
  assert.throws(() => proxyTargets({}, localFile('{"port": 1}')), /unknown key 'port'/);
  assert.throws(() => proxyTargets({}, localFile('[]')), /expected a JSON object/);
});

test('the config keeps the read-only path ahead of /api and sets Origin', () => {
  const config = proxyConfig(proxyTargets({}, none));
  assert.deepEqual(Object.keys(config), ['/api/ro', '/api']);
  assert.equal(config['/api/ro'].headers.Origin, 'http://127.0.0.1:8781');
  assert.equal(config['/api'].target, 'http://127.0.0.1:8780');
});

test('the page title is the tool name', () => {
  const html = fs.readFileSync(path.join(__dirname, 'src/index.html'), 'utf8');
  assert.match(html, /<title>Generative Stage<\/title>/);
});
