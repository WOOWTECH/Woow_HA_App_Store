export const meta = {
  id: 'p28', title: 'Path Ignore Rule Explorer', category: 'Developer tools', version: '1.1.0',
  description: 'Match supplied relative paths against ordered glob rules with negation, without accessing the filesystem.',
  example: { paths: ['src/app.js', 'build/app.js', 'build/keep.txt', 'docs/debug.log'], patterns: ['build/', '*.log', '!build/keep.txt'] }
};
function safePath(path, label) {
  if (typeof path !== 'string' || !path || path.length > 256 || path.startsWith('/') || /[\\:\u0000-\u001f\u007f]/.test(path)) throw new Error(`${label} must be a relative POSIX path up to 256 characters`);
  const segments = path.split('/');
  if (segments.some(s => !s || s === '.' || s === '..')) throw new Error(`${label} cannot contain empty, dot, or parent traversal segments`);
  return segments;
}
function segmentMatch(pattern, value) {
  // Dynamic programming avoids catastrophic regex backtracking for repeated stars.
  let previous = Array(value.length + 1).fill(false); previous[0] = true;
  for (const char of pattern) {
    const next = Array(value.length + 1).fill(false);
    if (char === '*') next[0] = previous[0];
    for (let i = 1; i <= value.length; i++) next[i] = char === '*' ? previous[i] || next[i - 1] : previous[i - 1] && (char === '?' || char === value[i - 1]);
    previous = next;
  }
  return previous[value.length];
}
function pathMatch(pattern, path) {
  let previous = Array(path.length + 1).fill(false); previous[0] = true;
  for (const segment of pattern) {
    const next = Array(path.length + 1).fill(false);
    if (segment === '**') next[0] = previous[0];
    for (let i = 1; i <= path.length; i++) next[i] = segment === '**' ? previous[i] || next[i - 1] : previous[i - 1] && segmentMatch(segment, path[i - 1]);
    previous = next;
  }
  return previous[path.length];
}
export function run(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input) || Object.keys(input).some(k => !['paths', 'patterns'].includes(k))) throw new Error('Input must contain paths and patterns');
  if (!Array.isArray(input.paths) || input.paths.length > 200 || !Array.isArray(input.patterns) || input.patterns.length > 100) throw new Error('Provide at most 200 paths and 100 patterns');
  const paths = input.paths.map(p => ({ text: p, segments: safePath(p, 'Path') }));
  if (new Set(input.paths).size !== input.paths.length) throw new Error('Duplicate paths are not supported');
  let complexity = 0;
  const rules = [];
  for (let index = 0; index < input.patterns.length; index++) {
    const original = input.patterns[index];
    if (typeof original !== 'string' || original.length > 256) throw new Error('Patterns must be strings up to 256 characters');
    if (!original || original.startsWith('#')) continue;
    let text = original, negate = false;
    if (text.startsWith('!')) { negate = true; text = text.slice(1); }
    const anchored = text.startsWith('/');
    if (anchored) text = text.slice(1);
    const directory = text.endsWith('/');
    if (directory) text = text.slice(0, -1);
    const segments = safePath(text, 'Pattern');
    if (/[\[\]{}!]/.test(text) || segments.some(s => s.includes('**') && s !== '**')) throw new Error('Only *, ?, and whole-segment ** glob syntax is supported');
    if (directory) segments.push('**');
    // A slashless unanchored pattern matches a basename at any depth.
    const anyDepth = !anchored && !text.includes('/');
    if (anyDepth) segments.unshift('**');
    for (const path of paths) complexity += (text.length + 1) * (path.text.length + 1) * (directory ? path.segments.length : 1);
    rules.push({ original, index: index + 1, negate, segments, directory });
  }
  if (complexity > 10000000) throw new Error('Combined paths and patterns exceed the matching work limit');
  const results = paths.map(path => {
    let ignored = false, matchedPattern = null, matchedRule = null;
    for (const rule of rules) {
      // Directory rules match descendants only; the submitted path denotes a file.
      const matches = rule.directory
        ? path.segments.slice(0, -1).some((_, i) => pathMatch(rule.segments.slice(0, -1), path.segments.slice(0, i + 1)))
        : pathMatch(rule.segments, path.segments);
      if (matches) { ignored = !rule.negate; matchedPattern = rule.original; matchedRule = rule.index; }
    }
    return { path: path.text, ignored, matchedPattern, matchedRule };
  });
  return { results, ignored: results.filter(r => r.ignored).map(r => r.path), included: results.filter(r => !r.ignored).map(r => r.path) };
}
