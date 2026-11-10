export const meta = {
  id: 'p43', title: 'Retry and backoff scheduler', category: 'Scheduling',
  description: 'Simulate worker contention, retry limits, and capped exponential delays.',
  version: '1.1.0',
  example: { workers: 2, attemptDuration: 1, baseDelay: 2, factor: 2, maxDelay: 10,
    jobs: [{ id: 'import', failuresBeforeSuccess: 2, maxAttempts: 4 }, { id: 'notify', failuresBeforeSuccess: 0 }] }
};
const object = x => x !== null && typeof x === 'object' && !Array.isArray(x);
function check(ok, message) { if (!ok) throw new Error(message); }
function integer(value, name, min, max) {
  check(Number.isSafeInteger(value) && value >= min && value <= max, name + ' must be an integer from ' + min + ' to ' + max);
  return value;
}
export function run(input) {
  check(object(input), 'Input must be an object');
  const workers = integer(input.workers ?? 1, 'workers', 1, 16);
  const duration = integer(input.attemptDuration ?? 1, 'attemptDuration', 1, 3600);
  const base = integer(input.baseDelay ?? 2, 'baseDelay', 0, 86400);
  const factor = integer(input.factor ?? 2, 'factor', 1, 10);
  const cap = integer(input.maxDelay ?? 3600, 'maxDelay', 0, 86400);
  check(Array.isArray(input.jobs) && input.jobs.length >= 1 && input.jobs.length <= 100, 'jobs must contain 1 to 100 jobs');
  const ids = new Set();
  const jobs = input.jobs.map((j, index) => {
    check(object(j) && typeof j.id === 'string' && /^[A-Za-z0-9_-]{1,64}$/.test(j.id), 'Each job needs a valid id');
    check(!ids.has(j.id), 'Duplicate job id: ' + j.id); ids.add(j.id);
    return { id: j.id, index, readyAt: integer(j.submittedAt ?? 0, 'submittedAt', 0, 1000000000),
      failures: integer(j.failuresBeforeSuccess, 'failuresBeforeSuccess', 0, 20),
      maxAttempts: integer(j.maxAttempts ?? 3, 'maxAttempts', 1, 21),
      attempts: 0, status: 'pending', finishedAt: null };
  });
  let now = 0;
  let active = [];
  const attempts = [];
  while (jobs.some(j => j.status === 'pending' || j.status === 'running')) {
    for (const a of active.filter(a => a.end === now).sort((a, b) => a.job.index - b.job.index)) {
      const j = a.job;
      if (a.outcome === 'success') { j.status = 'succeeded'; j.finishedAt = now; }
      else if (j.attempts >= j.maxAttempts) { j.status = 'exhausted'; j.finishedAt = now; }
      else {
        j.status = 'pending';
        j.readyAt = now + Math.min(cap, base * factor ** (j.attempts - 1));
      }
    }
    active = active.filter(a => a.end !== now);
    const ready = jobs.filter(j => j.status === 'pending' && j.readyAt <= now).sort((a, b) => a.readyAt - b.readyAt || a.index - b.index);
    for (let worker = 1; worker <= workers && ready.length; worker++) {
      if (active.some(a => a.worker === worker)) continue;
      const job = ready.shift();
      job.attempts++; job.status = 'running';
      const outcome = job.attempts <= job.failures ? 'failure' : 'success';
      active.push({ job, worker, end: now + duration, outcome });
      attempts.push({ job: job.id, attempt: job.attempts, worker, start: now, end: now + duration, outcome });
    }
    const nextTimes = active.map(a => a.end);
    if (active.length < workers) nextTimes.push(...jobs.filter(j => j.status === 'pending').map(j => j.readyAt));
    if (!nextTimes.length) break;
    now = Math.min(...nextTimes);
  }
  return { finishedAt: now, succeeded: jobs.filter(j => j.status === 'succeeded').length,
    exhausted: jobs.filter(j => j.status === 'exhausted').length,
    jobs: jobs.map(({ id, status, attempts, finishedAt }) => ({ id, status, attempts, finishedAt })), attempts };
}
