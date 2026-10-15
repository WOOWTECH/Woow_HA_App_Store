import { AdminApi, ApiError } from './api.js';
import { products, UiError, explicitUrl, backendPayload, granularPolicy, toolRows, policyPayload, policyFingerprint, effectiveGrant, clientExample, claudeConnectorUrl } from './contracts.js';
import './styles.css';

const root = document.querySelector('#app');
let api, state, busy = false, revealed = null, revealTimer, dialog, revealEpoch = 0;
const routes = { overview: '總覽', backend: '後端連線', tools: '工具權限', access: '連線與權杖' };
const icons = { overview: 'view-grid', backend: 'server-network', tools: 'shield-check', access: 'tune-variant' };
function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else if (key === 'class') node.className = value;
    else if (typeof value === 'boolean') { if (value) node.setAttribute(key, ''); }
    else if (value !== null && value !== undefined) node.setAttribute(key, value);
  }
  node.append(...children.filter(v => v !== null && v !== undefined));
  return node;
}
const icon = name => el('span', { class: 'icon-tile', 'aria-hidden': 'true' }, el('i', { class: `mdi mdi-${name}` }));
const p = text => el('p', {}, text);
const button = (text, action, attrs = {}) => el('button', { type: 'button', onclick: action, ...attrs }, text);
const chip = text => el('span', { class: 'chip' }, text);
const card = (title, ...children) => el('section', { class: 'card' }, el('h2', {}, title), ...children);
function notice(text, error = false) {
  const box = document.querySelector('#notice');
  if (box) { box.className = `notice ${error ? 'error' : ''}`; box.replaceChildren(text); box.hidden = false; box.focus(); }
}
function route() {
  const path = location.pathname.slice(api.mount.length).replace(/^\/+|\/+$/g, '');
  return Object.hasOwn(routes, path) ? path : 'overview';
}
function navigate(name) {
  hideToken();
  history.pushState(null, '', `${api.mount}/${name}`);
  render();
  document.querySelector('h1')?.focus();
}
function hideToken() {
  revealEpoch++;
  revealed = null;
  clearTimeout(revealTimer);
  for (const id of ['#token-secret', '#claude-secret']) {
    document.querySelector(id)?.replaceChildren();
    document.querySelector(id)?.setAttribute('hidden', '');
  }
}
function fail(error) {
  hideToken();
  if (error instanceof ApiError && [401, 403].includes(error.status)) {
    state = null;
    renderDenied(error.message);
  } else notice(error instanceof UiError ? error.message : '操作未完成。請重新整理狀態後再試。', true);
}
async function task(action) {
  if (busy) return;
  busy = true;
  root.setAttribute('aria-busy', 'true');
  const controls = [...root.querySelectorAll('button:not(:disabled), input:not(:disabled), select:not(:disabled)')];
  controls.forEach(node => node.disabled = true);
  try { await action(); } catch (error) { fail(error); }
  finally { busy = false; root.removeAttribute('aria-busy'); controls.forEach(node => node.disabled = false); }
}
async function reload(message) {
  hideToken();
  state = await api.bootstrap();
  render();
  if (message) notice(message);
}
function confirmAction(title, description, label = '確認繼續') {
  return new Promise(resolve => {
    const previous = document.activeElement;
    dialog = el('dialog', { 'aria-labelledby': 'confirm-title', 'aria-describedby': 'confirm-description' },
      el('h2', { id: 'confirm-title' }, title), el('p', { id: 'confirm-description' }, description));
    const finish = answer => { dialog.close(); dialog.remove(); dialog = null; previous?.focus(); resolve(answer); };
    dialog.append(el('div', { class: 'actions' }, button('取消', () => finish(false), { autofocus: true }), button(label, () => finish(true), { class: 'primary' })));
    dialog.addEventListener('cancel', event => { event.preventDefault(); finish(false); });
    document.body.append(dialog);
    dialog.showModal();
  });
}
function renderDenied(message) {
  root.replaceChildren(el('main', { class: 'blocked' }, icon('shield-account'), el('h1', {}, '管理介面無法使用'), p(message), p('此頁只接受 Home Assistant 的伺服器端管理員授權，不提供另一組登入密碼。'), button('重新檢查權限', () => task(() => reload()))));
}
const statusText = value => ({ alive: '管理服務可用', state_error: '設定儲存異常', running: '執行中', stopped: '已停止', starting: '啟動中', backoff: '退避等待', failed: '啟動失敗', not_started: '尚未啟動', unconfigured: '尚未設定', unreachable: '無法連線', reachable: '可連線', unknown: '未知' }[value] ?? '未知狀態');
function overview() {
  const health = state.health ?? {};
  const child = health.child ?? {};
  return el('div', { class: 'stack' },
    el('div', { class: 'health-grid' },
      card('管理服務', icon('monitor-dashboard'), el('h3', {}, statusText(health.management)), p('管理程序與設定儲存的狀態。')),
      card('MCP 子行程', icon('server-network'), el('h3', {}, statusText(child.state)), p(child.transport_ready === true ? '協定探測：已就緒' : '協定探測：尚未就緒'), p('不等同後端可連線。')),
      card('後端服務', icon('signal'), el('h3', {}, statusText(health.backend)), p('來自伺服器的獨立唯讀健康探測。'))),
    card('從這裡開始', p('讓你的 MCP 用戶端連上需要的服務。先設定後端，再確認工具權限，最後複製手動連線範例。'),
      el('div', { class: 'steps' }, ...[['01', '設定後端', '由此介面管理 URL 與憑證。', 'backend'], ['02', '檢查工具', '預設唯讀，逐項確認寫入授權。', 'tools'], ['03', '連接用戶端', '明確指定 MCP 端點與 Bearer。', 'access']].map(([n, title, text, target]) => el('div', {}, el('span', { class: 'step-number' }, n), el('h3', {}, title), p(text), button('前往設定', () => navigate(target)))))),
    card('目前設定', el('dl', { class: 'summary' }, el('dt', {}, '產品'), el('dd', {}, products[state.product].name), el('dt', {}, '後端連線'), el('dd', {}, state.connection_configured ? '已設定（憑證不顯示）' : '尚未設定'), el('dt', {}, 'MCP 端點'), el('dd', {}, safeEndpoint() ?? '尚未設定，無法產生可直接使用的連線'), el('dt', {}, '權杖'), el('dd', {}, state.token_active ? '有效' : '已撤銷 / 未啟用')),
      p('狀態來自最近一次管理 API 回應，不代表真實用戶端驗收。後端離線不應觸發容器持續重新啟動。')));
}
function backend() {
  const form = el('form', { autocomplete: 'off' });
  const action = el('select', { id: 'connection-action', name: 'action' },
    el('option', { value: 'preserve' }, '保留現有設定（不變更）'),
    el('option', { value: 'replace' }, '提供新值，取代整組設定'),
    el('option', { value: 'clear' }, '清除整組後端設定'));
  const fields = el('fieldset', { disabled: true, hidden: true }, el('legend', {}, '新的後端連線'));
  for (const [key, label, type] of products[state.product].fields) {
    const input = type === 'mode' ? el('select', { id: key, name: key }, el('option', { value: 'read' }, 'read — 唯讀'), el('option', { value: 'module' }, 'module — 既有 MCP 模組')) : el('input', {
      id: key, name: key, type: type.includes('secret') ? 'password' : type.includes('url') ? 'url' : 'text',
      autocomplete: type.includes('secret') ? 'new-password' : 'off', spellcheck: 'false', autocapitalize: 'none',
      maxlength: type.includes('secret') ? '8192' : type.includes('url') ? '2048' : '256',
      required: !type.startsWith('optional'), 'aria-describedby': 'connection-help',
    });
    fields.append(el('div', { class: 'field' }, el('label', { for: key }, label), input));
  }
  action.addEventListener('change', () => {
    fields.hidden = action.value !== 'replace'; fields.disabled = fields.hidden;
    if (fields.hidden) fields.querySelectorAll('input').forEach(input => input.value = '');
  });
  form.append(el('div', { class: 'field' }, el('label', { for: 'connection-action' }, '這次要如何處理設定？'), action),
    p('保留不會送出變更。此 API 不支援只保留個別憑證：取代時請重新輸入所有必要欄位，空白不代表保留。'),
    fields, el('p', { id: 'connection-help', class: 'hint' }, state.product === 'odoo-manage' ? 'module 模式要求後端已安裝 MCP module；此介面不會安裝模組或變更 Odoo。read 模式不可保存寫入授權。' : state.product === 'hermes' ? 'Dashboard 為選填；URL、使用者、密碼需整組提供。全部留空會移除 Dashboard 設定。' : state.product === 'opendesign' ? 'OpenDesign 只需要 URL；不要求後端 token。' : 'URL 不可含帳密、查詢參數或片段。新憑證只用於這次提交，不儲存在瀏覽器。'),
    el('button', { type: 'submit', class: 'primary' }, '儲存後端設定'));
  form.addEventListener('submit', async event => {
    event.preventDefault();
    let payload;
    try { payload = backendPayload(state.product, action.value, Object.fromEntries(new FormData(form))); } catch (error) { fail(error); return; }
    if (!payload) { notice('已保留現有設定，未送出變更。'); return; }
    if (!await confirmAction(action.value === 'clear' ? '清除後端連線？' : '取代後端連線？', '此操作可能重新啟動或停止 MCP 子行程，現有連線可能中斷。舊憑證不會在介面中顯示。', '確認儲存')) { payload = null; return; }
    await task(async () => {
      try { await api.mutate('backend', payload); }
      finally { payload = null; fields.querySelectorAll('input[type=password]').forEach(input => input.value = ''); }
      await reload('伺服器已確認儲存。請等待健康探測更新，這不代表後端已連線成功。');
    });
  });
  return card('後端連線設定', chip(state.connection_configured ? '已設定 · 憑證隱藏' : '尚未設定'), p('URL 與憑證由管理介面擁有，不由 HA Add-on options 覆寫。'), form);
}
function tools() {
  const granular = granularPolicy(state);
  const form = el('form');
  const rows = toolRows(state);
  form.append(p('停用與授權必須由伺服器逐次檢查 tools/call。此頁的控制項不是安全邊界，也不會替你執行工具。'));
  if (!granular) form.append(el('div', { class: 'notice' }, '工具授權版本不相容，無法儲存。請重新整理；不會以舊版全域開關取代精確授權。'));
  if (state.writes_enabled) form.append(p('注意：伺服器回報舊版全域寫入目前開啟。此頁不將它標示為唯讀。'));
  if (!rows.length) form.append(p('伺服器未提供工具清單，無法編輯權限。'));
  for (const row of rows) {
    const disabled = el('input', { type: 'checkbox', name: 'disabled', value: row.name, checked: state.disabled?.includes(row.name) });
    const controls = el('div', { class: 'tool-controls' }, el('label', { class: 'check' }, disabled, '停用此工具'));
    const operations = row.operations.length ? row.operations : row.write ? [null] : [];
    for (const operation of operations) {
      const value = JSON.stringify({ tool: row.name, operation });
      controls.append(el('label', { class: 'check' }, el('input', { type: 'checkbox', name: 'grant', value,
        checked: granular && effectiveGrant(state, row, operation),
        disabled: !granular || !row.classified || disabled.checked,
      }), operation === null ? '明確允許此工具寫入' : `允許寫入操作：${operation}`));
    }
    disabled.addEventListener('change', () => controls.querySelectorAll('[name=grant]').forEach(input => {
      input.disabled = disabled.checked || !granular || !row.classified;
      if (disabled.checked) input.checked = false;
    }));
    form.append(el('article', { class: 'tool-row' }, el('div', {}, el('h3', { class: 'tool-name' }, row.name), chip(!row.classified ? '分類未知 · 不提供授權' : operations.length ? '含寫入操作' : '唯讀')), controls));
  }
  form.append(el('button', { type: 'submit', class: 'primary', disabled: !rows.length || !granular }, '儲存工具權限'));
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const data = new FormData(form);
    try { policyPayload(state, data.getAll('disabled'), data.getAll('grant').map(v => JSON.parse(v))); } catch (error) { fail(error); return; }
    if (!await confirmAction('套用工具權限？', '寫入可能變更後端資料。只授權你確實需要的工具或操作；伺服器仍必須強制檢查每次呼叫。', '確認套用')) return;
    const expectedPolicy = policyFingerprint(state);
    await task(async () => {
      await api.mutate('policy', fresh => {
        if (policyFingerprint(fresh) !== expectedPolicy) throw new UiError('工具授權版本已變更。請重新整理後再試。');
        return policyPayload(fresh, data.getAll('disabled'), data.getAll('grant').map(v => JSON.parse(v)));
      });
      await reload('伺服器已確認儲存工具權限。此頁未執行任何工具。');
    });
  });
  return card('工具與寫入授權', chip(`${rows.length} 個伺服器提供的工具`), form);
}
function safeEndpoint() { try { return state.endpoint ? explicitUrl(state.endpoint, true) : null; } catch { return null; } }
async function copy(text) {
  try { await navigator.clipboard.writeText(text); notice('已複製。若包含權杖，請在使用後清除剪貼簿。'); }
  catch { notice('瀏覽器未允許剪貼簿。請手動選取並複製；未自動轉往其他服務。', true); }
}
async function tokenAction(action) {
  const descriptions = {
    reveal: ['顯示目前權杖？', '權杖將在此頁短暫顯示 60 秒，切換頁面或離開視窗即隱藏。請避免螢幕分享。'],
    claude: ['顯示 Claude.ai 連線網址？', '這個網址含有真實權杖，等同密碼：只貼進 Claude.ai 的自訂連接器設定，不要分享、截圖或貼到聊天。網址將短暫顯示 60 秒，切換頁面或離開視窗即隱藏。'],
    rotate: ['重新產生權杖？', '舊權杖立即失效，所有用戶端都需更新。已送出的後端工作不會因此復原。新權杖僅短暫顯示。'],
    revoke: ['撤銷權杖？', '用戶端將無法使用此權杖連線。已送出的工作不會回復；需重新產生權杖才能恢復存取。'],
  };
  hideToken();
  if (!await confirmAction(...descriptions[action], action === 'revoke' ? '確認撤銷' : '確認繼續')) return;
  const epoch = revealEpoch;
  await task(async () => {
    const result = await api.mutate(`token/${action === 'claude' ? 'reveal' : action}`); // same CSRF reveal as 顯示權杖
    if (action === 'revoke') { await reload('權杖已撤銷。舊權杖不可再用於新的授權請求。'); return; }
    state = await api.bootstrap();
    render();
    if (!result?.token) { notice('目前沒有有效權杖。請確認伺服器狀態。', true); return; }
    if (typeof result.token !== 'string' || !/^[A-Za-z0-9_-]{43}$/.test(result.token)) throw new UiError('權杖回應格式不符，未顯示。');
    if (epoch !== revealEpoch || document.hidden) { notice('操作已完成，但頁面曾離開焦點，權杖未顯示。需要時請重新要求顯示。'); return; }
    if (action === 'claude') {
      const url = claudeConnectorUrl(safeEndpoint(), result.token);
      revealed = url;
      const area = document.querySelector('#claude-secret');
      area.hidden = false;
      area.replaceChildren(p('60 秒後自動隱藏；剪貼簿不會自動清除。網址外洩時請按「重新產生」，舊網址立即失效。'), el('code', { class: 'secret' }, url), el('div', { class: 'actions' }, button('複製 Claude.ai 連線網址', () => revealed && copy(revealed)), button('立即隱藏', hideToken)));
      revealTimer = setTimeout(hideToken, 60000);
      return;
    }
    revealed = result.token;
    const area = document.querySelector('#token-secret');
    area.hidden = false;
    area.replaceChildren(p('60 秒後自動隱藏；剪貼簿不會自動清除。'), el('code', { class: 'secret' }, revealed), el('div', { class: 'actions' }, button('複製權杖', () => revealed && copy(revealed)), button('複製含權杖範例', async () => {
      if (await confirmAction('複製含權杖範例？', '這份範例會包含真實權杖。不要貼到聊天、Git 或公開文件。') && revealed) await copy(clientExample(safeEndpoint(), revealed));
    }), button('立即隱藏', hideToken)));
    revealTimer = setTimeout(hideToken, 60000);
  });
}
function access() {
  const endpoint = safeEndpoint();
  const input = el('input', { id: 'endpoint', name: 'endpoint', type: 'url', value: endpoint ?? '', placeholder: 'https://YOUR-MCP-HOST:PORT/mcp', autocomplete: 'off', required: true, 'aria-describedby': 'endpoint-help' });
  const form = el('form', {}, el('div', { class: 'field' }, el('label', { for: 'endpoint' }, 'MCP 用戶端端點'), input), el('p', { id: 'endpoint-help', class: 'hint' }, '明確填寫用戶端可到達的 /mcp URL，不是 Ingress 網址。不會由此頁的網域推測；這裡不要放權杖（Claude.ai 用的含權杖網址由下方另外產生）。'), el('div', { class: 'actions' }, el('button', { type: 'submit', class: 'primary' }, '儲存端點'), button('清除端點', async () => {
    if (await confirmAction('清除 MCP 端點？', '只清除用戶端連線範例的端點設定，不會撤銷權杖。')) await task(async () => { await api.mutate('endpoint', { endpoint: null }); await reload('已清除端點。'); });
  })));
  form.addEventListener('submit', event => {
    event.preventDefault();
    let value;
    try { value = explicitUrl(input.value, true); } catch (error) { fail(error); return; }
    task(async () => { await api.mutate('endpoint', { endpoint: value }); await reload('MCP 端點已儲存。這不代表網路可達性已驗證。'); });
  });
  return el('div', { class: 'stack' }, card('明確設定你的連線端點', chip(endpoint ? '已設定端點' : '尚未設定'), form),
    card('Add-on 權杖', chip(state.token_active ? '有效 · 預設隱藏' : '已撤銷 / 未啟用'), p('每個 Add-on 使用一把獨立 Bearer 權杖。權杖不是 HA 管理員密碼，也不會授予管理介面權限。'), el('div', { class: 'actions' }, button('顯示權杖', () => tokenAction('reveal'), { disabled: !state.token_active }), button('重新產生', () => tokenAction('rotate')), button('撤銷權杖', () => tokenAction('revoke'), { disabled: !state.token_active })), el('div', { id: 'token-secret', class: 'secret-box', hidden: true, 'aria-live': 'polite' })),
    card('Claude.ai 自訂連接器', chip(endpoint && state.token_active ? '可產生 · 預設隱藏' : '尚無法產生'),
      p('Claude.ai 網頁版的自訂連接器無法帶 Authorization header，改用含權杖的專屬網址：在 Claude.ai 新增自訂連接器時貼進伺服器網址欄位，OAuth 進階設定留空。Claude.ai 從網際網路連線，上方端點必須是它連得到的 HTTPS 網址。'),
      p('這個網址等同密碼：任何拿到網址的人都能以本 Add-on 的權限呼叫工具。只貼進 Claude.ai，不要分享、截圖或貼到聊天、Git；外洩或不再使用時請按上方「重新產生」或「撤銷權杖」，舊網址立即失效。'),
      endpoint ? null : p('尚未設定 MCP 用戶端端點：請先在上方填寫 Claude.ai 可從網際網路連到的 https://…/mcp 網址並儲存，才能產生連線網址。'),
      endpoint && !state.token_active ? p('權杖已撤銷或未啟用：請先按「重新產生」。') : null,
      el('div', { class: 'actions' }, button('顯示 Claude.ai 連線網址', () => tokenAction('claude'), { disabled: !endpoint || !state.token_active })),
      el('div', { id: 'claude-secret', class: 'secret-box', hidden: true, 'aria-live': 'polite' })),
    card('手動加入 MCP 用戶端', p('適用支援 Streamable HTTP 的用戶端；欄位名稱依用戶端而異。先填端點，再於用戶端安全地填入 Bearer。未驗證所有用戶端相容性。'),
      endpoint ? null : p('以下端點只是佔位文字，不能直接連線。'), el('pre', { tabindex: '0', 'aria-label': '不含真實權杖的連線範例' }, el('code', {}, clientExample(endpoint))), button('複製佔位範例', () => copy(clientExample(endpoint))), p('一般複製永遠使用 <YOUR_ADDON_TOKEN> 佔位文字，不含真實權杖。建議跨主機連線使用 HTTPS。')));
}
function render() {
  const current = route();
  root.replaceChildren(el('a', { href: '#main', class: 'skip' }, '跳至主要內容'),
    el('header', { class: 'topbar' }, el('div', { class: 'brand-caption' }, icon('home-automation'), el('div', {}, el('strong', {}, 'Woow MCP'), el('span', {}, '智慧空間 · 服務管理'), el('span', { class: 'brand-accent', lang: 'en' }, 'Welcome'))), el('div', { class: 'product-label' }, products[state.product].name, chip('HA 管理介面'))),
    el('div', { class: 'shell' }, el('aside', {}, el('p', { class: 'nav-caption' }, '工作空間'), el('nav', { 'aria-label': '管理導覽' }, ...Object.entries(routes).map(([key, label]) => el('a', { href: `${api.mount}/${key}`, 'aria-current': current === key ? 'page' : null, onclick: event => { if (!event.ctrlKey && !event.metaKey && !event.shiftKey && event.button === 0) { event.preventDefault(); if (!busy) navigate(key); } } }, icon(icons[key]), label))), el('div', { class: 'sidebar-note' }, p('設定由你掌握'), p('後端憑證只在明確更新時送出。權限由伺服器驗證。'))),
      el('main', { id: 'main' }, el('div', { class: 'page-heading' }, el('div', {}, el('p', { class: 'eyebrow' }, `${products[state.product].name} / MANAGEMENT`), el('h1', { tabindex: '-1' }, routes[current]), p({ overview: '一眼看清連線，安心管理你的服務。', backend: '把連線留在這裡，把秘密留在伺服器。', tools: '只開啟需要的能力，每次寫入都有明確授權。', access: '給用戶端正確的入口，不混用管理網址。' }[current])), button('重新整理狀態', () => task(() => reload('已取得最新管理狀態。')))), el('div', { id: 'notice', role: 'status', tabindex: '-1', hidden: true }),
        ({ overview, backend, tools, access })[current](), el('footer', {}, 'GUI 管理設定 · HA 管理員授權 · Streamable HTTP'))));
}
window.addEventListener('popstate', () => { hideToken(); if (state) render(); });
window.addEventListener('pagehide', () => {
  hideToken();
  document.querySelectorAll('input[type=password]').forEach(input => input.value = '');
});
window.addEventListener('blur', hideToken);
document.addEventListener('visibilitychange', () => { if (document.hidden) hideToken(); });
try {
  api = new AdminApi(document.querySelector('meta[name=mcp-ui-base]')?.content);
  root.replaceChildren(el('main', { class: 'blocked', role: 'status' }, p('正在驗證管理權限…')));
  await reload();
} catch (error) { renderDenied(error instanceof UiError ? error.message : '管理服務無法使用。'); }
