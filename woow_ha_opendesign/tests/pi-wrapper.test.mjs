import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import test from 'node:test';

import {
  buildPiArgs,
  createTransientPiConfig,
  profileToPiConfig,
  validateActiveProfile,
} from '../rootfs/opt/ha-opendesign/ha-pi-wrapper.mjs';

const profile = {
  id: 'openrouter-main',
  label: 'OpenRouter main',
  protocol: 'openai-compatible',
  baseUrl: 'https://openrouter.ai/api/v1',
  authStyle: 'bearer',
  apiFlavor: 'openai-completions',
  apiKey: 'TEST_KEY_DO_NOT_PERSIST',
  model: 'anthropic/claude-sonnet-4.6',
  updatedAt: '2026-09-04T00:00:00.000Z',
};

test('profile validation permits only the approved Pi provider kinds', () => {
  assert.deepEqual(validateActiveProfile(profile), profile);
  assert.throws(
    () => validateActiveProfile({ ...profile, protocol: 'unknown' }),
    /unsupported profile protocol/,
  );
  assert.throws(
    () => validateActiveProfile({ ...profile, baseUrl: 'http://localhost:8080' }),
    /HTTPS base URL/,
  );
  assert.throws(
    () => validateActiveProfile({ ...profile, apiKey: '' }),
    /API key/,
  );
});

test('profile mapping uses environment interpolation and preserves API-key header mode', () => {
  const compatible = profileToPiConfig(profile);
  assert.deepEqual(compatible, {
    providers: {
      'ha-profile': {
        baseUrl: 'https://openrouter.ai/api/v1',
        api: 'openai-completions',
        apiKey: '$OD_PI_PROFILE_KEY',
        authHeader: true,
        models: [{ id: 'anthropic/claude-sonnet-4.6', name: 'anthropic/claude-sonnet-4.6' }],
      },
    },
  });

  const apiKeyHeader = profileToPiConfig({ ...profile, authStyle: 'api-key' });
  assert.equal(apiKeyHeader.providers['ha-profile'].authHeader, false);
  assert.deepEqual(apiKeyHeader.providers['ha-profile'].headers, { 'api-key': '$OD_PI_PROFILE_KEY' });

  assert.equal(profileToPiConfig({ ...profile, protocol: 'anthropic' }).providers['ha-profile'].api, 'anthropic-messages');
  assert.equal(profileToPiConfig({ ...profile, protocol: 'openai' }).providers['ha-profile'].api, 'openai-responses');
  assert.equal(profileToPiConfig({ ...profile, protocol: 'google' }).providers['ha-profile'].api, 'google-generative-ai');
});

test('Pi invocation forces the active profile model and strips caller model override', () => {
  assert.deepEqual(
    buildPiArgs(['--mode', 'rpc', '--model', 'attacker/model', '--thinking', 'high'], profile),
    ['--mode', 'rpc', '--thinking', 'high', '--model', 'ha-profile/anthropic/claude-sonnet-4.6', '--no-session'],
  );
});

test('transient Pi config has restrictive modes and never contains the profile API key', async () => {
  const root = await mkdtemp(path.join(tmpdir(), 'ha-opendesign-pi-wrapper-test-'));
  try {
    const runtime = await createTransientPiConfig(profile, root);
    const config = await readFile(runtime.modelsPath, 'utf8');
    assert.match(config, /\$OD_PI_PROFILE_KEY/);
    assert.doesNotMatch(config, /TEST_KEY_DO_NOT_PERSIST/);
    assert.equal((await (await import('node:fs/promises')).stat(runtime.dir)).mode & 0o777, 0o700);
    assert.equal((await (await import('node:fs/promises')).stat(runtime.modelsPath)).mode & 0o777, 0o600);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
