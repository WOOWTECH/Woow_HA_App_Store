export const meta = {
  id: 'p30', title: 'Deterministic Pairwise Test Generator', category: 'Testing', version: '1.1.0',
  description: 'Build a reproducible test set covering every value pair across independent factors using deterministic greedy selection.',
  example: { factors: [{ name: 'browser', values: ['Chromium', 'Firefox'] }, { name: 'theme', values: ['light', 'dark'] }, { name: 'account', values: ['guest', 'member'] }] }
};
export function run(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input) || Object.keys(input).some(k => !['factors', 'maxCases'].includes(k))) throw new Error('Input must contain factors and optional maxCases');
  const { factors, maxCases = 256 } = input;
  if (!Array.isArray(factors) || factors.length < 2 || factors.length > 8) throw new Error('factors must contain 2–8 factors');
  if (!Number.isInteger(maxCases) || maxCases < 1 || maxCases > 256) throw new Error('maxCases must be an integer between 1 and 256');
  const names = new Set();
  let cartesianCount = 1;
  for (const factor of factors) {
    if (!factor || typeof factor !== 'object' || Array.isArray(factor) || Object.keys(factor).some(k => !['name', 'values'].includes(k)) || typeof factor.name !== 'string' || !/^[A-Za-z][A-Za-z0-9_]{0,39}$/.test(factor.name) || ['constructor', 'prototype'].includes(factor.name)) throw new Error('Each factor needs a safe unique name of 1–40 characters');
    if (names.has(factor.name)) throw new Error(`Duplicate factor name ${factor.name}`);
    names.add(factor.name);
    if (!Array.isArray(factor.values) || factor.values.length < 1 || factor.values.length > 8) throw new Error('Each factor needs 1–8 unique scalar values');
    for (const value of factor.values) if (!(value === null || typeof value === 'boolean' || (typeof value === 'number' && Number.isFinite(value)) || (typeof value === 'string' && value.length <= 80))) throw new Error('Factor values must be null, booleans, finite numbers, or strings up to 80 characters');
    if (new Set(factor.values.map(v => JSON.stringify(v))).size !== factor.values.length) throw new Error(`Duplicate values for factor ${factor.name}`);
    cartesianCount *= factor.values.length;
    if (cartesianCount > 4096) throw new Error('Cartesian space exceeds 4096 combinations');
  }
  const pairSpecs = [];
  let totalPairs = 0;
  for (let a = 0; a < factors.length; a++) for (let b = a + 1; b < factors.length; b++) {
    pairSpecs.push({ a, b, offset: totalPairs });
    totalPairs += factors[a].values.length * factors[b].values.length;
  }
  const candidates = [];
  function expand(indices) {
    if (indices.length === factors.length) {
      candidates.push({ indices, pairs: pairSpecs.map(({ a, b, offset }) => offset + indices[a] * factors[b].values.length + indices[b]) });
      return;
    }
    for (let i = 0; i < factors[indices.length].values.length; i++) expand([...indices, i]);
  }
  expand([]);
  const covered = new Uint8Array(totalPairs), chosen = [];
  let coveredPairs = 0;
  while (coveredPairs < totalPairs) {
    if (chosen.length >= maxCases) throw new Error(`maxCases is insufficient: ${totalPairs - coveredPairs} pairs remain uncovered`);
    let best = null, bestScore = 0;
    for (const candidate of candidates) {
      let score = 0;
      for (const pair of candidate.pairs) if (!covered[pair]) score++;
      // First Cartesian candidate wins ties; factor/value input order defines the tie order.
      if (score > bestScore) { best = candidate; bestScore = score; }
    }
    if (!best) throw new Error('Unable to cover remaining pairs');
    chosen.push(best.indices);
    for (const pair of best.pairs) if (!covered[pair]) { covered[pair] = 1; coveredPairs++; }
  }
  return {
    factorOrder: factors.map(f => f.name), cartesianCount, totalPairs, coveredPairs, testCount: chosen.length,
    cases: chosen.map((indices, i) => ({ case: i + 1, values: Object.fromEntries(factors.map((factor, j) => [factor.name, factor.values[indices[j]]])) }))
  };
}
