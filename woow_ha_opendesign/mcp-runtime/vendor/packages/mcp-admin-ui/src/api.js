import { mountPath, products, UiError } from './contracts.js';

export class ApiError extends UiError {
  constructor(status) {
    const messages = {
      400: '設定格式不符。伺服器未確認儲存，請檢查欄位。',
      401: '管理身分已失效。請從 Home Assistant 重新開啟。',
      403: '你沒有管理權限，或安全驗證已失效。請由 Home Assistant 管理員重新開啟；此頁無法繞過授權。',
      404: '此伺服器尚未提供所需管理 API。',
      409: '設定已變更或版本不相容。請重新整理後再試。',
      422: '欄位驗證未通過。請確認 URL、必要欄位與憑證格式。',
      503: '管理狀態暫時無法使用。請檢查服務與受保護的設定儲存。',
    };
    super(messages[status] ?? '請求未獲成功確認。請重新整理狀態，勿假設變更已套用。');
    this.status = status;
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
      response = await this.fetcher(path, { ...options, credentials: 'same-origin', cache: 'no-store', redirect: 'error', signal: AbortSignal.timeout(12000) });
    } catch { throw new UiError('連線中斷或逾時；無法確認操作結果。請重新整理狀態後再操作。'); }
    if (!response.ok) throw new ApiError(response.status); // Never reflect response bodies or submitted secrets.
    if (response.status === 204) return null;
    try { return await response.json(); } catch { throw new UiError('伺服器回應格式不符，無法確認操作結果。'); }
  }
  async bootstrap() {
    const value = await this.request(`${this.mount}/api/bootstrap`);
    if (!value || mountPath(value.base_path) !== this.mount || value.api_base !== `${this.mount}/api` || !Object.hasOwn(products, value.product)) throw new UiError('管理 API 路徑或產品版本不相容。');
    return value;
  }
  async mutate(operation, payload) {
    const allowed = ['backend', 'endpoint', 'policy', 'token/reveal', 'token/rotate', 'token/revoke'];
    if (!allowed.includes(operation)) throw new UiError('不支援的操作。');
    const fresh = await this.bootstrap();
    if (typeof fresh.csrf !== 'string' || !/^[A-Za-z0-9_-]{16,256}$/.test(fresh.csrf)) throw new UiError('缺少有效安全驗證；未送出變更。請重新開啟管理介面。');
    const token = operation.startsWith('token/');
    const result = await this.request(`${fresh.api_base}/${operation}`, {
      method: token ? 'POST' : 'PUT',
      headers: { 'X-CSRF-Token': fresh.csrf, ...(token ? {} : { 'Content-Type': 'application/json' }) },
      ...(token ? {} : { body: JSON.stringify(typeof payload === 'function' ? payload(fresh) : payload) }),
    });
    if ((!token && result?.saved !== true) || (operation === 'token/revoke' && result !== null)) throw new UiError('伺服器未回傳預期確認，無法確認操作結果。請重新整理狀態。');
    return result;
  }
}
