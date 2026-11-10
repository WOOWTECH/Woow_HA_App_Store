import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { RuntimeError } from './state.mjs';

export function findExecutable(name, env = process.env) {
  const candidates = path.isAbsolute(name) ? [name] : (env.PATH || '').split(path.delimiter).map(dir => path.join(dir, name));
  for (const file of candidates) { try { fs.accessSync(file, fs.constants.X_OK); if (fs.statSync(file).isFile()) return path.resolve(file); } catch {} }
  return null;
}
/** Child output stays private. Errors contain only a fixed category and exit code. */
export function runProcess(command, args, { env = process.env, cwd, timeoutMs = 30000, maxBytes = 4 * 1024 * 1024, signal } = {}) {
  if (!Array.isArray(args) || !args.every(arg => typeof arg === 'string') || !Number.isFinite(timeoutMs) || timeoutMs <= 0) throw new RuntimeError('INVALID_PROCESS_OPTIONS');
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { shell: false, stdio: ['ignore', 'pipe', 'pipe'], env, cwd, windowsHide: true });
    let out = [], bytes = 0, failure, killed;
    const stop = code => { failure ||= new RuntimeError(code); child.kill('SIGTERM'); killed ||= setTimeout(() => child.kill('SIGKILL'), 1500); killed.unref(); };
    const timeout = setTimeout(() => stop('COMMAND_TIMEOUT'), timeoutMs); timeout.unref();
    const abort = () => stop('COMMAND_ABORTED'); signal?.addEventListener('abort', abort, { once: true }); if (signal?.aborted) abort();
    child.stdout.on('data', data => { bytes += data.length; if (bytes > maxBytes) stop('COMMAND_OUTPUT_LIMIT'); else out.push(data); });
    child.stderr.on('data', data => { bytes += data.length; if (bytes > maxBytes) stop('COMMAND_OUTPUT_LIMIT'); });
    child.once('error', () => { failure ||= new RuntimeError('COMMAND_UNAVAILABLE'); });
    child.once('close', code => {
      clearTimeout(timeout); clearTimeout(killed); signal?.removeEventListener('abort', abort);
      if (failure) reject(failure);
      else if (code !== 0) reject(new RuntimeError('COMMAND_FAILED', `Command failed (exit ${Number.isInteger(code) ? code : 'signal'}).`));
      else resolve(Buffer.concat(out).toString('utf8'));
    });
  });
}
