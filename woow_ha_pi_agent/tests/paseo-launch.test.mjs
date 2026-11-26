// rootfs/usr/local/lib/pi-paseo-ha/launch.mjs is what the s6 pi-web service executes.
// `node --check` only parses it: a renamed export in one of its imports passes every
// unit test and then dies at link time ("does not provide an export"), taking Pi Web's
// settings pages with it. This runs the real file from a copy of the rootfs layout
// (/usr/local/lib and /usr/local/share under a temporary prefix), with only the
// Omnigent launcher and Pi Web replaced by a stand-in. The image smoke does the same
// with the real Omnigent launcher, real Pi Web and the installed plugin.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { pathToFileURL } from 'node:url';

const root = path.resolve(import.meta.dirname, '..');
const lib = path.join(root, 'rootfs/usr/local/lib');
const FAILURE = /SyntaxError|ERR_MODULE_NOT_FOUND|Cannot find module|does not provide an export/;
const ingress = '/api/hassio_ingress/launchfixture0123456789';

/** A copy of the launcher's files at <base>/root/usr/local, an agent directory and a stand-in child. */
function layout(t) {
  const base = fs.mkdtempSync(path.join(os.tmpdir(), 'hl-'));
  t.after(() => fs.rmSync(base, { recursive: true, force: true }));
  const prefix = path.join(base, 'root/usr/local');
  for (const name of ['pi-paseo-ha', 'pi-launch']) fs.cpSync(path.join(lib, name), path.join(prefix, 'lib', name), { recursive: true });
  fs.cpSync(path.join(root, 'rootfs/usr/local/share/pi-paseo-ha'), path.join(prefix, 'share/pi-paseo-ha'), { recursive: true });
  const marker = path.join(base, 'child.json');
  fs.mkdirSync(path.join(prefix, 'lib/pi-omnigent-ha'), { recursive: true });
  fs.writeFileSync(path.join(prefix, 'lib/pi-omnigent-ha/launch.mjs'),
    `import fs from 'node:fs';\nfs.writeFileSync(${JSON.stringify(marker)}, JSON.stringify({ argv: process.argv.slice(2), runtime: process.env.PI_PASEO_RUNTIME_DIR }));\nsetTimeout(() => process.exit(0), 120_000); // idles like Pi Web; never outlives a failed test for long\n`);
  const agentDir = path.join(base, 'a');
  fs.mkdirSync(path.join(agentDir, 'home'), { recursive: true });
  const socket = path.join(agentDir, 'paseo-ha.sock');
  assert.ok(Buffer.byteLength(socket) < 100, `${socket} is too long for a Unix socket; set TMPDIR to a shorter directory`);
  return { prefix, marker, agentDir, socket, launcher: path.join(prefix, 'lib/pi-paseo-ha/launch.mjs') };
}
/** Start the launcher as s6 does (plain node, no extra flags). By default PI_PASEO_AUTO_SETUP=false: nothing registers, no daemon. */
function start(t, f, { args = [], register = false, env = {} } = {}) {
  // Its own process group: a failed test kills the launcher and the stand-in together, and the pipes close.
  const child = spawn(process.execPath, [f.launcher, ...args], { detached: true, stdio: ['ignore', 'pipe', 'pipe'],
    env: { PATH: process.env.PATH, HOME: path.join(f.agentDir, 'home'), PI_CODING_AGENT_DIR: f.agentDir, ...(register ? {} : { PI_PASEO_AUTO_SETUP: 'false' }), ...env } });
  const run = { child, stdout: '', stderr: '' };
  child.stdout.setEncoding('utf8').on('data', chunk => { run.stdout += chunk; });
  child.stderr.setEncoding('utf8').on('data', chunk => { run.stderr += chunk; });
  run.exit = new Promise(resolve => child.once('exit', (code, signal) => resolve({ code, signal })));
  t.after(() => {
    try { process.kill(-child.pid, 'SIGKILL'); } catch { /* already gone */ }
    child.stdout.destroy(); child.stderr.destroy();
  });
  return run;
}
/** The launcher's exit, or a failure with its stderr if it has not ended within `ms`. */
async function ended(run, ms = 15000) {
  let timer;
  const late = new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(`the launcher did not exit within ${ms} ms\n${run.stderr}`)), ms); });
  try { return await Promise.race([run.exit, late]); } finally { clearTimeout(timer); }
}
const get = (socketPath, route, headers = {}) => new Promise((resolve, reject) => {
  const request = http.request({ socketPath, path: route, headers, timeout: 5000 }, response => {
    const chunks = [];
    response.on('data', chunk => chunks.push(chunk));
    response.on('end', () => resolve({ status: response.statusCode, headers: response.headers, body: Buffer.concat(chunks).toString() }));
  });
  request.on('error', reject).on('timeout', () => request.destroy(new Error('timeout'))).end();
});
/** Poll until `read` gives a truthy value; fail with the launcher's stderr if it exits first or never does. */
async function until(run, what, read) {
  for (let attempt = 0; attempt < 100; attempt++) {
    const value = await Promise.resolve().then(read).catch(() => null);
    if (value) return value;
    if (run.child.exitCode !== null || run.child.signalCode !== null) break;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  assert.fail(`${what}; exit ${run.child.exitCode}/${run.child.signalCode}\n${run.stderr}`);
}

test('the s6 entry point starts, serves its page on the private socket, starts its child by location and stops within the budget', { timeout: 60_000 }, async t => {
  const f = layout(t);
  const run = start(t, f, { args: ['--forwarded'] });
  const page = await until(run, 'the launcher never served /paseo/setup', async () => {
    const response = await get(f.socket, '/paseo/setup', { 'X-Ingress-Path': ingress });
    return response.status === 200 && response;
  });
  assert.match(page.headers['content-type'], /^text\/html/);
  assert.ok(page.body.includes(`src="${ingress}/paseo/app.js"`));
  assert.match(page.body, /<a id="open" href="https:\/\/app\.paseo\.sh\/" target="_blank" rel="noopener noreferrer">/);
  assert.match(page.body, /name="paseo-token" content="[a-f0-9]{64}"/);
  assert.equal((await get(f.socket, '/paseo-web/')).status, 404);
  await until(run, 'the launcher never started its child', () => fs.existsSync(f.marker));
  assert.deepEqual(JSON.parse(fs.readFileSync(f.marker, 'utf8')), { argv: ['--forwarded'], runtime: '/opt/woow/paseo-runtime' }, 'the Omnigent launcher beside it, with the arguments it was given and, on a fresh home, the runtime in the image');
  const stopped = Date.now();
  run.child.kill('SIGTERM');
  assert.deepEqual(await ended(run), { code: 0, signal: null }, 'a requested stop is a clean exit');
  assert.ok(Date.now() - stopped < 5000, 'inside the launcher\'s 5 s stop budget');
  assert.doesNotMatch(run.stderr, FAILURE, run.stderr);
});

test('a launcher that cannot link fails at once and loudly, and this test would see it', { timeout: 60_000 }, async t => {
  // The review's mutation: one imported name no longer exists. `node --check` and every unit test stay green.
  const f = layout(t);
  const source = fs.readFileSync(f.launcher, 'utf8');
  assert.ok(source.includes('import { seed, startLifecycle, findPlugin, BUNDLE }'));
  fs.writeFileSync(f.launcher, source.replace('import { seed, startLifecycle, findPlugin, BUNDLE }', 'import { seed, startLifecycl, findPlugin, BUNDLE }'));
  const run = start(t, f);
  const result = await ended(run);
  assert.notEqual(result.code, 0);
  assert.match(run.stderr, /SyntaxError[^\n]*does not provide an export named 'startLifecycl'/);
  assert.equal(fs.existsSync(f.socket), false); assert.equal(fs.existsSync(f.marker), false);
});

test('a failed registration cannot keep the lifecycle restore from running', { timeout: 60_000 }, async t => {
  // Unreadable settings make seed() throw. The launcher must still try the restore (which logs its own line) and serve the page.
  const f = layout(t);
  fs.writeFileSync(path.join(f.agentDir, 'settings.json'), '{broken');
  const run = start(t, f, { register: true });
  await until(run, 'the launcher never served /paseo/setup', async () => (await get(f.socket, '/paseo/setup')).status === 200);
  await until(run, 'the lifecycle restore was never attempted after the failed seed', () => /Paseo setup needs attention/.test(run.stderr));
  assert.equal((run.stderr.match(/Paseo initialization needs attention; Pi Web remains available\./g) || []).length, 1, 'the failed seed is logged once');
  assert.equal(fs.readFileSync(path.join(f.agentDir, 'settings.json'), 'utf8'), '{broken', 'and nothing was overwritten');
  assert.doesNotMatch(run.stderr, FAILURE, run.stderr);
  run.child.kill('SIGTERM'); assert.deepEqual(await ended(run), { code: 0, signal: null });
});

test('a runtime saved in the home directory stays in use when the plugin cannot be asked, and a runtime named by the operator is never replaced', { timeout: 60_000 }, async t => {
  // Here no plugin is installed (the fixture has no /opt/woow), so the launcher cannot ask which release is needed and
  // does what it always did. That a saved runtime without the needed release gives way to the image's is
  // tests/paseo-runtime-dir.test.mjs (stand-in plugin), tests/paseo-contract.test.mjs (the frozen plugin) and the image smoke.
  if (fs.existsSync('/opt/woow/pi-paseo-plugin')) return t.skip('this host carries the add-on\'s plugin, which the launcher would consult');
  const f = layout(t);
  const saved = path.join(f.agentDir, 'home/.local/share/pi-paseo/runtime');
  fs.mkdirSync(path.join(saved, 'releases'), { recursive: true });
  const run = start(t, f);
  await until(run, 'the launcher never started its child', () => fs.existsSync(f.marker));
  assert.equal(JSON.parse(fs.readFileSync(f.marker, 'utf8')).runtime, saved);
  run.child.kill('SIGTERM'); assert.deepEqual(await ended(run), { code: 0, signal: null });
  assert.deepEqual(fs.readdirSync(saved), ['releases'], 'and the launcher added nothing to it');

  const named = layout(t), own = path.join(named.agentDir, 'my-runtime');
  fs.mkdirSync(path.join(named.agentDir, 'home/.local/share/pi-paseo/runtime'), { recursive: true });
  const second = start(t, named, { env: { PI_PASEO_RUNTIME_DIR: own } });
  await until(second, 'the launcher never started its child', () => fs.existsSync(named.marker));
  assert.equal(JSON.parse(fs.readFileSync(named.marker, 'utf8')).runtime, own, 'the operator\'s directory, whatever is saved in the home');
  second.child.kill('SIGTERM'); assert.deepEqual(await ended(second), { code: 0, signal: null });
});

test('every relative import of both launchers resolves and every named import is a real export', async () => {
  for (const name of ['pi-paseo-ha', 'pi-omnigent-ha']) {
    const file = path.join(lib, name, 'launch.mjs');
    const imports = [...fs.readFileSync(file, 'utf8').matchAll(/import\s+(?:(\w+)\s*,?\s*)?(?:\{([^}]*)\}\s*)?from\s+'(\.[^']+)'/g)];
    assert.ok(imports.length >= 3, `${name}: found its imports`);
    for (const [, defaultName, named, specifier] of imports) {
      const target = path.resolve(path.dirname(file), specifier);
      assert.ok(fs.existsSync(target), `${name} imports ${specifier}, which exists`);
      const module = await import(pathToFileURL(target).href);
      if (defaultName) assert.ok('default' in module, `${name}: ${specifier} has a default export`);
      for (const item of (named || '').split(',').map(part => part.trim().split(/\s+as\s+/)[0]).filter(Boolean)) {
        assert.ok(item in module, `${name}: ${specifier} exports ${item}`);
      }
    }
  }
});
