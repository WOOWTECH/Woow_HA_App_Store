export const meta = {
  id: 'p31', title: 'Flashcard quiz scorer', category: 'Learning', version: '1.1.0',
  description: 'Grade weighted flashcards, accept answer aliases, and identify cards to review.',
  example: { cards: [{ id: 'capital', prompt: 'Capital of Japan?', answers: ['Tokyo', '東京'], weight: 2 }, { id: 'sum', prompt: '7 + 8?', answers: ['15'] }], responses: { capital: ' tokyo ', sum: '14' }, caseSensitive: false },
  fields: [{ key: 'cards', label: 'Flashcards', type: 'json' }, { key: 'responses', label: 'Answers by card ID', type: 'json' }]
};

function object(value, label) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(`${label} must be an object`);
}
function string(value, label, max, nonempty = true) {
  if (typeof value !== 'string' || value.length > max || (nonempty && !value.trim())) throw new Error(`${label} must be ${nonempty ? 'a nonempty' : 'a'} string of at most ${max} characters`);
}
const round = n => Number(n.toFixed(4));

export function run(input) {
  object(input, 'input');
  const { cards, responses, caseSensitive = false } = input;
  if (!Array.isArray(cards) || cards.length < 1 || cards.length > 200) throw new Error('cards must contain 1–200 cards');
  object(responses, 'responses');
  if (typeof caseSensitive !== 'boolean') throw new Error('caseSensitive must be boolean');
  const normalize = value => {
    const clean = value.normalize('NFKC').trim().replace(/\s+/gu, ' ');
    return caseSensitive ? clean : clean.toLowerCase();
  };
  const ids = new Set();
  for (const card of cards) {
    object(card, 'card');
    string(card.id, 'card.id', 80);
    if (card.id !== card.id.trim() || ids.has(card.id)) throw new Error('card IDs must be unique and have no surrounding whitespace');
    ids.add(card.id);
    string(card.prompt, 'card.prompt', 1000);
    if (!Array.isArray(card.answers) || card.answers.length < 1 || card.answers.length > 20) throw new Error('card.answers must contain 1–20 accepted answers');
    card.answers.forEach(a => string(a, 'accepted answer', 1000));
    const { weight = 1 } = card;
    if (typeof weight !== 'number' || !Number.isFinite(weight) || weight < 0.01 || weight > 1000) throw new Error('card.weight must be a finite number from 0.01 to 1000');
  }
  for (const [id, response] of Object.entries(responses)) {
    if (!ids.has(id)) throw new Error(`response references unknown card: ${id}`);
    string(response, `response for ${id}`, 2000, false);
  }
  let earned = 0, possible = 0, correct = 0, incorrect = 0, unanswered = 0;
  const results = cards.map(card => {
    const response = Object.hasOwn(responses, card.id) ? responses[card.id] : '';
    const normalized = normalize(response);
    const status = !normalized ? 'unanswered' : card.answers.some(a => normalize(a) === normalized) ? 'correct' : 'incorrect';
    const { weight = 1 } = card;
    const points = status === 'correct' ? weight : 0;
    earned += points;
    possible += weight;
    if (status === 'correct') correct++;
    else if (status === 'incorrect') incorrect++;
    else unanswered++;
    return { id: card.id, prompt: card.prompt, status, response, acceptedAnswers: [...card.answers], earnedPoints: round(points), possiblePoints: round(weight) };
  });
  return { cardCount: cards.length, correct, incorrect, unanswered, earnedPoints: round(earned), possiblePoints: round(possible), percent: Number((100 * earned / possible).toFixed(2)), results, reviewIds: results.filter(r => r.status !== 'correct').map(r => r.id) };
}
