import assert from 'node:assert/strict';
import { once } from 'node:events';
import { createServer } from 'node:http';

// This is deliberately not a credential. It exercises the native browser
// request shape without putting a usable key in an image, /data, or test logs.
const FAKE_API_KEY = 'od-byok-test-key-not-a-secret';
const MODEL = 'od-byok-stream-model';
const COMPLETION = 'OD_BYOK_OPENCODE_STREAM_OK';
const daemonUrl = process.env.OD_BYOK_DAEMON_URL || 'http://127.0.0.1:8099';
const projectId = `byok-opencode-${process.pid}`;
const requests = [];

function fail(message) {
  throw new Error(message);
}

async function fetchWithTimeout(url, options) {
  const signal = AbortSignal.timeout(60_000);
  return fetch(url, { ...options, signal });
}

const provider = createServer((request, response) => {
  let body = '';
  request.setEncoding('utf8');
  request.on('data', (chunk) => { body += chunk; });
  request.on('end', () => {
    let parsedBody;
    try {
      parsedBody = JSON.parse(body);
    } catch {
      parsedBody = null;
    }
    requests.push({
      method: request.method,
      path: request.url,
      authorization: request.headers.authorization,
      model: parsedBody?.model,
      stream: parsedBody?.stream,
    });

    const authenticated = request.method === 'POST'
      && request.url === '/v1/chat/completions'
      && request.headers.authorization === `Bearer ${FAKE_API_KEY}`
      && parsedBody?.model === MODEL
      && parsedBody?.stream === true;
    if (!authenticated) {
      response.writeHead(401, { 'content-type': 'application/json' });
      response.end('{"error":{"message":"mock authentication or request mismatch"}}');
      return;
    }

    response.writeHead(200, {
      'cache-control': 'no-cache',
      connection: 'keep-alive',
      'content-type': 'text/event-stream; charset=utf-8',
    });
    const chunk = (delta, finishReason = null) => JSON.stringify({
      id: 'od-byok-mock-stream',
      object: 'chat.completion.chunk',
      created: 0,
      model: MODEL,
      choices: [{ index: 0, delta, finish_reason: finishReason }],
    });
    response.write(`data: ${chunk({ role: 'assistant', content: COMPLETION })}\n\n`);
    response.write(`data: ${chunk({}, 'stop')}\n\n`);
    response.end('data: [DONE]\n\n');
  });
});

provider.listen(0, '127.0.0.1');
await once(provider, 'listening');
const address = provider.address();
if (!address || typeof address === 'string') fail('mock provider did not bind a TCP port');

try {
  const projectResponse = await fetchWithTimeout(`${daemonUrl}/api/projects`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      id: projectId,
      name: 'Native OpenCode BYOK streaming smoke',
      skipDiscoveryBrief: true,
    }),
  });
  if (!projectResponse.ok) fail(`could not create native BYOK smoke project (HTTP ${projectResponse.status})`);

  // This is the upstream browser-local API BYOK request contract. The provider
  // object is sent only for this run; the launcher/add-on never persists it.
  const runResponse = await fetchWithTimeout(`${daemonUrl}/api/runs`, {
    method: 'POST',
    headers: { 'content-type': 'application/json', 'x-od-client': 'web' },
    body: JSON.stringify({
      agentId: 'byok-opencode',
      projectId,
      message: `Reply with exactly ${COMPLETION}.`,
      currentPrompt: `Reply with exactly ${COMPLETION}.`,
      priorTranscript: '',
      conversationId: null,
      sessionMode: 'chat',
      model: MODEL,
      byokProvider: {
        protocol: 'openai',
        apiKey: FAKE_API_KEY,
        baseUrl: `http://127.0.0.1:${address.port}/v1`,
        model: MODEL,
        requiresApiKey: true,
      },
    }),
  });
  if (!runResponse.ok) fail(`native byok-opencode run creation failed (HTTP ${runResponse.status})`);
  const created = await runResponse.json();
  if (typeof created?.runId !== 'string' || !created.runId) fail('native byok-opencode did not create a run');

  const streamResponse = await fetchWithTimeout(
    `${daemonUrl}/api/runs/${encodeURIComponent(created.runId)}/events`,
  );
  const runOutput = await streamResponse.text();
  if (!streamResponse.ok) fail(`native byok-opencode event stream failed (HTTP ${streamResponse.status})`);
  if (!runOutput.includes(COMPLETION)) fail('native byok-opencode stream did not contain the mock completion');

  // OpenCode may issue one preliminary capability probe before the actual
  // completion. Assert the credential-bearing streaming request itself rather
  // than incorrectly treating that probe as a duplicate generation.
  const completionRequests = requests.filter((request) => (
    request.method === 'POST'
    && request.path === '/v1/chat/completions'
    && request.authorization === `Bearer ${FAKE_API_KEY}`
    && request.model === MODEL
    && request.stream === true
  ));
  assert.ok(completionRequests.length >= 1, 'the selected provider must receive a streaming completion request');
  console.log('native byok-opencode mock stream passed');
} finally {
  await new Promise((resolve) => provider.close(resolve));
}
