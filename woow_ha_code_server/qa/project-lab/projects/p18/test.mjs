import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { meta, run } from './app.mjs';
const cases = JSON.parse(readFileSync(new URL('./cases.json', import.meta.url), 'utf8'));
assert.ok(cases.length >= 4);
assert.ok(cases.filter(c => !c.error).length >= 2);
assert.ok(cases.some(c => c.error));
assert.equal(meta.id, new URL('.', import.meta.url).pathname.split('/').filter(Boolean).at(-1));
assert.equal(meta.version, '1.1.0');
for (const key of ['title', 'category', 'description']) assert.ok(typeof meta[key] === 'string' && meta[key].length > 0);
assert.ok(meta.example && typeof meta.example === 'object' && !Array.isArray(meta.example));
function freeze(value) {
  if (value && typeof value === 'object') { Object.values(value).forEach(freeze); Object.freeze(value); }
  return value;
}
let passed = 0;
for (const fixture of cases) {
  const input = freeze(structuredClone(fixture.input));
  if (fixture.error) {
    assert.throws(() => run(input), error => error instanceof Error && error.message.length > 0 && (!fixture.errorIncludes || error.message.includes(fixture.errorIncludes)), fixture.name);
  } else {
    const actual = run(input);
    assert.deepStrictEqual(actual, fixture.expected, fixture.name);
    assert.deepStrictEqual(JSON.parse(JSON.stringify(actual)), actual, `${fixture.name}: serializable result`);
    assert.deepStrictEqual(run(input), fixture.expected, `${fixture.name}: deterministic repeat`);
  }
  assert.deepStrictEqual(input, fixture.input, `${fixture.name}: input must remain unchanged`);
  passed++;
}
const sample = run(freeze(structuredClone(meta.example)));
assert.deepStrictEqual(JSON.parse(JSON.stringify(sample)), sample);
console.log(JSON.stringify({ id: meta.id, passed, rejected: cases.filter(c => c.error).length, sample: 'passed', immutableInputs: true }));
