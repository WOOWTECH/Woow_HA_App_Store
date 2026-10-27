import { createHash } from 'node:crypto';
import { gzip } from 'node:zlib';
import { promisify } from 'node:util';
const compress = promisify(gzip);
const cache = new Map();
const maxCacheBytes = 32 * 1024 * 1024, maxCacheEntries = 4;
let cacheBytes = 0;
let pendingTransform = Promise.resolve();
function transformSerially(fn) {
  const result = pendingTransform.then(fn);
  pendingTransform = result.catch(() => {});
  return result;
}
function cached(key) {
  const value = cache.get(key);
  if (value) { cache.delete(key); cache.set(key, value); }
  return value;
}
function remember(key, value) {
  const size = value.plain.length + value.compressed.length;
  if (size > maxCacheBytes) return;
  if (cache.has(key)) { cacheBytes -= cache.get(key).size; cache.delete(key); }
  while (cache.size >= maxCacheEntries || cacheBytes + size > maxCacheBytes) {
    const oldest = cache.keys().next().value;
    cacheBytes -= cache.get(oldest).size; cache.delete(oldest);
  }
  cache.set(key, { ...value, size }); cacheBytes += size;
}
export function ingressCacheUsage() { return { entries: cache.size, bytes: cacheBytes, maxBytes: maxCacheBytes, maxEntries: maxCacheEntries }; }
function acceptsGzip(header = '') {
  const values = header.split(',').map(value => value.trim().toLowerCase().split(';'));
  const match = values.find(([name]) => name === 'gzip') || values.find(([name]) => name === '*');
  return !!match && !match.slice(1).some(value => /^\s*q\s*=/.test(value) && !(Number(value.split('=')[1]) > 0));
}
const etag = bytes => '"' + createHash('sha256').update(bytes).digest('hex') + '"';

// HA supplies this header after authenticating the browser. Never interpolate
// an arbitrary forwarded path into compiled JavaScript or pairing links.
export function ingressPrefix(value) {
  return typeof value === 'string' && /^\/api\/hassio_ingress\/[A-Za-z0-9_-]{16,128}$/.test(value) ? value : '';
}

export function pairUrl(value, prefix = '') {
  if (typeof value !== 'string' || !/^\/paseo-web\/#\S+$/.test(value) || /[\\\x00-\x20\x7f]/.test(value)) {
    throw Object.assign(new Error('Invalid pairing URL'), { code: 'PAIRING_ORIGIN_INVALID' });
  }
  return ingressPrefix(prefix) + value;
}

// Expo Router embeds the base URL in its routing and dynamic chunk loader,
// as well as HTML asset paths. Rewrite all three at the same boundary. Never
// persist the per-session Ingress path in the shared release on disk.
export async function ingressResponse(response, prefix, method = 'GET', { pathname = '', acceptEncoding = '', ifNoneMatch = '' } = {}) {
  const headers = new Headers(response.headers);
  headers.set('Vary', 'Accept-Encoding, X-Ingress-Path');
  prefix = ingressPrefix(prefix);
  const immutable = response.status === 200 && !/^text\/html/.test(headers.get('content-type') || '') && /^\/paseo-web\/(?:_expo\/static|assets)\/.+[.-][a-f0-9]{16,}\.[a-z0-9]+$/.test(pathname);
  headers.set('Cache-Control', immutable ? 'private, max-age=31536000, immutable' : 'private, no-store');
  if (/text\/html|javascript|text\/css|application\/json/.test(headers.get('content-type') || '')) {
    if (headers.has('content-encoding')) throw new Error('Expected uncompressed client');
    // URL already includes the prefix at the browser cache boundary. Bound the
    // process cache by entries AND bytes; never persist HA session paths.
    const key = prefix + pathname;
    const value = await transformSerially(async () => {
      const hit = immutable ? cached(key) : null;
      if (hit) { await response.body?.cancel(); return hit; }
      const text = await response.text();
      const plain = Buffer.from(prefix ? text.replaceAll('/paseo-web', prefix + '/paseo-web') : text);
      const compressed = await compress(plain, { level: 6 });
      const result = { plain, compressed, plainTag: etag(plain), compressedTag: etag(compressed) };
      if (immutable) remember(key, result);
      return result;
    });
    const gzipped = acceptsGzip(acceptEncoding);
    const body = gzipped ? value.compressed : value.plain;
    headers.set('Content-Length', String(body.length));
    if (gzipped) headers.set('Content-Encoding', 'gzip'); else headers.delete('Content-Encoding');
    const tag = gzipped ? value.compressedTag : value.plainTag;
    if (immutable) headers.set('ETag', tag); else headers.delete('ETag');
    if (immutable && ifNoneMatch.split(',').some(value => value.trim().replace(/^W\//, '') === tag || value.trim() === '*')) {
      headers.delete('Content-Length');
      return new Response(null, { status: 304, headers });
    }
    return new Response(method === 'HEAD' ? null : body, { status: response.status, headers });
  }
  return new Response(method === 'HEAD' ? null : response.body, { status: response.status, headers });
}
