import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { seed, startLifecycle, findPlugin, BUNDLE } from './lifecycle.mjs';
import { chooseRuntimeDir } from './runtime-dir.mjs';
import { createServer } from './server.mjs';
import { superviseChild } from '../pi-launch/child-shutdown.mjs';

const socket = path.join(process.env.PI_CODING_AGENT_DIR, 'paseo-ha.sock');
// A runtime the operator names is used as given. Otherwise the one saved in the home directory while it can
// serve the registered plugin, else the one in the image (runtime-dir.mjs).
process.env.PI_PASEO_RUNTIME_DIR ||= await chooseRuntimeDir({ home: process.env.HOME, pluginRoot: async () => (await findPlugin())?.root ?? BUNDLE });
let stop, closing = false;
// Registration and the lifecycle restore are separate steps: a failed seed (unreadable
// settings, an unwritable marker) must never keep an already registered plugin from
// being restored.
try { seed(); } catch { console.error('Paseo initialization needs attention; Pi Web remains available.'); }
try { stop = await startLifecycle(); } catch { console.error('Paseo initialization needs attention; Pi Web remains available.'); }
const server = createServer();
server.on('error', () => console.error('Paseo settings socket unavailable.'));
try {
  try { if (fs.lstatSync(socket).isSocket()) fs.unlinkSync(socket); else throw new Error('Socket path occupied'); }
  catch (error) { if (error.code !== 'ENOENT') throw error; }
  server.listen(socket, () => fs.chmodSync(socket, 0o666));
} catch { console.error('Paseo settings socket unavailable; Pi Web remains available.'); }
// Preserve the existing Omnigent bridge and official Pi Web 0.12 launcher: the one
// beside this directory (/usr/local/lib/pi-omnigent-ha/launch.mjs in the image).
const child = spawn(process.execPath, [path.join(import.meta.dirname, '../pi-omnigent-ha/launch.mjs'), ...process.argv.slice(2)], { stdio: 'inherit', env: process.env });
// Stop budget (issue 212): Supervisor SIGKILLs the container 10 s after
// `docker stop`, and s6-overlay waits for this service without a limit. A Paseo
// plugin supervisor that is still activating (provider probes, daemon start)
// only notices SIGTERM after that step, which can take minutes, so its stop is
// bounded here. Whatever is left then is stopped by s6-overlay's final
// SIGTERM/SIGKILL of the container's processes.
superviseChild(child, {
  name: 'Paseo',
  killAfterMs: 4500, cleanupTimeoutMs: 4000, deadlineMs: 5000,
  cleanup: async () => {
    if (closing) return; closing = true;
    server.close(); server.closeAllConnections();
    try { await stop?.(); } catch { console.error('Paseo shutdown needs attention.'); }
  },
});
