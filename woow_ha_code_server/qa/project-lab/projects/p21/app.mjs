export const meta = {
  id: 'p21', title: 'HTTP Error Budget Analyzer', category: 'Reliability', version: '1.1.0',
  description: 'Aggregate supplied HTTP observations and measure consumption of a request-based error budget.',
  example: { observations: [{ status: 200, count: 995 }, { status: 500, count: 5 }], sloPercent: 99 },
  fields: [{ key: 'observations', label: 'HTTP observations', type: 'json' }, { key: 'sloPercent', label: 'Success SLO (%)', type: 'number' }]
};
const round = n => Number(n.toFixed(6));
export function run(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) throw new Error('Input must be an object');
  if (Object.keys(input).some(k => !['observations', 'sloPercent', 'failureStatuses'].includes(k))) throw new Error('Unknown input field');
  const { observations, sloPercent = 99.9, failureStatuses } = input;
  if (!Array.isArray(observations) || observations.length < 1 || observations.length > 1000) throw new Error('observations must contain 1–1000 entries');
  if (typeof sloPercent !== 'number' || !Number.isFinite(sloPercent) || sloPercent < 0 || sloPercent > 100 || Math.abs(sloPercent * 10000 - Math.round(sloPercent * 10000)) > 1e-7) throw new Error('sloPercent must be 0–100 with at most four decimal places');
  if (failureStatuses !== undefined && (!Array.isArray(failureStatuses) || failureStatuses.length > 500 || failureStatuses.some(s => !Number.isInteger(s) || s < 100 || s > 599))) throw new Error('failureStatuses must be an array of HTTP codes 100–599');
  const failedCodes = failureStatuses === undefined ? null : new Set(failureStatuses);
  const counts = new Map();
  let totalRequests = 0, failedRequests = 0;
  for (const row of observations) {
    if (!row || typeof row !== 'object' || Array.isArray(row) || Object.keys(row).some(k => !['status', 'count'].includes(k)) || !Number.isInteger(row.status) || row.status < 100 || row.status > 599 || !Number.isInteger(row.count) || row.count < 1 || row.count > 1e9) throw new Error('Each observation needs status 100–599 and integer count 1–1000000000');
    totalRequests += row.count;
    if (totalRequests > 1e9) throw new Error('Total request count must not exceed 1000000000');
    if (failedCodes ? failedCodes.has(row.status) : row.status >= 500) failedRequests += row.count;
    counts.set(row.status, (counts.get(row.status) || 0) + row.count);
  }
  const budgetUnits = 1000000 - Math.round(sloPercent * 10000);
  const allowedFailures = totalRequests * budgetUnits / 1000000;
  return {
    totalRequests, successfulRequests: totalRequests - failedRequests, failedRequests,
    successPercent: round((totalRequests - failedRequests) / totalRequests * 100),
    allowedFailures: round(allowedFailures), remainingFailures: round(allowedFailures - failedRequests),
    burnRate: allowedFailures === 0 ? (failedRequests === 0 ? 0 : null) : round(failedRequests / allowedFailures),
    withinBudget: failedRequests * 1000000 <= totalRequests * budgetUnits,
    byStatus: [...counts].sort((a, b) => a[0] - b[0]).map(([status, count]) => ({ status, count }))
  };
}
