import test from 'node:test';
import assert from 'node:assert/strict';
import {refreshSharedMcp} from '../src/mcp-refresh.mjs';

const codes = ['SESSION_BUSY', 'MCP_RESUME_UNAVAILABLE', 'MCP_NATIVE_UNAVAILABLE', 'MCP_CONFIG_INVALID'];
const original = {id: 'original-agent', provider: 'claude', status: 'idle', persistence: {provider: 'claude', sessionId: 'original-native'}};
const wrapped = code => Object.assign(new Error(`${code} requestType=refresh_agent_request code=agent_refresh_failed`), {
  name: 'DaemonRpcError', requestType: 'refresh_agent_request', code: 'agent_refresh_failed', requestId: 'private-request-id',
});

async function rejected(error, expected) {
  let reads = 0, refreshes = 0, syncs = 0;
  const client = {
    async fetchAgent() { reads++; return {agent: original}; },
    async refreshAgent(id) { assert.equal(id, original.id); refreshes++; throw error; },
  };
  await assert.rejects(refreshSharedMcp(client, original.id, async () => { syncs++; return {}; }), result => {
    assert.equal(result.code, expected);
    assert.equal(result.message, expected);
    assert.equal(result.cause, undefined);
    assert.equal(JSON.stringify(result).includes('private-'), false);
    return true;
  });
  assert.deepEqual({reads, refreshes, syncs}, {reads: 1, refreshes: 1, syncs: 1});
  assert.equal(original.persistence.sessionId, 'original-native');
}

test('preserves all guarded refresh codes from exact pinned DaemonRpcError envelopes without retry', async () => {
  for (const code of codes) await rejected(wrapped(code), code);
});

test('preserves bare codes and structured refresh codes without exposing diagnostic text', async () => {
  for (const code of codes) {
    await rejected(new Error(code), code);
    await rejected(Object.assign(new Error('private-diagnostic'), {requestType: 'refresh_agent_request', code}), code);
  }
});

test('unknown, malformed, other-request and secret-bearing envelopes remain generic', async () => {
  const good = 'MCP_NATIVE_UNAVAILABLE';
  for (const error of [
    wrapped('private-server-diagnostic'),
    Object.assign(wrapped(good), {requestType: 'create_agent_request'}),
    Object.assign(wrapped(good), {code: 'private-code'}),
    Object.assign(wrapped(good), {name: 'Error'}),
    Object.assign(wrapped(good), {message: `${wrapped(good).message} private-token`}),
    Object.assign(wrapped(good), {message: `private-prefix ${wrapped(good).message}`}),
    Object.assign(new Error('private-diagnostic'), {code: good}),
    new Error(`${good} private-token`),
    null,
  ]) await rejected(error, 'MCP_RELOAD_FAILED');
});
