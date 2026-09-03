import assert from 'node:assert/strict';
import { access, mkdir, mkdtemp, rm, symlink } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import test from 'node:test';
import {
  assertCaptureBudget,
  canonicalizeOutputDir,
  chooseRenderMode,
  classifyIpAddress,
  createByteBudget,
  confinedOutputPath,
  daemonOriginFromBaseHref,
  evaluateRequestPolicy,
  injectBaseHref,
  isLoopbackHttpUrl,
  planCapture,
  RENDER_LIMITS,
  routeRendererRequest,
  runWithAbsoluteDeadline,
  Semaphore,
  validateRendererInput,
} from '../rootfs/opt/ha-opendesign/headless-renderer.mjs';

test('injectBaseHref inserts an escaped base immediately after head', () => {
  assert.equal(
    injectBaseHref('<html><head class="x"><title>T</title></head></html>', 'http://127.0.0.1:7456/a?x=1&y="q"'),
    '<html><head class="x"><base href="http://127.0.0.1:7456/a?x=1&amp;y=&quot;q&quot;"><title>T</title></head></html>',
  );
  assert.equal(injectBaseHref('<main>x</main>', 'http://localhost:7456/raw/'), '<base href="http://localhost:7456/raw/"><main>x</main>');
});

test('loopback base validation rejects remote or non-http navigation', () => {
  assert.equal(isLoopbackHttpUrl('http://127.0.0.1:7456/raw/'), true);
  assert.equal(isLoopbackHttpUrl('https://localhost/raw/'), true);
  assert.equal(isLoopbackHttpUrl('https://example.com/raw/'), false);
  assert.equal(isLoopbackHttpUrl('file:///etc/passwd'), false);
});

test('renderer input is validated and confined to the daemon export root', () => {
  const valid = validateRendererInput({
    html: '<h1>ok</h1>',
    outputDir: '/tmp/od-test/export-render/job-1',
    baseHref: 'http://127.0.0.1:7456/api/projects/p/raw/',
    width: 1920,
    height: 1080,
  }, { dataDir: '/tmp/od-test' });
  assert.equal(valid.width, 1920);
  assert.equal(valid.pageImageFormat, 'png');
  assert.throws(() => validateRendererInput({ html: 'x', outputDir: '/etc' }, { dataDir: '/tmp/od-test' }), /child of/);
  assert.throws(() => validateRendererInput({ html: 'x', outputDir: 'relative' }, { dataDir: '/tmp/od-test' }), /absolute/);
  assert.throws(() => validateRendererInput({ html: 'x', outputDir: '/tmp/od-test/export-render/job', baseHref: 'https://example.com' }, { dataDir: '/tmp/od-test' }), /loopback/);
  assert.throws(() => validateRendererInput({ html: 'x', outputDir: '/tmp/od-test/export-render/job', baseHref: 'http://127.0.0.1:8099/' }, { dataDir: '/tmp/od-test' }), /exact OpenDesign daemon origin/);
});

test('output filenames cannot escape their supplied directory', () => {
  assert.equal(confinedOutputPath('/tmp/export', 'slide-0.png'), '/tmp/export/slide-0.png');
  assert.throws(() => confinedOutputPath('/tmp/export', '../secret'), /basename/);
  assert.throws(() => confinedOutputPath('tmp/export', 'slide.png'), /absolute/);
});

test('canonical output confinement creates a direct child only after trusting its parent', async (t) => {
  const base = await mkdtemp(path.join(tmpdir(), 'od-render-create-'));
  t.after(() => rm(base, { recursive: true, force: true }));
  const dataDir = path.join(base, 'data');
  const exportRoot = path.join(dataDir, 'export-render');
  const outputDir = path.join(exportRoot, 'job');
  await mkdir(exportRoot, { recursive: true });
  assert.equal(await canonicalizeOutputDir(outputDir, { dataDir }), outputDir);
  await access(outputDir);
});

test('canonical output confinement rejects an outputDir symlink escape', async (t) => {
  const base = await mkdtemp(path.join(tmpdir(), 'od-render-path-'));
  t.after(() => rm(base, { recursive: true, force: true }));
  const dataDir = path.join(base, 'data');
  const exportRoot = path.join(dataDir, 'export-render');
  const outside = path.join(base, 'outside');
  await mkdir(exportRoot, { recursive: true });
  await mkdir(outside);
  try {
    await symlink(outside, path.join(exportRoot, 'job-link'));
  } catch (error) {
    if (error?.code === 'EPERM' || error?.code === 'EACCES') return t.skip('symlink creation unavailable');
    throw error;
  }
  await assert.rejects(
    canonicalizeOutputDir(path.join(exportRoot, 'job-link'), { dataDir }),
    /canonical outputDir escapes/,
  );
});

test('canonical confinement also rejects a replaced export root', async (t) => {
  const base = await mkdtemp(path.join(tmpdir(), 'od-render-root-'));
  t.after(() => rm(base, { recursive: true, force: true }));
  const dataDir = path.join(base, 'data');
  const outside = path.join(base, 'outside');
  await mkdir(dataDir);
  await mkdir(outside);
  try {
    await symlink(outside, path.join(dataDir, 'export-render'));
  } catch (error) {
    if (error?.code === 'EPERM' || error?.code === 'EACCES') return t.skip('symlink creation unavailable');
    throw error;
  }
  await assert.rejects(
    canonicalizeOutputDir(path.join(dataDir, 'export-render', 'job'), { dataDir }),
    /canonical export root escapes/,
  );
  await assert.rejects(
    access(path.join(outside, 'job')),
    (error) => error?.code === 'ENOENT',
    'validation must happen before mkdir can create outside/job',
  );
});

test('deck detection honors explicit caller intent', () => {
  assert.equal(chooseRenderMode(false, 4), 'page');
  assert.equal(chooseRenderMode(true, 0), 'missing-deck');
  assert.equal(chooseRenderMode(true, 3), 'deck');
  assert.equal(chooseRenderMode(undefined, 2), 'deck');
  assert.equal(chooseRenderMode(undefined, 0), 'page');
});

test('IP classification rejects HA-reachable and special address ranges', () => {
  for (const address of [
    '0.0.0.0', '10.0.0.1', '100.64.0.1', '127.0.0.1', '169.254.169.254',
    '172.16.1.1', '192.168.1.1', '198.18.0.1', '224.0.0.1', '::', '::1',
    '::169.254.169.254', '::ffff:127.0.0.1', '::ffff:7f00:1',
    '::ffff:0:169.254.169.254',
    '64:ff9b::a9fe:a9fe', '64:ff9b::8.8.8.8', '64:ff9b:1::a9fe:a9fe',
    '2002:a9fe:a9fe::', '2002:c0a8:0101::',
    '2001:0000:0808:0808:0000:0000:5601:5601',
    '2606:4700::5efe:a9fe:a9fe', 'fc00::1', 'fd00::1', 'fe80::1',
    'ff02::1', '100::1', '2001:db8::1',
  ]) assert.equal(classifyIpAddress(address), 'non-public', address);
  assert.equal(classifyIpAddress('8.8.8.8'), 'public');
  assert.equal(classifyIpAddress('::ffff:8.8.8.8'), 'public');
  assert.equal(classifyIpAddress('::ffff:0:8.8.8.8'), 'public');
  assert.equal(classifyIpAddress('2002:0808:0808::'), 'public');
  assert.equal(classifyIpAddress('2606:4700::5efe:0808:0808'), 'public');
  assert.equal(classifyIpAddress('2606:4700:4700::1111'), 'public');
  assert.equal(classifyIpAddress('not-an-ip'), 'invalid');
});

test('request policy allows local schemes and only the exact daemon loopback origin', async () => {
  const daemonOrigin = daemonOriginFromBaseHref('http://127.0.0.1:7456/api/projects/p/raw/');
  assert.deepEqual(await evaluateRequestPolicy('data:image/png;base64,AA==', { daemonOrigin }), { allow: true, reason: 'local-document-scheme' });
  assert.deepEqual(await evaluateRequestPolicy('blob:null/id', { daemonOrigin }), { allow: true, reason: 'local-document-scheme' });
  assert.deepEqual(await evaluateRequestPolicy('about:blank', { daemonOrigin }), { allow: true, reason: 'local-document-scheme' });
  assert.deepEqual(await evaluateRequestPolicy('http://127.0.0.1:7456/api/health', { daemonOrigin }), { allow: true, reason: 'exact-daemon-origin' });
  assert.equal((await evaluateRequestPolicy('http://127.0.0.1:8099/api/health', { daemonOrigin })).allow, false);
  assert.equal((await evaluateRequestPolicy('http://169.254.169.254/latest/meta-data', { daemonOrigin })).allow, false);
  assert.equal((await evaluateRequestPolicy('http://100.64.0.1/', { daemonOrigin })).allow, false);
  assert.equal((await evaluateRequestPolicy('http://[fe80::1]/', { daemonOrigin })).allow, false);
  assert.equal((await evaluateRequestPolicy('http://[64:ff9b::a9fe:a9fe]/', { daemonOrigin })).allow, false);
  assert.equal((await evaluateRequestPolicy('http://[2002:a9fe:a9fe::]/', { daemonOrigin })).allow, false);
  assert.equal((await evaluateRequestPolicy('file:///etc/passwd', { daemonOrigin })).allow, false);
});

test('request policy rejects DNS names with any private answer and gates public assets', async () => {
  const privateDns = async () => [{ address: '93.184.216.34' }, { address: '192.168.1.10' }];
  for (const hostname of ['supervisor', 'homeassistant.local', 'metadata.google.internal', 'mixed.example']) {
    assert.deepEqual(
      await evaluateRequestPolicy(`https://${hostname}/image.png`, { resolveHost: privateDns, allowPublicHttpAssets: true }),
      { allow: false, reason: 'dns-non-public-address' },
    );
  }
  const publicAnswers = [{ address: '93.184.216.34', family: 4 }, { address: '2606:2800:220:1:248:1893:25c8:1946', family: 6 }];
  const publicDns = async () => publicAnswers;
  let validatedAnswers = null;
  assert.deepEqual(
    await evaluateRequestPolicy('https://public.example/image.png', {
      resolveHost: publicDns,
      allowPublicHttpAssets: true,
      onValidatedAddresses: (answers) => { validatedAnswers = answers; },
    }),
    { allow: true, reason: 'validated-public-dns' },
  );
  assert.deepEqual(validatedAnswers, publicAnswers, 'the renderer must connect to the answers it validated');
  assert.deepEqual(
    await evaluateRequestPolicy('https://public.example/image.png', { resolveHost: publicDns }),
    { allow: false, reason: 'external-network-disabled' },
  );
});

test('aggregate capture limits reject excessive slides and total pixels', () => {
  assert.doesNotThrow(() => assertCaptureBudget({ count: 4, width: 1920, height: 1080, stitch: true }));
  assert.throws(
    () => assertCaptureBudget({ count: RENDER_LIMITS.MAX_SLIDES + 1, width: 320, height: 180 }),
    /slide render limit/,
  );
  assert.throws(
    () => assertCaptureBudget({ count: RENDER_LIMITS.MAX_SLIDES, width: 8192, height: 8192 }),
    /aggregate pixel budget/,
  );
  assert.equal(RENDER_LIMITS.MAX_OUTPUT_BYTES, 128 * 1024 * 1024);
  assert.equal(RENDER_LIMITS.MAX_REMOTE_FETCHES, 4);
  assert.equal(RENDER_LIMITS.MAX_REMOTE_TOTAL_BYTES, 64 * 1024 * 1024);
  const bytes = createByteBudget(10, 'focused byte budget');
  assert.equal(bytes.consume(4), 4);
  assert.equal(bytes.consume(6), 10);
  assert.throws(() => bytes.consume(1), /focused byte budget exceeds 10 bytes/);
});

test('semaphore caps concurrency and releases queued jobs', async () => {
  const semaphore = new Semaphore(2);
  let active = 0;
  let peak = 0;
  const jobs = Array.from({ length: 8 }, (_value, index) => semaphore.run(async () => {
    active += 1;
    peak = Math.max(peak, active);
    await new Promise((resolve) => setTimeout(resolve, 5));
    active -= 1;
    return index;
  }));
  assert.deepEqual(await Promise.all(jobs), [0, 1, 2, 3, 4, 5, 6, 7]);
  assert.equal(peak, 2);
});

test('remote-resource permits bound DNS resolution through pinned fetch completion', async () => {
  const remoteResources = new Semaphore(2);
  let activeResolvers = 0;
  let peakResolvers = 0;
  let resolverStarts = 0;
  let fetchStarts = 0;
  let releaseFetch;
  const fetchGate = new Promise((resolve) => { releaseFetch = resolve; });
  const resolveHost = async () => {
    resolverStarts += 1;
    activeResolvers += 1;
    peakResolvers = Math.max(peakResolvers, activeResolvers);
    await new Promise((resolve) => setTimeout(resolve, 5));
    activeResolvers -= 1;
    return [{ address: '93.184.216.34', family: 4 }];
  };
  const jobs = Array.from({ length: 8 }, (_value, index) => routeRendererRequest({
    request: () => ({ url: () => `https://asset-${index}.example/image.png` }),
    abort: async () => { throw new Error('public test request was unexpectedly blocked'); },
    continue: async () => { throw new Error('public test request unexpectedly bypassed pinned fetch'); },
  }, {
    fulfillRequest: async (_route, address) => {
      assert.equal(address.address, '93.184.216.34');
      fetchStarts += 1;
      await fetchGate;
    },
    remoteBudget: createByteBudget(1024, 'resolver test budget'),
    remoteResources,
    resolveHost,
  }));
  while (fetchStarts < 2) await new Promise((resolve) => setTimeout(resolve, 1));
  await new Promise((resolve) => setTimeout(resolve, 10));
  assert.equal(resolverStarts, 2, 'queued requests must not resolve DNS while fetch permits are held');
  assert.equal(peakResolvers, 2, 'resolver concurrency must match the remote-resource limit');
  releaseFetch();
  const policies = await Promise.all(jobs);
  assert.equal(resolverStarts, 8);
  assert.ok(policies.every((policy) => policy.reason === 'validated-public-dns'));
});

test('absolute deadline aborts work even when it remains active', async () => {
  let observedAbort = false;
  await assert.rejects(
    runWithAbsoluteDeadline(async (signal) => {
      await new Promise((resolve) => signal.addEventListener('abort', () => {
        observedAbort = true;
        resolve();
      }, { once: true }));
      await new Promise(() => {});
    }, 10, 'focused deadline expired'),
    /focused deadline expired/,
  );
  assert.equal(observedAbort, true);
});

test('capture planning covers one slide, all slides, stitching and pagination', () => {
  assert.deepEqual(planCapture({ mode: 'deck', count: 3 }), { indices: [0, 1, 2], stitch: false });
  assert.deepEqual(planCapture({ mode: 'deck', count: 3, index: 1, stitch: true }), { indices: [1], stitch: true });
  assert.equal(planCapture({ mode: 'deck', count: 2, index: 2 }).errorCode, 'SLIDE_INDEX_OUT_OF_RANGE');
  assert.deepEqual(
    planCapture({ mode: 'page', paginate: true, documentHeight: 2200, viewportHeight: 1000 }).pages,
    [{ y: 0, height: 1000 }, { y: 1000, height: 1000 }, { y: 2000, height: 200 }],
  );
});
