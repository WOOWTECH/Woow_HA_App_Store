import assert from 'node:assert/strict';
import { once } from 'node:events';
import { mkdir, mkdtemp, readFile, rm, stat, symlink, writeFile } from 'node:fs/promises';
import { request as httpRequest } from 'node:http';
import { tmpdir } from 'node:os';
import path from 'node:path';
import test from 'node:test';

import {
  BYOK_ENDPOINT,
  DEFAULT_PRIVATE_MARKER,
  PRIVATE_MARKER_HEADER,
  startByokStore,
  validateState,
} from '../rootfs/opt/ha-opendesign/ha-byok-store.mjs';

const timestamp = '2026-09-04T00:00:00.000Z';

function state(revision = 0) {
  return {
    version: 1,
    revision,
    activeProfileId: 'compatible-main',
    profiles: {
      'compatible-main': {
        id: 'compatible-main',
        label: 'Compatible main',
        protocol: 'openai-compatible',
        baseUrl: 'https://provider.example/v1',
        authStyle: 'bearer',
        apiFlavor: 'openai-responses',
        apiKey: 'test-credential-not-for-production',
        model: 'example/model',
        updatedAt: timestamp,
      },
    },
  };
}

async function start(profilesFile) {
  const server = await startByokStore({ profilesFile, host: '127.0.0.1', port: 0 });
  const address = server.address();
  return { server, port: address.port };
}

function call(port, { method = 'GET', body, marker = true, pathname = BYOK_ENDPOINT } = {}) {
  return new Promise((resolve, reject) => {
    const payload = body === undefined ? undefined : JSON.stringify(body);
    const headers = {};
    if (marker) headers[PRIVATE_MARKER_HEADER] = DEFAULT_PRIVATE_MARKER;
    if (payload !== undefined) {
      headers['content-type'] = 'application/json';
      headers['content-length'] = Buffer.byteLength(payload);
    }
    const request = httpRequest({ host: '127.0.0.1', port, method, path: pathname, headers }, (response) => {
      const chunks = [];
      response.on('data', (chunk) => chunks.push(chunk));
      response.on('end', () => resolve({
        status: response.statusCode,
        headers: response.headers,
        text: Buffer.concat(chunks).toString('utf8'),
        body: JSON.parse(Buffer.concat(chunks).toString('utf8')),
      }));
    });
    request.once('error', reject);
    if (payload !== undefined) request.write(payload);
    request.end();
  });
}

async function withStorage(run) {
  const root = await mkdtemp(path.join(tmpdir(), 'ha-opendesign-byok-store-'));
  const credentials = path.join(root, 'data', 'opendesign', 'credentials');
  const profilesFile = path.join(credentials, 'byok-profiles.json');
  await mkdir(credentials, { recursive: true, mode: 0o700 });
  await (await import('node:fs/promises')).chmod(credentials, 0o700);
  try {
    await run({ root, credentials, profilesFile });
  } finally {
    await rm(root, { recursive: true, force: true });
  }
}

test('profile state validation accepts all four supported provider protocols only', () => {
  const official = ['anthropic', 'openai', 'google'];
  for (const protocol of official) {
    const candidate = state();
    candidate.profiles['compatible-main'] = {
      id: 'compatible-main',
      label: 'Official provider',
      protocol,
      apiKey: candidate.profiles['compatible-main'].apiKey,
      model: 'official-model',
      updatedAt: timestamp,
    };
    assert.equal(validateState(candidate).profiles['compatible-main'].protocol, protocol);
  }
  const candidate = state();
  candidate.profiles['compatible-main'].protocol = 'unsupported';
  assert.throws(() => validateState(candidate));
});

test('profile store rejects direct calls and supports marker-authenticated full-state persistence', async () => {
  await withStorage(async ({ credentials, profilesFile }) => {
    const { server, port } = await start(profilesFile);
    try {
      const direct = await call(port, { marker: false });
      assert.equal(direct.status, 403);
      assert.equal(direct.headers['cache-control'], 'no-store');

      const concurrent = await Promise.all([
        call(port, { method: 'PUT', body: state() }),
        call(port, { method: 'PUT', body: state() }),
      ]);
      assert.deepEqual(concurrent.map((response) => response.status).sort(), [200, 409]);
      const created = concurrent.find((response) => response.status === 200);
      assert.equal(created.body.revision, 1);
      assert.equal(created.headers['cache-control'], 'no-store');

      const read = await call(port);
      assert.equal(read.status, 200);
      assert.equal(read.body.activeProfileId, 'compatible-main');
      assert.equal(typeof read.body.profiles['compatible-main'].apiKey, 'string');
      assert.equal(read.body.profiles['compatible-main'].apiKey.length, state().profiles['compatible-main'].apiKey.length);

      const stale = await call(port, { method: 'PUT', body: state(0) });
      assert.equal(stale.status, 409);

      const invalid = state(1);
      invalid.profiles['compatible-main'].baseUrl = 'http://not-https.example';
      const rejected = await call(port, { method: 'PUT', body: invalid });
      assert.equal(rejected.status, 400);
      assert.doesNotMatch(rejected.text, /test-credential-not-for-production/);
      assert.equal((await stat(credentials)).mode & 0o777, 0o700);
      assert.equal((await stat(profilesFile)).mode & 0o777, 0o600);
      assert.equal((await stat(profilesFile)).uid, process.getuid());
    } finally {
      server.close();
      await once(server, 'close');
    }
  });
});

test('profile store rejects symlinked credential directories and files without following them', async () => {
  const root = await mkdtemp(path.join(tmpdir(), 'ha-opendesign-byok-symlink-'));
  try {
    const outside = path.join(root, 'outside');
    await mkdir(outside, { mode: 0o700 });
    const linkedCredentials = path.join(root, 'data', 'opendesign', 'credentials');
    await mkdir(path.dirname(linkedCredentials), { recursive: true, mode: 0o700 });
    await symlink(outside, linkedCredentials);
    let store = await start(path.join(linkedCredentials, 'byok-profiles.json'));
    try {
      assert.equal((await call(store.port)).status, 500);
      assert.equal((await call(store.port, { method: 'PUT', body: state() })).status, 500);
      await assert.rejects(readFile(path.join(outside, 'byok-profiles.json'), 'utf8'));
    } finally {
      store.server.close();
      await once(store.server, 'close');
    }

    const credentials = path.join(root, 'credentials');
    await mkdir(credentials, { mode: 0o700 });
    const target = path.join(root, 'outside-profile.json');
    await writeFile(target, '{"outside":true}\n', { mode: 0o600 });
    await symlink(target, path.join(credentials, 'byok-profiles.json'));
    store = await start(path.join(credentials, 'byok-profiles.json'));
    try {
      assert.equal((await call(store.port)).status, 500);
      assert.equal((await call(store.port, { method: 'PUT', body: state() })).status, 500);
      assert.equal(await readFile(target, 'utf8'), '{"outside":true}\n');
    } finally {
      store.server.close();
      await once(store.server, 'close');
    }
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test('profile store persists a safely written state across sidecar restart', async () => {
  await withStorage(async ({ profilesFile }) => {
    let store = await start(profilesFile);
    try {
      assert.equal((await call(store.port, { method: 'PUT', body: state() })).status, 200);
    } finally {
      store.server.close();
      await once(store.server, 'close');
    }
    store = await start(profilesFile);
    try {
      const persisted = await call(store.port);
      assert.equal(persisted.status, 200);
      assert.equal(persisted.body.revision, 1);
      assert.equal(persisted.body.profiles['compatible-main'].model, 'example/model');
    } finally {
      store.server.close();
      await once(store.server, 'close');
    }
  });
});
