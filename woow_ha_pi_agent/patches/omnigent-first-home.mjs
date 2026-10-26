// Serialized into the verified Pi Web 0.12 client AppShell layout effect.
// It only opens a saved session; Pi Web owns restoration and conversation UI.
export function watchOmnigentFirstHome() {
  const prefix = window.__INGRESS_PATH__ || '';
  if (prefix && !/^\/api\/hassio_ingress\/[A-Za-z0-9_-]{16,128}$/.test(prefix)) return;
  const initialUrl = window.location.href;
  const marker = `woow-ha:omnigent-first-home:${prefix}`;
  const controller = new AbortController();
  let stopped = false;
  let deadline;
  const events = ['pointerdown', 'keydown', 'input', 'paste', 'drop', 'touchstart', 'compositionstart', 'wheel', 'popstate'];
  const stop = () => {
    stopped = true;
    window.__WOOW_OMNIGENT_HOME_GUARD__?.stop();
    clearTimeout(deadline);
    controller.abort();
    for (const event of events) window.removeEventListener(event, stop, true);
  };
  const untouched = () => {
    if (stopped || window.__WOOW_OMNIGENT_HOME_GUARD__?.interacted || window.location.href !== initialUrl || window.location.search || window.location.hash
        || ![prefix, prefix + '/'].includes(window.location.pathname)) return false;
    // Unavailable/corrupt storage fails closed. A new composer is a selection too.
    if (sessionStorage.getItem(marker) || sessionStorage.getItem('pi-web:tab-open-session')) return false;
    const memory = JSON.parse(localStorage.getItem('pi-web:last-open-by-workspace') || '{}');
    if (!memory || typeof memory !== 'object' || Array.isArray(memory) || Object.values(memory).some(Boolean)) return false;
    const terminals = JSON.parse(sessionStorage.getItem('pi-web:terminal-tabs') || '{}');
    if (!terminals || typeof terminals !== 'object' || Array.isArray(terminals) || terminals.activeId || terminals.tabs?.length) return false;
    for (const input of document.querySelectorAll('textarea,input,[contenteditable="true"]')) {
      if (input.value || input.textContent || input.files?.length) return false;
    }
    return true;
  };
  try { if (!untouched()) { stop(); return; } } catch { stop(); return; }
  for (const event of events) window.addEventListener(event, stop, true);
  deadline = setTimeout(stop, 30000);
  const read = async url => {
    const response = await fetch(url, { cache: 'no-store', credentials: 'same-origin', signal: controller.signal,
      headers: { 'X-Omnigent-Onboarding': '1' } });
    if (!response.ok) throw new Error('Onboarding unavailable');
    return response.json();
  };
  void (async () => {
    try {
      for (let attempt = 0; attempt < 30 && untouched(); attempt++) {
        try {
          const first = await read(prefix + '/omnigent/onboarding');
          if (first.pending !== true || !untouched()) return;
          if (typeof first.sessionId === 'string' && /^[a-zA-Z0-9-]{1,80}$/.test(first.sessionId)) {
            const catalog = await read(prefix + '/api/sessions?summary=1');
            if (Array.isArray(catalog.sessions) && catalog.sessions.some(session => session.id === first.sessionId)) {
              // Disable/completion/removal while the session catalog loads wins.
              const latest = await read(prefix + '/omnigent/onboarding');
              if (latest.pending !== true || !untouched()) return;
              if (latest.sessionId === first.sessionId) {
                sessionStorage.setItem(marker, first.sessionId);
                // Keep the homepage's history entry. Back/reload sees the marker.
                window.location.assign(prefix + '/?session=' + encodeURIComponent(first.sessionId));
                return;
              }
            }
          }
        } catch { if (stopped) return; }
        await new Promise(resolve => setTimeout(resolve, 1000));
      }
    } catch { /* Offline, denied, malformed and aborted reads do not navigate. */ }
    finally { stop(); }
  })();
  return stop;
}
