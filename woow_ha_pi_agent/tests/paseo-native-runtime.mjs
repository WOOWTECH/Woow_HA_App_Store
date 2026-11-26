// Offline image contract: execute the two actual patched native PID writers.
// All writes are confined to a disposable home; no daemon/provider is started.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { execFileSync, spawnSync } from 'node:child_process';

// The image's copy of cli-runtime/versions.json: the pins it was built from.
const PINS = '/usr/local/share/woow-ha-pi-agent/versions.json';
export async function verifyNativeRuntime({ bundle, runtimeDir, pins = JSON.parse(fs.readFileSync(PINS, 'utf8')).agentConnect }) {
  const layout = await import(pathToFileURL(path.join(bundle, 'src/runtime-layout.mjs')).href);
  const patch = await import(pathToFileURL(path.join(bundle, 'src/pid-lock-patch.mjs')).href);
  const transition = await import(pathToFileURL(path.join(bundle, 'src/pid-transition.mjs')).href);
  const pkg = JSON.parse(fs.readFileSync(path.join(bundle, 'package.json')));
  assert.equal(pkg.name, '@woowtech/pi-paseo');
  assert.equal(pkg.version, pins.version);
  assert.equal(layout.PASEO_VERSION, pins.paseoVersion);
  assert.equal(layout.RUNTIME_REVISION, pins.runtimeRevision);
  assert.equal(layout.runtimeReady({ runtimeDir }), true);
  const root = layout.runtimeDirectory({ runtimeDir });
  const receipt = JSON.parse(fs.readFileSync(path.join(root, '.pi-paseo-runtime.json')));
  assert.equal(receipt.revision, pins.runtimeRevision);
  for (const name of ['cli', 'server']) {
    assert.equal(JSON.parse(fs.readFileSync(path.join(root, 'node_modules/@getpaseo', name, 'package.json'))).version,
      pins.paseoVersion, `${name} must belong to the pinned daemon version`);
  }
  assert.equal(patch.pidLockPatchReady(root), true, 'both native copies and transition helpers must match');
  assert.match(execFileSync('flock', ['--version'], { encoding: 'utf8', timeout: 5000 }), /util-linux/);
  const modules = await Promise.all(patch.PID_LOCK_COPIES.map(copy =>
    import(pathToFileURL(path.join(root, 'node_modules/@getpaseo/server', copy, 'pid-lock.js')).href)));
  assert.equal(modules.length, 2);
  const home = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'ha-paseo-native-')));
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
      // A persisted PID from another boot must not block the new image, even
      // when that numeric PID is alive again. Only the fixture file is removed.
      fs.writeFileSync(pidFile, JSON.stringify({ pid: process.pid, startedAt: '2000-01-01T00:00:00.000Z',
        hostname: 'offline-fixture', uid: process.getuid(), listen: null, heartbeat: true,
        bootId: '00000000-0000-0000-0000-000000000000', piPaseoProtocol: 'linux-flock-v1' }), { mode: 0o600 });
      assert.equal((await control.isLocked(home)).locked, false, 'a previous-boot PID is stale');
      await supervisor.acquirePidLock(home, null);
      const lock = await control.getPidLockInfo(home);
      assert.equal(lock.pid, process.pid);
      assert.equal(lock.piPaseoProtocol, 'linux-flock-v1');
      assert.equal(lock.bootId, fs.readFileSync('/proc/sys/kernel/random/boot_id', 'utf8').trim());
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
    await verifyStaleRecovery({ bundle, runtimeDir, home, writer: modules[0] });
    return { runtime: layout.RUNTIME_REVISION, patchId: patch.PID_LOCK_PATCH_ID,
      writerCopies: modules.length, competingFlockExcluded: true, allFourWritersPerCopy: true,
      previousBootRecoveryPerCopy: true, controlledBirthProofRecovery: true, identityFilesRetained: true,
      uid: process.getuid(), passed: true };
  } finally { fs.rmSync(home, { recursive: true, force: true }); }
}

/** Exercise the frozen plugin's receipt recovery with a controlled process-birth
 * reader. No daemon is started or signalled; identity files contain fixture data.
 * A real container restart remains a separate acceptance gate. */
async function verifyStaleRecovery({ bundle, runtimeDir, home, writer }) {
  const state = await import(pathToFileURL(path.join(bundle, 'src/state.mjs')).href);
  const identity = await import(pathToFileURL(path.join(bundle, 'src/daemon-identity.mjs')).href);
  const previousStateDir = process.env.PI_PASEO_STATE_DIR;
  process.env.PI_PASEO_STATE_DIR = path.join(home, 'state');
  try {
    const loc = { ...state.locations(), runtimeDir };
    const { installationId } = state.updateState({});
    state.atomicJson(path.join(loc.paseoHome, '.pi-paseo-owner.json'), { installationId, home: loc.paseoHome });
    const files = ['server-id', 'daemon-keypair.json', 'config.json'];
    for (const name of files) fs.writeFileSync(path.join(loc.paseoHome, name), JSON.stringify({ fixture: name }), { mode: 0o600 });
    const before = files.map(name => fs.readFileSync(path.join(loc.paseoHome, name)));
    const birth = identity.readLinuxBirth(process.pid);
    let absent = false, supervisorChecks = 0;
    const recovery = identity.createDaemonIdentity({ readBirth: () => absent ? null : birth,
      assertNoSupervisor: () => { supervisorChecks++; } });
    await state.withRuntimeLock(async () => {
      await writer.acquirePidLock(loc.paseoHome, null);
      const lock = await writer.getPidLockInfo(loc.paseoHome);
      const pidFile = path.join(loc.paseoHome, 'paseo.pid');
      const pidBytes = fs.readFileSync(pidFile), pidStat = fs.statSync(pidFile);
      const guard = path.join(loc.paseoHome, '.pi-paseo-pid-transition.guard');
      const guardInode = fs.statSync(guard).ino;
      await assert.rejects(recovery.recoverStaleInstance(loc, lock), { code: 'DAEMON_NOT_OWNED' }, 'no proof, no recovery');
      const verifyOwner = instance => assert.equal(instance.pid, process.pid);
      const observed = await recovery.observeOwnedInstance(loc, lock, verifyOwner);
      await recovery.rememberOwnedInstance(loc, lock, verifyOwner, observed);
      await assert.rejects(recovery.recoverStaleInstance(loc, lock), { code: 'DAEMON_NOT_OWNED' }, 'a live incarnation is not stale');
      absent = true;
      const { quarantine } = await recovery.recoverStaleInstance(loc, lock);
      assert.equal(fs.existsSync(pidFile), false);
      assert.deepEqual(fs.readFileSync(quarantine), pidBytes, 'retain the stale record as evidence');
      assert.equal(fs.statSync(quarantine).ino, pidStat.ino);
      assert.equal(supervisorChecks, 2, 'check for a replacement supervisor on both sides of the rename');
      await writer.acquirePidLock(loc.paseoHome, null);
      await writer.releasePidLock(loc.paseoHome, { ownerPid: process.pid });
      assert.equal(fs.statSync(guard).ino, guardInode, 'recovery never removes the shared guard');
    });
    assert.equal(state.readState().installationId, installationId);
    files.forEach((name, index) => {
      assert.deepEqual(fs.readFileSync(path.join(loc.paseoHome, name)), before[index], `${name} retained`);
      assert.equal(fs.statSync(path.join(loc.paseoHome, name)).mode & 0o777, 0o600);
    });
  } finally {
    if (previousStateDir === undefined) delete process.env.PI_PASEO_STATE_DIR;
    else process.env.PI_PASEO_STATE_DIR = previousStateDir;
  }
}
