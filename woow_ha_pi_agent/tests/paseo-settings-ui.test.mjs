import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const read = name => fs.readFileSync(new URL(`../rootfs/usr/local/share/pi-paseo-ha/${name}`, import.meta.url), 'utf8');
const source = read('app.js');
const tick = () => new Promise(resolve => setImmediate(resolve));
// The status the bridge sends: no webReady/webVersion any more (Agent Connect 0.1.23 removed the bundled client).
const ready = target => ({ installed: true, enabled: true, version: 'candidate', phase: 'ready', selectedTarget: target,
  settings: { target }, activeTarget: target, configurationPending: false, targetSelectionAvailable: true, running: true, reachable: true, providers: [] });
async function page(handler) {
  let clock = 0, nextTimer = 0;
  const timers = new Map(), listeners = new Map();
  const nodes = new Map();
  const node = id => {
    if (!nodes.has(id)) nodes.set(id, { value: id === 'target' ? 'paseo' : '', disabled: false, hidden: false,
      removeAttribute(name) { delete this[name]; }, replaceChildren(...children) { this.children = children; } });
    return nodes.get(id);
  };
  const requests = [];
  vm.runInNewContext(source, { URL, URLSearchParams, AbortController, Date: { now: () => clock }, location: { search: '' }, confirm: () => true,
    setTimeout(fn, ms) { timers.set(++nextTimer, { fn, at: clock + ms }); return nextTimer; }, clearTimeout: id => timers.delete(id),
    window: { addEventListener(name, fn) { listeners.set(name, fn); } },
    document: { getElementById: node, querySelector: selector => ({ content: selector.includes('ingress') ? '/api/hassio_ingress/fixture01234567890123' : 'private-token' }), createElement: () => ({}) },
    fetch: async (url, init) => { const body = init.body ? JSON.parse(init.body) : null; requests.push(body);
      const data = await handler(body, init); return data?.httpError ? { ok: false, json: async () => ({ error: { code: data.httpError } }) } : { ok: true, json: async () => data }; },
  });
  await tick();
  return { node, requests, async dispatch(name, event) { listeners.get(name)?.(event); await tick(); }, async advance(ms) {
    clock += ms;
    for (const [id, timer] of [...timers]) if (timer.at <= clock) { timers.delete(id); timer.fn(); }
    await tick();
  } };
}
const origins = { paseo: 'https://app.paseo.sh', woowtech: 'https://smart.woowtech.io', apporo: 'https://smart.apporo.ai' };
const labels = { paseo: 'Paseo', woowtech: 'Woowtech Smart', apporo: 'Apporo Smart' };
test('unsaved target survives refresh, disables pairing, clears old links, and save preserves the selected target', async () => {
  let state = ready('paseo');
  const p = await page(body => {
    if (body?.action === 'save') state = { ...ready(body.target), configurationPending: true };
    return state;
  });
  p.node('pair-link').href = '/old-private-link'; p.node('pair-link').hidden = false;
  p.node('target').value = 'apporo'; p.node('target').onchange();
  assert.equal(p.node('pair-link').hidden, true); assert.equal(p.node('pair-link').href, undefined);
  assert.equal(p.node('pair').disabled, true); assert.equal(p.node('save').disabled, false);
  await p.node('refresh').onclick();
  assert.equal(p.node('target').value, 'apporo'); assert.match(p.node('target-notice').textContent, /尚未儲存/);
  await p.node('save').onclick();
  assert.deepEqual(p.requests.at(-1), { action: 'save', target: 'apporo' });
  assert.equal(p.node('target').value, 'apporo'); assert.equal(p.node('save').disabled, true);
  assert.equal(p.node('pair').disabled, true); assert.match(p.node('target-notice').textContent, /停止服務.*啟動服務/);
  await p.node('pair').onclick(); assert.equal(p.requests.at(-1).action, 'save');
  state.configurationPending = false;
  await p.node('refresh').onclick(); assert.equal(p.node('pair').disabled, false);
  assert.equal(p.node('open').href, 'https://smart.apporo.ai/');
});
test('every target opens its own official site and pairs only through the exact https://<origin>/#offer=<base64url> link', async () => {
  for (const target of Object.keys(origins)) {
    const origin = origins[target], host = new URL(origin).host;
    const link = `${origin}/#offer=abc_DEF-123`;
    let paired = { target, url: link };
    const p = await page(body => body?.action === 'pair' ? paired : ready(target));
    assert.equal(p.node('open').href, origin + '/'); assert.equal(p.node('open').textContent, `開啟 ${labels[target]} 對話介面`); assert.equal(p.node('open').hidden, false);
    assert.equal(p.node('pair').disabled, false, `${target}: a status without any web state allows pairing`);
    await p.node('pair').onclick();
    assert.deepEqual(p.requests.at(-1), { action: 'pair', target });
    assert.equal(p.node('pair-link').hidden, false); assert.equal(p.node('pair-link').href, link);
    assert.equal(p.node('pair-link').textContent, `開啟並配對 ${labels[target]}`);
    const others = Object.keys(origins).filter(id => id !== target);
    for (const value of [{ target: others[0], url: `${origins[others[0]]}/#offer=private` }, { target, url: `${origins[others[0]]}/#offer=private` },
      { target, url: `${origin}.evil.test/#offer=private` }, { target, url: `https://evil.${host}/#offer=private` }, { target, url: `${origin}:444/#offer=private` },
      { target, url: `${origin}:443/#offer=private` }, { target, url: `https://ａ${host.slice(1)}/#offer=private` }, { target, url: origin.replace('https://', 'HTTPS://') + '/#offer=private' },
      { target, url: `https://${host}./#offer=private` }, { target, url: `https://${host.toUpperCase()}/#offer=private` }, { target, url: `https://${host[0].toUpperCase()}${host.slice(1)}/#offer=private` },
      { target, url: origin.replace('https://', 'http://') + '/#offer=private' }, { target, url: origin.replace('https://', 'https://user:secret@') + '/#offer=private' },
      { target, url: `${origin}/welcome#offer=private` }, { target, url: `${origin}/?next=evil#offer=private` }, { target, url: `${origin}/#unknown=private` },
      { target, url: `${origin}/#offer=` }, { target, url: `${origin}/#offer=bad!` }, { target, url: `${origin}/#offer=a b` }, { target, url: `${origin}/#offer=a\nb` },
      { target, url: `${origin}/#offer=a\\b` }, { target, url: 'javascript:alert(1)' }, { target, url: '//' + host + '/#offer=private' }, { target, url: '' }, { target, url: null },
      // what Agent Connect <= 0.1.22 returned for Paseo (its bundled client), with and without the Ingress prefix
      { target, url: '/paseo-web/welcome#offer=private' }, { target, url: '/api/hassio_ingress/fixture01234567890123/paseo-web/welcome#offer=private' }, { target, url: '/paseo-web/#offer=private' }]) {
      paired = value; await p.node('refresh').onclick(); await p.node('pair').onclick();
      assert.equal(p.node('pair-link').hidden, true, JSON.stringify(value)); assert.equal(p.node('pair-link').href, undefined, JSON.stringify(value));
      assert.match(p.node('notice').textContent, /操作未完成/, JSON.stringify(value));
    }
  }
});
test('a package that cannot switch targets still pairs Paseo on the official site and only its selector stays disabled', async () => {
  const p = await page(body => body?.action === 'pair' ? { target: 'paseo', url: 'https://app.paseo.sh/#offer=private' }
    : { ...ready('paseo'), targetSelectionAvailable: false });
  assert.equal(p.node('target').disabled, true); assert.equal(p.node('pair').disabled, false);
  assert.match(p.node('target-notice').textContent, /更新 Agent Connect 套件/);
  await p.node('pair').onclick(); assert.equal(p.node('pair-link').hidden, false);
  assert.equal(p.node('pair-link').href, 'https://app.paseo.sh/#offer=private');
  assert.equal(p.node('open').href, 'https://app.paseo.sh/');
});
test('the page links only official sites: the static page and script name no local web client and open in a new tab', () => {
  const html = read('index.html');
  assert.match(html, /<a id="open" hidden href="https:\/\/app\.paseo\.sh\/" target="_blank" rel="noopener noreferrer">/);
  assert.match(html, /<a id="pair-link" hidden target="_blank" rel="noopener noreferrer">/);
  assert.match(html, /<option value="paseo">Paseo<\/option>/);
  for (const [name, text] of [['index.html', html], ['app.js', source]]) {
    assert.doesNotMatch(text, /paseo-web|web-client|webClient|webReady|webVersion/, name);
    assert.doesNotMatch(text, /href="(?!https:\/\/app\.paseo\.sh\/|__INGRESS_PREFIX__)[^"]*"/, `${name}: the only fixed links are the official site and this add-on's own paths`);
  }
  assert.doesNotMatch(source, /agentCollaboration/, 'no collaboration switch in this page yet');
});

test('failed status refresh invalidates old pairing readiness and a successful refresh restores it', async () => {
  let fail = false;
  const p = await page(() => { if (fail) throw Error('STATUS_FAILED'); return ready('apporo'); });
  assert.equal(p.node('pair').disabled, false);
  fail = true; await p.node('refresh').onclick();
  assert.equal(p.node('pair').disabled, true); assert.equal(p.node('open').hidden, true);
  assert.match(p.node('notice').textContent, /STATUS_FAILED/);
  const count = p.requests.length; await p.node('pair').onclick(); assert.equal(p.requests.length, count);
  fail = false; await p.node('refresh').onclick(); assert.equal(p.node('pair').disabled, false);
});

test('slow start shows progress immediately and a delayed daemon becomes usable automatically for all brands', async () => {
  for (const target of Object.keys(origins)) {
    let state = { ...ready(target), running: false, reachable: false, activeTarget: null, phase: 'disabled' }, finish;
    const p = await page(body => body?.action === 'start' ? new Promise(resolve => { finish = () => resolve({ ...state, startScheduled: true }); }) : state);
    const start = p.node('start').onclick();
    assert.match(p.node('start').textContent, /啟動中/); assert.match(p.node('notice').textContent, /正在啟動/);
    finish(); await start;
    assert.equal(p.node('pair').disabled, true); assert.match(p.node('notice').textContent, /自動更新/);
    state = { ...ready(target), phase: 'running' };
    await p.advance(3000);
    assert.equal(p.node('pair').disabled, false); assert.match(p.node('notice').textContent, /服務已啟動/);
    assert.equal(p.requests.filter(body => body?.action === 'start').length, 1);
    assert.deepEqual(p.requests.find(body => body?.action === 'start'), { action: 'start', target });
    const count = p.requests.length; await p.advance(3000); assert.equal(p.requests.length, count, 'startup polling ends on success');
  }
});

test('saved target different from the live brand explains the required stop and never silently restarts', async () => {
  for (const target of ['apporo', 'paseo']) {
    const p = await page(() => ({ ...ready(target), activeTarget: 'woowtech', configurationPending: true }));
    const count = p.requests.length;
    await p.node('start').onclick();
    assert.equal(p.requests.length, count);
    assert.match(p.node('notice').textContent, /尚未套用.*Woowtech Smart.*停止服務.*啟動服務/);
    assert.equal(p.node('pair').disabled, true);
  }
});

test('an unsaved selector cannot start the previously saved brand', async () => {
  const p = await page(() => ready('woowtech'));
  p.node('target').value = 'apporo'; p.node('target').onchange();
  assert.equal(p.node('start').disabled, true);
  const count = p.requests.length; await p.node('start').onclick();
  assert.equal(p.requests.length, count); assert.match(p.node('notice').textContent, /儲存標的/);
});

test('an expired page explains how to recover and a fresh status restores controls', async () => {
  let expired = false;
  const p = await page(() => expired ? { httpError: 'UNTRUSTED_REQUEST' } : ready('paseo'));
  expired = true; await p.node('start').onclick();
  assert.match(p.node('notice').textContent, /設定頁已過期.*Home Assistant/);
  assert.equal(p.node('start').disabled, true); assert.equal(p.node('refresh').disabled, false);
  expired = false; await p.node('refresh').onclick(); assert.equal(p.node('start').disabled, false);
});

test('a hung request times out, unlocks refresh and never retries the mutation', async () => {
  const p = await page((body, init) => body?.action === 'start' ? new Promise((_, reject) => {
    init.signal.addEventListener('abort', () => reject(Object.assign(new Error('aborted'), { name: 'AbortError' })), { once: true });
  }) : ready('paseo'));
  const start = p.node('start').onclick(); await p.advance(30000); await start;
  assert.match(p.node('notice').textContent, /逾時.*未確認/); assert.equal(p.node('refresh').disabled, false);
  assert.equal(p.requests.filter(body => body?.action === 'start').length, 1);
});

test('slow background status cannot block Stop or overwrite its newer response', async () => {
  let state = { ...ready('apporo'), phase: 'disabled', running: false, reachable: false }, delayRead = false, finishRead;
  const p = await page(body => {
    if (body?.action === 'start') return { ...state, startScheduled: true };
    if (body?.action === 'stop') { state = { ...state, phase: 'disabled', running: false, reachable: false }; return state; }
    if (delayRead) return new Promise(resolve => { finishRead = resolve; });
    return state;
  });
  await p.node('start').onclick(); delayRead = true; await p.advance(3000);
  assert.equal(p.node('stop').disabled, false);
  await p.node('stop').onclick();
  finishRead(ready('apporo')); await tick();
  assert.equal(p.node('pair').disabled, true); assert.match(p.node('notice').textContent, /已停止/);
});

test('an external target change during startup is observed without saving or restarting it', async () => {
  let state = { ...ready('apporo'), phase: 'disabled', running: false, reachable: false };
  const p = await page(body => body?.action === 'start' ? { ...state, startScheduled: true } : state);
  await p.node('start').onclick(); state = ready('paseo'); await p.advance(3000);
  assert.match(p.node('notice').textContent, /其他操作已變更/);
  assert.equal(p.node('target').value, 'paseo'); assert.equal(p.requests.filter(Boolean).length, 1);
});

test('a daemon PID alone does not enable pairing, and startup observation has a deadline', async () => {
  let state = { ...ready('apporo'), reachable: false, phase: 'starting' };
  const p = await page(body => body?.action === 'start' ? { ...state, startScheduled: true } : state);
  assert.equal(p.node('pair').disabled, true); await p.node('start').onclick();
  await p.advance(120000); assert.match(p.node('notice').textContent, /尚未確認啟動完成/);
  assert.equal(p.requests.filter(body => body?.action === 'start').length, 1);
  const count = p.requests.length; await p.advance(3000); assert.equal(p.requests.length, count);
});

test('a newly started PID with a pending target is a transition, not a request to stop again', async () => {
  let state = { ...ready('apporo'), phase: 'disabled', running: false, reachable: false, configurationPending: true };
  const p = await page(body => body?.action === 'start' ? { ...state, startScheduled: true } : state);
  await p.node('start').onclick();
  state = { ...ready('apporo'), phase: 'starting', activeTarget: 'woowtech', reachable: false, configurationPending: true };
  await p.advance(3000); assert.match(p.node('notice').textContent, /正在啟動/);
  state = ready('apporo'); await p.advance(3000);
  assert.equal(p.node('pair').disabled, false); assert.equal(p.requests.filter(Boolean).length, 1);
});

test('the clicked target is preserved when another page changes the Start response target', async () => {
  const p = await page(body => body?.action === 'start'
    ? { ...ready('apporo'), running: false, reachable: false, phase: 'starting', startScheduled: true }
    : { ...ready('paseo'), running: false, reachable: false, phase: 'disabled' });
  await p.node('start').onclick();
  assert.deepEqual(p.requests.at(-1), { action: 'start', target: 'paseo' });
  assert.match(p.node('notice').textContent, /其他操作已變更/);
});

test('returning from the page cache clears an abandoned request and reads status again', async () => {
  let hold = false;
  const p = await page((_body, init) => hold ? new Promise((_, reject) => {
    init.signal.addEventListener('abort', () => reject(Object.assign(new Error('aborted'), { name: 'AbortError' })), { once: true });
  }) : ready('paseo'));
  hold = true; const refresh = p.node('refresh').onclick();
  await p.dispatch('pagehide', { persisted: true }); await refresh;
  hold = false; await p.dispatch('pageshow', { persisted: true });
  assert.equal(p.node('refresh').disabled, false); assert.equal(p.node('start').disabled, false);
  assert.equal(p.node('pair').disabled, false);
});
