// Offline image contract: execute the two actual patched native PID writers.
// All writes are confined to a disposable home; no daemon/provider is started.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { execFileSync, spawnSync } from 'node:child_process';

export async function verifyNativeRuntime({ bundle, runtimeDir }) {
  const layout = await import(pathToFileURL(path.join(bundle, 'src/runtime-layout.mjs')).href);
  const patch = await import(pathToFileURL(path.join(bundle, 'src/pid-lock-patch.mjs')).href);
  const transition = await import(pathToFileURL(path.join(bundle, 'src/pid-transition.mjs')).href);
  const pkg = JSON.parse(fs.readFileSync(path.join(bundle, 'package.json')));
  assert.equal(pkg.name, '@woowtech/pi-paseo');
  assert.equal(pkg.version, '0.1.13');
  assert.equal(layout.RUNTIME_REVISION, '0.11.2-r3-6d8dbe515479');
  assert.equal(layout.runtimeReady({ runtimeDir }), true);
  const root = layout.runtimeDirectory({ runtimeDir });
  assert.equal(patch.pidLockPatchReady(root), true, 'both native copies and transition helpers must match');
  assert.match(execFileSync('flock', ['--version'], { encoding: 'utf8', timeout: 5000 }), /util-linux/);
  const modules = await Promise.all(patch.PID_LOCK_COPIES.map(copy =>
    import(pathToFileURL(path.join(root, 'node_modules/@getpaseo/server', copy, 'pid-lock.js')).href)));
  assert.equal(modules.length, 2);
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'ha-paseo-native-'));
  fs.chmodSync(home, 0o700);
  const pidFile = path.join(home, 'paseo.pid');
  const guard = path.join(home, '.pi-paseo-pid-transition.guard');
  const inode = file => { const s = fs.statSync(file); return [s.dev, s.ino]; };
  try {
    await transition.withPidTransition(home, () => {
      const competing = spawnSync('flock', ['--exclusive', '--nonblock', '--conflict-exit-code', '73', guard, '/bin/true'], { timeout: 5000 });
      assert.equal(competing.status, 73, 'the baked helper must exclude another flock process');
    });
    const guardInode = inode(guard);
    // Swap roles so each compiled copy exercises every writer, including a
    // successful release, while both still contend on the same guard inode.
    for (const [control, supervisor] of [modules, [...modules].reverse()]) {
      await supervisor.acquirePidLock(home, null);
      const lock = await control.getPidLockInfo(home);
      assert.equal(lock.pid, process.pid);
      assert.equal(lock.piPaseoProtocol, 'linux-flock-v1');
      const pidInode = inode(pidFile);
      await control.acquirePidLock(home, null); // same-owner acquire must not nest/deadlock
      await Promise.all([
        control.updatePidLock(home, { listen: '127.0.0.1:1', serverId: 'offline-image-fixture' }),
        supervisor.refreshPidLock(home),
      ]);
      assert.deepEqual(inode(pidFile), pidInode);
      assert.equal((await supervisor.getPidLockInfo(home)).piPaseoProtocol, 'linux-flock-v1');
      await control.releasePidLock(home, { ownerPid: process.pid, startedAt: 'different-owner-generation' });
      assert.deepEqual(inode(pidFile), pidInode, 'mismatched generation cannot release the owner');
      await supervisor.releasePidLock(home, { ownerPid: process.pid, startedAt: lock.startedAt });
      assert.equal(fs.existsSync(pidFile), false);
      await assert.rejects(control.refreshPidLock(home), { name: 'PidLockError' });
      assert.equal(fs.existsSync(pidFile), false, 'heartbeat cannot recreate a released lock');
      assert.deepEqual(inode(guard), guardInode, 'transition guard remains the same persistent inode');
      assert.equal(fs.statSync(guard).mode & 0o777, 0o600);
    }
    return { runtime: layout.RUNTIME_REVISION, patchId: patch.PID_LOCK_PATCH_ID,
      writerCopies: modules.length, competingFlockExcluded: true, allFourWritersPerCopy: true,
      uid: process.getuid(), passed: true };
  } finally { fs.rmSync(home, { recursive: true, force: true }); }
}
