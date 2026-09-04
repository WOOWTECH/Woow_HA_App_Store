(() => {
  'use strict';

  const prefix = window.__OD_INGRESS_PATH__ || '';
  if (!prefix) return;

  // Supervisor's public prefix is transport routing, not an OpenDesign route.
  // Keep the iframe's logical history unprefixed so OpenDesign's client-side
  // route switch recognizes /settings, /design-systems, etc. Network APIs and
  // assets are still prefixed by the wrappers below.
  const nativeHistoryPushState = history.pushState;
  const nativeHistoryReplaceState = history.replaceState;
  if (window.location.pathname === prefix || window.location.pathname.startsWith(`${prefix}/`)) {
    const logicalPath = window.location.pathname.slice(prefix.length) || '/';
    nativeHistoryReplaceState.call(history, history.state, '', `${logicalPath}${window.location.search}${window.location.hash}`);
  }

  const alreadyScoped = (pathname) => pathname === prefix
    || pathname.startsWith(`${prefix}/`)
    || pathname.startsWith('/api/hassio_ingress/');

  const pathFromUrl = (value, websocket = false) => {
    if (typeof value !== 'string') return null;
    if (value.startsWith('/') && !value.startsWith('//')) return value;
    try {
      const url = new URL(value, window.location.href);
      if (url.host !== window.location.host) return null;
      if (websocket) {
        if (url.protocol !== 'ws:' && url.protocol !== 'wss:' && url.protocol !== 'http:' && url.protocol !== 'https:') return null;
      } else {
        // Blob/data/about URLs are browser-local resources, not ingress paths.
        // In particular, rewriting a blob: download URL breaks export links.
        if (url.protocol !== 'http:' && url.protocol !== 'https:') return null;
        if (url.origin !== window.location.origin) return null;
      }
      return `${url.pathname}${url.search}${url.hash}`;
    } catch {
      return null;
    }
  };

  const rewrite = (value, websocket = false) => {
    const raw = value instanceof URL ? value.href : String(value);
    const pathname = pathFromUrl(raw, websocket);
    if (!pathname || alreadyScoped(pathname)) return value;
    return `${prefix}${pathname}`;
  };

  const originalFetch = window.fetch.bind(window);
  window.fetch = (input, init) => {
    if (typeof input === 'string' || input instanceof URL) {
      return originalFetch(rewrite(input), init);
    }
    if (input instanceof Request) {
      const next = rewrite(input.url);
      if (next !== input.url) input = new Request(new URL(next, input.url).href, input);
    }
    return originalFetch(input, init);
  };

  const NativeXHR = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function open(method, url) {
    arguments[1] = rewrite(url);
    return NativeXHR.apply(this, arguments);
  };

  if (window.EventSource) {
    const NativeEventSource = window.EventSource;
    class IngressEventSource extends NativeEventSource {
      constructor(url, options) { super(rewrite(url), options); }
    }
    Object.defineProperties(IngressEventSource, {
      CONNECTING: { value: NativeEventSource.CONNECTING },
      OPEN: { value: NativeEventSource.OPEN },
      CLOSED: { value: NativeEventSource.CLOSED },
    });
    window.EventSource = IngressEventSource;
  }

  if (window.WebSocket) {
    const NativeWebSocket = window.WebSocket;
    class IngressWebSocket extends NativeWebSocket {
      constructor(url, protocols) {
        const scoped = rewrite(url, true);
        super(scoped, protocols);
      }
    }
    Object.defineProperties(IngressWebSocket, {
      CONNECTING: { value: NativeWebSocket.CONNECTING },
      OPEN: { value: NativeWebSocket.OPEN },
      CLOSING: { value: NativeWebSocket.CLOSING },
      CLOSED: { value: NativeWebSocket.CLOSED },
    });
    window.WebSocket = IngressWebSocket;
  }

  const wrapWorker = (name) => {
    const Native = window[name];
    if (!Native) return;
    window[name] = class IngressWorker extends Native {
      constructor(url, options) { super(rewrite(url), options); }
    };
  };
  wrapWorker('Worker');
  wrapWorker('SharedWorker');

  const logicalHistoryUrl = (value) => {
    const pathname = pathFromUrl(String(value));
    if (!pathname) return value;
    if (pathname === prefix) return '/';
    if (pathname.startsWith(`${prefix}/`)) return pathname.slice(prefix.length) || '/';
    return pathname;
  };
  const wrapHistory = (method, native) => {
    history[method] = function logicalHistory(state, title, url) {
      if (url != null) arguments[2] = logicalHistoryUrl(url);
      return native.apply(this, arguments);
    };
  };
  wrapHistory('pushState', nativeHistoryPushState);
  wrapHistory('replaceState', nativeHistoryReplaceState);

  // Best effort: restore the transport prefix in the history entry before a
  // user/browser leaves the iframe, so a manual reload remains ingress-routed.
  window.addEventListener('beforeunload', () => {
    if (!window.location.pathname.startsWith(prefix)) {
      nativeHistoryReplaceState.call(
        history,
        history.state,
        '',
        `${prefix}${window.location.pathname}${window.location.search}${window.location.hash}`,
      );
    }
  });

  const rewriteCss = (value) => typeof value === 'string'
    ? value.replace(/url\(\s*(["']?)(\/[^/][^"')\s]*)\1\s*\)/gi, (_match, quote, url) => `url(${quote}${rewrite(url)}${quote})`)
    : value;
  const urlAttributes = new Set(['action', 'href', 'poster', 'src']);
  const originalSetAttribute = Element.prototype.setAttribute;
  Element.prototype.setAttribute = function setAttribute(name, value) {
    const attribute = String(name).toLowerCase();
    if (urlAttributes.has(attribute)) value = rewrite(value);
    if (attribute === 'style') value = rewriteCss(value);
    return originalSetAttribute.call(this, name, value);
  };

  const nativeSetProperty = CSSStyleDeclaration.prototype.setProperty;
  CSSStyleDeclaration.prototype.setProperty = function setProperty(name, value, priority) {
    return nativeSetProperty.call(this, name, rewriteCss(value), priority);
  };
  const nativeInsertRule = CSSStyleSheet.prototype.insertRule;
  CSSStyleSheet.prototype.insertRule = function insertRule(rule, index) {
    return nativeInsertRule.call(this, rewriteCss(rule), index);
  };

  const patchProperty = (constructor, property) => {
    if (!constructor) return;
    const descriptor = Object.getOwnPropertyDescriptor(constructor.prototype, property);
    if (!descriptor?.set || !descriptor.get) return;
    Object.defineProperty(constructor.prototype, property, {
      configurable: descriptor.configurable,
      enumerable: descriptor.enumerable,
      get: descriptor.get,
      set(value) { descriptor.set.call(this, rewrite(value)); },
    });
  };
  [
    [window.HTMLAnchorElement, 'href'],
    [window.HTMLFormElement, 'action'],
    [window.HTMLImageElement, 'src'],
    [window.HTMLIFrameElement, 'src'],
    [window.HTMLLinkElement, 'href'],
    [window.HTMLScriptElement, 'src'],
    [window.HTMLSourceElement, 'src'],
    [window.HTMLVideoElement, 'poster'],
  ].forEach(([constructor, property]) => patchProperty(constructor, property));

  const scopeTree = (root) => {
    if (!(root instanceof Element)) return;
    const elements = [root, ...root.querySelectorAll('[href],[src],[action],[poster],[style],style')];
    for (const element of elements) {
      for (const attribute of urlAttributes) {
        if (!element.hasAttribute(attribute)) continue;
        const value = element.getAttribute(attribute);
        const scoped = rewrite(value);
        if (scoped !== value) originalSetAttribute.call(element, attribute, scoped);
      }
      if (element.hasAttribute('style')) {
        const value = element.getAttribute('style');
        const scoped = rewriteCss(value);
        if (scoped !== value) originalSetAttribute.call(element, 'style', scoped);
      }
      if (element.tagName === 'STYLE') element.textContent = rewriteCss(element.textContent);
    }
  };
  new MutationObserver((records) => records.forEach((record) => record.addedNodes.forEach(scopeTree)))
    .observe(document.documentElement, { childList: true, subtree: true });

  // A service worker scoped to '/' would control Home Assistant itself.
  if (navigator.serviceWorker?.register) {
    navigator.serviceWorker.register = () => Promise.reject(new Error('Service workers are disabled under Home Assistant Ingress'));
  }
})();
