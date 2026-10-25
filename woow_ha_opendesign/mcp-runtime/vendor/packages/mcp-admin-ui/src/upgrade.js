import { AdminApi } from './api.js';
import { UiError, products } from './contracts.js';
import './styles.css';

// This entry runs only on the authenticated, pre-start upgrade listener.
const root = document.querySelector('#app');
const policies = { all_on: '完整功能（預設）', preserve: '保留限制，逐項審查' };
const deltas = [
  ['effective_writes_added', '新增有效寫入權限'],
  ['effective_writes_removed', '移除有效寫入權限'],
  ['disabled_added', '新增停用工具'],
  ['disabled_removed', '解除停用工具'],
  ['new_tools', '新版新增工具'],
  ['new_write_operations', '新版新增寫入操作'],
  ['argument_review_tools', '參數範圍需要重新審查的工具'],
];
let api, snapshot = null, policy = 'all_on', phase = 'loading', confirmed = false;
let message = '', pollDeadline = 0, applyStatus = 0;

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else if (typeof value === 'boolean') { if (value) node.setAttribute(key, ''); }
    else node.setAttribute(key, value);
  }
  // Report names are always text nodes, including strings containing HTML.
  node.append(...children.filter(value => value !== null));
  return node;
}
const p = text => el('p', {}, text);
const button = (text, action, attrs = {}) => el('button', { type: 'button', onclick: action, ...attrs }, text);
const icon = name => el('span', { class: 'icon-tile', 'aria-hidden': 'true' }, el('i', { class: `mdi mdi-${name}` }));
const names = values => values.length ? el('ul', { class: 'secret' }, ...values.map(value => el('li', {}, value))) : p('無');
const stringList = value => Array.isArray(value) && value.every(item => typeof item === 'string');

function validatePreview(value) {
  const invalid = () => { throw new UiError('升級預覽格式不相容，未送出變更。請重新載入預覽。'); };
  if (value.stage !== 'upgrade_review' || value.default_policy !== 'all_on') invalid();
  if (typeof value.csrf !== 'string' || !/^[A-Za-z0-9_-]{16,256}$/.test(value.csrf)) {
    throw new UiError('缺少有效安全驗證，未送出變更。請從原服務入口重新開啟。');
  }
  for (const key of Object.keys(policies)) {
    const report = value.plans?.[key];
    if (!report || report.product !== value.product || report.policy !== key
        || !Number.isSafeInteger(report.source_schema) || report.source_schema < 1
        || !Number.isSafeInteger(report.target_schema) || report.target_schema <= report.source_schema
        || typeof report.source_sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(report.source_sha256)
        || deltas.some(([field]) => !stringList(report[field]))) invalid();
    for (const part of ['before', 'after']) {
      if (!report[part] || typeof report[part].writes_enabled !== 'boolean'
          || !stringList(report[part].disabled) || !stringList(report[part].enabled_write_tools)) invalid();
      const denied = report[part].denied_operations ?? {};
      if (typeof denied !== 'object' || Array.isArray(denied)
          || Object.values(denied).some(ops => !stringList(ops))) invalid();
    }
  }
  const { all_on: full, preserve } = value.plans;
  if (full.source_sha256 !== preserve.source_sha256 || full.source_schema !== preserve.source_schema
      || full.target_schema !== preserve.target_schema) invalid();
  return value;
}

function policyDetails(title, value) {
  const denied = Object.entries(value.denied_operations ?? {}).flatMap(([tool, ops]) => ops.map(op => `${tool}:${op}`));
  return el('details', {}, el('summary', {}, title),
    el('dl', { class: 'summary' },
      el('dt', {}, '舊式全域寫入開關'), el('dd', {}, value.writes_enabled ? '開啟' : '關閉'),
      el('dt', {}, `停用工具（${value.disabled.length}）`), el('dd', {}, names(value.disabled)),
      el('dt', {}, `停用操作（${denied.length}）`), el('dd', {}, names(denied)),
      el('dt', {}, `明確寫入授權（${value.enabled_write_tools.length}）`), el('dd', {}, names(value.enabled_write_tools))));
}

function preview() {
  const report = snapshot.plans[policy];
  return el('section', { class: 'card', 'aria-labelledby': 'preview-title', id: 'upgrade-preview' },
    el('h2', { id: 'preview-title' }, '這個選擇會改變什麼'),
    p(`目前選擇：${policies[policy]}。設定格式 ${report.source_schema} → ${report.target_schema}。`),
    p('下列有效寫入差異已計入停用工具與停用操作；明確授權即使保留，也可能因工具停用而暫不生效。'),
    ...deltas.map(([field, title]) => el('details', { open: ['effective_writes_added', 'effective_writes_removed', 'disabled_added', 'disabled_removed'].includes(field) && report[field].length > 0 },
      el('summary', {}, `${title}（${report[field].length}）`), names(report[field]))),
    p('新版新增項目不代表此選擇全部允許；請以有效寫入差異與升級後的停用清單為準。參數範圍可能比舊版更廣。'),
    policyDetails('升級前的政策與授權', report.before), policyDetails('升級後的政策與授權', report.after),
    el('details', {}, el('summary', {}, '本次審閱的設定摘要'),
      p('確認只會套用這份設定的預覽；設定變更後必須重新審閱。'),
      el('span', { class: 'secret', id: 'reviewed-digest' }, report.source_sha256)));
}

function choices() {
  return el('section', { class: 'card' }, el('h2', {}, '選擇升級後的工具政策'),
    el('fieldset', { disabled: phase !== 'review' }, el('legend', {}, '升級政策'),
      ...Object.entries(policies).map(([key, title]) => el('div', { class: 'field' },
        el('label', { class: 'check', for: `policy-${key}` },
          el('span', { class: 'icon-tile' }, el('input', { type: 'radio', name: 'policy', id: `policy-${key}`, value: key,
            checked: policy === key, 'aria-describedby': `hint-${key}`, onchange: () => {
              if (phase !== 'review') return;
              policy = key; confirmed = false; render(); document.querySelector(`#policy-${key}`).focus();
            } })), el('span', {}, title)),
        pWithId(`hint-${key}`, key === 'all_on'
          ? '選擇完整功能與新版寫入權限，並解除工具停用限制。實際變更以下方預覽為準；請先審閱，再明確確認。'
          : '保留限制；新工具、擴充讀取或參數範圍的工具會先停用。許多工具可能無法使用，需在啟動後逐項審查再開啟。')))));
}
const pWithId = (id, text) => el('p', { id }, text);

function render() {
  const busy = ['loading', 'applying', 'starting'].includes(phase);
  root.setAttribute('aria-busy', String(busy));
  document.title = 'Woow MCP · 升級前確認';
  const content = el('div', { class: 'stack' });
  if (snapshot && ['review', 'applying', 'error'].includes(phase)) {
    content.append(choices(), preview(), el('section', { class: 'card' }, el('h2', {}, '確認後才會升級並啟動'),
      el('label', { class: 'check' }, el('input', { id: 'upgrade-confirm', type: 'checkbox', checked: confirmed,
        disabled: phase !== 'review', onchange: event => {
          confirmed = phase === 'review' && event.target.checked;
          document.querySelector('#upgrade-apply').disabled = !confirmed;
        } }), el('span', {}, `我已審閱「${policies[policy]}」的權限差異，確認套用並啟動服務。`)),
      el('div', { class: 'actions' }, button(phase === 'applying' ? '正在送出升級確認…' : '確認升級並啟動', apply,
        { id: 'upgrade-apply', class: 'primary', disabled: phase !== 'review' || !confirmed }))));
  }
  if (phase === 'error') content.append(el('div', { class: 'actions' }, button('重新載入升級預覽', loadPreview)));
  if (phase === 'waiting') content.append(el('section', { class: 'card' }, el('h2', {}, '尚未確認服務啟動'),
    p('自動檢查已停止。你可以再檢查一次；這只會讀取狀態，不會再次送出升級。'),
    el('div', { class: 'actions' }, button('再檢查啟動狀態', watchStartup))));
  root.replaceChildren(el('a', { class: 'skip', href: '#main' }, '跳至主要內容'),
    el('header', { class: 'topbar' }, el('div', { class: 'brand-caption' }, icon('home-automation'),
      el('div', {}, el('strong', {}, 'woowtech'), el('span', { class: 'brand-accent' }, 'Welcome'))),
      el('div', { class: 'product-label' }, snapshot ? `${products[snapshot.product].name} MCP` : 'MCP', el('span', { class: 'chip' }, 'HA 升級確認'))),
    el('div', { class: 'shell' }, el('aside', {}, el('div', { class: 'nav-caption' }, '啟動前的必要步驟'),
      el('div', { class: 'sidebar-note' }, p('01 選擇工具政策'), p('02 審閱權限差異'), p('03 確認升級並啟動'))),
      el('main', { id: 'main', tabindex: '-1' }, el('div', { class: 'page-heading' }, el('div', {},
        el('h1', {}, ['starting', 'waiting', 'normal'].includes(phase) ? '正在啟動服務' : '升級前，先確認工具權限'),
        p(['starting', 'waiting', 'normal'].includes(phase)
          ? '升級設定已儲存；正在確認一般管理服務是否可用。'
          : '服務尚未啟動。請先選擇並審閱升級政策，明確確認後才會套用設定與啟動。'))),
      el('div', { id: 'upgrade-status', class: `notice${phase === 'error' ? ' error' : ''}`, role: phase === 'error' ? 'alert' : 'status', tabindex: '-1' },
        message || (phase === 'loading' ? '正在載入升級預覽…' : `已選擇「${policies[policy]}」；尚未套用任何變更。`)), content)));
}

function fail(error, stale = false) {
  phase = 'error'; confirmed = false;
  message = stale ? '設定已變更，本次預覽已過期。未確認套用成功；請重新載入預覽、審閱新差異並再次確認。'
    : error instanceof UiError ? error.message : '無法確認操作結果。請重新載入預覽後再審閱。';
  render(); document.querySelector('#upgrade-status').focus();
}

function openRuntime() {
  phase = 'normal'; message = '一般管理服務已回應，正在開啟管理介面。工具與後端狀態請在管理介面查看。';
  render(); location.replace(`${api.mount}/`);
}

async function loadPreview() {
  if (['applying', 'starting'].includes(phase)) return;
  phase = 'loading'; confirmed = false; snapshot = null; message = ''; render();
  try {
    const value = await api.bootstrap();
    if (!Object.hasOwn(value, 'stage')) { openRuntime(); return; }
    if (value.stage === 'starting') { await watchStartup(); return; }
    snapshot = validatePreview(value); policy = 'all_on'; phase = 'review'; render();
  } catch (error) { fail(error); }
}

async function apply() {
  if (phase !== 'review' || !confirmed || !snapshot) return;
  // Capture exactly what was displayed. Do not bootstrap/replace this digest
  // before POST, even to refresh CSRF. A 409 requires a new deliberate review.
  const reviewed = { policy, expected_sha256: snapshot.plans[policy].source_sha256 };
  const csrf = snapshot.csrf;
  phase = 'applying'; confirmed = false; message = '正在送出確認；尚未確認儲存成功，請稍候。'; render();
  try {
    const result = await api.request(`${api.mount}/api/upgrade/apply`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf }, body: JSON.stringify(reviewed),
    });
    if (applyStatus !== 202 || result?.saved !== true || result?.stage !== 'starting') {
      throw new UiError('伺服器未回傳預期的升級確認，無法確認結果。請重新載入預覽檢查狀態。');
    }
  } catch (error) { fail(error, error.status === 409); return; }
  await watchStartup();
}

async function watchStartup() {
  if (phase === 'starting') return;
  phase = 'starting'; confirmed = false;
  message = '伺服器已確認儲存，服務啟動中；一般管理服務尚未回應。連線可能暫時中斷，請稍候。'; render();
  pollDeadline = Date.now() + 60000;
  try {
    for (let attempt = 0; attempt < 12 && Date.now() < pollDeadline; attempt++) {
      await new Promise(resolve => setTimeout(resolve, 1500));
      try {
        const value = await api.bootstrap();
        if (!Object.hasOwn(value, 'stage')) { openRuntime(); return; }
      } catch (error) {
        if ([401, 403].includes(error.status)) {
          phase = 'waiting'; message = error.message; render(); return;
        }
        // Listener shutdown, 503 and connection refusal are expected during handoff.
      }
    }
    phase = 'waiting'; message = '升級已儲存，但等待時間已到，尚未確認一般管理服務可用。請稍後再檢查，或查看附加元件日誌。'; render();
  } finally { pollDeadline = 0; }
}

try {
  api = new AdminApi(document.querySelector('meta[name="mcp-ui-base"]')?.content, async (path, options) => {
    const signal = pollDeadline
      ? AbortSignal.any([options.signal, AbortSignal.timeout(Math.max(1, Math.min(5000, pollDeadline - Date.now())))])
      : options.signal;
    const response = await fetch(path, { ...options, signal });
    if (options.method === 'POST') applyStatus = response.status;
    return response;
  });
  await loadPreview();
} catch (error) { fail(error); }
