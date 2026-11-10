export const meta = {
  id: 'p22', title: 'Semver Compatibility Comparator', category: 'Developer tools', version: '1.1.0',
  description: 'Compare strict semantic versions and evaluate explicit comparator, caret, and tilde ranges.',
  example: { current: '1.4.0', candidate: '1.5.2', range: '^1.4.0' },
  fields: [{ key: 'current', label: 'Current version', type: 'text' }, { key: 'candidate', label: 'Candidate version', type: 'text' }, { key: 'range', label: 'Allowed range', type: 'text' }]
};
function parse(s) {
  if (typeof s !== 'string' || s.length > 128) throw new Error('Version must be a string of at most 128 characters');
  const m = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$/.exec(s);
  if (!m) throw new Error(`Invalid semantic version: ${s}`);
  const pre = m[4] ? m[4].split('.') : [];
  if (pre.some(p => /^\d+$/.test(p) && p.length > 1 && p[0] === '0')) throw new Error('Numeric prerelease identifiers cannot have leading zeros');
  return { core: m.slice(1, 4).map(BigInt), pre };
}
function compare(a, b) {
  for (let i = 0; i < 3; i++) if (a.core[i] !== b.core[i]) return a.core[i] < b.core[i] ? -1 : 1;
  if (!a.pre.length || !b.pre.length) return a.pre.length === b.pre.length ? 0 : a.pre.length ? -1 : 1;
  for (let i = 0; i < Math.max(a.pre.length, b.pre.length); i++) {
    if (i >= a.pre.length) return -1;
    if (i >= b.pre.length) return 1;
    const x = a.pre[i], y = b.pre[i];
    if (x === y) continue;
    const xn = /^\d+$/.test(x), yn = /^\d+$/.test(y);
    if (xn && yn) return BigInt(x) < BigInt(y) ? -1 : 1;
    if (xn !== yn) return xn ? -1 : 1;
    return x < y ? -1 : 1;
  }
  return 0;
}
function compileRange(range) {
  if (typeof range !== 'string' || !range.trim() || range.length > 1024) throw new Error('range must be a nonempty string up to 1024 characters');
  const branches = range.split('||');
  if (branches.length > 8) throw new Error('At most eight range alternatives are supported');
  return branches.map(branch => {
    const parts = branch.trim().split(/\s+/);
    if (!branch.trim() || parts.length > 8) throw new Error('Each range alternative needs 1–8 comparators');
    const anchors = [], tests = [];
    for (const token of parts) {
      const match = /^(\^|~|>=|<=|>|<|=)?(.+)$/.exec(token);
      if (!match) throw new Error('Invalid range comparator');
      const operator = match[1] || '=', base = parse(match[2]);
      anchors.push(base);
      if (operator === '^' || operator === '~') {
        const core = [...base.core];
        const index = operator === '~' ? 1 : core[0] > 0n ? 0 : core[1] > 0n ? 1 : 2;
        core[index]++;
        for (let j = index + 1; j < 3; j++) core[j] = 0n;
        tests.push(['>=', base], ['<', { core, pre: ['0'] }]);
      } else tests.push([operator, base]);
    }
    return { anchors, tests };
  });
}
export function run(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input) || Object.keys(input).some(k => !['current', 'candidate', 'range'].includes(k))) throw new Error('Input must contain current, candidate, and optional range');
  const current = parse(input.current), candidate = parse(input.candidate), cmp = compare(candidate, current);
  let change = 'none';
  const names = ['major', 'minor', 'patch'];
  for (let i = 0; i < 3; i++) if (current.core[i] !== candidate.core[i]) { change = names[i]; break; }
  if (change === 'none' && cmp !== 0) change = 'prerelease';
  let satisfiesRange = null;
  if (input.range !== undefined) {
    const branches = compileRange(input.range);
    satisfiesRange = branches.some(({ anchors, tests }) => {
      if (candidate.pre.length && !anchors.some(a => a.pre.length && a.core.every((n, i) => n === candidate.core[i]))) return false;
      return tests.every(([op, base]) => { const c = compare(candidate, base); return op === '=' ? c === 0 : op === '>' ? c > 0 : op === '>=' ? c >= 0 : op === '<' ? c < 0 : c <= 0; });
    });
  }
  return { current: input.current, candidate: input.candidate, comparison: cmp < 0 ? 'older' : cmp > 0 ? 'newer' : 'same', change, range: input.range ?? null, satisfiesRange };
}
