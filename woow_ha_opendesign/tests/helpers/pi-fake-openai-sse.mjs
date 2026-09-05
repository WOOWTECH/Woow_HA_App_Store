import { createServer } from 'node:http';
import { once } from 'node:events';

const COMPLETION_TEXT = 'PI_RPC_FAKE_PROVIDER_OK';

function completionChunk(delta, finishReason, usage) {
  return {
    id: 'pi-rpc-fake-completion',
    object: 'chat.completion.chunk',
    created: 0,
    model: 'pi-rpc-test-model',
    choices: [{ index: 0, delta, finish_reason: finishReason }],
    ...(usage ? { usage } : {}),
  };
}

export async function startFakeOpenAiSseProvider(apiKey) {
  const requests = [];
  const server = createServer((request, response) => {
    const accepted = request.method === 'POST'
      && request.url === '/v1/chat/completions'
      && request.headers.authorization === `Bearer ${apiKey}`;
    requests.push({
      accepted,
      method: request.method,
      path: request.url,
      model: undefined,
    });

    let requestBody = '';
    request.setEncoding('utf8');
    request.on('data', (chunk) => {
      requestBody += chunk;
    });
    request.on('end', () => {
      try {
        requests.at(-1).model = JSON.parse(requestBody).model;
      } catch {
        // The harness records the failed request without exposing its body.
      }
      if (!accepted) {
        response.writeHead(401, { 'content-type': 'application/json' });
        response.end('{"error":{"message":"unauthorized"}}');
        return;
      }

      response.writeHead(200, {
        'cache-control': 'no-cache',
        'content-type': 'text/event-stream',
      });
      response.end([
        `data: ${JSON.stringify(completionChunk({ role: 'assistant', content: COMPLETION_TEXT }, null))}\n\n`,
        `data: ${JSON.stringify(completionChunk({}, 'stop', { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 }))}\n\n`,
        'data: [DONE]\n\n',
      ].join(''));
    });
  });

  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  const address = server.address();
  if (!address || typeof address === 'string') throw new Error('Fake provider could not bind.');

  return {
    baseUrl: `http://127.0.0.1:${address.port}/v1`,
    completionText: COMPLETION_TEXT,
    requests,
    async close() {
      server.close();
      await once(server, 'close');
    },
  };
}
