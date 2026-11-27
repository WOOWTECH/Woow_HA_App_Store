import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { atomicJson, privateDirectory, assertSafePath, processIdentity, RuntimeError, withLockTransition, checkLockSignal, pauseForLock } from './state.mjs';

export function readRecord(file, fallback = {}) {
  try {
    assertSafePath(file);
    const record = JSON.parse(fs.readFileSync(file, 'utf8'));
    if (!record || typeof record !== 'object' || Array.isArray(record)) throw new Error();
    return record;
  } catch (e) {
    if (e.code === 'ENOENT') return fallback;
    if (e.code === 'UNSAFE_SYMLINK') throw e;
    throw new Error('Invalid plugin state file');
  }
}
export function writeRecord(file, record) { atomicJson(file, record); }
function sameDirectory(a, b) { return a?.ino === b?.ino && a?.dev === b?.dev && a?.mtimeMs === b?.mtimeMs; }
function liveOwner(owner) {
  if (!Number.isInteger(owner.pid) || owner.pid <= 1) return false;
  const identity = processIdentity(owner.pid);
  if (owner.identity && identity) return owner.identity === identity;
  try { process.kill(owner.pid, 0); return true; } catch (error) { return error.code === 'EPERM'; }
}
export async function withLock(file, fn, { timeoutMs = 15000, signal } = {}) {
  checkLockSignal(signal);
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) throw new RuntimeError('INVALID_LOCK_OPTIONS');
  privateDirectory(path.dirname(file));
  const until = Date.now() + timeoutMs, token = crypto.randomUUID();
  let acquired;
  while (true) {
    checkLockSignal(signal);
    if (Date.now() >= until) throw new RuntimeError('LOCK_BUSY', 'Plugin operation is already running');
    acquired = withLockTransition(file, () => {
      for (let attempt = 0; attempt < 2; attempt++) {
        assertSafePath(file);
        try {
          fs.mkdirSync(file, { mode: 0o700 });
          const stat = fs.lstatSync(file);
          try { writeRecord(path.join(file, 'owner.json'), { pid: process.pid, identity: processIdentity(process.pid), token }); }
          catch (error) { fs.rmSync(file, { recursive: true, force: true }); throw error; }
          return stat;
        } catch (e) {
          if (e.code !== 'EEXIST') throw e;
          try {
            const before = assertSafePath(file);
            if (!before) continue;
            if (!before.isDirectory()) throw new RuntimeError('UNSAFE_LOCK');
            let owner;
            try { owner = readRecord(path.join(file, 'owner.json')); }
            catch (error) { if (error.code === 'UNSAFE_SYMLINK') throw error; }
            const old = Date.now() - before.mtimeMs > 30000;
            // Identity-bearing dead owners can be reclaimed immediately. Older
            // incomplete acquisitions still need the existing grace period.
            if (!liveOwner(owner || {}) && (owner?.identity || old)) {
              const again = assertSafePath(file);
              if (sameDirectory(before, again)) fs.rmSync(file, { recursive: true, force: true });
              continue;
            }
          } catch (error) { if (error.code !== 'ENOENT') throw error; else continue; }
          return null;
        }
      }
      return null;
    }, { timeoutMs: until - Date.now(), deadline:until, signal });
    if (acquired) break;
    if (Date.now() >= until) throw new RuntimeError('LOCK_BUSY', 'Plugin operation is already running');
    await pauseForLock(Math.min(100, Math.max(1, until - Date.now())), signal);
  }
  try {
    return await fn();
  } finally {
    try {
      const current = assertSafePath(file);
      if (current?.ino === acquired.ino && current?.dev === acquired.dev && readRecord(path.join(file, 'owner.json')).token === token) fs.rmSync(file, { recursive: true, force: true });
    } catch {}
  }
}
