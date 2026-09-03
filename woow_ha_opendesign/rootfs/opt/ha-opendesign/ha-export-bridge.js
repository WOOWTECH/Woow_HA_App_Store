((root, factory) => {
  const api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  else api.install();
})(typeof globalThis !== 'undefined' ? globalThis : this, function createApi(root) {
  'use strict';

  const PROJECT_API = /\/api\/projects\/([^/]+)\//;

  function pathOnly(value) {
    try {
      return new URL(String(value), root.location?.href || 'http://localhost/').pathname;
    } catch {
      return '';
    }
  }

  function redirectPdfRequest(value, method = 'GET') {
    if (String(method).toUpperCase() !== 'POST') return null;
    const pathname = pathOnly(value);
    const match = /^(.*\/api\/projects\/[^/]+\/export)\/pdf$/.exec(pathname);
    return match ? `${match[1]}/pdf-image` : null;
  }

  function decodePath(value) {
    try {
      return value.split('/').map(decodeURIComponent).join('/');
    } catch {
      return '';
    }
  }

  function extractArtifactContext(value, init) {
    const pathname = pathOnly(value);
    const project = PROJECT_API.exec(pathname);
    if (!project) return null;
    let fileName = '';
    const preview = /\/api\/projects\/[^/]+\/(?:preview\/[^/]+|raw)\/(.+)$/.exec(pathname);
    const legacy = /\/api\/projects\/[^/]+\/files\/(.+)\/preview$/.exec(pathname);
    if (preview) fileName = decodePath(preview[1]);
    else if (legacy) fileName = decodePath(legacy[1]);
    if (!fileName && typeof init?.body === 'string') {
      try {
        const body = JSON.parse(init.body);
        if (typeof body.fileName === 'string') fileName = body.fileName;
      } catch {
        // Non-JSON request bodies do not carry export context.
      }
    }
    return { projectId: decodePath(project[1]), fileName };
  }

  function filenameFromDisposition(response, fallback) {
    const header = response.headers?.get?.('content-disposition') || '';
    const utf8 = /filename\*=UTF-8''([^;]+)/i.exec(header);
    if (utf8) {
      try { return decodeURIComponent(utf8[1].replace(/^"|"$/g, '')); } catch { /* use fallback */ }
    }
    const plain = /filename="?([^";]+)"?/i.exec(header);
    return plain?.[1] || fallback;
  }

  function triggerDownload(blob, filename) {
    const href = root.URL.createObjectURL(blob);
    const anchor = root.document.createElement('a');
    anchor.href = href;
    anchor.download = filename;
    anchor.style.display = 'none';
    root.document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    root.setTimeout(() => root.URL.revokeObjectURL(href), 5000);
  }

  function imageFormatFromDialog(dialog) {
    const selected = dialog.querySelector('input[name="image-export-format"]:checked');
    return selected?.value === 'jpeg' || selected?.value === 'jpg' ? 'jpeg'
      : selected?.value === 'png' ? 'png'
        : null;
  }

  function install() {
    if (root.__OD_HA_EXPORT_BRIDGE_INSTALLED__) return;
    const ingressPrefix = root.__OD_INGRESS_PATH__;
    if (typeof ingressPrefix !== 'string'
      || !/^\/api\/hassio_ingress\/[A-Za-z0-9_-]{16,128}$/.test(ingressPrefix)) return;
    root.__OD_HA_EXPORT_BRIDGE_INSTALLED__ = true;
    const state = { projectId: '', fileName: '' };
    const nativeFetch = root.fetch.bind(root);

    const remember = (value, init) => {
      const found = extractArtifactContext(value, init);
      if (!found) return;
      state.projectId = found.projectId || state.projectId;
      state.fileName = found.fileName || state.fileName;
    };

    root.fetch = async (input, init) => {
      const value = typeof input === 'string' || input instanceof root.URL ? String(input) : input?.url;
      const method = init?.method || input?.method || 'GET';
      remember(value, init);
      const redirected = redirectPdfRequest(value, method);
      if (!redirected) return nativeFetch(input, init);

      let redirectedInput = redirected;
      let redirectedInit = init;
      if (root.Request && input instanceof root.Request) {
        // Applying init to the original first preserves Fetch's Request + init
        // override semantics, then the second construction changes only URL.
        const effectiveRequest = init === undefined ? input : new root.Request(input, init);
        redirectedInput = new root.Request(new root.URL(redirected, input.url).href, effectiveRequest);
        redirectedInit = undefined;
      }
      const response = await nativeFetch(redirectedInput, redirectedInit);
      if (!response.ok) return response;
      const blob = await response.blob();
      const context = extractArtifactContext(value, init);
      const stem = (context?.fileName || 'artifact').split('/').pop().replace(/\.html?$/i, '') || 'artifact';
      triggerDownload(blob, filenameFromDisposition(response, `${stem}.pdf`));
      // exportProjectAsPdf expects the desktop endpoint's { ok: true } shape;
      // returning it prevents the caller from running its browser-PDF fallback.
      return new root.Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    };

    const instrumentDialog = (dialog) => {
      if (!dialog || dialog.dataset.odHaImageBridge === '1') return;
      root.document.querySelectorAll?.('iframe[src]').forEach((frame) => remember(frame.getAttribute('src')));
      if (!dialog.querySelector('input[name="image-export-format"]')) return;
      const save = dialog.querySelector('.modal-foot .viewer-action.primary');
      if (!save) return;
      dialog.dataset.odHaImageBridge = '1';
      save.addEventListener('click', async (event) => {
        const format = imageFormatFromDialog(dialog);
        if (!format || !state.projectId || !state.fileName) return;
        event.preventDefault();
        event.stopPropagation();
        event.stopImmediatePropagation();
        save.disabled = true;
        try {
          const url = `/api/projects/${encodeURIComponent(state.projectId)}/export/image`;
          const response = await root.fetch(url, {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify({ fileName: state.fileName, imageFormat: format }),
          });
          if (!response.ok) {
            let message = `image export failed (${response.status})`;
            try {
              const body = await response.json();
              if (body?.error?.message) message = body.error.message;
            } catch { /* keep status message */ }
            throw new Error(message);
          }
          const blob = await response.blob();
          const stem = state.fileName.split('/').pop().replace(/\.html?$/i, '') || 'artifact';
          triggerDownload(blob, filenameFromDisposition(response, `${stem}.${format === 'jpeg' ? 'jpg' : 'png'}`));
        } catch (error) {
          root.alert?.(error instanceof Error ? error.message : String(error));
        } finally {
          save.disabled = false;
          dialog.querySelector('.modal-foot .ghost-link.button-like')?.click();
        }
      }, true);
    };

    const inspect = (node) => {
      if (!(node instanceof root.Element)) return;
      remember(node.getAttribute?.('src'));
      instrumentDialog(node.matches?.('[role="dialog"]') ? node : node.querySelector?.('[role="dialog"]'));
      node.querySelectorAll?.('iframe[src]').forEach((frame) => remember(frame.getAttribute('src')));
    };
    inspect(root.document.documentElement);
    new root.MutationObserver((records) => records.forEach((record) => record.addedNodes.forEach(inspect)))
      .observe(root.document.documentElement, { childList: true, subtree: true });
  }

  return {
    createForRoot: (target) => createApi(target),
    extractArtifactContext,
    imageFormatFromDialog,
    install,
    redirectPdfRequest,
  };
});
