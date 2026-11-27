// Real HTTP acceptance for the sessions JSON response path. Uses only owned,
// synthetic session files and removes its one private fixture directory.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import { gunzipSync } from 'node:zlib';
import { pathToFileURL } from 'node:url';

const MAX_WIRE_BYTES = 1024 * 1024;
const MAX_JSON_BYTES = 4 * 1024 * 1024;
const REQUEST_TIMEOUT_MS = 15000;

export async function verifySessionsHttpJson({ baseUrl, agentDir, piWebRoot, minimumSessions = 24 }) {
  assert.ok(Number.isInteger(minimumSessions) && minimumSessions >= 24, 'fixture count must trigger the compression threshold');
  const sessionsRoot = path.resolve(agentDir, 'sessions');
  fs.mkdirSync(sessionsRoot, { recursive: true, mode: 0o700 });
  const fixtureDir = fs.mkdtempSync(path.join(sessionsRoot, 'rc6-http-json-gzip-'));
  try {
    assert.equal(path.dirname(fs.realpathSync(fixtureDir)), fs.realpathSync(sessionsRoot), 'fixture stays directly in the owned sessions tree');
    const sessionManagerModule = path.join(piWebRoot, 'node_modules/@earendil-works/pi-coding-agent/dist/core/session-manager.js');
    const { SessionManager } = await import(pathToFileURL(sessionManagerModule).href);
    const token = randomUUID();
    const expectedIds = new Set();
    for (let index = 0; index < minimumSessions; index += 1) {
      const id = `http-gzip-${token}-${index}`;
      const session = SessionManager.create(agentDir, fixtureDir, { id });
      session.appendSessionInfo(`Synthetic compression acceptance session ${index} ${'n'.repeat(96)}`);
      session.appendMessage({ role: 'user', content: [{ type: 'text', text: `Synthetic HTTP response payload ${index} ${'x'.repeat(192)}` }] });
      expectedIds.add(id);
    }

    const target = new URL('/api/sessions?force=1', baseUrl);
    assert.equal(target.protocol, 'http:', 'acceptance is limited to the owned local image server');
    assert.equal(target.hostname, '127.0.0.1', 'acceptance cannot send requests to a remote host');
    assert.equal(target.username, '', 'acceptance URL cannot carry credentials');
    assert.equal(target.password, '', 'acceptance URL cannot carry credentials');
    const response = await new Promise((resolve, reject) => {
      let settled = false;
      const fail = error => {
        if (settled) return;
        settled = true;
        reject(error);
      };
      const request = http.request(target, { method: 'GET', headers: { accept: 'application/json', 'accept-encoding': 'gzip' } }, result => {
        const chunks = [];
        let wireBytes = 0;
        const declaredLength = Number(result.headers['content-length']);
        if (Number.isFinite(declaredLength) && declaredLength > MAX_WIRE_BYTES) {
          result.destroy(new Error(`sessions response exceeds ${MAX_WIRE_BYTES} wire-byte limit`));
          fail(new Error(`sessions response exceeds ${MAX_WIRE_BYTES} wire-byte limit`));
          return;
        }
        result.on('data', chunk => {
          wireBytes += chunk.byteLength;
          if (wireBytes > MAX_WIRE_BYTES) {
            const error = new Error(`sessions response exceeds ${MAX_WIRE_BYTES} wire-byte limit`);
            result.destroy(error);
            fail(error);
            return;
          }
          chunks.push(chunk);
        });
        result.on('error', fail);
        result.on('aborted', () => fail(new Error('sessions response stream aborted')));
        result.on('close', () => {
          if (!result.complete) fail(new Error('sessions response stream closed before completion'));
        });
        result.on('end', () => {
          if (!result.complete) return fail(new Error('sessions response stream ended before completion'));
          if (settled) return;
          settled = true;
          resolve({ status: result.statusCode, headers: result.headers, body: Buffer.concat(chunks), wireBytes });
        });
      });
      request.on('error', fail);
      request.on('abort', () => fail(new Error('sessions HTTP request aborted')));
      request.setTimeout(REQUEST_TIMEOUT_MS, () => request.destroy(new Error('sessions endpoint timed out')));
      request.end();
    });
    assert.equal(response.status, 200, 'the live HTTP sessions endpoint responds');
    assert.match(response.headers['content-type'] ?? '', /^application\/json\b/i);
    const encodings = String(response.headers['content-encoding'] ?? '').split(',').map(value => value.trim().toLowerCase()).filter(Boolean);
    assert.deepEqual(encodings, ['gzip'], 'the oversized JSON response has exactly one gzip encoding');
    const decoded = gunzipSync(response.body, { maxOutputLength: MAX_JSON_BYTES });
    assert.ok(decoded.byteLength > 8192, 'synthetic session list is large enough to cross the compression threshold');
    const payload = JSON.parse(decoded.toString('utf8'));
    assert.ok(Array.isArray(payload.sessions), 'the response is decoded JSON, not a gzip byte stream labelled as JSON');
    const returnedIds = new Set(payload.sessions.map(session => session.id));
    for (const id of expectedIds) assert.ok(returnedIds.has(id), `HTTP response includes synthetic session ${id}`);

    // Exercise the ordinary browser/client path too: Node fetch transparently
    // decompresses content-encoding, and Response.json() must parse it directly.
    const fetchResponse = await fetch(target, { headers: { accept: 'application/json', 'accept-encoding': 'gzip' },
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS) });
    assert.equal(fetchResponse.status, 200, 'fetch() receives the live sessions response');
    assert.match(fetchResponse.headers.get('content-type') ?? '', /^application\/json\b/i);
    const fetchEncodings = String(fetchResponse.headers.get('content-encoding') ?? '').split(',').map(value => value.trim().toLowerCase()).filter(Boolean);
    assert.deepEqual(fetchEncodings, ['gzip'], 'fetch() receives one gzip-encoded JSON response');
    const fetchPayload = await fetchResponse.json();
    assert.ok(Array.isArray(fetchPayload.sessions), 'fetch().json() parses the automatically decompressed response');
    const fetchIds = new Set(fetchPayload.sessions.map(session => session.id));
    for (const id of expectedIds) assert.ok(fetchIds.has(id), `fetch().json() includes synthetic session ${id}`);
    return { status: response.status, encoding: encodings[0], sessions: expectedIds.size,
      wireBytes: response.wireBytes, decodedBytes: decoded.byteLength, fetchJson: true,
      returnedSyntheticSessions: expectedIds.size };
  } finally {
    fs.rmSync(fixtureDir, { recursive: true, force: true });
  }
}
