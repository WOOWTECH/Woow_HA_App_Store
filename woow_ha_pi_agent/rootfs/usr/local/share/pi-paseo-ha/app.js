(() => {
  const prefix = document.querySelector('meta[name=ingress-prefix]').content;
  const token = document.querySelector('meta[name=paseo-token]').content;
  const $ = id => document.getElementById(id);
  const embedded = new URLSearchParams(location.search).get('embedded') === '1';
  if (embedded) { $('back').target = '_parent'; $('onboarding').target = '_parent'; }
  window.addEventListener('keydown', event => { if (embedded && event.key === 'Escape') parent.document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); });
  let busy = false;
  async function request(action) {
    if (busy) return;
    busy = true; document.querySelectorAll('button').forEach(node => { node.disabled = true; });
    try {
      const response = await fetch(prefix + '/api/paseo', { method: action ? 'POST' : 'GET', cache: 'no-store', headers: { 'X-Paseo-Token': token, 'Content-Type': 'application/json' }, ...(action ? { body: JSON.stringify({ action }) } : {}) });
      const data = await response.json();
      if (!response.ok) throw Error(data.error?.code || 'REQUEST_FAILED');
      if (action === 'pair') {
        if (typeof data.url !== 'string' || !data.url.startsWith(prefix + '/paseo-web/#') || /[\\\s]/.test(data.url)) throw Error('PAIRING_ORIGIN_INVALID');
        $('pair-link').href = data.url; $('pair-link').hidden = false;
        $('notice').textContent = '連結已產生，請點選「開啟並配對 Paseo」。';
      } else {
        $('notice').textContent = `插件 ${data.version || '未安裝'} · ${data.phase || 'unavailable'} · 網頁 ${data.webReady ? data.webVersion : '準備中'}`;
        $('engines').replaceChildren(...(data.providers || []).map(row => { const card = document.createElement('article'); card.textContent = `${row.provider}：${row.status || 'unknown'}${row.chatVerified ? '（已驗證對話）' : ''}`; return card; }));
        $('onboarding').hidden = !data.onboardingUrl;
        if (data.onboardingUrl) $('onboarding').href = prefix + data.onboardingUrl;
        $('pair-link').hidden = true; $('pair-link').removeAttribute('href');
      }
    } catch (error) { $('notice').textContent = '操作未完成：' + error.message; }
    finally { busy = false; document.querySelectorAll('button').forEach(node => { node.disabled = false; }); }
  }
  $('refresh').onclick = () => request(); $('start').onclick = () => request('start'); $('pair').onclick = () => request('pair');
  $('stop').onclick = () => { if (confirm('停止 Paseo？目前進行中的對話會中斷。')) void request('stop'); };
  void request();
})();
