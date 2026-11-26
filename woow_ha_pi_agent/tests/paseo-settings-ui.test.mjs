import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const read = name => fs.readFileSync(new URL(`../rootfs/usr/local/share/pi-paseo-ha/${name}`, import.meta.url), 'utf8');
const source = read('app.js');
const tick = () => new Promise(resolve => setImmediate(resolve));
// The status the bridge sends: no webReady/webVersion any more (Agent Connect 0.1.23 removed the bundled client).
const ready = target => ({ installed: true, enabled: true, version: 'candidate', phase: 'ready', selectedTarget: target,
  settings: { target }, configurationPending: false, targetSelectionAvailable: true, running: true, providers: [] });
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
  assert.equal(p.node('pair').disabled, true); assert.match(p.node('target-notice').textContent, /停止並重新啟動/);
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
  assert.match(html, /<a id="open" href="https:\/\/app\.paseo\.sh\/" target="_blank" rel="noopener noreferrer">/);
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
