import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { randomUUID } from 'node:crypto';
import { setTimeout as delay } from 'node:timers/promises';
import { spawnSync } from 'child_process';

export class RuntimeError extends Error {
  constructor(code, message = code) { super(message); this.name = 'RuntimeError'; this.code = code; }
}
export function locations() {
  const home = path.resolve(process.env.HOME || os.homedir());
  const dataDir = path.resolve(process.env.PI_AGENT_DATA_DIR || '/data/pi-agent');
  const agentDir = path.resolve(process.env.PI_CODING_AGENT_DIR || dataDir);
  const stateDir = path.join(path.resolve(process.env.WOOW_CONNECTOR_DATA_DIR || path.join(dataDir, 'connectors')), 'paseo');
  const runtimeDir = path.resolve(process.env.WOOW_PASEO_RUNTIME_DIR || '/opt/woow-connectors/paseo/runtime');
  let savedPort;
  assertSafePath(path.join(stateDir, 'state.json'));
  try { savedPort = JSON.parse(fs.readFileSync(path.join(stateDir, 'state.json'), 'utf8')).port; } catch {}
  const port = Number(savedPort || process.env.WOOW_PASEO_PORT || 6769);
  if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new RuntimeError('INVALID_PORT');
  return { home, dataDir, agentDir, stateDir, paseoHome: path.join(stateDir, 'daemon'), runtimeDir, port };
}
// Reject links in any component, including dangling links and redirected parents.
export function assertSafePath(file) {
  let current = path.resolve(file), leaf;
  while (true) {
    try {
      const stat = fs.lstatSync(current);
      if (stat.isSymbolicLink()) {
        // macOS exposes its root-owned temporary paths through fixed system
        // aliases. User-created or redirected aliases remain unsafe.
        const systemAlias = process.platform === 'darwin' && stat.uid === 0 &&
          ['/var', '/tmp'].includes(current) &&
          path.resolve(path.dirname(current), fs.readlinkSync(current)) === '/private' + current;
        if (!systemAlias) throw new RuntimeError('UNSAFE_SYMLINK');
      }
      if (current === path.resolve(file)) leaf = stat;
    } catch (error) { if (error.code !== 'ENOENT') throw error; }
    const parent = path.dirname(current);
    if (parent === current) return leaf;
    current = parent;
  }
}
export function privateDirectory(dir) {
  assertSafePath(dir);
  fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
  assertSafePath(dir); fs.chmodSync(dir, 0o700);
}
export function atomicJson(file, value) {
  privateDirectory(path.dirname(file));
  assertSafePath(file);
  const temp = `${file}.${process.pid}.${randomUUID()}.tmp`;
  try {
    const fd = fs.openSync(temp, 'wx', 0o600);
    try { fs.writeFileSync(fd, `${JSON.stringify(value, null, 2)}\n`); fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
    fs.renameSync(temp, file); fs.chmodSync(file, 0o600);
  } finally { try { fs.unlinkSync(temp); } catch {} }
}
const forbiddenKey = /^(password|apiKey|token|accessToken|refreshToken|secret|pairingUrl|connectionUri|qr|credentials)$/i;
function assertPublic(value) {
  if (!value || typeof value !== 'object') return;
  for (const [key, child] of Object.entries(value)) {
    if (forbiddenKey.test(key)) throw new RuntimeError('STATE_SECRET_FIELD');
    assertPublic(child);
  }
}
export function readState() {
  const file = path.join(locations().stateDir, 'state.json');
  try {
    assertSafePath(file);
    const value = JSON.parse(fs.readFileSync(file, 'utf8'));
    if (!value || typeof value !== 'object' || Array.isArray(value)) throw new RuntimeError('STATE_CORRUPT');
    assertPublic(value); return value;
  } catch (error) { if (error.code === 'ENOENT') return {}; if (error instanceof RuntimeError) throw error; throw new RuntimeError('STATE_CORRUPT'); }
}
export function processIdentity(pid) {
  if (!Number.isInteger(pid) || pid <= 1) return null;
  try {
    process.kill(pid, 0);
    if (process.platform === 'linux') {
      const stat = fs.readFileSync(`/proc/${pid}/stat`, 'utf8');
      return fs.readFileSync('/proc/sys/kernel/random/boot_id', 'utf8').trim() + ':' + stat.slice(stat.lastIndexOf(')') + 2).split(' ')[19];
    }
    return `alive:${pid}`;
  } catch { return null; }
}
const acquisitionGraceMs = 30000;
function sameFile(a, b) { return a?.ino === b?.ino && a?.dev === b?.dev && a?.mtimeMs === b?.mtimeMs; }
function pidAlive(pid) {
  if (!Number.isInteger(pid) || pid <= 1) return false;
  try { process.kill(pid, 0); return true; } catch (error) { return error.code === 'EPERM'; }
}
export function checkLockSignal(signal) {
  if (signal?.aborted) throw new RuntimeError('LOCK_ABORTED');
}
export async function pauseForLock(ms, signal) {
  checkLockSignal(signal);
  try { await delay(ms, undefined, { signal }); }
  catch (error) { if (error.name === 'AbortError') throw new RuntimeError('LOCK_ABORTED'); throw error; }
}
/**
 * Linux requires util-linux flock; other platforms fail closed. The persistent
 * guard must never be unlinked: every participant must lock the same inode.
 * flock inherits fd 3, so its lock remains on our open file description after
 * the utility exits. Closing our fd releases it even on process death. Only
 * acquisition/reclamation/publication run here, never an async operation body.
 */
export function withLockTransition(file, fn, { timeoutMs = 1000, deadline, signal } = {}) {
  checkLockSignal(signal);
  if (process.platform !== 'linux') throw new RuntimeError('LOCK_GUARD_UNSUPPORTED');
  const guard = file + '.guard';
  assertSafePath(guard);
  let fd;
  try {
    fd = fs.openSync(guard, fs.constants.O_RDWR | fs.constants.O_CREAT | fs.constants.O_NOFOLLOW | fs.constants.O_NONBLOCK, 0o600);
    const stat = fs.fstatSync(fd), current = assertSafePath(guard);
    if (!stat.isFile() || stat.nlink !== 1 || current?.ino !== stat.ino || current?.dev !== stat.dev) throw new RuntimeError('UNSAFE_LOCK');
    fs.fchmodSync(fd, 0o600);
    const result = spawnSync('flock', ['--exclusive', '--nonblock', '--conflict-exit-code', '73', '3'], {
      stdio: ['ignore', 'ignore', 'ignore', fd], shell: false,
      env: { PATH: process.env.PATH ?? '/usr/bin:/bin', LC_ALL: 'C' },
      timeout: Math.max(1, Math.min(1000, timeoutMs)), killSignal: 'SIGKILL',
    });
    if (result.error) {
      // Expiring the enclosing operation is contention, not a separate helper
      // failure. No protected callback ran; finally closes the OS guard fd.
      if(result.error.code==='ETIMEDOUT'&&deadline!==undefined&&Date.now()>=deadline)return null;
      throw new RuntimeError(result.error.code === 'ENOENT' ? 'LOCK_GUARD_UNAVAILABLE' : result.error.code === 'ETIMEDOUT' ? 'LOCK_GUARD_TIMEOUT' : 'LOCK_GUARD_FAILED');
    }
    checkLockSignal(signal);
    if (result.status === 73) return null;
    if (result.status !== 0 || result.signal) throw new RuntimeError('LOCK_GUARD_FAILED');
    return fn();
  } catch (error) {
    if (error instanceof RuntimeError) throw error;
    throw new RuntimeError(error.code === 'ELOOP' ? 'UNSAFE_SYMLINK' : 'LOCK_GUARD_FAILED');
  } finally { if (fd !== undefined) fs.closeSync(fd); }
}
function acquire(file, options) {
  return withLockTransition(file, () => acquireGuarded(file), options);
}
function acquireGuarded(file) {
  assertSafePath(file);
  const token = randomUUID();
  // A reclaimed lock is published again before releasing the OS guard.
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const fd = fs.openSync(file, 'wx', 0o600);
      let acquired;
      try {
        acquired = fs.fstatSync(fd);
        fs.writeFileSync(fd, JSON.stringify({ pid: process.pid, identity: processIdentity(process.pid), token, createdAt: new Date().toISOString() }));
        fs.fsyncSync(fd);
      } catch (error) {
        const current = assertSafePath(file);
        if (acquired && current?.ino === acquired.ino && current?.dev === acquired.dev) fs.unlinkSync(file);
        throw error;
      } finally { fs.closeSync(fd); }
      return () => {
        // A live owner cannot be reclaimed by guarded acquirers. Release does
        // not need another subprocess or a wait on the transition guard.
        try {
          const current = assertSafePath(file);
          if (current?.ino === acquired.ino && current?.dev === acquired.dev && JSON.parse(fs.readFileSync(file, 'utf8')).token === token) fs.unlinkSync(file);
        } catch {}
      };
    } catch (error) {
      if (error.code !== 'EEXIST') throw error;
      try {
        const before = assertSafePath(file);
        const contents = fs.readFileSync(file, 'utf8');
        let owner;
        try { owner = JSON.parse(contents); } catch {}
        if (owner && typeof owner === 'object') {
          const identity = processIdentity(owner.pid);
          if (owner.identity && identity === owner.identity) return null;
          // If process metadata is unavailable, retain a demonstrably live owner.
          if (!identity && pidAlive(owner.pid)) return null;
          if (!owner.identity && pidAlive(owner.pid)) return null;
        } else if (Date.now() - before.mtimeMs <= acquisitionGraceMs) {
          // Protect an incomplete acquisition from an older, unguarded version.
          return null;
        }
        if (sameFile(before, assertSafePath(file)) && fs.readFileSync(file, 'utf8') === contents) { fs.unlinkSync(file); continue; }
      } catch (failure) {
        if (failure.code === 'UNSAFE_SYMLINK') throw failure;
        if (failure.code === 'ENOENT') continue;
        return null;
      }
      return null;
    }
  }
  return null;
}
export function updateState(patch) {
  assertPublic(patch); const dir = locations().stateDir; privateDirectory(dir);
  const file = path.join(dir, 'state.lock'); const deadline = Date.now() + 3000; let release;
  while (!release) {
    if (Date.now() >= deadline) throw new RuntimeError('STATE_BUSY');
    release = acquire(file, { timeoutMs: deadline - Date.now(), deadline });
    if (!release) Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, Math.min(20, Math.max(1, deadline - Date.now())));
  }
  try {
    const current = readState();
    const updated = { version: 1, installationId: randomUUID(), ...current, ...patch, updatedAt: new Date().toISOString() };
    atomicJson(path.join(dir, 'state.json'), updated); return updated;
  } finally { release(); }
}
export async function withRuntimeLock(fn, { timeoutMs = 300000, signal } = {}) {
  checkLockSignal(signal);
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) throw new RuntimeError('INVALID_LOCK_OPTIONS');
  const dir = locations().stateDir; privateDirectory(dir); const file = path.join(dir, 'runtime.lock');
  const deadline = Date.now() + timeoutMs; let release;
  while (!release) {
    checkLockSignal(signal);
    if (Date.now() >= deadline) throw new RuntimeError('RUNTIME_BUSY');
    release = acquire(file, { timeoutMs: deadline - Date.now(), deadline, signal });
    if (!release) await pauseForLock(Math.min(100, Math.max(1, deadline - Date.now())), signal);
  }
  try { return await fn(); } finally { release(); }
}
