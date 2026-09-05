import { spawn } from 'node:child_process';
import { mkdtemp, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

import { createTransientPiConfig } from '../rootfs/opt/ha-opendesign/ha-pi-wrapper.mjs';
import { startFakeOpenAiSseProvider } from './helpers/pi-fake-openai-sse.mjs';

const PI_BIN = fileURLToPath(new URL('../runtime/pi/node_modules/.bin/pi', import.meta.url));
const SENTINEL_KEY = 'PI_EXECUTION_HARNESS_SENTINEL_NEVER_PERSIST';

const profile = {
  id: 'pi-execution-harness',
  label: 'Pi execution harness',
  protocol: 'openai-compatible',
  baseUrl: 'https://profile.invalid/v1',
  authStyle: 'bearer',
  apiFlavor: 'openai-completions',
  apiKey: SENTINEL_KEY,
  model: 'pi-rpc-test-model',
};

function requireSafe(condition, message) {
  if (!condition) throw new Error(message);
}

async function allFileContents(directory) {
  const contents = [];
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const entryPath = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      contents.push(...await allFileContents(entryPath));
    } else if (entry.isFile()) {
      contents.push(await readFile(entryPath, 'utf8'));
    }
  }
  return contents;
}

async function runPiRpc({ directory, completionText }) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [
      PI_BIN,
      '--mode', 'rpc',
      '--model', 'ha-profile/pi-rpc-test-model',
      '--no-session',
      '--no-tools',
      '--no-extensions',
      '--no-skills',
      '--no-prompt-templates',
      '--no-themes',
      '--no-context-files',
    ], {
      env: {
        ...process.env,
        OD_PI_PROFILE_KEY: SENTINEL_KEY,
        PI_CODING_AGENT_DIR: directory,
        PI_CODING_AGENT_SESSION_DIR: path.join(directory, 'sessions'),
        PI_OFFLINE: '1',
        PI_SKIP_VERSION_CHECK: '1',
        PI_TELEMETRY: '0',
      },
      stdio: ['pipe', 'pipe', 'pipe'],
    });

    let stdout = '';
    let stdoutBuffer = '';
    let stderr = '';
    let assistantCompleted = false;
    let settled = false;
    let finished = false;
    const timeout = setTimeout(() => {
      child.kill('SIGKILL');
      finish(new Error('Pi RPC run timed out.'));
    }, 10_000);

    function finish(error) {
      if (finished) return;
      finished = true;
      clearTimeout(timeout);
      if (error) {
        reject(error);
      } else {
        resolve({ stdout, stderr, assistantCompleted, settled });
      }
    }

    function processLine(line) {
      let event;
      try {
        event = JSON.parse(line);
      } catch {
        return;
      }
      if (event.type === 'message_end' && event.message?.role === 'assistant') {
        assistantCompleted = event.message.content?.some((part) => part.text === completionText) === true;
      }
      if (event.type === 'agent_settled') {
        settled = true;
        child.stdin.end();
      }
    }

    child.stdout.setEncoding('utf8');
    child.stdout.on('data', (chunk) => {
      stdout += chunk;
      stdoutBuffer += chunk;
      let newline;
      while ((newline = stdoutBuffer.indexOf('\n')) >= 0) {
        const line = stdoutBuffer.slice(0, newline);
        stdoutBuffer = stdoutBuffer.slice(newline + 1);
        processLine(line);
      }
    });
    child.stderr.setEncoding('utf8');
    child.stderr.on('data', (chunk) => {
      stderr += chunk;
    });
    child.once('error', () => finish(new Error('Pi RPC process could not start.')));
    child.once('exit', (code) => {
      if (code !== 0 || !assistantCompleted || !settled) {
        finish(new Error('Pi RPC process did not complete successfully.'));
        return;
      }
      finish();
    });
    child.stdin.write(`${JSON.stringify({ id: 'prompt-1', type: 'prompt', message: `Reply only ${completionText}.` })}\n`);
  });
}

test('profile-derived transient config completes a Pi RPC run without persisting its key', { timeout: 15_000 }, async () => {
  const root = await mkdtemp(path.join(tmpdir(), 'ha-opendesign-pi-execution-'));
  const provider = await startFakeOpenAiSseProvider(SENTINEL_KEY);
  try {
    const runtime = await createTransientPiConfig(profile, root);
    const config = JSON.parse(await readFile(runtime.modelsPath, 'utf8'));
    config.providers['ha-profile'].baseUrl = provider.baseUrl;
    await writeFile(runtime.modelsPath, `${JSON.stringify(config)}\n`, { mode: 0o600 });

    const result = await runPiRpc({ directory: runtime.dir, completionText: provider.completionText });
    requireSafe(result.assistantCompleted && result.settled, 'Pi RPC response was incomplete.');
    requireSafe(result.stdout.includes(SENTINEL_KEY) === false && result.stderr.includes(SENTINEL_KEY) === false, 'Pi RPC output exposed the profile key.');
    requireSafe(provider.requests.length === 1, 'Fake provider received an unexpected request count.');
    requireSafe(provider.requests[0].accepted, 'Pi did not authenticate to the fake provider.');
    requireSafe(provider.requests[0].model === profile.model, 'Pi used an unexpected provider model.');

    const persistedContents = await allFileContents(root);
    requireSafe(persistedContents.every((content) => content.includes(SENTINEL_KEY) === false), 'Transient Pi files persisted the profile key.');
    requireSafe(persistedContents.some((content) => content.includes('$OD_PI_PROFILE_KEY')), 'Transient Pi config did not retain environment interpolation.');
  } finally {
    await provider.close();
    await rm(root, { recursive: true, force: true });
  }
});
