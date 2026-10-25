import { mountPath, products, UiError } from './contracts.js';

export class ApiError extends UiError {
  constructor(status, code = null) {
    const messages = {
      400: '設定格式不符。伺服器未確認儲存，請檢查欄位。',
      401: '管理身分已失效。請從服務入口重新開啟。',
      403: '你沒有管理權限，或安全驗證已失效。請從原服務入口重新驗證；此頁無法繞過授權。',
      404: '此伺服器尚未提供所需管理 API。',
      409: '設定已變更或版本不相容。請重新整理後再試。',
      422: '欄位驗證未通過。請確認 URL、必要欄位與憑證格式。',
      503: '管理狀態暫時無法使用。請檢查服務與受保護的設定儲存。',
    };
    super(messages[status] ?? '請求未獲成功確認。請重新整理狀態，勿假設變更已套用。');
    this.status = status;
    this.code = code;
    if (code === 'config_conflict') this.message = '設定已被其他操作更新。草稿已保留；請先重新整理狀態、檢查新設定，再重新編輯。未送出任何變更。';
    if (code === 'config_apply_failed') this.message = '設定已儲存，但子行程尚未套用成功。請重新整理套用狀態，檢查後再重試啟動。';
  }
}
export class AdminApi {
  constructor(mount, fetcher = globalThis.fetch.bind(globalThis)) {
    this.mount = mountPath(mount);
    this.fetcher = fetcher;
  }
  async request(path, options = {}) {
    let response;
    try {
      response = await this.fetcher(path, { ...options, credentials: 'same-origin', cache: 'no-store', redirect: 'error', signal: AbortSignal.timeout(25000) });
    } catch { throw new UiError('連線中斷或逾時；無法確認操作結果。請重新整理狀態後再操作。'); }
    if (!response.ok) {
      // Only these fixed codes affect copy. Never reflect server bodies or submitted secrets.
      let code;
      try { code = (await response.json())?.detail?.code; } catch { /* non-JSON error */ }
      throw new ApiError(response.status, ['config_conflict', 'config_apply_failed'].includes(code) ? code : null);
    }
    if (response.status === 204) return null;
    try { return await response.json(); } catch { throw new UiError('伺服器回應格式不符，無法確認操作結果。'); }
  }
  async bootstrap() {
    const value = await this.request(`${this.mount}/api/bootstrap`);
    if (!value || mountPath(value.base_path) !== this.mount || value.api_base !== `${this.mount}/api` || !Object.hasOwn(products, value.product)) throw new UiError('管理 API 路徑或產品版本不相容。');
    return value;
  }
  async mutate(operation, payload, revision) {
    const allowed = ['backend', 'endpoint', 'policy', 'token/reveal', 'token/rotate', 'token/revoke', 'backend/test', 'child/restart'];
    if (!allowed.includes(operation)) throw new UiError('不支援的操作。');
    const fresh = await this.bootstrap();
    if (typeof fresh.csrf !== 'string' || !/^[A-Za-z0-9_-]{16,256}$/.test(fresh.csrf)) throw new UiError('缺少有效安全驗證；未送出變更。請重新開啟管理介面。');
    const token = operation.startsWith('token/');
    const action = token || ['backend/test', 'child/restart'].includes(operation);
    if (revision !== undefined && (typeof revision !== 'string' || !/^[A-Za-z0-9_-]{16,128}$/.test(revision))) throw new UiError('設定版本格式不符；請重新整理後再試。');
    const result = await this.request(`${fresh.api_base}/${operation}`, {
      method: action ? 'POST' : 'PUT',
      headers: { 'X-CSRF-Token': fresh.csrf, ...(action ? {} : { 'Content-Type': 'application/json' }),
        ...(revision === undefined ? {} : { 'If-Match': `"${revision}"` }) },
      ...(action ? {} : { body: JSON.stringify(typeof payload === 'function' ? payload(fresh) : payload) }),
    });
    if ((!action && result?.saved !== true) || (operation === 'token/revoke' && result !== null)
        || (operation === 'child/restart' && (result?.accepted !== true || result?.apply_state !== 'pending'))
        || (operation === 'backend/test' && result?.tested_configuration !== 'saved')) throw new UiError('伺服器未回傳預期確認，無法確認操作結果。請重新整理狀態。');
    return result;
  }
  async capabilities() { return this.request(`${this.mount}/api/capabilities`); }
  async diagnostics() { return this.request(`${this.mount}/api/diagnostics`); }
  async configuration() { return this.request(`${this.mount}/api/configuration`); }
}
