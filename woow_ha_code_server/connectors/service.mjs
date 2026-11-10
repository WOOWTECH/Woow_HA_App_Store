#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {dispatch} from './cli.mjs';

const stateRoot = path.resolve(process.env.WOOW_CONNECTOR_DATA_DIR || path.join(process.env.PI_AGENT_DATA_DIR || '/data/pi-agent', 'connectors'));
function privateRoot() {
  let current = stateRoot;
  while (true) {
    try {if (fs.lstatSync(current).isSymbolicLink()) throw new Error('Unsafe state directory');}
    catch (error) {if (error.code !== 'ENOENT') throw error;}
    const parent = path.dirname(current); if (parent === current) break; current = parent;
  }
  fs.mkdirSync(stateRoot, {recursive: true, mode: 0o700});
  const stat = fs.statSync(stateRoot);
  if (stat.uid !== process.getuid()) throw new Error('State belongs to a different user');
  fs.chmodSync(stateRoot, 0o700);
  const lock = path.join(stateRoot, 'service.lock');
  const fd = fs.openSync(lock, fs.constants.O_CREAT | fs.constants.O_WRONLY | fs.constants.O_NOFOLLOW, 0o600);
  fs.fchmodSync(fd, 0o600); fs.closeSync(fd);
  return lock;
}

async function supervise() {
  let stopped = false, wake;
  const stop = () => {stopped = true; wake?.();};
  process.once('SIGTERM', stop); process.once('SIGINT', stop);
  const previous = new Map();
  while (!stopped) {
    // Restore is authorized only by the adapter's persisted connection state.
    for (const connector of ['paseo', 'omnigent']) {
      if (stopped) break;
      const result = await dispatch({connector, action: 'restore'});
      const state = result.ok ? 'ok' : /^[A-Z_0-9]+$/.test(result.error?.code || '') ? result.error.code : 'failed';
      if (previous.get(connector) !== state) {
        process.stderr.write(JSON.stringify({connector, restore: state}) + '\n'); previous.set(connector, state);
      }
    }
    if (!stopped) await new Promise(resolve => {
      const timer = setTimeout(done, 30000);
      function done() {clearTimeout(timer); wake = undefined; resolve();}
      wake = done;
    });
  }
}

try {
  const lock = privateRoot();
  if (process.argv.includes('--locked')) await supervise();
  else {
    const child = spawn('/usr/bin/flock', ['--no-fork', '--nonblock', '--conflict-exit-code', '0', lock, process.execPath, fileURLToPath(import.meta.url), '--locked'], {stdio: 'inherit'});
    for (const signal of ['SIGTERM', 'SIGINT']) process.on(signal, () => child.kill(signal));
    child.on('error', () => {process.stderr.write('Connector service could not acquire its process lock.\n'); process.exitCode = 1;});
    child.on('exit', code => {process.exitCode = code ?? 1;});
  }
} catch {
  process.stderr.write('Connector service requires a private, writable state directory.\n'); process.exitCode = 1;
}
