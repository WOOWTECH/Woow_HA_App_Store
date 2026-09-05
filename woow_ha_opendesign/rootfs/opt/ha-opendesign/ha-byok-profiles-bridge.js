((root, factory) => {
  const api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  else api.install();
})(typeof globalThis !== 'undefined' ? globalThis : this, function createApi(root) {
  'use strict';

  const API_PATH = '/api/ha-opendesign/byok/profiles';
  const CONFIG_KEY = 'open-design:config';
  const ROOT_ID = 'od-ha-byok-profiles-bridge';
  const LAUNCHER_ID = 'od-ha-byok-profiles-launcher';
  const PI_AGENT_ID = 'pi';

  function isIngressPage() {
    return typeof root.__OD_INGRESS_PATH__ === 'string'
      && /^\/api\/hassio_ingress\/[A-Za-z0-9_-]{16,128}$/.test(root.__OD_INGRESS_PATH__);
  }

  function isSettingsPage() {
    return root.location?.pathname === '/settings';
  }

  function emptyState() {
    return { version: 1, revision: 0, activeProfileId: null, profiles: {} };
  }

  function normalizeState(value) {
    if (!value || typeof value !== 'object' || Array.isArray(value)
      || !value.profiles || typeof value.profiles !== 'object' || Array.isArray(value.profiles)) {
      throw new Error('Profiles could not be loaded.');
    }
    return {
      version: value.version,
      revision: value.revision,
      activeProfileId: typeof value.activeProfileId === 'string' ? value.activeProfileId : null,
      profiles: value.profiles,
    };
  }

  function activeProfile(state) {
    const profile = state?.activeProfileId ? state.profiles?.[state.activeProfileId] : null;
    return profile && typeof profile === 'object' && typeof profile.model === 'string' ? profile : null;
  }

  class ProfilesClient {
    constructor(fetcher = root.fetch?.bind(root)) {
      this.fetcher = fetcher;
    }

    async get() {
      const response = await this.fetcher(API_PATH, { cache: 'no-store' });
      if (!response.ok) throw new Error('Profiles could not be loaded.');
      return normalizeState(await response.json());
    }

    async put(state) {
      const response = await this.fetcher(API_PATH, {
        method: 'PUT',
        cache: 'no-store',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(state),
      });
      if (response.status === 409) {
        const error = new Error('Profiles changed in another session. Reload and retry.');
        error.code = 'conflict';
        throw error;
      }
      if (!response.ok) throw new Error('Profiles could not be saved.');
      return normalizeState(await response.json());
    }
  }

  function parseConfig(storage) {
    try {
      const raw = storage.getItem(CONFIG_KEY);
      if (!raw) return {};
      const value = JSON.parse(raw);
      return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
    } catch {
      return {};
    }
  }

  function dispatchConfigStorageEvent(oldValue, newValue) {
    try {
      const event = typeof root.StorageEvent === 'function'
        ? new root.StorageEvent('storage', {
          key: CONFIG_KEY,
          oldValue,
          newValue,
          storageArea: root.localStorage,
          url: root.location?.href,
        })
        : new root.Event('storage');
      root.dispatchEvent(event);
    } catch {
      // A storage-restricted browser still receives the next configuration load.
    }
  }

  function syncPiConfig(config) {
    if (typeof root.fetch !== 'function') return;
    // This is the public app-config seam. Deliberately send only execution
    // preferences; browser API-provider fields (including any session key) are
    // neither read nor copied by this bridge.
    root.fetch('/api/app-config', {
      method: 'PUT',
      cache: 'no-store',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ agentId: config.agentId, agentModels: config.agentModels }),
    }).catch(() => {});
  }

  function configurePiForProfile(profile, storage = root.localStorage) {
    if (!profile || typeof profile.model !== 'string' || !profile.model.trim() || !storage) return null;
    const previous = parseConfig(storage);
    const agentModels = { ...(previous.agentModels && typeof previous.agentModels === 'object' ? previous.agentModels : {}) };
    agentModels[PI_AGENT_ID] = { ...(agentModels[PI_AGENT_ID] || {}), model: profile.model.trim() };
    const next = { ...previous, mode: 'daemon', agentId: PI_AGENT_ID, agentModels };
    try {
      const oldValue = storage.getItem(CONFIG_KEY);
      const newValue = JSON.stringify(next);
      storage.setItem(CONFIG_KEY, newValue);
      dispatchConfigStorageEvent(oldValue, newValue);
      syncPiConfig(next);
      return next;
    } catch {
      return null;
    }
  }

  function profileId(label) {
    const stem = String(label || 'profile').trim().toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '')
      .slice(0, 100) || 'profile';
    const suffix = typeof root.crypto?.randomUUID === 'function'
      ? root.crypto.randomUUID().replace(/-/g, '').slice(0, 12)
      : `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
    return `${stem}-${suffix}`.slice(0, 128);
  }

  function blankProfile() {
    return {
      id: '', label: '', protocol: 'anthropic', baseUrl: '', authStyle: 'bearer',
      apiFlavor: 'openai-completions', apiKey: '', model: '',
    };
  }

  function copyProfile(profile) {
    return { ...blankProfile(), ...profile, id: '', label: profile?.label ? `${profile.label} copy` : '' };
  }

  function setStatus(container, message, kind = '') {
    const status = container.querySelector('[data-byok-status]');
    status.textContent = message;
    status.dataset.kind = kind;
  }

  function field(container, name) {
    return container.querySelector(`[name="${name}"]`);
  }

  function updateProtocolFields(container) {
    const compatible = field(container, 'protocol').value === 'openai-compatible';
    for (const name of ['baseUrl', 'authStyle', 'apiFlavor']) field(container, name).disabled = !compatible;
  }

  function readForm(container, editingId) {
    const profile = {};
    for (const name of ['id', 'label', 'protocol', 'baseUrl', 'authStyle', 'apiFlavor', 'apiKey', 'model']) {
      profile[name] = field(container, name).value.trim();
    }
    if (editingId) profile.id = editingId;
    if (!profile.id) profile.id = profileId(profile.label);
    return profile;
  }

  function writeForm(container, profile, editingId) {
    const next = profile || blankProfile();
    for (const name of ['id', 'label', 'protocol', 'baseUrl', 'authStyle', 'apiFlavor', 'apiKey', 'model']) {
      field(container, name).value = next[name] || '';
    }
    field(container, 'id').readOnly = Boolean(editingId);
    updateProtocolFields(container);
  }

  function lockUpstreamModelControls(container, profile) {
    if (!profile) return;
    const matcher = /\bmodel\b/i;
    root.document.querySelectorAll('select,input,button,[role="combobox"]').forEach((element) => {
      if (container.contains(element)) return;
      const label = [
        element.getAttribute('aria-label'), element.getAttribute('title'), element.getAttribute('data-testid'),
        element.labels?.[0]?.textContent,
      ].filter(Boolean).join(' ');
      if (!matcher.test(label)) return;
      if ('disabled' in element) element.disabled = true;
      element.setAttribute('aria-disabled', 'true');
      element.setAttribute('title', 'The active Persistent BYOK profile model is authoritative.');
    });
  }

  function renderProfileOptions(container, state, selectedId) {
    const select = field(container, 'profilePicker');
    select.replaceChildren();
    const placeholder = root.document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = 'Create a profile…';
    select.appendChild(placeholder);
    for (const profile of Object.values(state.profiles)) {
      if (!profile || typeof profile !== 'object' || typeof profile.id !== 'string') continue;
      const option = root.document.createElement('option');
      option.value = profile.id;
      option.textContent = profile.label || profile.id;
      select.appendChild(option);
    }
    select.value = selectedId || '';
  }

  function bridgeMarkup() {
    return `<section id="${ROOT_ID}" role="dialog" aria-modal="true" aria-labelledby="od-ha-byok-title" hidden>
      <div class="od-ha-byok-card">
        <div class="od-ha-byok-header"><h2 id="od-ha-byok-title">Persistent BYOK profiles</h2><button type="button" data-byok-close aria-label="Close persistent BYOK profiles">Close</button></div>
        <p>Profiles persist in this Home Assistant add-on. Provider controls in OpenDesign remain session-only.</p>
        <p data-byok-authority hidden><strong>Active model:</strong> <output data-byok-model></output>. This profile model is authoritative; the OpenDesign model selector is disabled.</p>
        <label>Profile <select name="profilePicker" aria-label="Persistent BYOK profile"></select></label>
        <div class="od-ha-byok-actions"><button type="button" data-byok-new>New profile</button><button type="button" data-byok-duplicate>Duplicate</button><button type="button" data-byok-rename>Rename</button><button type="button" data-byok-set-active>Set active</button><button type="button" data-byok-delete>Delete</button></div>
        <label>Profile ID <input name="id" maxlength="128" aria-label="Profile ID"></label>
        <label>Name <input name="label" maxlength="120" aria-label="Profile name"></label>
        <label>Provider <select name="protocol" aria-label="Provider protocol"><option value="anthropic">Anthropic</option><option value="openai">OpenAI</option><option value="google">Google</option><option value="openai-compatible">OpenAI-compatible</option></select></label>
        <label>Model <input name="model" maxlength="256" aria-label="Profile model"></label>
        <label>API key <input name="apiKey" type="text" autocomplete="off" maxlength="4096" aria-label="API key"></label>
        <label>Compatible base URL <input name="baseUrl" type="url" aria-label="Compatible base URL"></label>
        <label>Compatible authentication <select name="authStyle" aria-label="Compatible authentication"><option value="bearer">Bearer token</option><option value="api-key">API-key header</option></select></label>
        <label>Compatible API <select name="apiFlavor" aria-label="Compatible API"><option value="openai-completions">OpenAI completions</option><option value="openai-responses">OpenAI responses</option></select></label>
        <div class="od-ha-byok-actions"><button type="button" data-byok-save>Save profile</button><button type="button" data-byok-reload>Reload profiles</button></div>
        <p data-byok-status role="status" aria-live="polite"></p>
      </div>
    </section>`;
  }

  function installStyles() {
    if (root.document.getElementById(`${ROOT_ID}-style`)) return;
    const style = root.document.createElement('style');
    style.id = `${ROOT_ID}-style`;
    style.textContent = `#${LAUNCHER_ID}{position:fixed;right:16px;bottom:16px;z-index:2147483000}#${ROOT_ID}{position:fixed;inset:0;z-index:2147483001;background:#0008;overflow:auto;padding:24px}#${ROOT_ID}[hidden]{display:none}#${ROOT_ID} .od-ha-byok-card{max-width:620px;margin:4vh auto;background:var(--background,#fff);color:var(--foreground,#111);padding:24px;border-radius:12px}#${ROOT_ID} label{display:block;margin:10px 0}#${ROOT_ID} input,#${ROOT_ID} select{display:block;width:100%;box-sizing:border-box}#${ROOT_ID} .od-ha-byok-actions,#${ROOT_ID} .od-ha-byok-header{display:flex;gap:8px;align-items:center;flex-wrap:wrap}#${ROOT_ID} .od-ha-byok-header h2{margin-right:auto}#${ROOT_ID} [data-byok-status][data-kind="error"]{color:#b42318}`;
    root.document.head?.appendChild(style);
  }

  function mount() {
    if (!isIngressPage() || !isSettingsPage() || root.document.getElementById(ROOT_ID)) return;
    installStyles();
    const launcher = root.document.createElement('button');
    launcher.id = LAUNCHER_ID;
    launcher.type = 'button';
    launcher.textContent = 'Persistent BYOK profiles';
    launcher.setAttribute('aria-haspopup', 'dialog');
    root.document.body.appendChild(launcher);
    const holder = root.document.createElement('div');
    holder.innerHTML = bridgeMarkup();
    const container = holder.firstElementChild;
    root.document.body.appendChild(container);
    const client = new ProfilesClient();
    let state = emptyState();
    let editingId = '';

    const selectedProfile = () => editingId ? state.profiles[editingId] : null;
    const showAuthority = () => {
      const profile = activeProfile(state);
      const authority = container.querySelector('[data-byok-authority]');
      authority.hidden = !profile;
      if (profile) {
        container.querySelector('[data-byok-model]').textContent = profile.model;
        lockUpstreamModelControls(container, profile);
      }
    };
    const select = (id) => {
      editingId = id && state.profiles[id] ? id : '';
      renderProfileOptions(container, state, editingId);
      writeForm(container, selectedProfile(), editingId);
    };
    const reload = async () => {
      setStatus(container, 'Loading profiles…');
      try {
        state = await client.get();
        configurePiForProfile(activeProfile(state));
        select(state.activeProfileId || editingId);
        showAuthority();
        setStatus(container, 'Profiles loaded.');
      } catch (error) {
        setStatus(container, error?.message || 'Profiles could not be loaded.', 'error');
      }
    };
    const save = async (nextState, selectedId) => {
      setStatus(container, 'Saving profile…');
      try {
        state = await client.put(nextState);
        configurePiForProfile(activeProfile(state));
        select(selectedId || state.activeProfileId);
        showAuthority();
        setStatus(container, 'Profile saved.');
      } catch (error) {
        setStatus(container, error?.message || 'Profiles could not be saved.', 'error');
      }
    };

    launcher.addEventListener('click', () => { container.hidden = false; void reload(); });
    container.querySelector('[data-byok-close]').addEventListener('click', () => { container.hidden = true; launcher.focus(); });
    field(container, 'profilePicker').addEventListener('change', (event) => select(event.target.value));
    field(container, 'protocol').addEventListener('change', () => updateProtocolFields(container));
    container.querySelector('[data-byok-new]').addEventListener('click', () => select(''));
    container.querySelector('[data-byok-duplicate]').addEventListener('click', () => {
      const source = selectedProfile();
      editingId = '';
      renderProfileOptions(container, state, '');
      writeForm(container, copyProfile(source), '');
    });
    container.querySelector('[data-byok-rename]').addEventListener('click', () => {
      field(container, 'label').focus();
      field(container, 'label').select();
    });
    container.querySelector('[data-byok-reload]').addEventListener('click', () => { void reload(); });
    container.querySelector('[data-byok-save]').addEventListener('click', () => {
      const profile = { ...selectedProfile(), ...readForm(container, editingId), updatedAt: new Date().toISOString() };
      const profiles = { ...state.profiles };
      if (editingId && editingId !== profile.id) delete profiles[editingId];
      profiles[profile.id] = profile;
      const activeProfileId = state.activeProfileId || profile.id;
      void save({ ...state, profiles, activeProfileId }, profile.id);
    });
    container.querySelector('[data-byok-set-active]').addEventListener('click', () => {
      const profile = { ...selectedProfile(), ...readForm(container, editingId), updatedAt: new Date().toISOString() };
      const profiles = { ...state.profiles, [profile.id]: profile };
      void save({ ...state, profiles, activeProfileId: profile.id }, profile.id);
    });
    container.querySelector('[data-byok-delete]').addEventListener('click', () => {
      if (!editingId) return;
      const profiles = { ...state.profiles };
      delete profiles[editingId];
      void save({ ...state, profiles, activeProfileId: state.activeProfileId === editingId ? null : state.activeProfileId }, '');
    });
    void reload();
  }

  function unmount() {
    root.document.getElementById(ROOT_ID)?.remove();
    root.document.getElementById(LAUNCHER_ID)?.remove();
  }

  function install() {
    if (root.__OD_HA_BYOK_PROFILES_BRIDGE_INSTALLED__ || !isIngressPage()) return;
    root.__OD_HA_BYOK_PROFILES_BRIDGE_INSTALLED__ = true;
    const reconcile = () => {
      if (isSettingsPage()) mount();
      else unmount();
    };
    root.addEventListener?.('popstate', reconcile);
    new root.MutationObserver(reconcile).observe(root.document.documentElement, { childList: true, subtree: true });
    reconcile();
  }

  return {
    API_PATH,
    ProfilesClient,
    activeProfile,
    configurePiForProfile,
    createForRoot: (target) => createApi(target),
    emptyState,
    install,
    normalizeState,
  };
});
