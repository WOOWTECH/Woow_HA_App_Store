import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { seed, loadPlugin, BUNDLE } from './lifecycle.mjs';
import { createServer } from './server.mjs';
import { startBootWorker } from './worker.mjs';
import { superviseChild } from '../pi-launch/child-shutdown.mjs';

const agentDir = process.env.PI_CODING_AGENT_DIR;
const socket = path.join(agentDir, 'omnigent-ha.sock');
// Codes only: an error message can carry paths or server responses.
const logCode = error => [error?.code, error?.name].find(value => typeof value === 'string' && /^[A-Za-z][A-Za-z0-9_]{0,63}$/.test(value)) || 'unknown';
let plugin, worker, child, stopWatching, shuttingDown = false, activeRoot = null;
// SIGTERM the worker's process group; on shutdown, wait for it (bounded) and
// SIGKILL the group if it is still there, so no worker outlives the add-on stop.
function stopWorker({ waitMs = 0 } = {}) {
  if (!worker) return Promise.resolve();
  const current = worker; worker = null;
  try { process.kill(-current.pid, 'SIGTERM'); } catch { return Promise.resolve(); }
  if (!waitMs || current.exitCode !== null || current.signalCode !== null) return Promise.resolve();
  return new Promise(resolve => {
    const timer = setTimeout(() => { try { process.kill(-current.pid, 'SIGKILL'); } catch {} resolve(); }, waitMs);
    current.once('exit', () => { clearTimeout(timer); resolve(); });
  });
}
async function activate() {
  const next = await loadPlugin();
  const lifecycle = next ? await next.lifecycle() : { active: false, registered: false, reason: 'package-removed-or-unregistered' };
  await (next || plugin)?.runtime.observeLifecycle?.(lifecycle);
  plugin = next || plugin;
  if (!lifecycle.active || !next.runtime.enabled()) { activeRoot = null; stopWorker(); return; }
  if (activeRoot === next.root) return;
  stopWorker();
  activeRoot = next.root;
  // Its boot result (resume outcome) and stderr reach the add-on log, redacted.
  worker = startBootWorker(next.root, { env: process.env });
  const current = worker;
  current.once('error', () => { if (worker === current) worker = null; });
  current.once('exit', () => { if (worker === current) worker = null; });
}
try {
  seed();
  const web = await import(`${BUNDLE}/src/web.mjs`);
  await activate();
  stopWatching = web.watchPackageLifecycle(async () => { if (!shuttingDown) await activate(); });
} catch (error) { console.error(`Omnigent setup needs attention (${logCode(error)}); Pi Web remains available.`); }

// A private Unix socket adds no host-network listener. Existing nginx peer
// restrictions remain the browser authentication boundary.
const server = createServer();
server.on('error', error => console.error(`Omnigent settings socket unavailable (${logCode(error)}).`));
try {
  try { if (fs.lstatSync(socket).isSocket()) fs.unlinkSync(socket); else throw new Error('Socket path occupied'); }
  catch (error) { if (error.code !== 'ENOENT') throw error; }
  server.listen(socket, () => fs.chmodSync(socket, 0o666));
} catch (error) { console.error(`Omnigent settings socket unavailable (${logCode(error)}); Pi Web remains available.`); }
// Use the pinned image runtime; never install/rebuild the plugin's Pi Web 0.10 overlay.
child = spawn('/usr/local/bin/pi-web', process.argv.slice(2), { stdio: 'inherit', env: process.env });
child.once('error', () => console.error('Pi Web failed to start.'));
// Stop budget (issue 212): inside the Paseo launcher's 5 s, so Pi Web gets
// 3.5 s to stop Next.js before it is killed, and this process always exits.
superviseChild(child, {
  name: 'Pi Web',
  killAfterMs: 3500, cleanupTimeoutMs: 2000, deadlineMs: 4000,
  cleanup: async () => {
    shuttingDown = true;
    server.close();
    server.closeAllConnections();
    await Promise.all([stopWorker({ waitMs: 1500 }), stopWatching?.()]);
  },
});
