#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {pathToFileURL} from 'node:url';

const ids = new Set(['woowtech.paseo', 'woowtech.omnigent']);
export function decide(previous, installed, bundled) {
  if (previous?.removed || previous?.userManaged) return 'preserve';
  if (previous && !installed) return 'removed';
  if (installed === bundled) return 'record';
  if (installed && (!previous || installed !== previous.version)) return 'user-managed';
  return 'install';
}

function safePath(file) {
  let current = path.resolve(file);
  while (true) {
    try {if (fs.lstatSync(current).isSymbolicLink()) throw new Error('Symlink in extension seed path');}
    catch (error) {if (error.code !== 'ENOENT') throw error;}
    const parent = path.dirname(current); if (parent === current) return; current = parent;
  }
}
function save(file, data) {
  safePath(file);
  const temporary = `${file}.${crypto.randomUUID()}.tmp`;
  fs.writeFileSync(temporary, JSON.stringify(data, null, 2) + '\n', {mode: 0o600, flag: 'wx'});
  fs.renameSync(temporary, file);
}

export function seed({env = process.env, run = execFileSync} = {}) {
  const bundleDir = env.WOOW_CONNECTOR_VSIX_DIR || '/opt/woow-connector-vsix';
  const extensionsDir = env.WOOW_CODE_EXTENSIONS_DIR || path.join(env.HOME || '/home/coder', '.local/share/code-server/extensions');
  // The receipt belongs to the installed extensions, not the agent data volume.
  // A recreated IDE (or a second IDE sharing agent data) can have a fresh
  // extension store. Its missing files must not be mistaken for an uninstall.
  safePath(extensionsDir); fs.mkdirSync(extensionsDir, {recursive: true, mode: 0o755});
  const receipt = path.join(extensionsDir, '.woow-connector-seed.json'); safePath(receipt);
  const previous = fs.existsSync(receipt) ? JSON.parse(fs.readFileSync(receipt, 'utf8')) : {};
  const manifest = JSON.parse(fs.readFileSync(path.join(bundleDir, 'manifest.json'), 'utf8'));
  const entries = Array.isArray(manifest) ? manifest : manifest.extensions;
  if (!Array.isArray(entries) || entries.length !== 2 || new Set(entries.map(x => x.id)).size !== 2) throw new Error('Invalid VSIX manifest');
  for (const entry of entries) {
    if (!ids.has(entry.id) || !/^\d+\.\d+\.\d+(?:-[\w.-]+)?$/.test(entry.version)
        || typeof entry.file !== 'string' || path.basename(entry.file) !== entry.file || !entry.file.endsWith('.vsix')) throw new Error('Invalid VSIX manifest');
    const artifact = path.join(bundleDir, entry.file); safePath(artifact);
    if (crypto.createHash('sha256').update(fs.readFileSync(artifact)).digest('hex') !== entry.sha256) throw new Error('VSIX checksum mismatch');
  }
  const options = {encoding: 'utf8', timeout: 120000, maxBuffer: 1024 * 1024, env, stdio: ['ignore', 'pipe', 'pipe']};
  const cli = env.WOOW_CODE_SERVER_BIN || 'code-server';
  const installed = Object.fromEntries(run(cli, ['--extensions-dir', extensionsDir, '--list-extensions', '--show-versions'], options)
    .split(/\r?\n/).map(line => line.trim().split('@')).filter(([id, version]) => ids.has(id) && version));
  const result = [];
  for (const entry of entries) {
    const action = decide(previous[entry.id], installed[entry.id], entry.version);
    if (action === 'install') {
      run(cli, ['--extensions-dir', extensionsDir, '--install-extension', path.join(bundleDir, entry.file), '--force'], options);
      const check = run(cli, ['--extensions-dir', extensionsDir, '--list-extensions', '--show-versions'], options);
      if (!check.split(/\r?\n/).some(line => line.trim() === `${entry.id}@${entry.version}`)) throw new Error('Extension installation was not verified');
    }
    if (action === 'install' || action === 'record') previous[entry.id] = {version: entry.version};
    if (action === 'removed') previous[entry.id] = {...previous[entry.id], removed: true};
    if (action === 'user-managed') previous[entry.id] = {version: installed[entry.id], userManaged: true};
    save(receipt, previous);
    result.push({id: entry.id, action});
  }
  return result;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {process.stdout.write(JSON.stringify(seed()) + '\n');}
  catch {process.stderr.write('WOOW connector extension installation failed. Use Extensions: Install from VSIX with the files in /opt/woow-connector-vsix.\n'); process.exitCode = 1;}
}
