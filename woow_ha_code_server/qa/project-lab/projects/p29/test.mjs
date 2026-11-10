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

const micro = run({ capacity: 0.001, initialTokens: 0, refillPerSecond: 0.001, requests: [{ atMs: 1, cost: 0.001 }, { atMs: 1000, cost: 0.001 }] });
assert.deepStrictEqual(micro.events[0], { atMs: 1, cost: 0.001, accepted: false, tokensBefore: 0.000001, tokensAfter: 0.000001, retryAfterMs: 999 });
assert.equal(micro.accepted, 1);
assert.equal(micro.finalTokens, 0);
const large = run({ capacity: 1000000, initialTokens: 0, refillPerSecond: 1000000, requests: [{ atMs: 86400000, cost: 1000000 }] });
assert.equal(large.accepted, 1);
assert.equal(large.finalTokens, 0);
console.log('p29: microtoken precision and maximum idle/refill bounds passed');
