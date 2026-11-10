const units = {
  m: ['length', 1], km: ['length', 1000], cm: ['length', 0.01], mm: ['length', 0.001], in: ['length', 0.0254], ft: ['length', 0.3048], yd: ['length', 0.9144], mi: ['length', 1609.344],
  kg: ['mass', 1], g: ['mass', 0.001], mg: ['mass', 0.000001], lb: ['mass', 0.45359237], oz: ['mass', 0.028349523125],
  s: ['time', 1], min: ['time', 60], h: ['time', 3600], day: ['time', 86400],
  L: ['volume', 1], mL: ['volume', 0.001], m3: ['volume', 1000], us_gal: ['volume', 3.785411784],
  'm/s': ['speed', 1], 'km/h': ['speed', 1 / 3.6], mph: ['speed', 0.44704],
  J: ['energy', 1], kJ: ['energy', 1000], Wh: ['energy', 3600], kWh: ['energy', 3600000],
  C: ['temperature', 1], F: ['temperature', 1], K: ['temperature', 1]
};
export const meta = {
  id: 'p33', title: 'Dimension-aware unit converter', category: 'Utilities', version: '1.1.0',
  description: 'Convert lengths, masses, times, volumes, speeds, energies, and absolute temperatures; reject dimension mismatches.',
  example: { value: 60, from: 'mph', to: 'km/h' },
  fields: [{ key: 'value', label: 'Value', type: 'number' }, { key: 'from', label: 'From unit', type: 'select', options: Object.keys(units) }, { key: 'to', label: 'To unit', type: 'select', options: Object.keys(units) }]
};
export function run(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) throw new Error('input must be an object');
  const { value, from, to } = input;
  if (typeof value !== 'number' || !Number.isFinite(value) || Math.abs(value) > 1e12) throw new Error('value must be a finite number with magnitude at most 1e12');
  if (typeof from !== 'string' || !Object.hasOwn(units, from)) throw new Error('from is not a supported unit');
  if (typeof to !== 'string' || !Object.hasOwn(units, to)) throw new Error('to is not a supported unit');
  const dimension = units[from][0];
  if (units[to][0] !== dimension) throw new Error(`incompatible dimensions: ${dimension} and ${units[to][0]}`);
  let result;
  if (dimension === 'temperature') {
    const minimum = { C: -273.15, F: -459.67, K: 0 };
    if (value < minimum[from]) throw new Error('temperature must not be below absolute zero');
    const kelvin = from === 'K' ? value : from === 'C' ? value + 273.15 : (value + 459.67) * 5 / 9;
    result = to === 'K' ? kelvin : to === 'C' ? kelvin - 273.15 : kelvin * 9 / 5 - 459.67;
  } else result = value * units[from][1] / units[to][1];
  result = Number(result.toFixed(9));
  return { dimension, value: value === 0 ? 0 : value, from, to, result: result === 0 ? 0 : result };
}
