export const meta = {
  id: 'p47', title: 'Event stream window aggregation', category: 'Analytics',
  description: 'Aggregate keyed tumbling windows while tracking watermark-based late-event rejection.',
  version: '1.1.0',
  example: { windowMs: 1000, allowedLatenessMs: 200, events: [
    { timestamp: 100, key: 'sensor-a', value: 10 },
    { timestamp: 1100, key: 'sensor-a', value: 14 },
    { timestamp: 950, key: 'sensor-a', value: 12 },
    { timestamp: 200, key: 'sensor-a', value: 99 }
  ] }
};
const object = x => x !== null && typeof x === 'object' && !Array.isArray(x);
function check(ok, message) { if (!ok) throw new Error(message); }
function integer(value, name, min, max) {
  check(Number.isSafeInteger(value) && value >= min && value <= max, name + ' must be an integer from ' + min + ' to ' + max);
  return value;
}
const rounded = x => Number(x.toFixed(6)) || 0;
export function run(input) {
  check(object(input), 'Input must be an object');
  const width = integer(input.windowMs, 'windowMs', 1, 86400000);
  const lateness = integer(input.allowedLatenessMs ?? 0, 'allowedLatenessMs', 0, 86400000);
  check(Array.isArray(input.events) && input.events.length <= 10000, 'events must be an array of at most 10000 entries');
  const events = input.events.map((e, index) => {
    check(object(e), 'Each event must be an object');
    integer(e.timestamp, 'timestamp', 0, 1000000000000);
    check(typeof e.key === 'string' && e.key.trim().length > 0 && e.key.length <= 64, 'event key must contain 1-64 characters');
    check(typeof e.value === 'number' && Number.isFinite(e.value) && Math.abs(e.value) <= 1000000000, 'event value must be a finite number between -1e9 and 1e9');
    return { timestamp: e.timestamp, key: e.key, value: e.value || 0, index };
  });
  let maxSeen = null;
  let accepted = 0;
  const buckets = new Map(), lateEvents = [];
  for (const e of events) {
    if (maxSeen !== null && e.timestamp < maxSeen - lateness) {
      lateEvents.push({ index: e.index, timestamp: e.timestamp, key: e.key });
      continue;
    }
    maxSeen = Math.max(maxSeen ?? e.timestamp, e.timestamp);
    accepted++;
    const start = Math.floor(e.timestamp / width) * width;
    const bucketId = JSON.stringify([start, e.key]);
    if (!buckets.has(bucketId)) buckets.set(bucketId, { start, end: start + width, key: e.key, count: 0, sum: 0, min: e.value, max: e.value });
    const bucket = buckets.get(bucketId);
    bucket.count++; bucket.sum += e.value;
    bucket.min = Math.min(bucket.min, e.value); bucket.max = Math.max(bucket.max, e.value);
  }
  const windows = [...buckets.values()].sort((a, b) => a.start - b.start || (a.key < b.key ? -1 : a.key > b.key ? 1 : 0))
    .map(b => ({ ...b, sum: rounded(b.sum), average: rounded(b.sum / b.count) }));
  return { watermark: maxSeen === null ? null : maxSeen - lateness, accepted, rejectedLate: lateEvents.length, windows, lateEvents };
}
