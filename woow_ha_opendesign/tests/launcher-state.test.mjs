import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import { once } from 'node:events';
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import test from 'node:test';

const launcher = await readFile(new URL('../rootfs/usr/local/bin/ha-opendesign', import.meta.url), 'utf8');
const legacyOverrides = ['OMNIGENT_CONFIG_HOME', 'OMNIGENT_DATA_DIR', 'OG_CONFIG_HOME', 'OG_DATA_DIR', 'OG_STATE_DIR', 'OG_STATUS_FILE', 'OG_WORKSPACE', 'OG_SERVER_URL', 'OG_SERVER_URL_FILE'];

function shellQuote(value) { return "'" + value.replaceAll("'", "'\\''") + "'"; }

async function waitFor(predicate, description) {
  for (let attempt = 0; attempt < 100; attempt++) {
    if (await predicate()) return;
    await delay(50);
  }
  throw new Error(`Timed out: ${description}`);
}

// Execute the whole launcher. Only container-specific paths, identities and
// external processes are substituted; preparation, env stripping, supervision
// and shutdown all run as shipped. No real /data or other runtime is touched.
async function boot(root) {
  const data = path.join(root, 'data');
  const bin = path.join(root, 'bin');
  const records = path.join(root, 'records');
  await mkdir(bin, { recursive: true });
  await rm(records, { recursive: true, force: true });
  await mkdir(records);
  const credentialHelper = path.join(root, 'credentials.py');
  await writeFile(credentialHelper, (await readFile(new URL('../rootfs/usr/local/libexec/ha-opendesign-credentials.py', import.meta.url), 'utf8'))
    .replace("HOME = Path('/data/opendesign/home')", `HOME = Path(${JSON.stringify(path.join(data, 'home'))})`));
  await writeFile(path.join(bin, 'id'), '#!/bin/sh\necho 0\n', { mode: 0o755 });
  await writeFile(path.join(bin, 'su-exec'), '#!/bin/sh\nshift\nexec "$@"\n', { mode: 0o755 });
  const child = path.join(root, 'child.mjs');
  await writeFile(child, `
import { writeFileSync } from 'node:fs';
const name = process.argv[2];
const keys = ${JSON.stringify(legacyOverrides)};
writeFileSync(process.env.RECORDS + '/' + name, JSON.stringify({
  pid: process.pid, data: process.env.OD_DATA_DIR, home: process.env.HOME,
  inherited: keys.filter(key => key in process.env),
  supervisor: 'SUPERVISOR_TOKEN' in process.env || 'HASSIO_TOKEN' in process.env,
}));
process.on('SIGTERM', () => { writeFileSync(process.env.RECORDS + '/' + name + '.stopped', 'yes'); process.exit(0); });
setInterval(() => {}, 1000);
`);
  const source = launcher
    .replace('readonly DATA_DIR=/data/opendesign', `readonly DATA_DIR=${shellQuote(data)}`)
    .replace('readonly NGINX_TMP=/tmp/ha-opendesign-nginx', `readonly NGINX_TMP=${shellQuote(path.join(root, 'nginx'))}`)
    .replaceAll('/run/ha-opendesign-paseo', path.join(root, 'paseo-run'))
    .replaceAll('/run/ha-opendesign-return', path.join(root, 'return-run'))
    .replace('python3 /usr/local/libexec/ha-opendesign-return.py', 'false')
    .replace('/usr/local/libexec/ha-opendesign-credentials.py', shellQuote(credentialHelper))
    .replaceAll('open-design:ha-ingress', `${process.getuid()}:${process.getgid()}`)
    .replaceAll('root:ha-ingress', `${process.getuid()}:${process.getgid()}`)
    .replaceAll('open-design:open-design', `${process.getuid()}:${process.getgid()}`)
    .replaceAll('ha-ingress:ha-ingress', `${process.getuid()}:${process.getgid()}`)
    .replaceAll('-user open-design', `-user ${process.getuid()}`)
    .replaceAll('-group open-design', `-group ${process.getgid()}`)
    .replace('/usr/local/bin/node /opt/ha-opendesign/headless-entry.mjs', `${shellQuote(process.execPath)} ${shellQuote(child)} opendesign`)
    .replace('/usr/local/bin/node /opt/opendesign-paseo/bin/serve.mjs', `${shellQuote(process.execPath)} ${shellQuote(child)} paseo`)
    .replace('/usr/sbin/nginx', `${shellQuote(process.execPath)} ${shellQuote(child)} nginx`)
    .replace('/usr/bin/ttyd', `${shellQuote(process.execPath)} ${shellQuote(child)} ttyd`)
    .replace('/opt/woow/bin/ha-opendesign-mcp', `${shellQuote(process.execPath)} ${shellQuote(child)} mcp`);
  const script = path.join(root, 'launcher');
  await writeFile(script, source);
  const processHandle = spawn('bash', [script], {
    env: { ...process.env, PATH: `${bin}:${process.env.PATH}`, RECORDS: records,
      SUPERVISOR_TOKEN: 'fake', HASSIO_TOKEN: 'fake',
      ...Object.fromEntries(legacyOverrides.map(key => [key, `${data}/home/.omnigent`])),
    }, stdio: ['ignore', 'ignore', 'pipe'],
  });
  let stderr = '';
  processHandle.stderr.on('data', chunk => { stderr += chunk; });
  const exited = once(processHandle, 'exit');
  try {
    await waitFor(async () => {
      if (processHandle.exitCode !== null) throw new Error(`launcher exited: ${stderr}`);
      return readFile(path.join(records, 'mcp')).then(() => true, () => false);
    }, 'children start');
    for (const name of ['opendesign', 'paseo', 'nginx', 'ttyd', 'mcp']) {
      await waitFor(() => readFile(path.join(records, name)).then(() => true, () => false), name);
      const record = JSON.parse(await readFile(path.join(records, name), 'utf8'));
      assert.equal(record.data, data);
      assert.equal(record.home, `${data}/home`);
      assert.deepEqual(record.inherited, [], 'legacy host overrides must not reach native service');
      assert.equal(record.supervisor, false);
    }
  } finally {
    processHandle.kill('SIGTERM');
    const killTimer = setTimeout(() => processHandle.kill('SIGKILL'), 8000);
    const [, signal] = await exited;
    clearTimeout(killTimer);
    assert.equal(signal, null, stderr);
  }
  for (const name of ['opendesign', 'paseo', 'nginx', 'ttyd', 'mcp']) {
    assert.equal(await readFile(path.join(records, `${name}.stopped`), 'utf8'), 'yes');
  }
  assert.doesNotMatch(stderr, /grace; sending KILL/);
}

test('launcher isolates retired logins and preserves new private state over restart and cold restore', async () => {
  const root = await mkdtemp(path.join(tmpdir(), 'ha-omnigent-launcher-'));
  const data = path.join(root, 'data');
  const fixtures = {
    'home/.omnigent/config.yaml': 'server: https://legacy.invalid\nhost:\n  host_id: retired-host\n',
    'home/.omnigent/auth_tokens.json': '{"token":"fake-legacy-not-for-adoption"}',
    '.backup/omnigent-retired/auth_tokens.json': '{"token":"fake-archived-not-for-adoption"}',
    'projects/retained.txt': 'existing project',
  };
  async function seed(entries) {
    for (const [name, contents] of Object.entries(entries)) {
      await mkdir(path.dirname(path.join(data, name)), { recursive: true });
      await writeFile(path.join(data, name), contents, { mode: 0o600 });
    }
  }
  async function preserved(entries) {
    for (const [name, contents] of Object.entries(entries)) {
      assert.equal(await readFile(path.join(data, name), 'utf8'), contents, `${name} must survive launcher startup`);
    }
  }
  try {
    await boot(root); // A completely empty installation needs no Omnigent home.
    await assert.rejects(readFile(path.join(data, 'integrations/omnigent/state.json')), { code: 'ENOENT' });
    // Direct upgrade from 0.2.0 plus archived 0.2.1 data: neither is adopted.
    await seed(fixtures);
    await boot(root);
    await preserved(fixtures);
    await assert.rejects(readFile(path.join(data, 'integrations/omnigent/state.json')), { code: 'ENOENT' });
    const configured = {
      'integrations/omnigent/state.json': '{"fixture":"daemon-owned-state"}',
      'integrations/omnigent/host/auth_tokens.json': '{"token":"fake-new-host"}',
      'integrations/omnigent/host/host.json': '{"host_id":"new-host"}',
    };
    await seed(configured);
    await boot(root);
    await preserved({ ...fixtures, ...configured });
    // A cold archive really leaves the original data tree before restoration.
    const archive = path.join(root, 'data.tar');
    assert.equal(spawnSync('tar', ['-cf', archive, '-C', data, '.']).status, 0);
    await rm(data, { recursive: true });
    await mkdir(data);
    assert.equal(spawnSync('tar', ['-xf', archive, '-C', data]).status, 0);
    await boot(root);
    await preserved({ ...fixtures, ...configured });
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test('headless entry waits for daemon-managed host shutdown before exiting', async () => {
  const root = await mkdtemp(path.join(tmpdir(), 'ha-omnigent-shutdown-'));
  const entry = await readFile(new URL('../rootfs/opt/ha-opendesign/headless-entry.mjs', import.meta.url), 'utf8');
  try {
    const daemon = path.join(root, 'daemon.mjs');
    await writeFile(daemon, `
import http from 'node:http';
import { writeFile } from 'node:fs/promises';
export async function startServer() {
  const server = http.createServer();
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  return { server, url: 'isolated-test', shutdown: async () => {
    await new Promise(resolve => setTimeout(resolve, 100));
    await writeFile(${JSON.stringify(path.join(root, 'host-stopped'))}, 'awaited');
  }};
}
`);
    await writeFile(path.join(root, 'entry.mjs'), entry
      .replace("import { renderSlides } from './headless-renderer.mjs';", 'const renderSlides = () => {};')
      .replace("'/app/apps/daemon/dist/server.js'", JSON.stringify(daemon)));
    const child = spawn(process.execPath, [path.join(root, 'entry.mjs')], { stdio: ['ignore', 'pipe', 'pipe'] });
    const exited = once(child, 'exit');
    let stdout = '';
    child.stdout.on('data', chunk => { stdout += chunk; });
    try {
      await waitFor(() => stdout.includes('with Playwright export renderer'), 'daemon ready');
      child.kill('SIGTERM');
      const timer = setTimeout(() => child.kill('SIGKILL'), 5000);
      const [code, signal] = await exited;
      clearTimeout(timer);
      assert.equal(signal, null);
      assert.equal(code, 0);
      assert.equal(await readFile(path.join(root, 'host-stopped'), 'utf8'), 'awaited');
    } finally { child.kill('SIGKILL'); }
  } finally { await rm(root, { recursive: true, force: true }); }
});
