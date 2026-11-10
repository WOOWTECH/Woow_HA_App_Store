export const meta = {
  id: 'p26', title: 'Dependency Graph Planner', category: 'Developer tools', version: '1.1.0',
  description: 'Produce deterministic dependency levels, a topological order, and a concrete cycle when scheduling is blocked.',
  example: { nodes: ['build', 'lint', 'test', 'deploy'], edges: [['build', 'lint'], ['build', 'test'], ['lint', 'deploy'], ['test', 'deploy']] }
};
export function run(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input) || Object.keys(input).some(k => !['nodes', 'edges'].includes(k))) throw new Error('Input must contain nodes and edges');
  const { nodes, edges } = input;
  if (!Array.isArray(nodes) || nodes.length > 200 || nodes.some(n => typeof n !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/.test(n))) throw new Error('nodes must contain at most 200 names using letters, digits, dot, dash, or underscore');
  const sorted = [...nodes].sort(), unique = new Set(nodes);
  if (unique.size !== nodes.length) throw new Error('Duplicate node names');
  if (!Array.isArray(edges) || edges.length > 5000) throw new Error('edges must contain at most 5000 [prerequisite, dependent] pairs');
  const outgoing = new Map(sorted.map(n => [n, new Set()])), incoming = new Map(sorted.map(n => [n, 0]));
  for (const edge of edges) {
    if (!Array.isArray(edge) || edge.length !== 2 || !unique.has(edge[0]) || !unique.has(edge[1])) throw new Error('Each edge must reference two declared nodes');
    const [from, to] = edge;
    if (outgoing.get(from).has(to)) throw new Error(`Duplicate edge ${from} -> ${to}`);
    outgoing.get(from).add(to); incoming.set(to, incoming.get(to) + 1);
  }
  const levels = [], order = [];
  let ready = sorted.filter(n => incoming.get(n) === 0);
  while (ready.length) {
    levels.push(ready); order.push(...ready);
    const next = [];
    for (const node of ready) for (const to of outgoing.get(node)) {
      incoming.set(to, incoming.get(to) - 1);
      if (incoming.get(to) === 0) next.push(to);
    }
    ready = next.sort();
  }
  const blocked = sorted.filter(n => incoming.get(n) > 0), blockedSet = new Set(blocked), state = new Map(), stack = [];
  let cycle = [];
  function visit(node) {
    state.set(node, 1); stack.push(node);
    for (const to of [...outgoing.get(node)].sort()) {
      if (!blockedSet.has(to)) continue;
      if (state.get(to) === 1) { cycle = [...stack.slice(stack.indexOf(to)), to]; return true; }
      if (!state.has(to) && visit(to)) return true;
    }
    stack.pop(); state.set(node, 2); return false;
  }
  for (const node of blocked) if (!state.has(node) && visit(node)) break;
  return { acyclic: blocked.length === 0, order, levels, blocked, cycle };
}
