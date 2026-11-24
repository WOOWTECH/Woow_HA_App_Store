// Issue 212: a launcher that receives SIGTERM must end within a bounded time
// after its child ends, and still run its cleanup. Supervisor SIGKILLs the
// container (exit 137) about 10 s after `docker stop`.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { exitCodeFor } from '../rootfs/usr/local/lib/pi-launch/child-shutdown.mjs';

const root = path.resolve(import.meta.dirname, '..');
const helper = path.join(root, 'rootfs/usr/local/lib/pi-launch/child-shutdown.mjs');

// A launcher like the real ones: spawns a child, keeps a long-lived handle
// open (as plugin timers and file watchers do), and writes a marker on cleanup.
function launcher(dir, { childScript, cleanupMs = 50, cleanupHangs = false, opts = '{}' }) {
  const file = path.join(dir, 'launcher.mjs');
  fs.writeFileSync(path.join(dir, 'child.mjs'), childScript);
  fs.writeFileSync(file, `
import fs from 'node:fs';
import { spawn } from 'node:child_process';
import { superviseChild } from ${JSON.stringify(helper)};
setInterval(() => {}, 1000); // keeps the event loop alive forever
const child = spawn(process.execPath, [${JSON.stringify(path.join(dir, 'child.mjs'))}], { stdio: 'ignore' });
superviseChild(child, { name: 'test', ...${opts}, cleanup: async () => {
  ${cleanupHangs ? 'await new Promise(() => {});' : `await new Promise(r => setTimeout(r, ${cleanupMs}));`}
  fs.writeFileSync(${JSON.stringify(path.join(dir, 'cleaned'))}, 'yes');
} });
fs.writeFileSync(${JSON.stringify(path.join(dir, 'ready'))}, String(child.pid));
`);
  return file;
}
async function run(t, options) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'launcher-stop-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const proc = spawn(process.execPath, [launcher(dir, options)], { stdio: ['ignore', 'inherit', 'pipe'] });
  let stderr = ''; proc.stderr.on('data', chunk => { stderr += chunk; });
  for (let i = 0; i < 100 && !fs.existsSync(path.join(dir, 'ready')); i++) await new Promise(r => setTimeout(r, 50));
  await new Promise(r => setTimeout(r, 200)); // child installs its own handler
  const childPid = Number(fs.readFileSync(path.join(dir, 'ready'), 'utf8'));
  t.after(() => { try { process.kill(childPid, 'SIGKILL'); } catch {} });
  const started = Date.now();
  proc.kill('SIGTERM');
  const [code, signal] = await once(proc, 'exit');
  const elapsed = Date.now() - started;
  let childAlive = true; try { process.kill(childPid, 0); } catch { childAlive = false; }
  return { code, signal, elapsed, cleaned: fs.existsSync(path.join(dir, 'cleaned')), childAlive, stderr };
}
const GRACEFUL = `process.on('SIGTERM', () => setTimeout(() => process.exit(0), 300)); setInterval(() => {}, 1000);`;
const STUBBORN = `process.on('SIGTERM', () => {}); setInterval(() => {}, 1000);`;

test('SIGTERM: launcher exits soon after its child ends, cleanup ran, exit 0', async t => {
  const r = await run(t, { childScript: GRACEFUL });
  assert.equal(r.code, 0, r.stderr); assert.equal(r.signal, null);
  assert.equal(r.cleaned, true, 'cleanup still runs on stop');
  assert.equal(r.childAlive, false);
  assert.ok(r.elapsed < 2000, `stopped in ${r.elapsed} ms despite a live interval`);
});
test('a child that ignores SIGTERM is killed and the launcher still ends in time', async t => {
  const r = await run(t, { childScript: STUBBORN, opts: '{ killAfterMs: 500, deadlineMs: 3000 }' });
  assert.equal(r.childAlive, false); assert.equal(r.cleaned, true);
  assert.ok(r.elapsed < 2500, `stopped in ${r.elapsed} ms`);
  assert.match(r.stderr, /sending SIGKILL/);
});
test('a cleanup that never finishes is abandoned at its limit', async t => {
  const r = await run(t, { childScript: GRACEFUL, cleanupHangs: true, opts: '{ cleanupTimeoutMs: 700, deadlineMs: 3000 }' });
  assert.equal(r.code, 0); assert.ok(r.elapsed < 2000, `stopped in ${r.elapsed} ms`);
  assert.match(r.stderr, /cleanup did not finish within 700 ms/);
});
test('the overall deadline holds even if the child cannot be reaped', async t => {
  const r = await run(t, { childScript: STUBBORN, cleanupHangs: true, opts: '{ killAfterMs: 5000, cleanupTimeoutMs: 5000, deadlineMs: 800 }' });
  assert.ok(r.elapsed < 1800, `stopped in ${r.elapsed} ms`);
  assert.match(r.stderr, /stop deadline of 800 ms reached/);
});
test('exit codes: a requested stop is not a failure; an unrequested crash is', () => {
  assert.equal(exitCodeFor(null, 'SIGTERM', 'SIGTERM'), 0);
  assert.equal(exitCodeFor(143, null, 'SIGTERM'), 0);
  assert.equal(exitCodeFor(0, null, 'SIGTERM'), 0);
  assert.equal(exitCodeFor(3, null, 'SIGTERM'), 3);
  assert.equal(exitCodeFor(null, 'SIGKILL', null), 1);
  assert.equal(exitCodeFor(2, null, null), 2);
});
test('both launchers use the bounded stop helper and never only set exitCode', () => {
  for (const name of ['pi-paseo-ha', 'pi-omnigent-ha']) {
    const source = fs.readFileSync(path.join(root, `rootfs/usr/local/lib/${name}/launch.mjs`), 'utf8');
    assert.match(source, /superviseChild\(/, name);
    assert.doesNotMatch(source, /process\.exitCode\s*=/, `${name}: exiting must not depend on the event loop draining`);
  }
});
