// Opt-in real-service acceptance, executed only inside the harness's disposable
// container. Credentials arrive as a read-only file, never argv or environment.
import assert from 'node:assert/strict';
import { readFile, readdir, stat, writeFile } from 'node:fs/promises';
import { setTimeout as delay } from 'node:timers/promises';

const mode = process.argv[2];
const root = '/data/opendesign/integrations/omnigent';
const credentialFile = '/run/ha-omnigent-smoke-credentials.json';
const receiptFile = '/data/opendesign/ha-omnigent-smoke-receipt.json';
const engines = ['claude', 'codex', 'opencode', 'pi'];
const check = (value, message) => assert.ok(value, message); // never print actual secrets/URLs
async function api(body) {
  const response = await fetch(`http://127.0.0.1:8099/api/integrations/omnigent/${body ? 'actions' : 'status'}`, {
    method: body ? 'POST' : 'GET', headers: { 'content-type': 'application/json', 'X-Ingress-Path': '/api/hassio_ingress/abcdefghijklmnop' },
    ...(body ? { body: JSON.stringify(body) } : {}), signal: AbortSignal.timeout(60_000),
  });
  check(response.ok, 'native integration request failed');
  const data = await response.json();
  return body ? data.status : data;
}
async function idle() {
  for (let attempt = 0; attempt < 660; attempt++) {
    const value = await api();
    if (value.operation?.phase !== 'running') {
      check(value.operation?.phase !== 'error', 'native verification failed; inspect sanitized status privately');
      return value;
    }
    await delay(1000);
  }
  throw new Error('native operation timed out');
}
async function managers() {
  const found = [];
  const hosts = [];
  for (const pid of await readdir('/proc')) {
    if (!/^\d+$/.test(pid)) continue;
    const command = await readFile(`/proc/${pid}/cmdline`, 'utf8').catch(() => '');
    if (command.includes('/integrations/omnigent/host-kit/supervisor.sh')) found.push(pid);
    if (/(?:^|\0)(?:[^\0]*\/)?omnigent\0host(?:\0|$)/.test(command)) hosts.push(pid);
  }
  return { supervisors: found, hosts };
}
async function managerCount(expected) {
  for (let attempt = 0; attempt < 150; attempt++) {
    const current = await managers();
    if (current.supervisors.length === expected && current.hosts.length === expected) {
      for (const pid of [...current.supervisors, ...current.hosts]) {
        const status = await readFile(`/proc/${pid}/status`, 'utf8');
        check(/^Uid:\s+1001\s/m.test(status), 'managed host must run as UID 1001');
        const environment = await readFile(`/proc/${pid}/environ`, 'utf8');
        check(!/(?:^|\0)(?:SUPERVISOR_TOKEN|HASSIO_TOKEN)=/.test(environment), 'host inherited Supervisor credentials');
      }
      return;
    }
    await delay(100);
  }
  throw new Error(`expected ${expected} native host manager(s)`);
}
function connected(value) {
  check(value.installed && value.enabled && value.loginConfirmed && value.host.connected, 'host must be connected with GUI approval');
  check(value.phase === 'ready', 'all four real engines must pass native reply/stop verification');
  check(JSON.stringify([...value.installedEngines].sort()) === JSON.stringify(engines), 'only the four bundled engines are allowed');
  for (const engine of engines) {
    const proof = value.verification[engine];
    check(proof?.ok && proof.reply === 'OMNIGENT_CONNECTION_OK' && proof.cleanup === 'stopped', 'real reply and stop receipt required for every engine');
    check(value.engines[engine]?.models?.some(model => model.id === proof.model), 'verified model must be selectable');
  }
}
async function credentials() {
  const metadata = await stat(credentialFile);
  check((metadata.mode & 0o077) === 0, 'test credential file must be private');
  const value = JSON.parse(await readFile(credentialFile, 'utf8'));
  check(['server', 'username', 'password'].every(key => typeof value[key] === 'string' && value[key].length > 0), 'test credential file is incomplete');
  return value;
}

try {
  if (mode === 'setup') {
    const before = await api();
    check(before.installed && !before.loginConfirmed && before.server === null, 'fresh setup must not reuse retired login');
    await managerCount(0);
    await api({ ...(await credentials()), action: 'setup' });
    const value = await idle();
    connected(value);
    await managerCount(1);
    await writeFile(receiptFile, JSON.stringify({ hostId: value.host.id, server: value.server }), { mode: 0o600 });
    const state = await stat(`${root}/state.json`);
    check(state.uid === 1001 && (state.mode & 0o777) === 0o600, 'private state ownership or mode incorrect');
  } else if (mode === 'resumed') {
    // Check before an HTTP status request can lazily launch a missing host.
    await managerCount(1);
    const value = await idle();
    connected(value);
    const receipt = JSON.parse(await readFile(receiptFile, 'utf8'));
    check(value.host.id === receipt.hostId && value.server === receipt.server, 'container recreation must retain host identity and server');
    check((await stat(`${root}/state.json`)).uid === 1001, 'restored private state must be repaired to UID 1001');
  } else if (mode === 'controls') {
    await api({ action: 'disable' });
    await managerCount(0);
    let value = await api();
    check(!value.enabled && !value.loginConfirmed && !value.host.connected, 'disable must revoke live host approval');
    await api({ action: 'enable' });
    value = await idle();
    check(!value.loginConfirmed && value.phase === 'needs-login', 're-enable must ask for fresh GUI login');
    await managerCount(0);
    await api({ ...(await credentials()), action: 'setup' });
    connected(await idle());
    await managerCount(1);
    await api({ action: 'disconnect' });
    value = await idle();
    check(!value.loginConfirmed && !value.host.connected && value.phase === 'needs-login', 'disconnect must clear connection');
    await managerCount(0);
  } else if (mode === 'stopped') {
    // Inspect the stopped data volume with a one-shot container, before boot.
    const state = JSON.parse(await readFile(`${root}/host/omnigent-host/status.json`, 'utf8'));
    check(state.state === 'stopped', 'host did not acknowledge graceful daemon/container shutdown');
  } else if (mode === 'logs') {
    let logs = '';
    for await (const chunk of process.stdin) logs += chunk;
    const input = await credentials();
    check(!logs.includes(input.password), 'password leaked into container logs');
    check(!logs.includes('grace; sending KILL'), 'launcher needed forced shutdown');
    const tokens = await readFile(`${root}/host/auth_tokens.json`, 'utf8').then(JSON.parse, () => ({}));
    function checkTokens(value) {
      if (typeof value === 'string' && value.length >= 16) check(!logs.includes(value), 'stored credential leaked into container logs');
      else if (value && typeof value === 'object') Object.values(value).forEach(checkTokens);
    }
    checkTokens(tokens);
  } else {
    throw new Error('unsupported connected smoke mode');
  }
  console.log(`Omnigent authenticated ${mode} contract: OK`);
} catch {
  // AssertionError would include inspected values by default. Keep all real
  // account evidence private; report only the phase to the public CI log.
  console.error(`Omnigent authenticated ${mode} contract failed (no credential or response dump)`);
  process.exitCode = 1;
}
