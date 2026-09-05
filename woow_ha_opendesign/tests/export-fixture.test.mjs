import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const fixturePath = fileURLToPath(new URL('./fixtures/export-deck.html', import.meta.url));

async function fixture() {
  return readFile(fixturePath, 'utf8');
}

test('export deck fixture is a self-contained two-slide export specification', async () => {
  const html = await fixture();

  assert.match(html, /<title>OpenDesign 匯出驗證 🎨<\/title>/);
  assert.equal((html.match(/<section class="slide">/g) || []).length, 2, 'fixture must contain exactly two slide sections');
  assert.match(html, /\.slide\s*\{[^}]*width:\s*640px;[^}]*height:\s*360px;/s);
  assert.match(html, /<section class="slide">第一張 \/ Slide one<span class="slide-number">1 \/ 2<\/span><\/section>/);
  assert.match(html, /<section class="slide">第二張 \/ Slide two<span class="slide-number">2 \/ 2<\/span><\/section>/);
  assert.match(html, /\.slide:first-of-type\s*\{\s*background:\s*#165DBA;\s*\}/);
  assert.match(html, /\.slide:last-of-type\s*\{\s*background:\s*#AA3333;\s*\}/);

  for (const forbidden of [/<script\b/i, /<link\b/i, /url\(/i, /https?:\/\//i, /@font-face/i, /@media\b/i, /animation\s*:/i, /\bDate\b/, /Math\.random/]) {
    assert.doesNotMatch(html, forbidden, `fixture must not contain ${forbidden}`);
  }
});
