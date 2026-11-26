// HA supplies this header after authenticating the browser. Never interpolate
// an arbitrary forwarded path into the settings page.
export function ingressPrefix(value) {
  return typeof value === 'string' && /^\/api\/hassio_ingress\/[A-Za-z0-9_-]{16,128}$/.test(value) ? value : '';
}

// Every target opens its own official site; the add-on serves no copy of any of
// them. These fixed origins are the only places pairing material may be sent.
export const connectionTargets = Object.freeze([
  Object.freeze({ id: 'paseo', label: 'Paseo', appUrl: 'https://app.paseo.sh' }),
  Object.freeze({ id: 'woowtech', label: 'Woowtech Smart', appUrl: 'https://smart.woowtech.io' }),
  Object.freeze({ id: 'apporo', label: 'Apporo Smart', appUrl: 'https://smart.apporo.ai' }),
]);
export function targetId(value = 'paseo') {
  if (!connectionTargets.some(target => target.id === value)) throw Object.assign(new Error('Invalid target'), { code: 'INVALID_TARGET' });
  return value;
}
// The one accepted form is `<target origin>/#offer=<base64url>`, byte for byte:
// no other scheme, host, port, userinfo, path or query, and no other fragment.
export function pairUrl(value, target = 'paseo') {
  target = targetId(target);
  const invalid = () => { throw Object.assign(new Error('Invalid pairing URL'), { code: 'PAIRING_ORIGIN_INVALID' }); };
  if (typeof value !== 'string' || /[\\\x00-\x20\x7f]/.test(value)) return invalid();
  let url;
  try { url = new URL(value); } catch { return invalid(); }
  const origin = connectionTargets.find(item => item.id === target).appUrl;
  if (url.origin !== origin || url.username || url.password || url.pathname !== '/' || url.search || !/^#offer=[A-Za-z0-9_-]+$/.test(url.hash) || !value.startsWith(origin + '/#')) return invalid();
  return value;
}
