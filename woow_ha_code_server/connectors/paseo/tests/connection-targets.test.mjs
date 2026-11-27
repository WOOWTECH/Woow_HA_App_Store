import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { CONNECTION_TARGETS, connectionTarget, targetConfiguration, targetPairUrl } from '../src/connection-targets.mjs';

const offer = (target, extra = {}) => {
  const payload = {
    v: 2,
    serverId: 'server-id',
    daemonPublicKeyB64: 'public-key',
    relay: { endpoint: target.relayEndpoint, useTls: true },
    ...extra,
  };
  return `${target.appUrl}/#offer=${Buffer.from(JSON.stringify(payload)).toString('base64url')}`;
};

test('publishes exactly the three canonical target profiles', () => {
  assert.deepEqual(CONNECTION_TARGETS.map(({ id, appUrl, relayEndpoint, protectedRelay }) => ({ id, appUrl, relayEndpoint, protectedRelay })), [
    { id: 'paseo', appUrl: 'https://app.paseo.sh', relayEndpoint: 'relay.paseo.sh:443', protectedRelay: true },
    { id: 'woowtech', appUrl: 'https://smart.woowtech.io', relayEndpoint: 'relay.woowtech.io:443', protectedRelay: false },
    { id: 'apporo', appUrl: 'https://smart.apporo.ai', relayEndpoint: 'relay.apporo.ai:443', protectedRelay: false },
  ]);
  assert.throws(() => connectionTarget('custom'), { code: 'INVALID_TARGET' });
});

test('pair URLs require exact origin, V2, selected relay and TLS', () => {
  for (const target of CONNECTION_TARGETS) assert.equal(targetPairUrl(offer(target), target.id), offer(target));
  const paseo = connectionTarget('paseo');
  assert.throws(() => targetPairUrl(offer(paseo).replace('app.paseo.sh', 'smart.woowtech.io'), 'paseo'), { code: 'PAIRING_ORIGIN_INVALID' });
  assert.throws(() => targetPairUrl(offer(paseo, { v: 1 }), 'paseo'), { code: 'PAIRING_TARGET_MISMATCH' });
  assert.throws(() => targetPairUrl(offer(paseo, { relay: { endpoint: 'relay.apporo.ai:443', useTls: true } }), 'paseo'), { code: 'PAIRING_TARGET_MISMATCH' });
  assert.throws(() => targetPairUrl(offer(paseo, { relay: { endpoint: paseo.relayEndpoint, useTls: false } }), 'paseo'), { code: 'PAIRING_TARGET_MISMATCH' });
  assert.throws(() => targetPairUrl(offer(paseo) + '&leak=1', 'paseo'), { code: 'PAIRING_ORIGIN_INVALID' });
});

test('Smart profiles reject protected-only offers and config pins one origin/relay', () => {
  const smart = connectionTarget('woowtech');
  assert.throws(() => targetPairUrl(offer(smart, { minimumSecurityMode: 'protected' }), smart.id), { code: 'PAIRING_SECURITY_UNSUPPORTED' });
  const config = targetConfiguration({ daemon: { cors: { allowedOrigins: ['https://app.paseo.sh', 'https://unrelated.example'] } } }, smart.id);
  assert.equal(config.app.baseUrl, smart.appUrl);
  assert.deepEqual(config.daemon.cors.allowedOrigins, ['https://unrelated.example', smart.appUrl]);
  assert.deepEqual(config.daemon.relay, { enabled: true, endpoint: smart.relayEndpoint, publicEndpoint: smart.relayEndpoint, useTls: true, publicUseTls: true, requireProtectedSecurity: false });
});

test('Paseo requires protected relay security on fresh configuration and after either Smart profile', () => {
  const configurations = [
    {},
    { daemon: { relay: { requireProtectedSecurity: false } } },
    targetConfiguration({}, 'woowtech'),
    targetConfiguration({}, 'apporo'),
  ];
  for (const config of configurations) {
    assert.equal(targetConfiguration(config, 'paseo').daemon.relay.requireProtectedSecurity, true);
  }
  for (const target of ['woowtech', 'apporo']) {
    assert.equal(targetConfiguration(targetConfiguration({}, 'paseo'), target).daemon.relay.requireProtectedSecurity, false);
    assert.equal(targetConfiguration({ daemon: { relay: { requireProtectedSecurity: true } } }, target).daemon.relay.requireProtectedSecurity, false);
  }
});

// Use an installed runtime's config.js, as in the immutable Pi source's SDK checks.
const sdkConfig = process.env.PI_PASEO_TEST_PERSISTED_CONFIG;
test('installed SDK resolves the selected profile security policy on fresh configuration and target switches', {
  skip: sdkConfig ? false : 'Set PI_PASEO_TEST_PERSISTED_CONFIG to the installed SDK config.js',
}, async () => {
  const { resolveConfigFromPersisted } = await import(pathToFileURL(path.resolve(sdkConfig)).href);
  for (const [target, initial, expected] of [
    ['paseo', {}, true],
    ['paseo', targetConfiguration({}, 'woowtech'), true],
    ['paseo', targetConfiguration({}, 'apporo'), true],
    ['woowtech', targetConfiguration({}, 'paseo'), false],
    ['apporo', targetConfiguration({}, 'paseo'), false],
  ]) {
    const config = targetConfiguration(initial, target);
    const resolved = resolveConfigFromPersisted('/nonexistent-agent-connect-config-probe', config, { env: {} });
    assert.equal(resolved.relayRequireProtectedSecurity, expected, target);
    assert.equal(resolved.relayEndpoint, connectionTarget(target).relayEndpoint);
    assert.equal(resolved.relayUseTls, true);
  }
});
