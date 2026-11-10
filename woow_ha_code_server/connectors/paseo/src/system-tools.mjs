import { findExecutable, runProcess } from './process.mjs';
import { RuntimeError } from './state.mjs';

// tree-kill uses GNU ps --ppid on Linux while cleaning up provider probes.
// Missing ps otherwise emits an unhandled child-process error in the daemon.
export async function requireSystemTools({ platform = process.platform, env = process.env, discover = findExecutable, run = runProcess } = {}) {
  if (!discover('flock', env)) throw new RuntimeError('FLOCK_REQUIRED');
  if (platform !== 'linux') return;
  const ps = discover('ps', env);
  if (!ps) throw new RuntimeError('PROCPS_REQUIRED');
  try {
    const version = await run(ps, ['--version'], { env, timeoutMs: 5000, maxBytes: 4096 });
    if (!/procps/i.test(version)) throw new Error();
  } catch { throw new RuntimeError('PROCPS_REQUIRED'); }
}
