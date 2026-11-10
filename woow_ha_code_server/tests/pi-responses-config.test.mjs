import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
const script = new URL('../patches/configure-pi-responses.mjs', import.meta.url).pathname;
function fixture(t, config) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pi-responses-'));
  t.after(() => fs.rmSync(dir, {recursive: true, force: true}));
  const file = path.join(dir, 'models.json');
  fs.writeFileSync(file, JSON.stringify(config), {mode: 0o600});
  return {dir, file, run: (...args) => spawnSync(process.execPath,
    [script, '--models', file, '--provider', 'gateway', ...args], {encoding: 'utf8'})};
}
const config = () => ({providers: {gateway: {api: 'openai-completions', apiKey: 'secret-fixture',
  baseUrl: 'https://gateway.example/v1', models: [{id: 'vendor/gpt-6-sol', reasoning: true},
    {id: 'vendor/gpt-6.1-sol', api: 'openai-completions'}, {id: 'deepseek-v3'}]},
  other: {api: 'openai-completions', models: [{id: 'gpt-6-sol'}]}}});
test('preview writes nothing and never exposes credentials', t => {
  const f = fixture(t, config()), before = fs.readFileSync(f.file, 'utf8');
  const r = f.run(); assert.equal(r.status, 0); assert.equal(fs.readFileSync(f.file, 'utf8'), before);
  assert.deepEqual(fs.readdirSync(f.dir), ['models.json']); assert.ok(!r.stdout.includes('secret-fixture'));
  assert.deepEqual(JSON.parse(r.stdout).changed, ['vendor/gpt-6-sol', 'vendor/gpt-6.1-sol']);
});
test('apply changes only selected GPT-6 models and saves a private exact backup', t => {
  const original = config(), f = fixture(t, original), before = fs.readFileSync(f.file, 'utf8');
  const r = f.run('--apply'); assert.equal(r.status, 0, r.stderr);
  const out = JSON.parse(r.stdout), updated = JSON.parse(fs.readFileSync(f.file));
  assert.equal(fs.readFileSync(out.backup, 'utf8'), before);
  for (const file of [f.file, out.backup]) assert.equal(fs.statSync(file).mode & 0o777, 0o600);
  for (const m of original.providers.gateway.models.slice(0, 2)) m.api = 'openai-responses';
  assert.deepEqual(updated, original); assert.ok(!r.stdout.includes('secret-fixture'));
  const second = f.run('--apply'); assert.equal(second.status, 0); assert.deepEqual(JSON.parse(second.stdout).changed, []);
  assert.equal(fs.readdirSync(f.dir).length, 2);
});
test('unknown APIs fail without a partial update', t => {
  const c = config(); c.providers.gateway.models[1].api = 'custom-api';
  const f = fixture(t, c), before = fs.readFileSync(f.file, 'utf8'), r = f.run('--apply');
  assert.equal(r.status, 1); assert.equal(fs.readFileSync(f.file, 'utf8'), before);
  assert.deepEqual(fs.readdirSync(f.dir), ['models.json']);
});
test('malformed JSON does not leak its contents', t => {
  const f = fixture(t, config()); fs.writeFileSync(f.file, '{"apiKey":"secret-fixture",');
  const r = f.run('--apply'); assert.equal(r.status, 1); assert.ok(!r.stderr.includes('secret-fixture'));
});
test('symlink configuration is refused without replacing the link', t => {
  const f = fixture(t, config()), target = path.join(f.dir, 'real.json');
  fs.renameSync(f.file, target); fs.symlinkSync(target, f.file);
  assert.equal(f.run('--apply').status, 1); assert.ok(fs.lstatSync(f.file).isSymbolicLink());
});
test('missing provider or unknown arguments cannot modify configuration', t => {
  const f = fixture(t, {providers: {}});
  assert.equal(f.run('--apply').status, 1); assert.equal(f.run('--oops').status, 1);
  assert.deepEqual(JSON.parse(fs.readFileSync(f.file)), {providers: {}});
});
