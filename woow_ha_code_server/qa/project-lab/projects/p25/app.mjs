export const meta = {
  id: 'p25', title: 'JSON Configuration Merge Inspector', category: 'Configuration', version: '1.1.0',
  description: 'Deep-merge JSON objects with explicit conflict policies and JSON Pointer paths for every change.',
  example: { base: { service: { port: 8080, mode: 'demo' }, tags: ['stable'] }, overlay: { service: { port: 9090 }, logging: true }, strategy: 'overlay' },
  fields: [{ key: 'base', label: 'Base configuration', type: 'json' }, { key: 'overlay', label: 'Overlay configuration', type: 'json' }, { key: 'strategy', label: 'Conflict policy', type: 'select', options: ['overlay', 'base', 'error'] }]
};
const record = v => v !== null && typeof v === 'object' && !Array.isArray(v) && [Object.prototype, null].includes(Object.getPrototypeOf(v));
const copy = v => JSON.parse(JSON.stringify(v));
const pointer = key => key.replace(/~/g, '~0').replace(/\//g, '~1');
function same(a, b) {
  if (a === b) return true;
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((v, i) => same(v, b[i]));
  if (record(a) && record(b)) return Object.keys(a).length === Object.keys(b).length && Object.keys(a).every(k => Object.hasOwn(b, k) && same(a[k], b[k]));
  return false;
}
export function run(input) {
  if (!record(input) || Object.keys(input).some(k => !['base', 'overlay', 'strategy'].includes(k))) throw new Error('Input must contain base, overlay, and optional strategy');
  const { base, overlay, strategy = 'overlay' } = input;
  if (!record(base) || !record(overlay)) throw new Error('base and overlay must be JSON objects');
  if (!['overlay', 'base', 'error'].includes(strategy)) throw new Error('strategy must be overlay, base, or error');
  let nodes = 0, characters = 0;
  function validate(value, depth) {
    if (++nodes > 10000 || depth > 20) throw new Error('Configuration exceeds 10000 values or 20 nesting levels');
    if (value === null || typeof value === 'boolean') return;
    if (typeof value === 'number' && Number.isFinite(value)) return;
    if (typeof value === 'string') {
      characters += value.length;
      if (value.length > 10000 || characters > 200000) throw new Error('Configuration string limits exceeded');
      return;
    }
    if (Array.isArray(value)) {
      if (value.length > 1000) throw new Error('Arrays may contain at most 1000 items');
      for (const item of value) validate(item, depth + 1);
      return;
    }
    if (!record(value)) throw new Error('Configuration must contain only JSON values');
    for (const [key, item] of Object.entries(value)) {
      if (key.length > 128 || ['__proto__', 'constructor', 'prototype'].includes(key)) throw new Error('Unsafe or overlong configuration key');
      characters += key.length;
      if (characters > 200000) throw new Error('Configuration string limits exceeded');
      validate(item, depth + 1);
    }
  }
  validate(base, 0); validate(overlay, 0);
  const conflicts = [], added = [];
  function merge(a, b, path) {
    const result = copy(a);
    for (const key of Object.keys(b).sort()) {
      const nextPath = `${path}/${pointer(key)}`;
      if (!Object.hasOwn(a, key)) { result[key] = copy(b[key]); added.push(nextPath); }
      else if (record(a[key]) && record(b[key])) result[key] = merge(a[key], b[key], nextPath);
      else if (!same(a[key], b[key])) {
        if (strategy === 'error') throw new Error(`Configuration conflict at ${nextPath}`);
        conflicts.push({ path: nextPath, base: copy(a[key]), overlay: copy(b[key]), resolution: strategy });
        result[key] = copy(strategy === 'overlay' ? b[key] : a[key]);
      }
    }
    return result;
  }
  const merged = merge(base, overlay, '');
  return { merged, conflicts, added };
}
