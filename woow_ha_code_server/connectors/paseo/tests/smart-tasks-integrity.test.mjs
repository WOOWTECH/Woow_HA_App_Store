import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { validateSmartTasksSource, smartTasksPatchReady } from '../src/smart-tasks-patch.mjs';

const payload = fileURLToPath(new URL('../runtime/better-paseo/', import.meta.url));
const normalRead = file => fs.readFileSync(file);

test('reviewed Better Paseo source payload validates completely', () => {
  const files = validateSmartTasksSource();
  assert.equal(files.length, 11);
  assert.ok(files.some(file => file.name === 'assets/icon.png'));
  assert.ok(files.some(file => file.name === 'index.client.ts'));
  assert.ok(files.some(file => file.name === 'server/builtin.js'));
});

for (const [label, victim, transform] of [
  ['truncated', 'server/builtin.js', bytes => bytes.subarray(0, Math.max(0, bytes.length - 1))],
  ['tampered', 'assets/icon.png', bytes => Buffer.concat([bytes, Buffer.from([0])])],
]) test(`${label} Better Paseo source fails before installation`, () => {
  const target = path.join(payload, victim);
  assert.throws(() => validateSmartTasksSource(file => file === target ? transform(normalRead(file)) : normalRead(file)), { code: 'SMART_TASKS_SOURCE_MISMATCH' });
});

test('missing Better Paseo source fails before installation', () => {
  const target = path.join(payload, 'index.client.ts');
  assert.throws(() => validateSmartTasksSource(file => {
    if (file === target) { const error = new Error('missing'); error.code = 'ENOENT'; throw error; }
    return normalRead(file);
  }), { code: 'SMART_TASKS_SOURCE_MISSING' });
});

test('runtime payload readiness fails closed when builtin payload is absent', t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'agent-connect-payload-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  assert.equal(smartTasksPatchReady(root), false);
});

test('build-time installer has no daemon stop or private-home mutation path', () => {
  const shell = fs.readFileSync(new URL('../install-runtime.sh', import.meta.url), 'utf8');
  assert.match(shell, /exec node "\$source_dir\/src\/runtime-installer.mjs"/);
  const installer = shell + fs.readFileSync(new URL('../src/runtime-installer.mjs', import.meta.url), 'utf8');
  assert.doesNotMatch(installer, /daemon\s+(?:stop|start)|PASEO_HOME|WOOW_CONNECTOR_DATA_DIR|paseo\.pid/);
  assert.match(installer, /markRuntimeReady/);
});
