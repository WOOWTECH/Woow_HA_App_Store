import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../rootfs/usr/local/share/pi-paseo-ha/app.js', import.meta.url), 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));
const ready = target => ({ installed: true, enabled: true, version: 'candidate', phase: 'ready', selectedTarget: target,
  settings: { target }, configurationPending: false, targetSelectionAvailable: true, running: true, webReady: true, providers: [] });
async function page(handler) {
  const nodes = new Map();
  const node = id => {
    if (!nodes.has(id)) nodes.set(id, { value: id === 'target' ? 'paseo' : '', disabled: false, hidden: false,
      removeAttribute(name) { delete this[name]; }, replaceChildren(...children) { this.children = children; } });
    return nodes.get(id);
  };
  const requests = [];
  vm.runInNewContext(source, { URL, URLSearchParams, location: { search: '' }, confirm: () => true,
    window: { addEventListener() {} },
    document: { getElementById: node, querySelector: selector => ({ content: selector.includes('ingress') ? '/api/hassio_ingress/fixture01234567890123' : 'private-token' }), createElement: () => ({}) },
    fetch: async (url, init) => { const body = init.body ? JSON.parse(init.body) : null; requests.push(body); return { ok: true, json: async () => handler(body) }; },
  });
  await tick();
  return { node, requests };
}
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
  assert.equal(p.node('pair').disabled, true); assert.match(p.node('target-notice').textContent, /停止並重新啟動/);
  await p.node('pair').onclick(); assert.equal(p.requests.at(-1).action, 'save');
  state.configurationPending = false;
  await p.node('refresh').onclick(); assert.equal(p.node('pair').disabled, false);
  assert.equal(p.node('open').href, 'https://smart.apporo.ai');
});
test('pair links display the selected brand and reject another target, another origin and executable input', async () => {
  let paired = { target: 'woowtech', url: 'https://smart.woowtech.io/#offer=private' };
  const p = await page(body => body?.action === 'pair' ? paired : ready('woowtech'));
  await p.node('pair').onclick();
  assert.deepEqual(p.requests.at(-1), { action: 'pair', target: 'woowtech' });
  assert.equal(p.node('pair-link').hidden, false); assert.equal(p.node('pair-link').href, paired.url);
  assert.match(p.node('pair-link').textContent, /Woowtech Smart/);
  for (const value of [{ target: 'apporo', url: 'https://smart.apporo.ai/#offer=private' },
    { target: 'woowtech', url: 'https://smart.apporo.ai/#offer=private' }, { target: 'woowtech', url: 'javascript:alert(1)' },
    { target: 'woowtech', url: 'https://smart.woowtech.io.evil.test/#offer=private' },
    { target: 'woowtech', url: 'https://smart.woowtech.io/#unknown=private' }, { target: 'woowtech', url: 'https://smart.woowtech.io/#offer=bad!' }]) {
    paired = value; await p.node('refresh').onclick(); await p.node('pair').onclick();
    assert.equal(p.node('pair-link').hidden, true); assert.equal(p.node('pair-link').href, undefined);
    assert.match(p.node('notice').textContent, /操作未完成/);
  }
});
test('Paseo pairing uses the current ingress prefix and legacy backend disables only the new target selector', async () => {
  const p = await page(body => body?.action === 'pair' ? { target: 'paseo', url: '/api/hassio_ingress/fixture01234567890123/paseo-web/welcome#offer=private' }
    : { ...ready('paseo'), targetSelectionAvailable: false });
  assert.equal(p.node('target').disabled, true); assert.equal(p.node('pair').disabled, false);
  await p.node('pair').onclick(); assert.equal(p.node('pair-link').hidden, false);
  assert.match(p.node('pair-link').href, /\/paseo-web\/welcome#offer=private$/);
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
