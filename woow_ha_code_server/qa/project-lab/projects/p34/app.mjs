export const meta = {
  id: 'p34', title: 'Pomodoro work/rest planner', category: 'Productivity', version: '1.1.0',
  description: 'Build a work and break schedule with long breaks, totals, and midnight rollover.',
  example: { sessions: 4, workMinutes: 25, shortBreakMinutes: 5, longBreakMinutes: 15, longBreakEvery: 2, startTime: '09:00' },
  fields: [{ key: 'sessions', label: 'Work sessions', type: 'number' }, { key: 'workMinutes', label: 'Work minutes', type: 'number' }, { key: 'shortBreakMinutes', label: 'Short break minutes', type: 'number' }, { key: 'longBreakMinutes', label: 'Long break minutes', type: 'number' }, { key: 'longBreakEvery', label: 'Long break every N sessions', type: 'number' }, { key: 'startTime', label: 'Start time (HH:MM)', type: 'text' }]
};
function integer(value, label, min, max) {
  if (!Number.isInteger(value) || value < min || value > max) throw new Error(`${label} must be an integer from ${min} to ${max}`);
}
function clock(minutes) {
  const minute = minutes % 1440;
  return `${String(Math.floor(minute / 60)).padStart(2, '0')}:${String(minute % 60).padStart(2, '0')}`;
}
export function run(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) throw new Error('input must be an object');
  const { sessions, workMinutes = 25, shortBreakMinutes = 5, longBreakMinutes = 15, longBreakEvery = 4, startTime = '09:00' } = input;
  integer(sessions, 'sessions', 1, 96);
  integer(workMinutes, 'workMinutes', 1, 240);
  integer(shortBreakMinutes, 'shortBreakMinutes', 0, 120);
  integer(longBreakMinutes, 'longBreakMinutes', 0, 240);
  integer(longBreakEvery, 'longBreakEvery', 1, 24);
  if (typeof startTime !== 'string' || !/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(startTime)) throw new Error('startTime must be a valid 24-hour HH:MM time');
  const [hours, minutes] = startTime.split(':').map(Number);
  let cursor = hours * 60 + minutes, totalRestMinutes = 0;
  const segments = [];
  const add = (kind, session, duration) => {
    if (duration === 0) return;
    segments.push({ kind, session, minutes: duration, start: clock(cursor), startDay: Math.floor(cursor / 1440), end: clock(cursor + duration), endDay: Math.floor((cursor + duration) / 1440) });
    cursor += duration;
  };
  for (let session = 1; session <= sessions; session++) {
    add('work', session, workMinutes);
    if (session < sessions) {
      const long = session % longBreakEvery === 0;
      const duration = long ? longBreakMinutes : shortBreakMinutes;
      add(long ? 'long-break' : 'short-break', session, duration);
      totalRestMinutes += duration;
    }
  }
  return { sessions, totalWorkMinutes: sessions * workMinutes, totalRestMinutes, totalMinutes: sessions * workMinutes + totalRestMinutes, finishTime: clock(cursor), finishDay: Math.floor(cursor / 1440), segments };
}
