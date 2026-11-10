import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { meta, run } from './app.mjs';

const fixtures = JSON.parse(readFileSync(new URL('./cases.json', import.meta.url), 'utf8'));
assert.ok(fixtures.length >= 4, 'At least four fixtures are required');
assert.ok(fixtures.filter(c => !c.error).length >= 2, 'At least two known-correct examples are required');
assert.ok(fixtures.some(c => c.error), 'A rejection fixture is required');
assert.equal(meta.id, new URL('.', import.meta.url).pathname.split('/').filter(Boolean).at(-1));
assert.equal(meta.version, '1.1.0');
for (const key of ['title', 'description', 'category']) assert.ok(typeof meta[key] === 'string' && meta[key].length > 0);
assert.ok(meta.example && typeof meta.example === 'object' && !Array.isArray(meta.example));
function freeze(value) {
  if (value && typeof value === 'object') { Object.values(value).forEach(freeze); Object.freeze(value); }
  return value;
}
for (const fixture of fixtures) {
  const input = freeze(structuredClone(fixture.input));
  const before = JSON.stringify(input);
  if (fixture.error) {
    assert.throws(() => run(input), error => error instanceof Error && (!fixture.errorContains || error.message.includes(fixture.errorContains)), fixture.name);
  } else {
    const result = run(input);
    assert.deepStrictEqual(result, fixture.expected, fixture.name);
    assert.deepStrictEqual(JSON.parse(JSON.stringify(result)), result, `${fixture.name}: JSON output`);
    assert.deepStrictEqual(run(structuredClone(input)), result, `${fixture.name}: deterministic`);
  }
  assert.equal(JSON.stringify(input), before, `${fixture.name}: immutable input`);
}
const sample = run(freeze(structuredClone(meta.example)));
assert.deepStrictEqual(JSON.parse(JSON.stringify(sample)), sample, 'Example must produce lossless JSON');
assert.throws(() => run(null), Error, 'Reject null input');
assert.throws(() => run([]), Error, 'Reject array input');
assert.throws(() => run({ ...structuredClone(meta.example), unexpectedInput: true }), Error, 'Reject unknown input keys');
console.log(`${meta.id}: ${fixtures.length} fixtures passed; example, metadata, deterministic output, immutable inputs, JSON and input-shape checks passed`);

// Independently enumerate the required value pairs and inspect returned rows.
const shapes = [[2, 2, 2], [3, 2, 4], [1, 3, 2, 2], [8, 8, 8, 8], [2, 2, 2, 2, 2, 2, 2, 2]];
for (const shape of shapes) {
  const factors = shape.map((size, i) => ({ name: `F${i}`, values: Array.from({ length: size }, (_, j) => `v${j}`) }));
  const result = run({ factors });
  assert.equal(result.coveredPairs, result.totalPairs);
  assert.equal(new Set(result.cases.map(c => JSON.stringify(c.values))).size, result.testCount, 'No repeated test rows');
  for (const row of result.cases) for (const factor of factors) assert.ok(factor.values.includes(row.values[factor.name]));
  let pairCount = 0;
  for (let a = 0; a < factors.length; a++) for (let b = a + 1; b < factors.length; b++) {
    for (const va of factors[a].values) for (const vb of factors[b].values) {
      pairCount++;
      assert.ok(result.cases.some(row => row.values[factors[a].name] === va && row.values[factors[b].name] === vb), `Missing pair ${a}:${va},${b}:${vb}`);
    }
  }
  assert.equal(result.totalPairs, pairCount);
  assert.deepStrictEqual(run({ factors }), result);
}
assert.throws(() => run({ factors: Array.from({ length: 5 }, (_, i) => ({ name: `F${i}`, values: [0, 1, 2, 3, 4, 5, 6, 7] })) }), /4096/);
console.log('p30: independent full pair-coverage audits passed for five factor shapes, including the 4096-combination limit');
