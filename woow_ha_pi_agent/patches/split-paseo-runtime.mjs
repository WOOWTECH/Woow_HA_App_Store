// Build-time only: split the prepared Paseo runtime into two image layers.
//
// Why: the CI step "Enforce transport-safe image layers" (tests/assert-image-layer-sizes.mjs)
// rejects any new layer over 256 MiB compressed, and one COPY of the whole runtime made one
// layer. The Claude Agent SDK's platform binary under node_modules/@anthropic-ai is most of
// the runtime's weight and grows with the SDK, so it gets a layer of its own:
//
//   <outputRoot>/a/<destination>  everything except <release>/node_modules/@anthropic-ai
//   <outputRoot>/b/<destination>  only that directory (plus the directories above it)
//
// Both trees keep the full destination path, so the final stage is two plain copies
//   COPY --from=paseo-builder <outputRoot>/a/ /
//   COPY --from=paseo-builder <outputRoot>/b/ /
// and the runtime ends up exactly where, and exactly as, one copy of it would have put it.
//
// How: the trees are hard links to the installed files (and recreated symlinks and
// directories), made inside the RUN that installed the runtime, so nothing is copied and
// every file keeps its inode, bytes, mode, owner and mtime. Directories and symlinks get
// their mode, owner and mtime (microsecond precision) set explicitly. Every file, symlink
// and directory below the runtime must end up in exactly one layer (only the directories
// above @anthropic-ai are in both, identical); a self-check compares the result with a
// listing taken before and refuses anything else, removing the output first. A hard link
// that would straddle the two layers is refused too: COPY would turn it into two files.
//
// Nothing here knows a Paseo version or runtime revision: the release directory comes from
// the plugin's own runtime layout, as in build-paseo.mjs.
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

/** Relative to the release directory: the directory that is a layer of its own. */
export const HEAVY = 'node_modules/@anthropic-ai';
const LAYERS = ['a', 'b'];
const SPLIT_FILE = 'split.json';
const OWN_NAMES = [...LAYERS, 'check', SPLIT_FILE];
/** Directories and symlinks keep their mtime to the microsecond (utimes takes seconds as a double). */
const TIME_TOLERANCE_NS = 2000n;

const seconds = ns => Number(ns / 1000n) / 1e6;
const posix = value => value.split(path.sep).join('/');
const inside = (child, parent) => { const relative = path.relative(parent, child); return relative === '' || (!relative.startsWith('..') && !path.isAbsolute(relative)); };
const parts = destination => path.resolve(destination).split(path.sep).filter(Boolean);

/** Every entry below `root` (itself as ''), parents before children, siblings sorted: directories, files and symlinks only. */
export function readTree(root) {
  const entries = new Map();
  const visit = (absolute, rel) => {
    const stat = fs.lstatSync(absolute, { bigint: true });
    const type = stat.isDirectory() ? 'dir' : stat.isFile() ? 'file' : stat.isSymbolicLink() ? 'symlink' : null;
    if (!type) throw new Error(`Unsupported file type at ${rel || '.'}: only directories, files and symlinks can be split`);
    entries.set(rel, { rel, abs: absolute, type, mode: Number(stat.mode & 0o7777n), uid: Number(stat.uid), gid: Number(stat.gid),
      size: type === 'file' ? stat.size : 0n, mtimeNs: stat.mtimeNs, dev: stat.dev, ino: stat.ino,
      ...(type === 'symlink' ? { target: fs.readlinkSync(absolute) } : {}) });
    if (type === 'dir') for (const name of fs.readdirSync(absolute).sort()) visit(path.join(absolute, name), rel ? `${rel}/${name}` : name);
  };
  visit(root, '');
  return entries;
}

/** 'b' below the heavy directory, 'ab' for the directories that lead to it, 'a' for the rest. */
export function layerOf(rel, heavyRel) {
  if (rel === heavyRel || rel.startsWith(`${heavyRel}/`)) return 'b';
  if (rel === '' || heavyRel.startsWith(`${rel}/`)) return 'ab';
  return 'a';
}

function setOwner(target, entry, symlink) {
  const stat = fs.lstatSync(target);
  if (stat.uid !== entry.uid || stat.gid !== entry.gid) (symlink ? fs.lchownSync : fs.chownSync)(target, entry.uid, entry.gid);
}
function link(from, to) {
  try { fs.linkSync(from, to); }
  catch (error) {
    if (error.code === 'EXDEV') throw new Error('The layer directories must be on the same filesystem as the runtime: they are hard links to the installed files', { cause: error });
    throw error;
  }
}
/** Create `wanted` entries (parents first) under `root`, which stands for the runtime directory and must not exist yet. */
function populate(entries, root, wanted) {
  const directories = [];
  for (const entry of entries) {
    if (!wanted(entry)) continue;
    const target = entry.rel ? path.join(root, ...entry.rel.split('/')) : root;
    if (entry.type === 'dir') { fs.mkdirSync(target, { mode: 0o700 }); directories.push([entry, target]); }
    else if (entry.type === 'file') link(entry.abs, target);
    else {
      fs.symlinkSync(entry.target, target);
      setOwner(target, entry, true);
      fs.lutimesSync(target, seconds(entry.mtimeNs), seconds(entry.mtimeNs));
    }
  }
  // Last and children first: adding entries changes a directory's mtime, and a mode may forbid writing.
  for (const [entry, target] of directories.reverse()) {
    fs.chmodSync(target, entry.mode);
    setOwner(target, entry, false);
    fs.utimesSync(target, seconds(entry.mtimeNs), seconds(entry.mtimeNs));
  }
}
/** The directories between the layer's root and the runtime directory: plain, with the runtime directory's owner and time. */
function makeAncestors(base, names, like) {
  fs.mkdirSync(base);
  const made = [base];
  let current = base;
  for (const name of names) { current = path.join(current, name); fs.mkdirSync(current); made.push(current); }
  return () => { for (const directory of made.reverse()) { fs.chmodSync(directory, 0o755); setOwner(directory, like, false); fs.utimesSync(directory, seconds(like.mtimeNs), seconds(like.mtimeNs)); } };
}
function removeTree(target) {
  let stat;
  try { stat = fs.lstatSync(target); } catch { return; }
  if (stat.isDirectory()) {
    try { fs.chmodSync(target, 0o700); } catch { /* not ours to change */ }
    for (const name of fs.readdirSync(target)) removeTree(path.join(target, name));
  }
  fs.rmSync(target, { recursive: true, force: true });
}
/** Clear a previous run's output; anything that is not one of our own names is refused. */
function clearOutput(outputRoot) {
  if (!fs.existsSync(outputRoot)) return;
  const names = fs.readdirSync(outputRoot);
  const foreign = names.filter(name => !OWN_NAMES.includes(name));
  if (foreign.length || (names.length && !names.includes(SPLIT_FILE))) throw new Error(`${outputRoot} is not the output of an earlier split; refusing to clear it`);
  for (const name of names) removeTree(path.join(outputRoot, name));
}

function sameEntry(source, found, where) {
  const fail = what => { throw new Error(`${where}: ${what} differs from the installed runtime`); };
  if (found.type !== source.type) fail('the type');
  if (found.mode !== source.mode) fail(`the mode (${found.mode.toString(8)} against ${source.mode.toString(8)})`);
  if (found.uid !== source.uid || found.gid !== source.gid) fail('the owner');
  if (source.type === 'file') {
    if (found.dev !== source.dev || found.ino !== source.ino) fail('the file itself (not a link to the installed file)');
    if (found.size !== source.size || found.mtimeNs !== source.mtimeNs) fail('the size or mtime');
  } else {
    if (source.type === 'symlink' && found.target !== source.target) fail('the link target');
    const delta = found.mtimeNs - source.mtimeNs;
    if ((delta < 0n ? -delta : delta) > TIME_TOLERANCE_NS) fail('the mtime');
  }
}
/**
 * Compare the two layer trees under `outputRoot` with `source` (the listing taken before):
 * every entry in exactly the layer it belongs to, nothing missing, nothing extra, every
 * file the installed file itself. Throws on the first difference.
 */
export function verifySplit({ source, destination, outputRoot, heavyRel }) {
  const names = parts(destination);
  const seen = new Map();
  for (const layer of LAYERS) {
    let directory = path.join(outputRoot, layer);
    for (const name of names) {
      const found = fs.existsSync(directory) ? fs.readdirSync(directory) : [];
      if (found.length !== 1 || found[0] !== name) throw new Error(`layer ${layer} must hold only ${destination}; found ${JSON.stringify(found)} in ${directory}`);
      directory = path.join(directory, name);
    }
    for (const [rel, entry] of readTree(directory)) (seen.get(rel) ?? seen.set(rel, []).get(rel)).push({ layer, entry });
  }
  for (const [rel, expected] of source) {
    const where = rel || '.';
    const found = seen.get(rel);
    if (!found) throw new Error(`${where} is in neither layer`);
    const layers = found.map(item => item.layer).join('');
    if (layers !== layerOf(rel, heavyRel)) throw new Error(`${where} must be in layer ${layerOf(rel, heavyRel)} exactly once, found in ${layers}`);
    for (const item of found) sameEntry(expected, item.entry, `${where} in layer ${item.layer}`);
  }
  for (const rel of seen.keys()) if (!source.has(rel)) throw new Error(`${rel} is in a layer but not in the installed runtime`);
}

/** Link both layers' entries into one tree at `target` (what the image holds once both are copied). */
export function mergeLayers({ outputRoot, destination, target }) {
  const names = parts(destination);
  const merged = new Map();
  for (const layer of LAYERS) for (const [rel, entry] of readTree(path.join(outputRoot, layer, ...names))) if (!merged.has(rel)) merged.set(rel, entry);
  const root = path.join(target, ...names);
  fs.mkdirSync(path.dirname(root), { recursive: true });
  populate(merged.values(), root, () => true);
  return root;
}

function summarize(source, heavyRel) {
  const layers = Object.fromEntries(LAYERS.map(layer => [layer, { dirs: 0, files: 0, symlinks: 0, bytes: 0 }]));
  for (const entry of source.values()) {
    const where = layerOf(entry.rel, heavyRel);
    for (const layer of LAYERS) {
      if (!where.includes(layer)) continue;
      const row = layers[layer];
      if (entry.type === 'dir') row.dirs++; else if (entry.type === 'symlink') row.symlinks++; else { row.files++; row.bytes += Number(entry.size); }
    }
  }
  return layers;
}

/**
 * Split `source` (the runtime directory) into <outputRoot>/a and <outputRoot>/b, each holding
 * its share at `destination` (the runtime's path in the image; the source's own by default).
 * `release` is the release directory inside `source`; `heavy` is relative to it.
 */
export function splitRuntime({ source, release, destination = source, outputRoot, heavy = HEAVY, verify = verifySplit }) {
  source = path.resolve(source); release = path.resolve(release); destination = path.resolve(destination); outputRoot = path.resolve(outputRoot);
  if (destination === path.parse(destination).root) throw new Error('The destination must be a directory below the root');
  const releaseRel = posix(path.relative(source, release));
  if (!releaseRel || releaseRel.startsWith('..') || path.isAbsolute(releaseRel)) throw new Error(`The release directory ${release} is not inside ${source}`);
  const heavyRel = `${releaseRel}/${heavy}`;
  if (inside(outputRoot, source) || inside(source, outputRoot)) throw new Error('The output must be a directory of its own, outside the runtime');

  const manifest = readTree(source);
  const found = manifest.get(heavyRel);
  if (!found || found.type !== 'dir') throw new Error(`${heavyRel} must be a directory inside the runtime; it is the layer of its own`);
  const groups = new Map();
  for (const entry of manifest.values()) if (entry.type === 'file') (groups.get(`${entry.dev}:${entry.ino}`) ?? groups.set(`${entry.dev}:${entry.ino}`, []).get(`${entry.dev}:${entry.ino}`)).push(entry);
  for (const group of groups.values()) {
    if (group.length > 1 && new Set(group.map(entry => layerOf(entry.rel, heavyRel))).size > 1) {
      throw new Error(`Hard links cannot be split across layers (COPY would make two files): ${group.map(entry => entry.rel).join(', ')}`);
    }
  }

  clearOutput(outputRoot);
  fs.mkdirSync(outputRoot, { recursive: true });
  fs.writeFileSync(path.join(outputRoot, SPLIT_FILE), JSON.stringify({ complete: false }) + '\n');
  const root = manifest.get('');
  const names = parts(destination);
  try {
    for (const layer of LAYERS) {
      const finish = makeAncestors(path.join(outputRoot, layer), names.slice(0, -1), root);
      populate(manifest.values(), path.join(outputRoot, layer, ...names), entry => layerOf(entry.rel, heavyRel).includes(layer));
      finish();
    }
    verify({ source: manifest, destination, outputRoot, heavyRel });
  } catch (error) {
    for (const name of OWN_NAMES) removeTree(path.join(outputRoot, name));
    throw error;
  }
  const summary = { destination, release: releaseRel, heavy: heavyRel, layers: summarize(manifest, heavyRel) };
  fs.writeFileSync(path.join(outputRoot, SPLIT_FILE), JSON.stringify({ complete: true, ...summary }, null, 2) + '\n');
  return summary;
}

/** One tree holding the whole runtime at `destination` under `target`: what a single copy would have been (for measuring). */
export function linkWhole({ source, destination = source, target }) {
  const names = parts(destination);
  const manifest = readTree(path.resolve(source));
  fs.mkdirSync(path.dirname(path.join(target, ...names)), { recursive: true });
  populate(manifest.values(), path.join(target, ...names), () => true);
}

async function main([bundle = '/opt/woow/pi-paseo-plugin', runtimeDir = '/opt/woow/paseo-runtime', outputRoot = '/opt/woow/paseo-runtime-layers']) {
  const layout = await import(pathToFileURL(path.join(bundle, 'src/runtime-layout.mjs')).href);
  const release = layout.runtimeDirectory({ runtimeDir });
  if (!layout.runtimeReady({ runtimeDir })) throw new Error('The Paseo runtime is not ready; nothing to split');
  const summary = splitRuntime({ source: runtimeDir, release, outputRoot });
  // The plugin's own validation of what the image will hold once both layers are copied.
  const checked = path.join(outputRoot, 'check');
  try {
    const merged = mergeLayers({ outputRoot, destination: runtimeDir, target: checked });
    if (!layout.runtimeReady({ runtimeDir: merged })) throw new Error('The Paseo runtime is not ready once both layers are merged');
  } catch (error) {
    for (const name of OWN_NAMES) removeTree(path.join(outputRoot, name));
    throw error;
  } finally { removeTree(checked); }
  console.log(JSON.stringify(summary));
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) await main(process.argv.slice(2));
