(() => {
  const prefix = location.pathname.replace(/\/omnigent\/?$/, '');
  const token = document.querySelector('meta[name="omnigent-token"]').content;
  const $ = id => document.getElementById(id);
  // The native Settings section embeds this private page. Escape closes the
  // host Settings dialog without adding another navigation path.
  if (new URLSearchParams(location.search).get('embedded') === '1' && window.parent !== window) {
    $('back').target = '_parent';
    document.addEventListener('keydown', event => {
      if (event.key !== 'Escape' || event.defaultPrevented) return;
      event.preventDefault();
      window.parent.document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    });
  }
  const labels = { claude: 'Claude Code', codex: 'Codex', pi: 'Pi Agent' };
  // Issue hints (plugin 0.3.30+) follow this page's language. An older plugin
  // sends only a code and message; the notice then keeps its earlier wording.
  const lang = document.documentElement.lang;
  const locales = [/^zh-(?:hans|cn|sg)\b/i.test(lang) ? 'zh-CN' : /^zh\b/i.test(lang) ? 'zh-TW' : 'en', 'zh-TW', 'en', 'zh-CN'];
  const hint = issue => { const value = locales.map(locale => issue?.hints?.[locale]).find(Boolean); return value ? `${value}（${issue.code}）` : null; };
  let view, busy = false;
  const clearPassword = () => { $('setup').elements.password.value = ''; };
  addEventListener('pagehide', clearPassword);
  document.addEventListener('visibilitychange', () => { if (document.hidden) clearPassword(); });
  const text = (tag, value) => { const node = document.createElement(tag); node.textContent = value; return node; };
  function modelOptions() {
    const selected = $('model').value;
    $('model').replaceChildren(new Option('預設模型', ''));
    for (const model of view?.engines.find(item => item.key === $('engine').value)?.models || []) $('model').add(new Option(model.label, model.id));
    if ([...$('model').options].some(option => option.value === selected)) $('model').value = selected;
  }
  function render(result, action) {
    view = result;
    const selected = $('engine').value;
    $('engine').replaceChildren(new Option('全部已安裝引擎', ''));
    $('engines').replaceChildren();
    for (const engine of result.engines || []) {
      const card = document.createElement('article');
      card.append(text('strong', labels[engine.key]), text('p', engine.version || '未安裝'),
        text('p', !engine.installed ? '不會自動安裝此引擎' : engine.verified && engine.ready ? '實際對話已通過' : '等待供應商授權或對話驗證'),
        text('small', `${engine.models.length} 個模型${engine.reason ? ` · ${engine.reason}` : ''}`));
      $('engines').append(card);
      if (engine.installed) $('engine').add(new Option(labels[engine.key], engine.key));
    }
    if ([...$('engine').options].some(option => option.value === selected)) $('engine').value = selected;
    modelOptions();
    $('connection').textContent = `${result.server || '尚未設定網址'} · ${result.host.connected ? '主機在線' : '主機離線'} · ${result.phase}`;
    $('open').hidden = !result.server;
    if (result.server) $('open').href = result.server;
    // Resume needs this host's recorded login; without it only the form helps.
    const canResume = result.active && result.loginConfirmed && (!result.host.connected || result.phase === 'error');
    $('resume').hidden = !canResume;
    const issue = result.issue, guidance = hint(issue);
    $('notice').textContent = !result.active ? '插件已停用或移除。請在 Pi Web Plugins 重新啟用或安裝。'
      : result.operation?.ok === false ? `操作尚未完成：${guidance && issue.code === result.operation.code ? guidance : result.operation.code || '請查看引擎狀態'}`
      : action === 'resume' && result.operation?.ok ? '已用原登入重新連線此主機。'
      : result.phase === 'ready' ? '全部已安裝引擎的實際對話已通過。'
      : guidance ? guidance
      // Never report a finished login while the plugin reports an error.
      : result.phase === 'error' ? (issue?.message ? `${issue.message}（${issue.code}）`
        : `連線發生問題${issue ? `（${issue.code}）` : ''}。${canResume ? '請按「重新連線」' : '請重新整理狀態'}；仍無法恢復時，請重新登入。`)
      : result.loginConfirmed ? 'Server 登入完成；請確認各引擎授權並驗證對話。' : '請輸入 Server URL、帳號及密碼，開始連線設定。';
  }
  async function request(body) {
    if (busy) return;
    busy = true;
    document.querySelectorAll('button,input,select').forEach(node => { node.disabled = true; });
    if (body) $('notice').textContent = body.action === 'verify' ? '正在驗證，可能需要數分鐘…'
      : body.action === 'resume' ? '正在以原登入重新連線，最多約需 90 秒…' : '正在處理…';
    try {
      const response = await fetch(`${prefix}/api/omnigent`, { method: body ? 'POST' : 'GET', cache: 'no-store',
        headers: { 'Content-Type': 'application/json', 'X-Omnigent-Token': token }, ...(body ? { body: JSON.stringify(body) } : {}) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error?.code || 'OMNIGENT_FAILED');
      render(result, body?.action);
    } catch (error) { $('notice').textContent = `無法完成操作（${/^[A-Z_0-9]+$/.test(error.message) ? error.message : '連線失敗'}）。請重新整理後重試。`; }
    finally {
      clearPassword(); busy = false;
      document.querySelectorAll('button,input,select').forEach(node => { node.disabled = !view?.active && node.id !== 'refresh'; });
    }
  }
  $('setup').addEventListener('submit', event => {
    event.preventDefault();
    const form = $('setup').elements;
    const body = { action: 'connect', server: form.server.value.trim(), username: form.username.value.trim(), password: form.password.value };
    clearPassword(); void request(body);
  });
  $('verify').addEventListener('submit', event => { event.preventDefault(); void request({ action: 'verify',
    ...($('engine').value ? { engine: $('engine').value } : {}), ...($('model').value ? { model: $('model').value } : {}) }); });
  $('engine').addEventListener('change', () => { $('model').value = ''; modelOptions(); });
  $('refresh').addEventListener('click', () => void request());
  $('resume').addEventListener('click', () => void request({ action: 'resume' }));
  $('disconnect').addEventListener('click', () => { if (confirm('取消此主機的 Omnigent 登入與連線？其他容器不受影響。')) void request({ action: 'disconnect', confirm: true }); });
  void request();
})();
