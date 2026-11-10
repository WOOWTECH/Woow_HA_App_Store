export const meta = {
  id: 'p32', title: 'Spaced repetition review planner', category: 'Learning', version: '1.1.0',
  description: 'Apply a bounded SM-2 style update and schedule each reviewed card on a UTC date.',
  example: { reviewDate: '2026-11-10', cards: [{ id: 'new-word', quality: 5 }, { id: 'familiar-word', quality: 4, repetitions: 2, intervalDays: 6, easeFactor: 2.5 }, { id: 'forgotten-word', quality: 1, repetitions: 4, intervalDays: 30, easeFactor: 2.2 }] },
  fields: [{ key: 'reviewDate', label: 'Review date (YYYY-MM-DD)', type: 'text' }, { key: 'cards', label: 'Reviewed cards', type: 'json' }]
};

function integer(value, name, min, max) {
  if (!Number.isInteger(value) || value < min || value > max) throw new Error(`${name} must be an integer from ${min} to ${max}`);
}
export function run(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) throw new Error('input must be an object');
  const { reviewDate, cards } = input;
  if (typeof reviewDate !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(reviewDate)) throw new Error('reviewDate must be YYYY-MM-DD');
  const date = new Date(`${reviewDate}T00:00:00.000Z`);
  if (!Number.isFinite(date.getTime()) || date.toISOString().slice(0, 10) !== reviewDate || date.getUTCFullYear() < 1900 || date.getUTCFullYear() > 2100) throw new Error('reviewDate must be a real date in years 1900–2100');
  if (!Array.isArray(cards) || cards.length < 1 || cards.length > 500) throw new Error('cards must contain 1–500 cards');
  const ids = new Set();
  const scheduled = cards.map(card => {
    if (!card || typeof card !== 'object' || Array.isArray(card)) throw new Error('each card must be an object');
    const { id, quality, repetitions = 0, intervalDays = 0, easeFactor = 2.5 } = card;
    if (typeof id !== 'string' || !id.trim() || id !== id.trim() || id.length > 80 || ids.has(id)) throw new Error('card IDs must be nonempty, unique, trimmed strings of at most 80 characters');
    ids.add(id);
    integer(quality, 'quality', 0, 5);
    integer(repetitions, 'repetitions', 0, 10000);
    integer(intervalDays, 'intervalDays', 0, 36500);
    if (repetitions > 0 && intervalDays === 0) throw new Error('previous successful reviews require a positive intervalDays');
    if (typeof easeFactor !== 'number' || !Number.isFinite(easeFactor) || easeFactor < 1.3 || easeFactor > 5) throw new Error('easeFactor must be a finite number from 1.3 to 5');
    const delta = 5 - quality;
    const nextEase = Number(Math.min(5, Math.max(1.3, easeFactor + 0.1 - delta * (0.08 + delta * 0.02))).toFixed(2));
    const successfulReviews = quality < 3 ? 0 : Math.min(10000, repetitions + 1);
    const nextInterval = quality < 3 || repetitions === 0 ? 1 : repetitions === 1 ? 6 : Math.min(36500, Math.max(1, Math.round(intervalDays * easeFactor)));
    const dueDate = new Date(date.getTime() + nextInterval * 86400000).toISOString().slice(0, 10);
    return { id, quality, successfulReviews, easeFactor: nextEase, intervalDays: nextInterval, dueDate };
  });
  return { reviewDate, total: scheduled.length, scheduled };
}
