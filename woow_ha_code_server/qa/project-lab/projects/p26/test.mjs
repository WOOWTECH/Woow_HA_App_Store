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

// Audit every simple directed graph on three vertices, including cycle evidence.
const allEdges = [['a', 'b'], ['a', 'c'], ['b', 'a'], ['b', 'c'], ['c', 'a'], ['c', 'b']];
for (let mask = 0; mask < 64; mask++) {
  const edges = allEdges.filter((_, i) => mask & (1 << i));
  const result = run({ nodes: ['c', 'b', 'a'], edges });
  assert.equal(new Set([...result.order, ...result.blocked]).size, 3);
  for (const [from, to] of edges) {
    if (result.order.includes(to)) assert.ok(result.order.includes(from) && result.order.indexOf(from) < result.order.indexOf(to));
  }
  if (result.acyclic) assert.equal(result.order.length, 3);
  else {
    assert.ok(result.cycle.length >= 3);
    assert.equal(result.cycle[0], result.cycle.at(-1));
    for (let i = 1; i < result.cycle.length; i++) assert.ok(edges.some(([a, b]) => a === result.cycle[i - 1] && b === result.cycle[i]));
  }
}
console.log('p26: topological-order and cycle-witness audit passed for all 64 three-node directed graphs');
