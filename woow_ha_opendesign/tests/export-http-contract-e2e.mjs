import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { inspectZipMembers } from './export-archive-inspection.mjs';

const baseUrl = process.env.OD_EXPORT_BASE_URL;
const ingressPath = process.env.OD_EXPORT_INGRESS_PATH;
if (!baseUrl || !ingressPath) {
  throw new Error('OD_EXPORT_BASE_URL and OD_EXPORT_INGRESS_PATH must be set');
}

const fixturePath = process.env.OD_EXPORT_FIXTURE_PATH || fileURLToPath(new URL('./fixtures/export-deck.html', import.meta.url));
const projectId = `export-http-${randomUUID()}`;
const title = 'OpenDesign 匯出驗證 🎨';

function endpoint(requestPath) {
  return new URL(requestPath, baseUrl).toString();
}

async function request(requestPath, options = {}) {
  const headers = new Headers(options.headers);
  headers.set('X-Ingress-Path', ingressPath);
  return fetch(endpoint(requestPath), { ...options, headers });
}

async function requestJson(requestPath, body) {
  return request(requestPath, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
}

async function assertStatus(response, expectedStatus) {
  if (response.status !== expectedStatus) {
    assert.fail(`expected HTTP ${expectedStatus}, received ${response.status}: ${await response.text()}`);
  }
}

function assertAttachment(response, expectedType) {
  assert.match(response.headers.get('content-type') || '', expectedType);
  assert.match(response.headers.get('content-disposition') || '', /attachment/i);
}

const fixture = await readFile(fixturePath, 'utf8');

const create = await requestJson('/api/projects', {
  id: projectId,
  name: 'Export HTTP contract',
  skipDiscoveryBrief: true,
});
await assertStatus(create, 200);

const upload = await requestJson(`/api/projects/${encodeURIComponent(projectId)}/files`, {
  name: 'export-deck.html',
  content: fixture,
});
await assertStatus(upload, 200);

const html = await requestJson(`/api/projects/${encodeURIComponent(projectId)}/export/html`, {
  fileName: 'export-deck.html',
  title,
});
await assertStatus(html, 200);
assertAttachment(html, /^text\/html\b/i);
assert.match(html.headers.get('content-type') || '', /(?:^|;)\s*charset\s*=\s*utf-8(?:\s*;|$)/i);
const htmlBody = await html.text();
assert.ok(htmlBody.length > 0, 'HTML export must not be empty');
assert.match(htmlBody, /<title\b[^>]*>\s*OpenDesign 匯出驗證 🎨\s*<\/title>/i);
assert.equal(
  (htmlBody.match(/<section\b[^>]*\bclass=(?:"[^"]*\bslide\b[^"]*"|'[^']*\bslide\b[^']*')/gi) || []).length,
  2,
  'HTML export must contain exactly two section.slide elements',
);
assert.match(htmlBody, /第一張 \/ Slide one/);
assert.match(htmlBody, /第二張 \/ Slide two/);

const malformedHtml = await requestJson(`/api/projects/${encodeURIComponent(projectId)}/export/html`, { title });
await assertStatus(malformedHtml, 400);
assert.doesNotMatch(malformedHtml.headers.get('content-type') || '', /^text\/html\b/i);
assert.doesNotMatch(malformedHtml.headers.get('content-disposition') || '', /attachment/i);
const malformedBody = await malformedHtml.json();
assert.equal(typeof malformedBody?.error?.code, 'string');
assert.equal(typeof malformedBody?.error?.message, 'string');

const archive = await request(`/api/projects/${encodeURIComponent(projectId)}/archive`);
await assertStatus(archive, 200);
assertAttachment(archive, /^application\/zip\b/i);
const archiveBytes = Buffer.from(await archive.arrayBuffer());
assert.deepEqual(archiveBytes.subarray(0, 2), Buffer.from('PK'));
const members = inspectZipMembers(archiveBytes);
assert.ok(members.some(({ name }) => name === 'export-deck.html'), JSON.stringify(members));
for (const { name } of members) {
  assert.ok(!name.startsWith('/'), name);
  assert.ok(!name.split('/').includes('..'), name);
}

console.log('export HTTP contract: HTML attachment/error and normal ZIP archive passed');
