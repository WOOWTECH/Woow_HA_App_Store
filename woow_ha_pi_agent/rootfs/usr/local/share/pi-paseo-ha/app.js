(() => {
  const prefix = document.querySelector('meta[name=ingress-prefix]').content;
  const token = document.querySelector('meta[name=paseo-token]').content;
  const $ = id => document.getElementById(id);
  // Every target is an official site opened in a new tab; this page serves no copy of one.
  const targets = {
    paseo: { label: 'Paseo', origin: 'https://app.paseo.sh' },
    woowtech: { label: 'Woowtech Smart', origin: 'https://smart.woowtech.io' },
    apporo: { label: 'Apporo Smart', origin: 'https://smart.apporo.ai' },
  };
  const knownTarget = value => Object.hasOwn(targets, value);
  const embedded = new URLSearchParams(location.search).get('embedded') === '1';
  if (embedded) $('back').target = '_parent';
  window.addEventListener('keydown', event => { if (embedded && event.key === 'Escape') parent.document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); });
  let busy = false, savedTarget = 'paseo', draftDirty = false, state = null;
  function clearPair() { $('pair-link').hidden = true; $('pair-link').removeAttribute('href'); }
  function updateControls() {
    const dirty = $('target').value !== savedTarget;
    const unavailable = !state?.enabled;
    const pending = state?.configurationPending === true;
    $('target').disabled = busy || unavailable || !state?.targetSelectionAvailable;
    $('save').disabled = busy || unavailable || !state?.targetSelectionAvailable || !dirty;
    $('refresh').disabled = busy;
    $('start').disabled = busy || unavailable;
    $('stop').disabled = busy || unavailable;
    $('pair').disabled = busy || unavailable || dirty || pending || !state?.running;
    $('open').hidden = unavailable || dirty || pending;
    $('open').href = targets[savedTarget].origin + '/';
    $('open').textContent = `開啟 ${targets[savedTarget].label} 對話介面`;
    $('target-notice').textContent = dirty ? '尚未儲存標的，請先儲存再配對。'
      : pending ? '標的已儲存。請在方便時停止並重新啟動服務，再產生配對連結。'
      : state && !state.targetSelectionAvailable ? '目前套件支援 Paseo；更新 Agent Connect 套件後可切換標的。' : '';
  }
  // Same rule as the bridge: exactly `<target origin>/#offer=<base64url>`, nothing else.
  function pairingUrl(value, target) {
    if (typeof value !== 'string' || /[\\\x00-\x20\x7f]/.test(value)) throw Error('PAIRING_ORIGIN_INVALID');
    let url;
    try { url = new URL(value); } catch { throw Error('PAIRING_ORIGIN_INVALID'); }
    const origin = targets[target].origin;
    if (url.origin !== origin || url.username || url.password || url.pathname !== '/' || url.search || !/^#offer=[A-Za-z0-9_-]+$/.test(url.hash) || !value.startsWith(origin + '/#')) throw Error('PAIRING_ORIGIN_INVALID');
    return value;
  }
  async function request(action, payload = {}) {
    if (busy) return;
    if (action === 'pair' && $('pair').disabled) return;
    busy = true; clearPair(); updateControls();
    const requestedTarget = payload.target;
    try {
      const response = await fetch(prefix + '/api/paseo', { method: action ? 'POST' : 'GET', cache: 'no-store', headers: { 'X-Paseo-Token': token, 'Content-Type': 'application/json' }, ...(action ? { body: JSON.stringify({ action, ...payload }) } : {}) });
      const data = await response.json();
      if (!response.ok) throw Error(data.error?.code || 'REQUEST_FAILED');
      if (action === 'pair') {
        if (data.target !== requestedTarget || savedTarget !== requestedTarget || $('target').value !== requestedTarget || state?.configurationPending) throw Error('CONFIGURATION_PENDING');
        $('pair-link').href = pairingUrl(data.url, requestedTarget); $('pair-link').hidden = false;
        $('pair-link').textContent = `開啟並配對 ${targets[requestedTarget].label}`;
        $('notice').textContent = '連結已產生，請點選下方連結完成配對。';
      } else {
        const target = data.settings?.target ?? data.selectedTarget ?? 'paseo';
        if (!knownTarget(target)) throw Error('INVALID_TARGET');
        if (action === 'save' && $('target').value === requestedTarget) draftDirty = false;
        savedTarget = target;
        if (!draftDirty) $('target').value = target;
        state = data;
        $('notice').textContent = `插件 ${data.version || '未安裝'} · ${data.phase || 'unavailable'} · ${targets[target].label}`;
        $('engines').replaceChildren(...(data.providers || []).map(row => { const card = document.createElement('article'); card.textContent = `${row.provider}：${row.status || 'unknown'}${row.chatVerified ? '（已驗證對話）' : ''}`; return card; }));
      }
    } catch (error) { state = null; clearPair(); $('notice').textContent = '操作未完成：' + error.message; }
    finally { busy = false; updateControls(); }
  }
  $('target').onchange = () => { draftDirty = true; clearPair(); updateControls(); };
  $('save').onclick = () => request('save', { target: $('target').value });
  $('refresh').onclick = () => request(); $('start').onclick = () => request('start');
  $('pair').onclick = () => request('pair', { target: savedTarget });
  $('stop').onclick = () => { if (confirm('停止 Agent Connect 服務？目前進行中的對話會中斷。')) return request('stop'); };
  updateControls(); void request();
})();
