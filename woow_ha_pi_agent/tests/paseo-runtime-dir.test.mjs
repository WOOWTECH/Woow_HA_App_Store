// Which runtime directory the launcher gives the Paseo plugin (PI_PASEO_RUNTIME_DIR). The case that matters is
// the first start after an update to a newer Paseo: a runtime saved in the user's home holds the earlier releases
// only, and the image carries the new one ready. Used as it is, the plugin would download about 0.7 GB at that
// start (its installer runs `npm ci` whenever the release it needs is not ready in the directory it is given).
// The plugin here is a stand-in with the one export the launcher uses; tests/paseo-contract.test.mjs asks the real
// frozen plugin, and the image smoke asks the real plugin about the real runtime.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { chooseRuntimeDir, BUNDLED_RUNTIME } from '../rootfs/usr/local/lib/pi-paseo-ha/runtime-dir.mjs';

const root = path.resolve(import.meta.dirname, '..');
const CURRENT = '2.0.0-r1-aaaaaaaaaaaa', EARLIER = '1.0.0-r4-bbbbbbbbbbbb';

/** A plugin whose release is `revision`: ready when <runtimeDir>/releases/<revision> holds a receipt that names it, like the real one. */
function plugin(base, revision = CURRENT) {
  const dir = path.join(base, `plugin-${revision}`);
  fs.mkdirSync(path.join(dir, 'src'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'src/runtime-layout.mjs'), `import fs from 'node:fs';
import path from 'node:path';
export const runtimeReady = loc => {
  try { return JSON.parse(fs.readFileSync(path.join(loc.runtimeDir, 'releases', ${JSON.stringify(revision)}, '.receipt.json'))).revision === ${JSON.stringify(revision)}; }
  catch { return false; }
};
`);
  return dir;
}
/** <runtimeDir>/releases/<revision>, complete (a receipt) or the leftover of an interrupted install (no receipt). */
function release(runtimeDir, revision, { complete = true } = {}) {
  const dir = path.join(runtimeDir, 'releases', revision);
  fs.mkdirSync(path.join(dir, 'node_modules/pkg'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'node_modules/pkg/index.js'), `// ${revision}\n`);
  if (complete) fs.writeFileSync(path.join(dir, '.receipt.json'), JSON.stringify({ revision }));
}
function world(t) {
  const base = fs.mkdtempSync(path.join(os.tmpdir(), 'ha-runtime-dir-'));
  t.after(() => fs.rmSync(base, { recursive: true, force: true }));
  const home = path.join(base, 'home'), bundled = path.join(base, 'opt/paseo-runtime');
  fs.mkdirSync(home, { recursive: true }); fs.mkdirSync(bundled, { recursive: true });
  return { base, home, bundled, saved: path.join(home, '.local/share/pi-paseo/runtime'), plugin: plugin(base) };
}
/** Every path, mode, mtime and content hash below `dir`: what "nothing in it was touched" means. */
function fingerprint(dir) {
  const rows = [];
  (function walk(current) {
    for (const entry of fs.readdirSync(current, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
      const file = path.join(current, entry.name), stat = fs.lstatSync(file);
      rows.push([path.relative(dir, file), stat.mode, stat.mtimeMs, entry.isFile() ? createHash('sha256').update(fs.readFileSync(file)).digest('hex') : '']);
      if (entry.isDirectory()) walk(file);
    }
  })(dir);
  return rows;
}
const ask = (w, extra = {}) => chooseRuntimeDir({ home: w.home, bundled: w.bundled, pluginRoot: async () => w.plugin, ...extra });

test('the bundled runtime is where the image puts it', () => {
  assert.equal(BUNDLED_RUNTIME, '/opt/woow/paseo-runtime');
  assert.ok(fs.readFileSync(path.join(root, 'Dockerfile'), 'utf8').includes('/opt/woow/paseo-runtime-layers/a/ /'), 'the final stage copies the runtime to the same place');
});

test('without a saved runtime the bundled one is used, and the plugin is not even asked', async t => {
  const w = world(t);
  release(w.bundled, CURRENT);
  let asked = 0;
  assert.equal(await ask(w, { pluginRoot: async () => { asked++; return w.plugin; } }), w.bundled);
  assert.equal(asked, 0, 'the common start costs nothing');
});

test('a saved runtime that holds only earlier releases does not hide the ready bundled one, and is left exactly as it was', async t => {
  const w = world(t);
  release(w.bundled, CURRENT);
  release(w.saved, EARLIER);
  fs.writeFileSync(path.join(w.saved, 'note'), 'the user\'s own file');
  const before = fingerprint(w.saved);
  assert.equal(await ask(w), w.bundled, 'no download: the image already carries the release');
  assert.deepEqual(fingerprint(w.saved), before, 'nothing in the saved runtime was changed, moved or removed');
});

test('a saved runtime that holds the needed release is kept, whether or not the bundled one has it', async t => {
  const w = world(t);
  release(w.saved, EARLIER); release(w.saved, CURRENT);
  assert.equal(await ask(w), w.saved, 'the bundled runtime is empty');
  release(w.bundled, CURRENT);
  assert.equal(await ask(w), w.saved, 'a runtime the user keeps still comes first');
});

test('a saved release that is not complete is not trusted: the plugin would reinstall it, the bundled one needs no install', async t => {
  const w = world(t);
  release(w.bundled, CURRENT);
  release(w.saved, CURRENT, { complete: false });
  assert.equal(await ask(w), w.bundled);
  fs.writeFileSync(path.join(w.saved, 'releases', CURRENT, '.receipt.json'), JSON.stringify({ revision: EARLIER }));
  assert.equal(await ask(w), w.bundled, 'a receipt that names another revision is no receipt');
});

test('when neither directory can serve the plugin the saved one stays, so that what the plugin installs persists', async t => {
  const w = world(t);
  release(w.saved, EARLIER);
  assert.equal(await ask(w), w.saved);
  release(w.bundled, EARLIER);
  assert.equal(await ask(w), w.saved, 'a bundled runtime of another revision does not serve this plugin either');
});

test('a plugin other than the bundled one is judged by its own release: a saved runtime that serves it is kept, one that does not stays when the image has nothing for it', async t => {
  const w = world(t);
  const other = plugin(w.base, '3.0.0-r1-cccccccccccc');
  release(w.bundled, CURRENT); release(w.saved, '3.0.0-r1-cccccccccccc');
  assert.equal(await ask(w, { pluginRoot: async () => other }), w.saved);
  fs.rmSync(path.join(w.saved, 'releases'), { recursive: true }); release(w.saved, EARLIER);
  assert.equal(await ask(w, { pluginRoot: async () => other }), w.saved, 'the image carries nothing for that plugin: it installs into the saved runtime, which persists');
  assert.equal(await ask(w), w.bundled, 'and the bundled plugin, asked about the same directories, gets the image runtime');
});

test('a plugin that cannot be found or asked leaves the saved runtime in place, as the launcher always did', async t => {
  const w = world(t);
  release(w.bundled, CURRENT); release(w.saved, EARLIER);
  // One directory per variant: a module is loaded once per location.
  const layout = (name, source) => {
    const dir = path.join(w.base, name); fs.mkdirSync(path.join(dir, 'src'), { recursive: true });
    fs.writeFileSync(path.join(dir, 'src/runtime-layout.mjs'), source); return dir;
  };
  const cases = {
    'no registered plugin could be read': async () => { throw new Error('Invalid package settings'); },
    'no layout module there (an older plugin)': async () => path.join(w.base, 'missing'),
    'a check that throws is no answer': async () => layout('throws', 'export const runtimeReady = () => { throw new Error("unsupported"); };\n'),
    'a layout without the check': async () => layout('without', 'export const other = 1;\n'),
    'a layout that does not parse': async () => layout('syntax', 'export const = ;\n'),
  };
  for (const [what, pluginRoot] of Object.entries(cases)) assert.equal(await ask(w, { pluginRoot }), w.saved, what);
});
