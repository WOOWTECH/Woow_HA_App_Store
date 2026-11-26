#!/usr/bin/env node
// Opt-in measurement, not a test (CI never runs it): what the Paseo runtime weighs as image
// layers. It splits a runtime with patches/split-paseo-runtime.mjs and reports, for the
// whole runtime (what one COPY would have been) and for each half, the number of files, the
// bytes and the size of `tar | gzip -6`, which is about what a registry layer is. The limit
// is the one tests/assert-image-layer-sizes.mjs applies to new layers on main.
//
//   node tests/measure-paseo-runtime-layers.mjs --lock <dir>       package.json and package-lock.json of a runtime;
//                                                                  runs `npm ci --omit=dev --ignore-scripts` (network)
//   node tests/measure-paseo-runtime-layers.mjs --archive <tgz>    an Agent Connect archive: its runtime/ lock, same
//   node tests/measure-paseo-runtime-layers.mjs --runtime <dir>    an installed runtime (<dir>/releases/<release>/node_modules)
//
// Options: --work <dir> (default: a temporary directory, removed at the end), --keep, --json.
// A runtime installed this way has the musl Claude SDK sibling removed, as patches/build-paseo.mjs does.
// Needs GNU tar and gzip; --lock and --archive need npm and the registry.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawn, execFileSync } from 'node:child_process';
import { splitRuntime, linkWhole, readTree } from '../patches/split-paseo-runtime.mjs';

const DESTINATION = '/opt/woow/paseo-runtime';
const LIMIT = 256 * 1024 * 1024;
const MiB = bytes => (bytes / 1048576).toFixed(1);

function options(argv) {
  const found = { json: false, keep: false };
  for (let i = 0; i < argv.length; i++) {
    const flag = argv[i];
    if (flag === '--json') found.json = true;
    else if (flag === '--keep') found.keep = true;
    else if (['--lock', '--archive', '--runtime', '--work'].includes(flag)) found[flag.slice(2)] = path.resolve(argv[++i] ?? '');
    else throw new Error(`Unknown option ${flag}`);
  }
  if ([found.lock, found.archive, found.runtime].filter(Boolean).length !== 1) throw new Error('Give exactly one of --lock, --archive or --runtime');
  return found;
}
function install(work, lockDirectory) {
  const source = path.join(work, 'runtime');
  const release = path.join(source, 'releases', 'measured');
  fs.mkdirSync(release, { recursive: true });
  for (const name of ['package.json', 'package-lock.json']) fs.copyFileSync(path.join(lockDirectory, name), path.join(release, name));
  console.error(`npm ci in ${release} ...`);
  execFileSync('npm', ['ci', '--omit=dev', '--ignore-scripts', '--no-audit', '--no-fund', '--prefix', release, '--cache', path.join(work, 'npm-cache')], { stdio: ['ignore', 'inherit', 'inherit'] });
  fs.rmSync(path.join(release, 'node_modules/@anthropic-ai', `claude-agent-sdk-linux-${process.arch}-musl`), { recursive: true, force: true });
  return { source, release };
}
function gzipSize(directory) {
  return new Promise((resolve, reject) => {
    const tar = spawn('tar', ['--sort=name', '-cf', '-', '-C', directory, '.'], { stdio: ['ignore', 'pipe', 'inherit'] });
    const gzip = spawn('gzip', ['-6', '-n'], { stdio: ['pipe', 'pipe', 'inherit'] });
    let bytes = 0;
    gzip.stdout.on('data', chunk => { bytes += chunk.length; });
    tar.stdout.pipe(gzip.stdin);
    tar.on('close', code => { if (code !== 0) reject(new Error(`tar exited ${code}`)); });
    gzip.on('close', code => (code === 0 ? resolve(bytes) : reject(new Error(`gzip exited ${code}`))));
  });
}
async function measure(label, directory) {
  let files = 0, raw = 0;
  for (const entry of readTree(directory).values()) if (entry.type === 'file') { files++; raw += Number(entry.size); }
  return { label, files, rawBytes: raw, gzipBytes: await gzipSize(directory) };
}

const given = options(process.argv.slice(2));
const work = given.work ?? fs.mkdtempSync(path.join(os.tmpdir(), 'paseo-layers-'));
fs.mkdirSync(work, { recursive: true });
try {
  let source, release;
  if (given.runtime) {
    source = given.runtime;
    const releases = fs.readdirSync(path.join(source, 'releases'));
    if (releases.length !== 1) throw new Error(`Expected one release below ${source}/releases, found ${releases.join(', ') || 'none'}`);
    release = path.join(source, 'releases', releases[0]);
  } else {
    let lock = given.lock;
    if (given.archive) {
      lock = path.join(work, 'lock');
      fs.mkdirSync(lock, { recursive: true });
      for (const name of ['package.json', 'package-lock.json']) {
        fs.writeFileSync(path.join(lock, name), execFileSync('tar', ['-xzOf', given.archive, `package/runtime/${name}`], { maxBuffer: 64 * 1024 * 1024 }));
      }
    }
    ({ source, release } = install(work, lock));
  }
  const output = path.join(work, 'layers'), whole = path.join(work, 'whole');
  fs.rmSync(whole, { recursive: true, force: true });
  const summary = splitRuntime({ source, release, destination: DESTINATION, outputRoot: output });
  linkWhole({ source, destination: DESTINATION, target: whole });
  const rows = [await measure('whole (one layer)', whole), await measure('layer a (all but @anthropic-ai)', path.join(output, 'a')), await measure('layer b (@anthropic-ai)', path.join(output, 'b'))];
  if (given.json) console.log(JSON.stringify({ release: summary.release, limitBytes: LIMIT, rows }, null, 2));
  else {
    console.log(`release ${path.basename(release)}; limit per layer ${MiB(LIMIT)} MiB (tests/assert-image-layer-sizes.mjs)`);
    console.log('layer'.padEnd(34), 'files'.padStart(7), 'raw MiB'.padStart(9), 'gzip -6 MiB'.padStart(12), '% of limit'.padStart(11));
    for (const row of rows) console.log(row.label.padEnd(34), String(row.files).padStart(7), MiB(row.rawBytes).padStart(9), MiB(row.gzipBytes).padStart(12), `${(100 * row.gzipBytes / LIMIT).toFixed(0)}%`.padStart(11));
  }
} finally {
  if (!given.keep && !given.work) {
    try { execFileSync('chmod', ['-R', 'u+rwx', work]); } catch { /* best effort: some package directories are read-only */ }
    fs.rmSync(work, { recursive: true, force: true });
  } else if (given.keep) console.error(`kept ${work}`);
}
