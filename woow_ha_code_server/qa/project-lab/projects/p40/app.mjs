export const meta = {
  id: 'p40', title: 'Weighted decision matrix', category: 'Planning', version: '1.1.0',
  description: 'Normalize benefit and cost criteria, apply weights, rank alternatives, and expose tied winners.',
  example: { criteria: [{ id: 'price', weight: 3, direction: 'cost' }, { id: 'battery', weight: 2, direction: 'benefit' }], alternatives: [{ name: 'Laptop A', values: { price: 800, battery: 8 } }, { name: 'Laptop B', values: { price: 1000, battery: 12 } }, { name: 'Laptop C', values: { price: 900, battery: 10 } }] },
  fields: [{ key: 'criteria', label: 'Weighted criteria', type: 'json' }, { key: 'alternatives', label: 'Alternatives and values', type: 'json' }]
};
function object(value, label) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(`${label} must be an object`);
}
function identifier(value, label, ids) {
  if (typeof value !== 'string' || !value.trim() || value !== value.trim() || value.length > 80 || ids.has(value)) throw new Error(`${label} must be a unique trimmed string of 1–80 characters`);
  ids.add(value);
}
const round = (n, digits = 4) => Number(n.toFixed(digits));
export function run(input) {
  object(input, 'input');
  const { criteria, alternatives } = input;
  if (!Array.isArray(criteria) || criteria.length < 1 || criteria.length > 20) throw new Error('criteria must contain 1–20 entries');
  if (!Array.isArray(alternatives) || alternatives.length < 2 || alternatives.length > 100) throw new Error('alternatives must contain 2–100 entries');
  const ids = new Set(), names = new Set();
  let totalWeight = 0;
  criteria.forEach(criterion => {
    object(criterion, 'criterion');
    identifier(criterion.id, 'criterion.id', ids);
    if (typeof criterion.weight !== 'number' || !Number.isFinite(criterion.weight) || criterion.weight < 0 || criterion.weight > 1e6) throw new Error('criterion.weight must be a finite number from 0 to 1000000');
    if (!['benefit', 'cost'].includes(criterion.direction)) throw new Error('criterion.direction must be benefit or cost');
    totalWeight += criterion.weight;
  });
  if (totalWeight <= 0) throw new Error('at least one criterion must have a positive weight');
  alternatives.forEach(alternative => {
    object(alternative, 'alternative');
    identifier(alternative.name, 'alternative.name', names);
    object(alternative.values, 'alternative.values');
    if (Object.keys(alternative.values).length !== ids.size || Object.keys(alternative.values).some(key => !ids.has(key))) throw new Error('alternative.values must have exactly the criterion IDs');
    criteria.forEach(({ id }) => {
      const value = alternative.values[id];
      if (!Object.hasOwn(alternative.values, id) || typeof value !== 'number' || !Number.isFinite(value) || Math.abs(value) > 1e12) throw new Error(`value for ${id} must be a finite number with magnitude at most 1e12`);
    });
  });
  const ranges = criteria.map(criterion => {
    const values = alternatives.map(a => a.values[criterion.id]);
    return { ...criterion, minimum: Math.min(...values), maximum: Math.max(...values) };
  });
  const rankings = alternatives.map(alternative => {
    let score = 0;
    const contributions = Object.fromEntries(ranges.map(criterion => {
      const { id, minimum, maximum, weight, direction } = criterion;
      const normalized = maximum === minimum ? 1 : direction === 'benefit' ? (alternative.values[id] - minimum) / (maximum - minimum) : (maximum - alternative.values[id]) / (maximum - minimum);
      const contribution = normalized * (weight / totalWeight) * 100;
      score += contribution;
      return [id, round(contribution)];
    }));
    return { rank: 0, name: alternative.name, score: round(score), contributions };
  }).sort((a, b) => b.score - a.score);
  rankings.forEach((row, index) => { row.rank = index > 0 && row.score === rankings[index - 1].score ? rankings[index - 1].rank : index + 1; });
  return { criteria: ranges.map(({ id, direction, weight, minimum, maximum }) => ({ id, direction, weight, normalizedWeight: round(weight / totalWeight, 6), minimum, maximum })), rankings, winnerNames: rankings.filter(r => r.rank === 1).map(r => r.name) };
}
