export const meta = {
  id: 'p41', title: 'Workflow DAG simulator', category: 'Workflow',
  description: 'Schedule dependent tasks across bounded workers and propagate failures.',
  version: '1.1.0',
  example: { concurrency: 2, tasks: [
    { id: 'fetch', duration: 3 }, { id: 'prepare', duration: 2 },
    { id: 'build', duration: 4, deps: ['fetch', 'prepare'] },
    { id: 'publish', duration: 1, deps: ['build'] }
  ] }
};

function requireValue(ok, message) { if (!ok) throw new Error(message); }
const object = x => x !== null && typeof x === 'object' && !Array.isArray(x);
const id = x => typeof x === 'string' && /^[A-Za-z0-9_-]{1,64}$/.test(x);

export function run(input) {
  requireValue(object(input), 'Input must be an object');
  const concurrency = input.concurrency ?? 2;
  requireValue(Number.isInteger(concurrency) && concurrency >= 1 && concurrency <= 16, 'concurrency must be an integer from 1 to 16');
  requireValue(Array.isArray(input.tasks) && input.tasks.length >= 1 && input.tasks.length <= 100, 'tasks must contain 1 to 100 tasks');
  const seen = new Set();
  const tasks = input.tasks.map((t, index) => {
    requireValue(object(t) && id(t.id), 'Every task needs an id of 1-64 letters, digits, underscores or hyphens');
    requireValue(!seen.has(t.id), 'Duplicate task id: ' + t.id);
    seen.add(t.id);
    requireValue(Number.isInteger(t.duration) && t.duration >= 1 && t.duration <= 100000, 'duration must be an integer from 1 to 100000 for ' + t.id);
    const deps = t.deps ?? [];
    requireValue(Array.isArray(deps) && deps.length <= 100 && deps.every(id) && new Set(deps).size === deps.length, 'deps must be unique task ids for ' + t.id);
    const outcome = t.outcome ?? 'success';
    requireValue(outcome === 'success' || outcome === 'fail', 'outcome must be success or fail');
    return { id: t.id, duration: t.duration, deps: [...deps], outcome, index, status: 'pending', start: null, end: null };
  });
  const byId = new Map(tasks.map(t => [t.id, t]));
  for (const t of tasks) for (const dep of t.deps) requireValue(byId.has(dep), 'Unknown dependency: ' + dep);
  const visited = new Set();
  const visiting = new Set();
  function visit(t) {
    requireValue(!visiting.has(t.id), 'Dependency cycle detected at ' + t.id);
    if (visited.has(t.id)) return;
    visiting.add(t.id);
    t.deps.forEach(d => visit(byId.get(d)));
    visiting.delete(t.id);
    visited.add(t.id);
  }
  tasks.forEach(visit);
  let now = 0;
  while (true) {
    for (const t of tasks) {
      if (t.status === 'running' && t.end === now) t.status = t.outcome === 'success' ? 'succeeded' : 'failed';
    }
    let changed;
    do {
      changed = false;
      for (const t of tasks) {
        if (t.status === 'pending' && t.deps.some(d => ['failed', 'blocked'].includes(byId.get(d).status))) {
          t.status = 'blocked';
          changed = true;
        }
      }
    } while (changed);
    let slots = concurrency - tasks.filter(t => t.status === 'running').length;
    for (const t of tasks) {
      if (slots && t.status === 'pending' && t.deps.every(d => byId.get(d).status === 'succeeded')) {
        t.status = 'running'; t.start = now; t.end = now + t.duration; slots--;
      }
    }
    const running = tasks.filter(t => t.status === 'running');
    if (!running.length) break;
    now = Math.min(...running.map(t => t.end));
  }
  const counts = { succeeded: 0, failed: 0, blocked: 0 };
  tasks.forEach(t => counts[t.status]++);
  return { makespan: now, counts, tasks: tasks.map(({ id, status, start, end }) => ({ id, status, start, end })) };
}
