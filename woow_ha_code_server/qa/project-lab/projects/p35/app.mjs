export const meta = {
  id: 'p35', title: 'Reading-time and content structure report', category: 'Writing', version: '1.1.0',
  description: 'Count prose words, headings, lists, paragraphs, and fenced code; estimate reading time.',
  example: { text: '# A calmer workday\n\nStart with one important task. Give it your full attention.\n\n- Silence notifications\n- Take a short break\n\n## Reflection\n\nWrite down what helped today.', wpm: 200 },
  fields: [{ key: 'text', label: 'Text or basic Markdown', type: 'textarea' }, { key: 'wpm', label: 'Words per minute', type: 'number' }]
};
const wordPattern = /[\p{L}\p{N}]+(?:['’\-][\p{L}\p{N}]+)*/gu;
export function run(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) throw new Error('input must be an object');
  const { text, wpm = 200 } = input;
  if (typeof text !== 'string' || text.length > 100000) throw new Error('text must be a string of at most 100000 characters');
  if (!Number.isInteger(wpm) || wpm < 50 || wpm > 1000) throw new Error('wpm must be an integer from 50 to 1000');
  const normalized = text.replace(/\r\n?/g, '\n');
  const lines = normalized === '' ? [] : normalized.split('\n');
  const headings = [], visible = [];
  let fence = null, codeBlocks = 0, listItems = 0, paragraphs = 0, inParagraph = false;
  lines.forEach((line, index) => {
    if (fence) {
      const close = /^ {0,3}(`{3,}|~{3,})\s*$/.exec(line);
      if (close && close[1][0] === fence.char && close[1].length >= fence.length) fence = null;
      return;
    }
    const opening = /^ {0,3}(`{3,}|~{3,})(.*)$/.exec(line);
    if (opening) {
      fence = { char: opening[1][0], length: opening[1].length };
      codeBlocks++;
      inParagraph = false;
      return;
    }
    if (!line.trim()) { inParagraph = false; return; }
    const heading = /^ {0,3}(#{1,6})\s+(.+?)\s*$/.exec(line);
    const list = /^\s*(?:[-+*]|\d+[.)])\s+(.*)$/.exec(line);
    if (heading) {
      const title = heading[2].replace(/\s+#+\s*$/, '').trim();
      headings.push({ level: heading[1].length, title, line: index + 1 });
      visible.push(title);
      inParagraph = false;
    } else if (list) {
      listItems++;
      visible.push(list[1]);
      inParagraph = false;
    } else {
      if (!inParagraph) paragraphs++;
      inParagraph = true;
      visible.push(line);
    }
  });
  const content = visible.join('\n');
  const words = content.match(wordPattern) ?? [];
  const sentences = (content.match(/[^.!?。！？]+(?:[.!?。！？]+|$)/gu) ?? []).filter(s => (s.match(wordPattern) ?? []).length > 0).length;
  return { characters: normalized.length, lines: lines.length, words: words.length, uniqueWords: new Set(words.map(w => w.toLowerCase())).size, sentences, paragraphs, headings, listItems, codeBlocks, readingSeconds: Math.ceil(words.length * 60 / wpm), wpm };
}
