import { existsSync } from 'node:fs';
import { lookup } from 'node:dns/promises';
import { lstat, mkdir, mkdtemp, readFile, realpath, rm, stat, unlink } from 'node:fs/promises';
import http from 'node:http';
import https from 'node:https';
import { isIP } from 'node:net';
import path from 'node:path';

const DEFAULT_WIDTH = 1440;
const DEFAULT_HEIGHT = 1000;
const MAX_DIMENSION = 8192;
const MAX_DOCUMENT_HEIGHT = 30_000;
const MAX_PIXELS = 48_000_000;
const MAX_SLIDES = 64;
const MAX_OUTPUT_BYTES = 128 * 1024 * 1024;
const MAX_HTML_BYTES = 32 * 1024 * 1024;
const RENDER_TIMEOUT_MS = 120_000;
const REMOTE_FETCH_TIMEOUT_MS = 15_000;
const MAX_REMOTE_FETCHES = 4;
const MAX_REMOTE_ASSET_BYTES = 32 * 1024 * 1024;
const MAX_REMOTE_TOTAL_BYTES = 64 * 1024 * 1024;
const SLIDE_SELECTOR = '.slide, [data-screen-label], .deck-slide, .ppt-slide';
const CHROME_SELECTOR = '.progress-bar, .notes-overlay, aside.notes, .speaker-notes, .deck-nav, .deck-hint, .deck-counter';

function abortError(signal, fallback = 'operation aborted') {
  if (signal?.reason instanceof Error) return signal.reason;
  const error = new Error(signal?.reason ? String(signal.reason) : fallback);
  error.name = 'AbortError';
  return error;
}

async function waitWithSignal(promise, signal) {
  if (!signal) return promise;
  if (signal.aborted) throw abortError(signal);
  let onAbort;
  const aborted = new Promise((_resolve, reject) => {
    onAbort = () => reject(abortError(signal));
    signal.addEventListener('abort', onAbort, { once: true });
  });
  try {
    return await Promise.race([promise, aborted]);
  } finally {
    signal.removeEventListener('abort', onAbort);
  }
}

export class Semaphore {
  constructor(maximum) {
    if (!Number.isInteger(maximum) || maximum < 1) throw new Error('semaphore maximum must be a positive integer');
    this.maximum = maximum;
    this.active = 0;
    this.waiters = [];
  }

  async acquire(signal) {
    if (signal?.aborted) throw abortError(signal);
    if (this.active < this.maximum) {
      this.active += 1;
      return this.release.bind(this);
    }
    return new Promise((resolve, reject) => {
      const waiter = { resolve, reject, signal, onAbort: null };
      waiter.onAbort = () => {
        const index = this.waiters.indexOf(waiter);
        if (index >= 0) this.waiters.splice(index, 1);
        reject(abortError(signal));
      };
      signal?.addEventListener('abort', waiter.onAbort, { once: true });
      this.waiters.push(waiter);
    });
  }

  release() {
    const waiter = this.waiters.shift();
    if (waiter) {
      waiter.signal?.removeEventListener('abort', waiter.onAbort);
      waiter.resolve(this.release.bind(this));
      return;
    }
    this.active -= 1;
  }

  async run(task, signal) {
    const release = await this.acquire(signal);
    try {
      return await task();
    } finally {
      release();
    }
  }
}

export async function runWithAbsoluteDeadline(task, timeoutMs, message = 'operation deadline exceeded') {
  const controller = new AbortController();
  let rejectDeadline;
  const deadline = new Promise((_resolve, reject) => { rejectDeadline = reject; });
  const timer = setTimeout(() => {
    const error = new Error(message);
    controller.abort(error);
    rejectDeadline(error);
  }, timeoutMs);
  try {
    return await Promise.race([Promise.resolve().then(() => task(controller.signal)), deadline]);
  } finally {
    clearTimeout(timer);
  }
}

export function assertCaptureBudget({ count, width, height, stitch = false }) {
  if (!Number.isInteger(count) || count < 1) throw new Error('capture count must be a positive integer');
  if (count > MAX_SLIDES) throw new Error(`deck exceeds the ${MAX_SLIDES}-slide render limit`);
  const multiplier = stitch && count > 1 ? 2 : 1;
  if (BigInt(count) * BigInt(width) * BigInt(height) * BigInt(multiplier) > BigInt(MAX_PIXELS)) {
    throw new Error('render exceeds the aggregate pixel budget');
  }
}

export function createByteBudget(maximum, label) {
  let used = 0;
  return {
    consume(bytes) {
      used += bytes;
      if (used > maximum) throw new Error(`${label} exceeds ${maximum} bytes`);
      return used;
    },
    get used() { return used; },
  };
}

const renderSemaphore = new Semaphore(1);

function escapeHtmlAttribute(value) {
  return value.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

export function injectBaseHref(html, baseHref) {
  if (!baseHref) return html;
  const tag = `<base href="${escapeHtmlAttribute(baseHref)}">`;
  if (/<head(?:\s[^>]*)?>/i.test(html)) {
    return html.replace(/<head(?:\s[^>]*)?>/i, (head) => `${head}${tag}`);
  }
  return `${tag}${html}`;
}

export function isLoopbackHttpUrl(value) {
  if (typeof value !== 'string') return false;
  try {
    const url = new URL(value);
    return (url.protocol === 'http:' || url.protocol === 'https:')
      && ['127.0.0.1', 'localhost', '::1', '[::1]'].includes(url.hostname);
  } catch {
    return false;
  }
}

function positiveDimension(value, fallback, label) {
  if (value == null) return fallback;
  if (!Number.isFinite(value) || value < 1 || value > MAX_DIMENSION) {
    throw new Error(`${label} must be between 1 and ${MAX_DIMENSION}`);
  }
  return Math.round(value);
}

export function confinedOutputPath(outputDir, filename) {
  if (!path.isAbsolute(outputDir)) throw new Error('outputDir must be an absolute path');
  if (typeof filename !== 'string' || filename.length === 0 || path.basename(filename) !== filename) {
    throw new Error('output filename must be a basename');
  }
  const output = path.resolve(outputDir, filename);
  const relative = path.relative(path.resolve(outputDir), output);
  if (relative.startsWith('..') || path.isAbsolute(relative)) {
    throw new Error('output path escapes outputDir');
  }
  return output;
}

export function validateRendererInput(value, options = {}) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('renderer input must be an object');
  const html = value.html;
  if (typeof html !== 'string' || html.length === 0) throw new Error('html must be a non-empty string');
  if (Buffer.byteLength(html, 'utf8') > MAX_HTML_BYTES) throw new Error('html exceeds the 32 MiB render limit');
  if (typeof value.outputDir !== 'string' || !path.isAbsolute(value.outputDir)) {
    throw new Error('outputDir must be supplied as an absolute path');
  }
  const dataDir = path.resolve(options.dataDir ?? process.env.OD_DATA_DIR ?? '/data/opendesign');
  const exportRoot = path.resolve(dataDir, 'export-render');
  const outputDir = path.resolve(value.outputDir);
  const relative = path.relative(exportRoot, outputDir);
  if (!relative || relative.startsWith('..') || path.isAbsolute(relative)) {
    throw new Error(`outputDir must be a child of ${exportRoot}`);
  }
  if (value.baseHref != null) {
    if (!isLoopbackHttpUrl(value.baseHref)) throw new Error('baseHref must be an HTTP(S) loopback URL');
    const expectedDaemonOrigin = options.daemonOrigin
      ?? `http://${process.env.OD_BIND_HOST ?? '127.0.0.1'}:${process.env.OD_PORT ?? '7456'}`;
    if (new URL(value.baseHref).origin !== new URL(expectedDaemonOrigin).origin) {
      throw new Error(`baseHref must use the exact OpenDesign daemon origin ${new URL(expectedDaemonOrigin).origin}`);
    }
  }
  if (value.deck != null && typeof value.deck !== 'boolean') throw new Error('deck must be boolean');
  if (value.editable != null && typeof value.editable !== 'boolean') throw new Error('editable must be boolean');
  if (value.stitch != null && typeof value.stitch !== 'boolean') throw new Error('stitch must be boolean');
  if (value.paginate != null && typeof value.paginate !== 'boolean') throw new Error('paginate must be boolean');
  if (value.pageImageFormat != null && !['png', 'jpeg'].includes(value.pageImageFormat)) {
    throw new Error('pageImageFormat must be png or jpeg');
  }
  if (value.index != null && (!Number.isInteger(value.index) || value.index < 0 || value.index > 9999)) {
    throw new Error('index must be a non-negative integer');
  }
  return {
    ...value,
    html,
    outputDir,
    width: positiveDimension(value.width, DEFAULT_WIDTH, 'width'),
    height: positiveDimension(value.height, DEFAULT_HEIGHT, 'height'),
    pageImageFormat: value.pageImageFormat === 'jpeg' ? 'jpeg' : 'png',
  };
}

export function chooseRenderMode(deck, slideCount) {
  if (deck === true && slideCount === 0) return 'missing-deck';
  if (deck === false) return 'page';
  return slideCount > 0 ? 'deck' : 'page';
}

export function planCapture({ mode, count, index, stitch, paginate, documentHeight, viewportHeight }) {
  if (mode === 'deck') {
    if (index != null && index >= count) return { errorCode: 'SLIDE_INDEX_OUT_OF_RANGE', indices: [] };
    return { indices: index == null ? Array.from({ length: count }, (_, i) => i) : [index], stitch: stitch === true };
  }
  const height = Math.max(1, Math.ceil(documentHeight));
  if (!paginate) return { pages: [{ y: 0, height }] };
  const pages = [];
  for (let y = 0; y < height; y += viewportHeight) pages.push({ y, height: Math.min(viewportHeight, height - y) });
  return { pages };
}

function executablePath() {
  const candidates = [
    process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
    '/usr/bin/chromium-browser',
    '/usr/bin/chromium',
  ].filter(Boolean);
  const found = candidates.find((candidate) => existsSync(candidate));
  if (!found) throw new Error('system Chromium executable not found');
  return found;
}

function isStrictChild(parent, candidate) {
  const relative = path.relative(parent, candidate);
  return Boolean(relative) && !relative.startsWith('..') && !path.isAbsolute(relative);
}

export async function canonicalizeOutputDir(outputDir, options = {}) {
  const dataDir = path.resolve(options.dataDir ?? process.env.OD_DATA_DIR ?? '/data/opendesign');
  const exportRoot = path.resolve(dataDir, 'export-render');
  const requestedOutputDir = path.resolve(outputDir);
  if (!isStrictChild(exportRoot, requestedOutputDir)) {
    throw new Error('canonical outputDir escapes the export root');
  }

  // The launcher owns creation of these trusted roots. Resolve and validate
  // them before creating caller-controlled paths so a replaced export-root
  // symlink cannot cause mkdir to write outside OD_DATA_DIR.
  const [canonicalDataDir, exportRootStat, canonicalExportRoot] = await Promise.all([
    realpath(dataDir),
    lstat(exportRoot),
    realpath(exportRoot),
  ]);
  const expectedExportRoot = path.join(canonicalDataDir, 'export-render');
  if (exportRootStat.isSymbolicLink()
    || !exportRootStat.isDirectory()
    || canonicalExportRoot !== expectedExportRoot
    || !isStrictChild(canonicalDataDir, canonicalExportRoot)) {
    throw new Error('canonical export root escapes OD_DATA_DIR or is a symlink');
  }

  let existingParent = path.dirname(requestedOutputDir);
  let canonicalParent;
  while (canonicalParent == null) {
    try {
      canonicalParent = await realpath(existingParent);
    } catch (error) {
      if (error?.code !== 'ENOENT' || existingParent === exportRoot) throw error;
      existingParent = path.dirname(existingParent);
    }
  }
  if (canonicalParent !== canonicalExportRoot && !isStrictChild(canonicalExportRoot, canonicalParent)) {
    throw new Error('canonical outputDir parent escapes the export root');
  }
  await mkdir(requestedOutputDir, { recursive: true });

  const [finalDataDir, finalExportRootStat, finalExportRoot, canonicalOutputDir] = await Promise.all([
    realpath(dataDir),
    lstat(exportRoot),
    realpath(exportRoot),
    realpath(requestedOutputDir),
  ]);
  if (finalExportRootStat.isSymbolicLink()
    || finalDataDir !== canonicalDataDir
    || finalExportRoot !== canonicalExportRoot
    || !isStrictChild(finalDataDir, finalExportRoot)) {
    throw new Error('canonical export root changed during output creation');
  }
  if (!isStrictChild(finalExportRoot, canonicalOutputDir)) {
    throw new Error('canonical outputDir escapes the export root');
  }
  return canonicalOutputDir;
}

function ipv4Number(address) {
  const parts = address.split('.').map(Number);
  if (parts.length !== 4 || parts.some((part) => !Number.isInteger(part) || part < 0 || part > 255)) return null;
  return (((parts[0] * 256 + parts[1]) * 256 + parts[2]) * 256 + parts[3]) >>> 0;
}

function inIpv4Cidr(value, base, bits) {
  const mask = bits === 0 ? 0 : (0xffffffff << (32 - bits)) >>> 0;
  return (value & mask) === (base & mask);
}

function ipv6Number(address) {
  let normalized = address.toLowerCase().split('%')[0];
  const dottedTail = /(?:^|:)(\d+\.\d+\.\d+\.\d+)$/.exec(normalized);
  if (dottedTail) {
    const value = ipv4Number(dottedTail[1]);
    if (value == null) return null;
    normalized = `${normalized.slice(0, dottedTail.index)}:${(value >>> 16).toString(16)}:${(value & 0xffff).toString(16)}`;
  }
  if ((normalized.match(/::/g) ?? []).length > 1) return null;
  const [leftRaw, rightRaw] = normalized.split('::');
  const left = leftRaw ? leftRaw.split(':') : [];
  const right = rightRaw ? rightRaw.split(':') : [];
  const omitted = normalized.includes('::') ? 8 - left.length - right.length : 0;
  const groups = [...left, ...Array(Math.max(0, omitted)).fill('0'), ...right];
  if (groups.length !== 8 || omitted < 0 || groups.some((group) => !/^[0-9a-f]{1,4}$/.test(group))) return null;
  return groups.reduce((value, group) => (value << 16n) | BigInt(`0x${group}`), 0n);
}

function inIpv6Cidr(value, base, bits) {
  const shift = 128n - BigInt(bits);
  return (value >> shift) === (base >> shift);
}

export function classifyIpAddress(address) {
  if (typeof address !== 'string') return 'invalid';
  address = address.startsWith('[') && address.endsWith(']') ? address.slice(1, -1) : address;
  const bareAddress = address.split('%')[0];
  const version = isIP(bareAddress);
  if (version === 4) {
    const value = ipv4Number(bareAddress);
    const blocked = [
      ['0.0.0.0', 8], ['10.0.0.0', 8], ['100.64.0.0', 10], ['127.0.0.0', 8],
      ['169.254.0.0', 16], ['172.16.0.0', 12], ['192.0.0.0', 24], ['192.0.2.0', 24],
      ['192.168.0.0', 16], ['198.18.0.0', 15], ['198.51.100.0', 24], ['203.0.113.0', 24],
      ['224.0.0.0', 4], ['240.0.0.0', 4],
    ];
    return blocked.some(([base, bits]) => inIpv4Cidr(value, ipv4Number(base), bits)) ? 'non-public' : 'public';
  }
  if (version === 6) {
    const value = ipv6Number(bareAddress);
    if (value == null) return 'invalid';
    const embeddedIpv4 = (embedded) => classifyIpAddress([
      Number((embedded >> 24n) & 0xffn), Number((embedded >> 16n) & 0xffn),
      Number((embedded >> 8n) & 0xffn), Number(embedded & 0xffn),
    ].join('.'));
    const mappedBase = ipv6Number('::ffff:0:0');
    const translatableBase = ipv6Number('::ffff:0:0:0');
    if (inIpv6Cidr(value, mappedBase, 96) || inIpv6Cidr(value, translatableBase, 96)) {
      return embeddedIpv4(value & 0xffffffffn);
    }
    // IPv4 transition mechanisms can otherwise disguise private/link-local
    // IPv4 destinations inside a globally shaped IPv6 literal.
    const sixToFourBase = ipv6Number('2002::');
    if (inIpv6Cidr(value, sixToFourBase, 16)) {
      const classification = embeddedIpv4((value >> 80n) & 0xffffffffn);
      if (classification !== 'public') return classification;
    }
    const teredoBase = ipv6Number('2001::');
    if (inIpv6Cidr(value, teredoBase, 32)) {
      const server = embeddedIpv4((value >> 64n) & 0xffffffffn);
      const client = embeddedIpv4((~value) & 0xffffffffn);
      if (server !== 'public' || client !== 'public') return 'non-public';
    }
    const isatapMarker = (value >> 32n) & 0xffffffffn;
    if (isatapMarker === 0x00005efen || isatapMarker === 0x02005efen) {
      const classification = embeddedIpv4(value & 0xffffffffn);
      if (classification !== 'public') return classification;
    }
    const blocked = [
      ['::', 128], ['::1', 128], ['::', 96], ['64:ff9b::', 96], ['64:ff9b:1::', 48], ['100::', 64],
      ['2001:2::', 48], ['2001:10::', 28], ['2001:db8::', 32], ['fc00::', 7],
      ['fe80::', 10], ['fec0::', 10], ['ff00::', 8],
    ];
    return blocked.some(([base, bits]) => inIpv6Cidr(value, ipv6Number(base), bits)) ? 'non-public' : 'public';
  }
  return 'invalid';
}

export async function evaluateRequestPolicy(value, options) {
  let url;
  try {
    url = new URL(value);
  } catch {
    return { allow: false, reason: 'invalid-url' };
  }
  if (['data:', 'blob:', 'about:'].includes(url.protocol)) return { allow: true, reason: 'local-document-scheme' };
  if (url.protocol !== 'http:' && url.protocol !== 'https:') return { allow: false, reason: 'unsupported-scheme' };
  if (url.username || url.password) return { allow: false, reason: 'url-credentials' };
  if (options?.daemonOrigin && url.origin === options.daemonOrigin) return { allow: true, reason: 'exact-daemon-origin' };

  const literalKind = classifyIpAddress(url.hostname);
  if (literalKind === 'non-public') return { allow: false, reason: 'non-public-address' };
  if (literalKind === 'public') {
    const address = url.hostname.startsWith('[') && url.hostname.endsWith(']')
      ? url.hostname.slice(1, -1)
      : url.hostname;
    options?.onValidatedAddresses?.([{ address, family: isIP(address) }]);
    return options?.allowPublicHttpAssets === true
      ? { allow: true, reason: 'validated-public-address' }
      : { allow: false, reason: 'external-network-disabled' };
  }

  let addresses;
  try {
    addresses = await waitWithSignal(
      (options?.resolveHost ?? lookup)(url.hostname, { all: true, verbatim: true }),
      options?.signal,
    );
  } catch (error) {
    if (options?.signal?.aborted) throw error;
    return { allow: false, reason: 'dns-failed' };
  }
  if (!Array.isArray(addresses) || addresses.length === 0) return { allow: false, reason: 'dns-empty' };
  if (addresses.some((entry) => classifyIpAddress(entry.address) !== 'public')) {
    return { allow: false, reason: 'dns-non-public-address' };
  }
  options?.onValidatedAddresses?.(addresses);
  return options?.allowPublicHttpAssets === true
    ? { allow: true, reason: 'validated-public-dns' }
    : { allow: false, reason: 'external-network-disabled' };
}

async function fulfillPinnedPublicRequest(route, address, { signal, totalBudget }) {
  if (signal?.aborted) throw abortError(signal);
  const request = route.request();
  const url = new URL(request.url());
  const headers = { ...request.headers(), host: url.host };
  delete headers.connection;
  delete headers['content-length'];
  delete headers['accept-encoding'];
  const body = request.postDataBuffer();
  const urlHostname = url.hostname.startsWith('[') && url.hostname.endsWith(']')
    ? url.hostname.slice(1, -1)
    : url.hostname;
  await new Promise((resolve, reject) => {
    const client = url.protocol === 'https:' ? https : http;
    let settled = false;
    let incoming;
    const finish = (error) => {
      if (settled) return;
      settled = true;
      clearTimeout(absoluteDeadline);
      signal?.removeEventListener('abort', onAbort);
      if (error) reject(error);
      else resolve();
    };
    const outgoing = client.request({
      family: address.family || isIP(address.address),
      headers,
      hostname: address.address,
      method: request.method(),
      path: `${url.pathname}${url.search}`,
      port: url.port || undefined,
      ...(url.protocol === 'https:' && !isIP(urlHostname) ? { servername: urlHostname } : {}),
    }, (response) => {
      incoming = response;
      const chunks = [];
      let total = 0;
      response.on('data', (chunk) => {
        try {
          total += chunk.length;
          if (total > MAX_REMOTE_ASSET_BYTES) throw new Error('remote renderer asset exceeds 32 MiB');
          totalBudget.consume(chunk.length);
          chunks.push(chunk);
        } catch (error) {
          response.destroy(error);
        }
      });
      response.on('error', finish);
      response.on('end', async () => {
        const responseHeaders = Object.fromEntries(Object.entries(response.headers)
          .filter(([name, value]) => value != null
            && !['connection', 'content-length', 'transfer-encoding'].includes(name))
          .map(([name, value]) => [name, Array.isArray(value) ? value.join(', ') : value]));
        try {
          await route.fulfill({
            body: Buffer.concat(chunks),
            headers: responseHeaders,
            status: response.statusCode ?? 502,
          });
          finish();
        } catch (error) {
          finish(error);
        }
      });
    });
    const onAbort = () => {
      const error = abortError(signal);
      incoming?.destroy(error);
      outgoing.destroy(error);
      finish(error);
    };
    const absoluteDeadline = setTimeout(() => {
      const error = new Error('remote renderer asset deadline exceeded');
      incoming?.destroy(error);
      outgoing.destroy(error);
      finish(error);
    }, REMOTE_FETCH_TIMEOUT_MS);
    absoluteDeadline.unref?.();
    signal?.addEventListener('abort', onAbort, { once: true });
    outgoing.on('error', finish);
    if (signal?.aborted) {
      onAbort();
      return;
    }
    if (body) outgoing.write(body);
    outgoing.end();
  });
}

export async function routeRendererRequest(route, options) {
  const {
    daemonOrigin,
    fulfillRequest = fulfillPinnedPublicRequest,
    remoteBudget,
    remoteResources,
    resolveHost,
    signal,
  } = options;
  if (!remoteResources || typeof remoteResources.run !== 'function') {
    throw new Error('remote resource semaphore is required');
  }
  // A single permit covers DNS resolution, policy evaluation, and the pinned
  // fetch. Hostile documents therefore cannot queue unbounded resolver work
  // while all of the fetch permits are occupied.
  return remoteResources.run(async () => {
    let validatedAddresses = [];
    const policy = await evaluateRequestPolicy(route.request().url(), {
      daemonOrigin,
      allowPublicHttpAssets: true,
      resolveHost,
      signal,
      onValidatedAddresses: (addresses) => { validatedAddresses = addresses; },
    });
    if (!policy.allow) {
      await route.abort('blockedbyclient');
    } else if (policy.reason === 'validated-public-address' || policy.reason === 'validated-public-dns') {
      // Connect to the address that was classified, while retaining the URL
      // host for Host/SNI. Chromium must not perform a second, rebindable DNS
      // lookup after policy approval.
      const address = validatedAddresses.find((entry) => entry.family === 4) ?? validatedAddresses[0];
      await fulfillRequest(route, address, { signal, totalBudget: remoteBudget });
    } else {
      await route.continue();
    }
    return policy;
  }, signal);
}

export function daemonOriginFromBaseHref(baseHref) {
  if (!baseHref) return null;
  try {
    return new URL(baseHref).origin;
  } catch {
    return null;
  }
}

function screenshotOptions(filepath, format) {
  return format === 'jpeg'
    ? { path: filepath, type: 'jpeg', quality: 88 }
    : { path: filepath, type: 'png' };
}

async function settleDocument(page) {
  await page.evaluate(async () => {
    const timeout = new Promise((resolve) => setTimeout(resolve, 5000));
    const fonts = document.fonts?.ready?.catch?.(() => undefined) ?? Promise.resolve();
    const images = Promise.all(Array.from(document.images).map((image) => {
      if (image.complete) return Promise.resolve();
      return new Promise((resolve) => {
        image.addEventListener('load', resolve, { once: true });
        image.addEventListener('error', resolve, { once: true });
      });
    }));
    await Promise.race([Promise.all([fonts, images]), timeout]);
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  });
}

async function realSlides(page) {
  return page.evaluate((selector) => Array.from(document.querySelectorAll(selector))
    .filter((element) => !element.closest('.mini-slide, .overview, .notes-overlay, .thumb')).length, SLIDE_SELECTOR);
}

async function measureDeck(page, fallback) {
  return page.evaluate(({ selector, fallback }) => {
    const slides = Array.from(document.querySelectorAll(selector))
      .filter((element) => !element.closest('.mini-slide, .overview, .notes-overlay, .thumb'));
    const element = slides.find((slide) => slide.getBoundingClientRect().width > 1) ?? slides[0];
    if (!element) return fallback;
    const stage = element.closest('deck-stage, #deck-stage, .deck-stage');
    const target = stage ?? element;
    const style = getComputedStyle(target);
    const width = Number.parseFloat(target.getAttribute('width') || target.style.width || style.width) || target.offsetWidth;
    const height = Number.parseFloat(target.getAttribute('height') || target.style.height || style.height) || target.offsetHeight;
    if (width < 1 || height < 1 || width > 8192 || height > 8192) return fallback;
    return { width: Math.round(width), height: Math.round(height) };
  }, { selector: SLIDE_SELECTOR, fallback });
}

async function stageSlide(page, index, size) {
  return page.evaluate(({ selector, chromeSelector, index, size }) => {
    document.getElementById('__od_headless_capture_layer')?.remove();
    document.querySelectorAll(chromeSelector).forEach((element) => element.style.setProperty('display', 'none', 'important'));
    document.querySelectorAll('deck-stage, #deck-stage, .deck-stage').forEach((stage) => {
      stage.setAttribute('noscale', '');
      stage.style.setProperty('transform', 'none', 'important');
    });
    const slides = Array.from(document.querySelectorAll(selector))
      .filter((element) => !element.closest('.mini-slide, .overview, .notes-overlay, .thumb'));
    const selected = slides[index];
    if (!selected) return false;
    slides.forEach((slide, current) => {
      const active = current === index;
      ['active', 'visible', 'is-active', 'current'].forEach((name) => slide.classList.toggle(name, active));
      slide.toggleAttribute('data-od-deck-active', active);
      slide.style.setProperty('visibility', active ? 'visible' : 'hidden', 'important');
      slide.style.setProperty('opacity', active ? '1' : '0', 'important');
    });
    const layer = document.createElement('div');
    layer.id = '__od_headless_capture_layer';
    layer.style.cssText = `position:fixed!important;inset:0 auto auto 0!important;width:${size.width}px!important;height:${size.height}px!important;overflow:hidden!important;z-index:2147483647!important;background:${getComputedStyle(document.body).backgroundColor || '#fff'}!important`;
    // Keep all slide siblings in the capture layer so structural selectors such
    // as :first-of-type/:last-of-type retain their authored meaning. Moving only
    // the selected slide made every capture match both selectors and duplicated
    // the last slide's styling across a deck.
    slides.forEach((slide, current) => {
      const active = current === index;
      const clone = slide.cloneNode(true);
      ['active', 'visible', 'is-active', 'current'].forEach((name) => clone.classList.toggle(name, active));
      clone.toggleAttribute('data-od-deck-active', active);
      clone.style.setProperty('display', 'block', 'important');
      clone.style.setProperty('position', 'absolute', 'important');
      clone.style.setProperty('inset', '0', 'important');
      clone.style.setProperty('margin', '0', 'important');
      clone.style.setProperty('transform', 'none', 'important');
      clone.style.setProperty('width', `${size.width}px`, 'important');
      clone.style.setProperty('height', `${size.height}px`, 'important');
      clone.style.setProperty('visibility', active ? 'visible' : 'hidden', 'important');
      clone.style.setProperty('opacity', active ? '1' : '0', 'important');
      layer.appendChild(clone);
    });
    document.documentElement.appendChild(layer);
    return true;
  }, { selector: SLIDE_SELECTOR, chromeSelector: CHROME_SELECTOR, index, size });
}

async function recordOutputFile(filepath, outputBudget) {
  const metadata = await stat(filepath);
  try {
    outputBudget.consume(metadata.size);
  } catch (error) {
    await unlink(filepath).catch(() => {});
    throw error;
  }
}

async function stitchFiles(context, files, outputDir, format, width, height, outputBudget) {
  const scale = Math.min(1, MAX_DOCUMENT_HEIGHT / (height * files.length), Math.sqrt(MAX_PIXELS / (width * height * files.length)));
  const outputWidth = Math.max(1, Math.floor(width * scale));
  const rowHeight = Math.max(1, Math.floor(height * scale));
  const outputHeight = rowHeight * files.length;
  const page = await context.newPage({ viewport: { width: outputWidth, height: Math.min(outputHeight, DEFAULT_HEIGHT) } });
  try {
    await page.setContent(`<style>html,body{margin:0;background:#fff}img{display:block;width:${outputWidth}px;height:${rowHeight}px}</style>`);
    // Read and decode one source at a time. Promise.all retained every encoded
    // slide in Node memory and caused large decks to spike HA memory usage.
    for (const file of files) {
      const source = `data:image/${format};base64,${(await readFile(file)).toString('base64')}`;
      await page.evaluate(async ({ source, outputWidth, rowHeight }) => {
        const image = document.createElement('img');
        image.width = outputWidth;
        image.height = rowHeight;
        image.src = source;
        await image.decode();
        document.body.appendChild(image);
      }, { source, outputWidth, rowHeight });
    }
    const ext = format === 'jpeg' ? 'jpg' : 'png';
    const filepath = confinedOutputPath(outputDir, `stitched.${ext}`);
    await page.screenshot({ ...screenshotOptions(filepath, format), fullPage: true });
    await recordOutputFile(filepath, outputBudget);
    return { files: [filepath], width: outputWidth, height: outputHeight };
  } finally {
    await page.close();
  }
}

async function captureDeck(context, page, input, count, outputBudget) {
  const requested = { width: input.width, height: input.height };
  const size = input.width !== DEFAULT_WIDTH || input.height !== DEFAULT_HEIGHT
    ? requested
    : await measureDeck(page, { width: 1920, height: 1080 });
  await page.setViewportSize(size);
  const plan = planCapture({ mode: 'deck', count, index: input.index, stitch: input.stitch });
  if (plan.errorCode) {
    return { ok: false, error: `slide index ${input.index} is out of range (deck has ${count} slide(s))`, errorCode: plan.errorCode };
  }
  assertCaptureBudget({ count: plan.indices.length, width: size.width, height: size.height, stitch: plan.stitch });
  const files = [];
  const ext = input.pageImageFormat === 'jpeg' ? 'jpg' : 'png';
  for (const index of plan.indices) {
    if (!await stageSlide(page, index, size)) return { ok: false, error: 'slide disappeared during capture', errorCode: 'RENDER_FAILED' };
    await page.waitForTimeout(50);
    const filepath = confinedOutputPath(input.outputDir, `slide-${index}.${ext}`);
    await page.screenshot({ ...screenshotOptions(filepath, input.pageImageFormat), clip: { x: 0, y: 0, width: size.width, height: size.height } });
    await recordOutputFile(filepath, outputBudget);
    files.push(filepath);
  }
  if (plan.stitch && files.length > 1) {
    const stitched = await stitchFiles(context, files, input.outputDir, input.pageImageFormat, size.width, size.height, outputBudget);
    return { ok: true, slideFiles: stitched.files, width: stitched.width, height: stitched.height, mode: 'deck' };
  }
  return { ok: true, slideFiles: files, width: size.width, height: size.height, mode: 'deck' };
}

async function capturePage(page, input, outputBudget) {
  await page.setViewportSize({ width: input.width, height: input.height });
  const dimensions = await page.evaluate(() => ({
    width: Math.max(document.documentElement.scrollWidth, document.body?.scrollWidth ?? 0, 1),
    height: Math.max(document.documentElement.scrollHeight, document.body?.scrollHeight ?? 0, 1),
  }));
  if (dimensions.height > MAX_DOCUMENT_HEIGHT || dimensions.width * dimensions.height > MAX_PIXELS) {
    return { ok: false, error: 'page exceeds the bounded capture size', errorCode: 'PAGE_TOO_TALL' };
  }
  const plan = planCapture({ mode: 'page', paginate: input.paginate, documentHeight: dimensions.height, viewportHeight: input.height });
  assertCaptureBudget({ count: 1, width: dimensions.width, height: dimensions.height });
  const files = [];
  const ext = input.pageImageFormat === 'jpeg' ? 'jpg' : 'png';
  for (let index = 0; index < plan.pages.length; index += 1) {
    const segment = plan.pages[index];
    const filepath = confinedOutputPath(input.outputDir, `page-${index}.${ext}`);
    if (input.paginate) {
      await page.screenshot({ ...screenshotOptions(filepath, input.pageImageFormat), clip: { x: 0, y: segment.y, width: Math.min(input.width, dimensions.width), height: segment.height } });
    } else {
      await page.screenshot({ ...screenshotOptions(filepath, input.pageImageFormat), fullPage: true });
    }
    await recordOutputFile(filepath, outputBudget);
    files.push(filepath);
  }
  return { ok: true, slideFiles: files, width: dimensions.width, height: input.paginate ? input.height : dimensions.height, mode: 'page' };
}

async function renderSlidesExclusive(rawInput, signal) {
  let browser;
  let chromiumHome;
  const closeOnAbort = () => void browser?.close().catch(() => {});
  signal.addEventListener('abort', closeOnAbort, { once: true });
  try {
    const input = validateRendererInput(rawInput);
    if (input.editable === true) {
      return { ok: false, error: 'Editable PPTX is unsupported in the Home Assistant add-on; choose screenshot PPTX.', errorCode: 'RENDER_FAILED' };
    }
    input.outputDir = await waitWithSignal(canonicalizeOutputDir(input.outputDir), signal);
    const { chromium } = await import('playwright-core');
    chromiumHome = await mkdtemp('/tmp/ha-opendesign-chromium-');
    const configHome = path.join(chromiumHome, 'config');
    const cacheHome = path.join(chromiumHome, 'cache');
    await Promise.all([mkdir(configHome), mkdir(cacheHome)]);
    const launch = chromium.launch({
      executablePath: executablePath(),
      headless: true,
      env: {
        ...process.env,
        HOME: chromiumHome,
        XDG_CONFIG_HOME: configHome,
        XDG_CACHE_HOME: cacheHome,
      },
      args: ['--no-sandbox', '--disable-dev-shm-usage', '--font-render-hinting=none'],
    });
    launch.then((launched) => {
      if (signal.aborted) void launched.close().catch(() => {});
    }, () => {});
    browser = await waitWithSignal(launch, signal);
    const context = await browser.newContext({
      viewport: { width: input.width, height: input.height },
      serviceWorkers: 'block',
    });
    const daemonOrigin = daemonOriginFromBaseHref(input.baseHref);
    const remoteFetches = new Semaphore(MAX_REMOTE_FETCHES);
    const remoteBudget = createByteBudget(MAX_REMOTE_TOTAL_BYTES, 'aggregate remote renderer resources');
    const outputBudget = createByteBudget(MAX_OUTPUT_BYTES, 'aggregate renderer output');
    // Block every WebSocket before creating any page. Chromium's ordinary
    // request routing does not cover ws/wss handshakes.
    await context.routeWebSocket('**/*', (webSocketRoute) => {
      webSocketRoute.close({ code: 1008, reason: 'WebSockets disabled in renderer' });
    });
    // Install the policy on the context before creating a page so workers and
    // the first navigation of any model-opened popup cannot bypass it.
    await context.route('**/*', async (route) => {
      try {
        await routeRendererRequest(route, {
          daemonOrigin,
          remoteBudget,
          remoteResources: remoteFetches,
          signal,
        });
      } catch {
        await route.abort('failed').catch(() => {});
      }
    });
    const page = await context.newPage();
    page.setDefaultTimeout(15_000);
    page.setDefaultNavigationTimeout(15_000);
    page.on('dialog', (dialog) => dialog.dismiss().catch(() => {}));
    page.on('popup', (popup) => popup.close().catch(() => {}));
    await page.setContent(injectBaseHref(input.html, input.baseHref), { waitUntil: 'domcontentloaded', timeout: 15_000 });
    await settleDocument(page);
    const count = await realSlides(page);
    if (count > MAX_SLIDES) throw new Error(`deck exceeds the ${MAX_SLIDES}-slide render limit`);
    const mode = chooseRenderMode(input.deck, count);
    if (mode === 'missing-deck') return { ok: false, error: 'no slide surfaces found in this deck', errorCode: 'NO_SLIDES' };
    return mode === 'deck'
      ? await captureDeck(context, page, input, count, outputBudget)
      : await capturePage(page, input, outputBudget);
  } finally {
    signal.removeEventListener('abort', closeOnAbort);
    await browser?.close().catch(() => {});
    if (chromiumHome) await rm(chromiumHome, { recursive: true, force: true }).catch(() => {});
  }
}

export async function renderSlides(rawInput) {
  try {
    return await runWithAbsoluteDeadline(
      (signal) => renderSemaphore.run(() => renderSlidesExclusive(rawInput, signal), signal),
      RENDER_TIMEOUT_MS,
      `headless renderer exceeded its ${RENDER_TIMEOUT_MS}ms deadline`,
    );
  } catch (error) {
    return { ok: false, error: `headless renderer failed: ${error instanceof Error ? error.message : String(error)}`, errorCode: 'RENDER_FAILED' };
  }
}

export const RENDER_LIMITS = Object.freeze({
  RENDER_TIMEOUT_MS,
  REMOTE_FETCH_TIMEOUT_MS,
  MAX_DIMENSION,
  MAX_DOCUMENT_HEIGHT,
  MAX_PIXELS,
  MAX_SLIDES,
  MAX_OUTPUT_BYTES,
  MAX_REMOTE_FETCHES,
  MAX_REMOTE_ASSET_BYTES,
  MAX_REMOTE_TOTAL_BYTES,
});
