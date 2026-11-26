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
  let busyAction = null, startAttempt = null, pollTimer = null, controller = null, generation = 0;
  const labels = { installing: '準備服務中', starting: '啟動中', running: '執行中', ready: '執行中',
    disabled: '已停止', stopped: '已停止', restart_required: '需要重新啟動', error: '服務發生錯誤', unavailable: '套件未啟用' };
  const serviceReady = () => state?.running && state?.reachable && !state?.configurationPending
    && ['running', 'ready'].includes(state?.phase);
  const activeLabel = () => targets[state?.activeTarget]?.label || '尚未啟動';
  function pendingMessage() {
    return `目前仍執行 ${activeLabel()}；已儲存 ${targets[savedTarget].label}。請先按「停止服務」，確認停止後再按「啟動服務」，以套用標的。現有對話不會因重複按啟動而被中斷。`;
  }
  function clearPair() { $('pair-link').hidden = true; $('pair-link').removeAttribute('href'); }
  function updateControls() {
    const dirty = $('target').value !== savedTarget;
    const unavailable = !state?.enabled;
    const pending = state?.configurationPending === true;
    $('target').disabled = busy || unavailable || !state?.targetSelectionAvailable;
    $('save').disabled = busy || unavailable || !state?.targetSelectionAvailable || !dirty;
    $('refresh').disabled = busy;
    $('start').disabled = busy || unavailable || dirty || Boolean(startAttempt);
    $('start').textContent = busyAction === 'start' || startAttempt ? '啟動中…' : '啟動服務';
    $('stop').textContent = busyAction === 'stop' ? '停止中…' : '停止服務';
    $('stop').disabled = busy || unavailable;
    $('pair').disabled = busy || unavailable || dirty || pending || !serviceReady() || Boolean(startAttempt);
    $('open').hidden = unavailable || dirty || pending || !serviceReady() || Boolean(startAttempt);
    $('open').href = targets[savedTarget].origin + '/';
    $('open').textContent = `開啟 ${targets[savedTarget].label} 對話介面`;
    $('target-notice').textContent = dirty ? '尚未儲存標的，請先儲存，再啟動服務或配對。'
      : pending ? pendingMessage()
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
  function schedulePoll() {
    clearTimeout(pollTimer); pollTimer = null;
    if (startAttempt) pollTimer = setTimeout(() => { void request(undefined, {}, true); }, 3000);
  }
  function renderStatus(action, data) {
    if (startAttempt && savedTarget !== startAttempt.target) {
      startAttempt = null;
      $('notice').textContent = '其他操作已變更連線標的。請確認目前設定；本頁不會覆寫或重新啟動服務。';
    } else if (state.configurationPending && state.running && !(startAttempt && ['installing', 'starting'].includes(state.phase))) {
      startAttempt = null; $('notice').textContent = pendingMessage();
    } else if (state.phase === 'restart_required') {
      startAttempt = null; $('notice').textContent = '服務需要重新啟動。請先按「停止服務」，確認停止後再按「啟動服務」。';
    } else if (state.phase === 'error' && !data.startScheduled) {
      startAttempt = null; $('notice').textContent = '服務啟動未完成。請重新整理狀態並查看外掛紀錄；尚未確認連線成功。';
    } else if (serviceReady()) {
      startAttempt = null;
      $('notice').textContent = `服務已啟動 · ${activeLabel()} · 插件 ${data.version || '未安裝'}`;
    } else if (startAttempt && Date.now() >= startAttempt.deadline) {
      startAttempt = null;
      $('notice').textContent = '尚未確認啟動完成。服務可能仍在準備中，請重新整理狀態；本頁不會自動重試啟動或停止服務。';
    } else if (startAttempt) {
      $('notice').textContent = `正在啟動 ${targets[startAttempt.target].label}，會自動更新狀態…`;
    } else {
      $('notice').textContent = `插件 ${data.version || '未安裝'} · ${labels[data.phase] || data.phase || '尚未啟動'} · 已儲存 ${targets[savedTarget].label}`;
    }
  }
  async function request(action, payload = {}, background = false) {
    if (busy || (background && controller)) { if (background) schedulePoll(); return; }
    if (action === 'pair' && $('pair').disabled) return;
    if (action === 'start' && $('target').value !== savedTarget) {
      $('notice').textContent = '尚未儲存標的，請先按「儲存標的」再啟動服務。'; return;
    }
    if (action === 'start' && state?.configurationPending && state?.running) {
      $('notice').textContent = '尚未套用新的標的。' + pendingMessage(); return;
    }
    if (action === 'stop' || action === 'save') startAttempt = null;
    // Bind progress to the clicked target, before awaiting the bridge. Another
    // settings page can save a different target while lifecycle() is pending.
    if (action === 'start') startAttempt = { target: savedTarget, deadline: Date.now() + 120000 };
    controller?.abort();
    const current = ++generation, abort = new AbortController(); controller = abort;
    const timeout = setTimeout(() => abort.abort(), action === 'stop' ? 120000 : 30000);
    busy = !background; busyAction = background ? null : action || 'refresh';
    if (!background) {
      clearPair();
      $('notice').textContent = action === 'start' ? `正在啟動 ${targets[savedTarget].label}…`
        : action === 'stop' ? '正在停止服務，請稍候…'
        : action === 'save' ? '正在儲存標的…' : action === 'pair' ? '正在產生配對連結…' : '正在讀取服務狀態…';
    }
    updateControls();
    const requestedTarget = payload.target;
    try {
      const response = await fetch(prefix + '/api/paseo', { method: action ? 'POST' : 'GET', cache: 'no-store', signal: abort.signal, headers: { 'X-Paseo-Token': token, 'Content-Type': 'application/json' }, ...(action ? { body: JSON.stringify({ action, ...payload }) } : {}) });
      const data = await response.json();
      if (current !== generation) return;
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
        renderStatus(action, data);
        $('engines').replaceChildren(...(data.providers || []).map(row => { const card = document.createElement('article'); card.textContent = `${row.provider}：${row.status || 'unknown'}${row.chatVerified ? '（已驗證對話）' : ''}`; return card; }));
      }
    } catch (error) {
      if (current !== generation) return;
      state = null; startAttempt = null; clearPair();
      $('notice').textContent = error.name === 'AbortError'
        ? '等待回應逾時，尚未確認操作結果。請重新整理狀態；本頁不會重送啟動或停止指令。'
        : error.message === 'UNTRUSTED_REQUEST' ? '設定頁已過期，請從 Home Assistant 重新開啟 Agent Connect。'
        : error.message === 'CONFIGURATION_PENDING' ? '操作未完成：連線標的已變更或尚未套用。請重新整理狀態，確認標的後停止再啟動服務。'
        : ['STATE_BUSY', 'RUNTIME_BUSY', 'LOCK_BUSY'].includes(error.message) ? '另有服務操作正在處理。本次操作未完成，請稍候重新整理狀態後再試。'
        : '操作未完成：' + error.message + '。請重新整理狀態後再試。';
    } finally {
      clearTimeout(timeout);
      if (current === generation) { controller = null; busy = false; busyAction = null; updateControls(); schedulePoll(); }
    }
  }
  $('target').onchange = () => { draftDirty = true; clearPair(); updateControls(); };
  $('save').onclick = () => request('save', { target: $('target').value });
  $('refresh').onclick = () => request(); $('start').onclick = () => request('start', { target: savedTarget });
  $('pair').onclick = () => request('pair', { target: savedTarget });
  $('stop').onclick = () => { if (confirm('停止 Agent Connect 服務？目前進行中的對話會中斷。')) return request('stop'); };
  function leavePage() {
    ++generation; startAttempt = null; clearTimeout(pollTimer);
    controller?.abort(); controller = null; busy = false; busyAction = null;
    state = null; clearPair(); updateControls();
  }
  window.addEventListener('pagehide', leavePage);
  window.addEventListener('pageshow', event => { if (event.persisted) { leavePage(); void request(); } });
  updateControls(); void request();
})();
