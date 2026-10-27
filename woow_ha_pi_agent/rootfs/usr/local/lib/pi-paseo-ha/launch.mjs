import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { seed, prepareImage, startLifecycle } from './lifecycle.mjs';
import { createServer } from './server.mjs';

const socket = path.join(process.env.PI_CODING_AGENT_DIR, 'paseo-ha.sock');
const savedRuntime = path.join(process.env.HOME, '.local/share/pi-paseo/runtime');
process.env.PI_PASEO_RUNTIME_DIR ||= fs.existsSync(savedRuntime) ? savedRuntime : '/opt/woow/paseo-runtime';
let stop, closing = false;
try {
  await prepareImage(); seed();
  stop = await startLifecycle();
} catch { console.error('Paseo initialization needs attention; Pi Web remains available.'); }
const server = createServer();
server.on('error', () => console.error('Paseo settings socket unavailable.'));
try {
  try { if (fs.lstatSync(socket).isSocket()) fs.unlinkSync(socket); else throw new Error('Socket path occupied'); }
  catch (error) { if (error.code !== 'ENOENT') throw error; }
  server.listen(socket, () => fs.chmodSync(socket, 0o666));
} catch { console.error('Paseo settings socket unavailable; Pi Web remains available.'); }
// Preserve the existing Omnigent bridge and official Pi Web 0.12 launcher.
const child = spawn(process.execPath, ['/usr/local/lib/pi-omnigent-ha/launch.mjs', ...process.argv.slice(2)], { stdio: 'inherit', env: process.env });
async function close() {
  if (closing) return; closing = true;
  server.close(); server.closeAllConnections();
  try { await stop?.(); } catch { console.error('Paseo shutdown needs attention.'); }
}
for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP']) process.on(signal, () => { child.kill(signal); void close(); });
child.on('error', async () => { await close(); process.exitCode = 1; });
child.on('exit', async (code, signal) => { await close(); process.exitCode = code ?? (signal ? 1 : 0); });
