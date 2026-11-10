import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { meta, run } from './app.mjs';
const cases = JSON.parse(readFileSync(new URL('./cases.json', import.meta.url), 'utf8'));
assert.ok(cases.length >= 4, 'at least four fixtures');
assert.ok(cases.filter(c => !c.error).length >= 2, 'at least two known outputs');
assert.ok(cases.some(c => c.error), 'at least one rejection');
assert.equal(meta.id, new URL('.', import.meta.url).pathname.split('/').filter(Boolean).at(-1));
assert.equal(meta.version, '1.1.0');
assert.ok(meta.example && typeof meta.example === 'object' && !Array.isArray(meta.example));
function freeze(value) {
  if (value && typeof value === 'object') { Object.values(value).forEach(freeze); Object.freeze(value); }
  return value;
}
for (const c of cases) {
  const input = freeze(structuredClone(c.input));
  if (c.error) {
    assert.throws(() => run(input), error => error instanceof Error && error.message.length > 0 && (!c.errorPattern || new RegExp(c.errorPattern, 'i').test(error.message)), c.name);
  } else {
    const result = run(input);
    assert.deepStrictEqual(result, c.expected, c.name);
    assert.deepStrictEqual(JSON.parse(JSON.stringify(result)), c.expected, c.name + ': JSON output');
    assert.deepStrictEqual(run(input), result, c.name + ': deterministic repeat');
  }
  console.log('PASS ' + c.name);
}
const sample = run(freeze(structuredClone(meta.example)));
assert.deepStrictEqual(JSON.parse(JSON.stringify(sample)), sample, 'example produces JSON');
console.log(JSON.stringify({project: meta.id, passed: cases.length, failed: 0, example: 'passed'}));
