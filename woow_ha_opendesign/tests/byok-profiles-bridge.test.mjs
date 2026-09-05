import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const bridge = require('../rootfs/opt/ha-opendesign/ha-byok-profiles-bridge.js');

const profile = {
  id: 'main',
  label: 'Main profile',
  protocol: 'openai-compatible',
  baseUrl: 'https://example.invalid/v1',
  authStyle: 'bearer',
  apiFlavor: 'openai-completions',
  apiKey: 'test-only-key',
  model: 'example/model',
};

function state(overrides = {}) {
  return {
    version: 1,
    revision: 4,
    activeProfileId: 'main',
    profiles: { main: profile },
    ...overrides,
  };
}

function response(body, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

function storage(initial = {}) {
  const values = new Map(Object.entries(initial));
  return {
    getItem(key) { return values.has(key) ? values.get(key) : null; },
    setItem(key, value) { values.set(key, value); },
  };
}

function browserRoot(fetcher, localStorage = storage()) {
  const events = [];
  return {
    Event: class { constructor(type) { this.type = type; } },
    StorageEvent: class {
      constructor(type, init) { this.type = type; Object.assign(this, init); }
    },
    dispatchEvent(event) { events.push(event); },
    events,
    fetch: fetcher,
    localStorage,
    location: { href: 'http://ha.invalid/settings' },
  };
}

test('profile client reads persistent profiles with a no-store GET', async () => {
  const calls = [];
  const client = new bridge.ProfilesClient(async (url, init) => {
    calls.push({ url, init });
    return response(state());
  });

  const loaded = await client.get();
  assert.equal(loaded.revision, 4);
  assert.equal(loaded.activeProfileId, 'main');
  assert.deepEqual(calls, [{
    url: '/api/ha-opendesign/byok/profiles',
    init: { cache: 'no-store' },
  }]);
});

test('profile client replaces full state through revisioned no-store PUT', async () => {
  const calls = [];
  const next = state({ revision: 5 });
  const client = new bridge.ProfilesClient(async (url, init) => {
    calls.push({ url, init });
    return response(next);
  });

  const saved = await client.put(next);
  assert.equal(saved.revision, 5);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, '/api/ha-opendesign/byok/profiles');
  assert.equal(calls[0].init.method, 'PUT');
  assert.equal(calls[0].init.cache, 'no-store');
  assert.equal(calls[0].init.headers['content-type'], 'application/json');
  assert.equal(JSON.parse(calls[0].init.body).revision, 5);
});

test('profile client reports a stale revision as reload-and-retry without reading an error body', async () => {
  const client = new bridge.ProfilesClient(async () => response({}, 409));
  await assert.rejects(client.put(state()), (error) => error.code === 'conflict'
    && error.message === 'Profiles changed in another session. Reload and retry.');
});

test('active persistent profile selects Pi Local CLI and its authoritative model through public storage/config events', () => {
  const calls = [];
  const localStorage = storage({
    'open-design:config': JSON.stringify({
      onboardingCompleted: true,
      agentId: 'codex',
      agentModels: { codex: { model: 'default' } },
    }),
  });
  const root = browserRoot((url, init) => {
    calls.push({ url, init });
    return Promise.resolve(response({ ok: true }));
  }, localStorage);
  const api = bridge.createForRoot(root);

  const configured = api.configurePiForProfile(profile);
  assert.equal(configured.mode, 'daemon');
  assert.equal(configured.agentId, 'pi');
  assert.equal(configured.agentModels.pi.model, 'example/model');
  assert.equal(JSON.parse(localStorage.getItem('open-design:config')).agentModels.pi.model, 'example/model');
  assert.equal(root.events.length, 1);
  assert.equal(root.events[0].type, 'storage');
  assert.equal(root.events[0].key, 'open-design:config');
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, '/api/app-config');
  assert.equal(calls[0].init.method, 'PUT');
  assert.deepEqual(JSON.parse(calls[0].init.body), {
    agentId: 'pi',
    agentModels: { codex: { model: 'default' }, pi: { model: 'example/model' } },
  });
});
