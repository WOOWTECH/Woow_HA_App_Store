import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { randomBytes } from 'node:crypto';
import { createOmnigentBridge } from './bridge.mjs';

const staticRoot = '/usr/local/share/pi-omnigent-ha';
const files = new Map([['/omnigent', ['index.html', 'text/html']], ['/omnigent/', ['index.html', 'text/html']],
  ['/omnigent/app.js', ['app.js', 'application/javascript']],
  ['/omnigent/style.css', ['style.css', 'text/css']]]);
// Only the bridge's own request and availability codes reach the page. A Node or
// system code (ENOENT, EACCES, ERR_MODULE_NOT_FOUND, ...) is logged, code only.
const publicCodes = new Set(['PLUGIN_UNAVAILABLE', 'INVALID_SETUP', 'INVALID_ENGINE', 'INVALID_MODEL', 'INVALID_ACTION']);
const logCode = error => [error?.code, error?.name].find(value => typeof value === 'string' && /^[A-Za-z][A-Za-z0-9_]{0,63}$/.test(value)) || 'unknown';
function safeCode(error) {
  if (publicCodes.has(error?.code)) return error.code;
  console.error(`Omnigent settings request failed (${logCode(error)}).`);
  return 'OMNIGENT_FAILED';
}

export function createServer({ bridge = createOmnigentBridge(), directory = staticRoot } = {}) {
  // This token stays in memory and the same-origin settings page. No cookie,
  // query-string token or browser origin can authorize a mutation by itself.
  const token = randomBytes(32).toString('hex');
  return http.createServer(async (req, res) => {
    const reply = (status, body) => {
      res.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' });
      res.end(JSON.stringify(body));
    };
    try {
      const url = new URL(req.url, 'http://localhost');
      if (url.pathname === '/api/omnigent') {
        const site = req.headers['sec-fetch-site'];
        let originAllowed = true;
        if (req.headers.origin) {
          try {
            const origin = new URL(req.headers.origin);
            // TLS can terminate at HA's external proxy. Supervisor preserves
            // the browser Host; Fetch Metadata + the private token also gate
            // same-site/different-origin callers without trusting forwarded URLs.
            originAllowed = ['https:', 'http:'].includes(origin.protocol) && origin.origin === req.headers.origin
              && origin.host === req.headers.host;
          } catch { originAllowed = false; }
        }
        if (!originAllowed || (site && !['same-origin', 'none'].includes(site))) return reply(403, { error: { code: 'UNTRUSTED_REQUEST' } });
        if (req.headers['x-omnigent-token'] !== token) return reply(403, { error: { code: 'UNTRUSTED_REQUEST' } });
        if (req.method === 'GET') return reply(200, await bridge.read());
        if (req.method !== 'POST') return reply(405, { error: { code: 'METHOD_NOT_ALLOWED' } });
        if (!/^application\/json(?:\s*;|$)/i.test(req.headers['content-type'] || '')) return reply(415, { error: { code: 'JSON_REQUIRED' } });
        const chunks = []; let bytes = 0;
        for await (const chunk of req) {
          bytes += chunk.length;
          if (bytes > 8192) return reply(413, { error: { code: 'REQUEST_TOO_LARGE' } });
          chunks.push(chunk);
        }
        let body;
        try { body = JSON.parse(Buffer.concat(chunks).toString()); } catch { return reply(400, { error: { code: 'INVALID_JSON' } }); }
        if (!body || typeof body !== 'object' || Array.isArray(body)) return reply(400, { error: { code: 'INVALID_REQUEST' } });
        return reply(200, await bridge.act(body));
      }
      const entry = files.get(url.pathname);
      if (!entry || req.method !== 'GET') return reply(404, { error: { code: 'NOT_FOUND' } });
      const prefix = /^\/api\/hassio_ingress\/[A-Za-z0-9_-]{16,128}$/.test(req.headers['x-ingress-path'] || '') ? req.headers['x-ingress-path'] : '';
      let content;
      try { content = fs.readFileSync(path.join(directory, entry[0]), 'utf8'); }
      catch (error) { if (error.code === 'ENOENT') return reply(404, { error: { code: 'NOT_FOUND' } }); throw error; }
      content = content.replace('__CSRF_TOKEN__', token).replaceAll('__INGRESS_PREFIX__', prefix);
      res.writeHead(200, { 'Content-Type': `${entry[1]}; charset=utf-8`, 'Cache-Control': 'no-store',
        'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer',
        'Content-Security-Policy': "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; form-action 'none'; base-uri 'none'; frame-ancestors 'self'" });
      res.end(content);
    } catch (error) {
      const code = safeCode(error);
      reply(code.startsWith('INVALID_') ? 400 : code === 'PLUGIN_UNAVAILABLE' ? 409 : 503, { error: { code } });
    }
  });
}
