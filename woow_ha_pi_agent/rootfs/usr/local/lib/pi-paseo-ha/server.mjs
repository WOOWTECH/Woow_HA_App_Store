import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { Readable } from 'node:stream';
import { ingressPrefix, ingressResponse } from './ingress.mjs';
import { randomBytes } from 'node:crypto';
import { createPaseoBridge } from './bridge.mjs';

const staticRoot = '/usr/local/share/pi-paseo-ha';
const files = new Map([['/paseo', ['index.html', 'text/html']], ['/paseo/', ['index.html', 'text/html']], ['/paseo/setup', ['index.html', 'text/html']],
  ['/paseo/app.js', ['app.js', 'application/javascript']], ['/paseo/launcher.js', ['launcher.js', 'application/javascript']],
  ['/paseo/style.css', ['style.css', 'text/css']]]);
const safeCode = error => /^[A-Z_0-9]{1,64}$/.test(error?.code || '') ? error.code : 'PASEO_FAILED';

export function createServer({ bridge = createPaseoBridge(), directory = staticRoot } = {}) {
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
      const prefix = ingressPrefix(req.headers['x-ingress-path']);
      if (url.pathname === '/paseo-web' || url.pathname.startsWith('/paseo-web/')) {
        if (!['GET', 'HEAD'].includes(req.method)) return reply(405, { error: { code: 'METHOD_NOT_ALLOWED' } });
        // Ask for plain bytes: the per-request Ingress base must also reach
        // Expo router and dynamic chunk URLs inside the compiled JavaScript.
        const response = await ingressResponse(await bridge.web(new Request(url, { method: 'GET', headers: { 'accept-encoding': 'identity' } })), prefix, req.method, {
          pathname: url.pathname, acceptEncoding: req.headers['accept-encoding'] || '', ifNoneMatch: req.headers['if-none-match'] || '',
        });
        res.writeHead(response.status, Object.fromEntries(response.headers));
        if (response.body) Readable.fromWeb(response.body).pipe(res); else res.end();
        return;
      }
      if (url.pathname === '/api/paseo') {
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
        if (!originAllowed || req.headers['x-paseo-token'] !== token || (site && !['same-origin', 'none'].includes(site))) return reply(403, { error: { code: 'UNTRUSTED_REQUEST' } });
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
        return reply(200, await bridge.act(body, prefix));
      }
      const entry = files.get(url.pathname);
      if (!entry || req.method !== 'GET') return reply(404, { error: { code: 'NOT_FOUND' } });
      const content = fs.readFileSync(path.join(directory, entry[0]), 'utf8').replace('__CSRF_TOKEN__', token).replaceAll('__INGRESS_PREFIX__', prefix);
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
