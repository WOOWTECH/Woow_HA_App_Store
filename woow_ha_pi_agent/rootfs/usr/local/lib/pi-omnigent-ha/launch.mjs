import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { seed, loadPlugin, BUNDLE } from './lifecycle.mjs';
import { createServer } from './server.mjs';

const agentDir = process.env.PI_CODING_AGENT_DIR;
const socket = path.join(agentDir, 'omnigent-ha.sock');
let plugin, worker, child, stopWatching, shuttingDown = false, activeRoot = null;
function stopWorker() {
  if (!worker) return;
  try { process.kill(-worker.pid, 'SIGTERM'); } catch {}
  worker = null;
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
  await next.web.ensureOnboarding();
  worker = spawn(process.execPath, [path.join(next.root, 'bin/cli.mjs'), 'boot'], { env: process.env, stdio: 'ignore', detached: true });
  const current = worker;
  current.once('error', () => { if (worker === current) worker = null; });
  current.once('exit', () => { if (worker === current) worker = null; });
}
try {
  seed();
  const web = await import(`${BUNDLE}/src/web.mjs`);
  await activate();
  stopWatching = web.watchPackageLifecycle(async () => { if (!shuttingDown) await activate(); });
} catch { console.error('Omnigent setup needs attention; Pi Web remains available.'); }

// A private Unix socket adds no host-network listener. Existing nginx peer
// restrictions remain the browser authentication boundary.
const server = createServer();
server.on('error', () => console.error('Omnigent settings socket unavailable.'));
try {
  try { if (fs.lstatSync(socket).isSocket()) fs.unlinkSync(socket); else throw new Error('Socket path occupied'); }
  catch (error) { if (error.code !== 'ENOENT') throw error; }
  server.listen(socket, () => fs.chmodSync(socket, 0o666));
} catch { console.error('Omnigent settings socket unavailable; Pi Web remains available.'); }
// Use the pinned image runtime; never install/rebuild the plugin's Pi Web 0.10 overlay.
child = spawn('/usr/local/bin/pi-web', process.argv.slice(2), { stdio: 'inherit', env: process.env });
async function close() {
  shuttingDown = true;
  stopWorker();
  await stopWatching?.();
  server.close();
  server.closeAllConnections();
}
for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP']) process.on(signal, () => { child.kill(signal); void close(); });
child.on('error', async () => { console.error('Pi Web failed to start.'); await close(); process.exitCode = 1; });
child.on('exit', async (code, signal) => { await close(); process.exitCode = code ?? (signal ? 1 : 0); });
