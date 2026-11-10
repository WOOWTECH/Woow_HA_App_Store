export const meta = {
  id: 'p45', title: 'Static site navigation and search builder', category: 'Publishing',
  description: 'Validate page hierarchies, build navigation and an inverted index, and rank offline searches.',
  version: '1.1.0',
  example: { pages: [
    { path: '/', title: 'Home', body: 'Small useful tools', tags: ['tools'] },
    { path: '/guide', parent: '/', title: 'Tools Guide', body: 'Learn to use the tools offline', tags: ['help'] }
  ], query: 'tools' }
};
const object = x => x !== null && typeof x === 'object' && !Array.isArray(x);
function check(ok, message) { if (!ok) throw new Error(message); }
const validPath = x => typeof x === 'string' && x.length <= 200 && (x === '/' || /^\/[A-Za-z0-9_-]+(?:\/[A-Za-z0-9_-]+)*$/.test(x));
const tokens = x => x.normalize('NFKC').toLowerCase().match(/[\p{L}\p{N}]+/gu) ?? [];
const compare = (a, b) => a < b ? -1 : a > b ? 1 : 0;
export function run(input) {
  check(object(input), 'Input must be an object');
  check(Array.isArray(input.pages) && input.pages.length >= 1 && input.pages.length <= 100, 'pages must contain 1 to 100 entries');
  const query = input.query ?? '';
  check(typeof query === 'string' && query.length <= 200, 'query must be a string of at most 200 characters');
  const ids = new Set();
  let characters = 0;
  const pages = input.pages.map(p => {
    check(object(p) && validPath(p.path), 'Each page needs a canonical absolute path without traversal or trailing slash');
    check(!ids.has(p.path), 'Duplicate page path: ' + p.path); ids.add(p.path);
    check(typeof p.title === 'string' && p.title.trim().length > 0 && p.title.length <= 200, 'title must contain 1-200 characters');
    check(typeof p.body === 'string' && p.body.length <= 20000, 'body must be a string of at most 20000 characters');
    const tags = p.tags ?? [];
    check(Array.isArray(tags) && tags.length <= 20 && tags.every(t => typeof t === 'string' && t.trim().length > 0 && t.length <= 64), 'tags must contain at most 20 short nonempty strings');
    const parent = p.parent ?? null;
    check(parent === null || validPath(parent), 'parent must be a canonical page path');
    characters += p.title.length + p.body.length + tags.join('').length;
    return { path: p.path, title: p.title, body: p.body, parent, tags: [...tags] };
  });
  check(characters <= 500000, 'Combined page text exceeds 500000 characters');
  const byPath = new Map(pages.map(p => [p.path, p]));
  for (const p of pages) check(p.parent === null || byPath.has(p.parent), 'Unknown parent: ' + p.parent);
  const visited = new Set(), visiting = new Set();
  function visit(p) {
    check(!visiting.has(p.path), 'Navigation cycle at ' + p.path);
    if (visited.has(p.path)) return;
    visiting.add(p.path);
    if (p.parent !== null) visit(byPath.get(p.parent));
    visiting.delete(p.path); visited.add(p.path);
  }
  pages.forEach(visit);
  const nodes = new Map(pages.map(p => [p.path, { path: p.path, title: p.title, children: [] }]));
  const navigation = [];
  for (const p of pages) {
    if (p.parent === null) navigation.push(nodes.get(p.path));
    else nodes.get(p.parent).children.push(nodes.get(p.path));
  }
  const terms = new Map();
  const weights = new Map();
  for (const p of pages) {
    const counts = new Map();
    for (const [source, weight] of [[p.title, 3], [p.tags.join(' '), 2], [p.body, 1]]) {
      for (const term of tokens(source)) counts.set(term, (counts.get(term) ?? 0) + weight);
    }
    weights.set(p.path, counts);
    for (const [term, weight] of counts) {
      if (!terms.has(term)) terms.set(term, []);
      terms.get(term).push({ path: p.path, weight });
    }
    check(terms.size <= 10000, 'Search index exceeds 10000 unique terms');
  }
  const queryTokens = [...new Set(tokens(query))];
  const results = queryTokens.length ? pages.filter(p => queryTokens.every(t => weights.get(p.path).has(t))).map(p => ({
    path: p.path, title: p.title, score: queryTokens.reduce((sum, t) => sum + weights.get(p.path).get(t), 0),
    snippet: p.body.replace(/\s+/g, ' ').trim().slice(0, 160)
  })).sort((a, b) => b.score - a.score || compare(a.path, b.path)) : [];
  return { navigation, index: [...terms.keys()].sort().map(term => ({ term, pages: terms.get(term) })),
    results, totals: { pages: pages.length, terms: terms.size } };
}
