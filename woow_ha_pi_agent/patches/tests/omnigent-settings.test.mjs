// PI_WEB_ROOT points to an unpacked official @agegr/pi-web@0.12.0 npm tarball.
// Test real compiled artifacts; never reproduce a minifier's output as a mock.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { patchSettings } from '../patch-omnigent-settings.mjs';

const source = process.env.PI_WEB_ROOT;
assert.ok(source, 'PI_WEB_ROOT is required: extract the official 0.12.0 npm artifact first');
function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ha-settings-patch-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  fs.copyFileSync(path.join(source, 'package.json'), path.join(root, 'package.json'));
  fs.cpSync(path.join(source, '.next'), path.join(root, '.next'), { recursive: true });
  return root;
}
function snapshot(root) {
  return Object.fromEntries(fs.readdirSync(root, { recursive: true }).sort()
    .filter(file => fs.lstatSync(path.join(root, file)).isFile())
    .map(file => [file, fs.readFileSync(path.join(root, file)).toString('base64')]));
}
test('real compiled client and SSR patch, all flight references change, repeat is byte-identical', t => {
  const root = fixture(t); const receipt = patchSettings(root);
  assert.equal(receipt.length, 10); assert.ok(receipt.every(item => item.changed));
  const file = receipt[0].file; assert.match(file, /page-[a-f0-9]{16}\.js$/);
  assert.ok(!file.includes('b3286479e7c79f5d'));
  const name = path.basename(file);
  for (const item of receipt.slice(2)) {
    const text = fs.readFileSync(path.join(root, item.file), 'utf8');
    assert.ok(text.includes(name)); assert.ok(!text.includes('page-b3286479e7c79f5d.js'));
  }
  const before = snapshot(root); assert.ok(patchSettings(root).every(item => !item.changed));
  assert.deepEqual(snapshot(root), before);
});
test('client and SSR file icons retain one HA ingress prefix after nginx rewrites JS', t => {
  const root = fixture(t);
  const receipt = patchSettings(root);
  const ingress = '/api/hassio_ingress/fixture01234567890123';
  for (const item of receipt.slice(0, 2)) {
    const compiled = fs.readFileSync(path.join(root, item.file), 'utf8');
    // The production nginx sub_filter also matches quoted /icons/ literals in
    // JS chunks. The runtime prefix expression must survive that byte rewrite.
    const served = compiled.replaceAll('"/icons/', `"${ingress}/icons/`);
    const expression = served.match(/(?:let|var)\s+[\w$]+=([^;]*catppuccin[^;]*);function\s+[\w$]+\(/)?.[1];
    assert.ok(expression, `${item.file}: real compiled icon expression found`);
    const actual = new Function('window', `return ${expression}`)({ __INGRESS_PATH__: ingress });
    assert.equal(actual, `${ingress}/icons/catppuccin`, `${item.file}: one ingress prefix`);
  }
});
test('changed SSR rejects without touching the compatible client or manifests', t => {
  const root = fixture(t); fs.appendFileSync(path.join(root, '.next/server/app/page.js'), '\n// upstream changed');
  const before = snapshot(root); assert.throws(() => patchSettings(root), /unsupported compiled artifact/);
  assert.deepEqual(snapshot(root), before);
});
test('changed flight reference rejects before any compiled file is written', t => {
  const root = fixture(t); fs.appendFileSync(path.join(root, '.next/server/app/index.rsc'), '\nchanged');
  const before = snapshot(root); assert.throws(() => patchSettings(root), /incompatible asset reference/);
  assert.deepEqual(snapshot(root), before);
});
test('duplicate settings client and unknown package version reject without partial changes', t => {
  const root = fixture(t); const chunks = path.join(root, '.next/static/chunks/app');
  const client = fs.readdirSync(chunks).find(file => file.startsWith('page-'));
  fs.copyFileSync(path.join(chunks, client), path.join(chunks, 'unexpected-copy.js'));
  let before = snapshot(root); assert.throws(() => patchSettings(root), /expected one client/);
  assert.deepEqual(snapshot(root), before); fs.unlinkSync(path.join(chunks, 'unexpected-copy.js'));
  const file = path.join(root, 'package.json'); const meta = JSON.parse(fs.readFileSync(file)); meta.version = '0.12.1'; fs.writeFileSync(file, JSON.stringify(meta));
  before = snapshot(root); assert.throws(() => patchSettings(root), /requires @agegr\/pi-web 0.12.0/);
  assert.deepEqual(snapshot(root), before);
});
test('tampering with a previously patched bundle is rejected on repeat', t => {
  const root = fixture(t); const [receipt] = patchSettings(root); const file = path.join(root, receipt.file);
  fs.writeFileSync(file, fs.readFileSync(file, 'utf8').replace('label:"Omnigent"', 'label:"changed"'));
  const before = snapshot(root); assert.throws(() => patchSettings(root)); assert.deepEqual(snapshot(root), before);
});
