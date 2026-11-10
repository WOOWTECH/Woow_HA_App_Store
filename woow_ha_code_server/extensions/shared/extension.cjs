'use strict';
const { createRuntime, settingsFrom, configureFields, validMessage, publicStatus, modelItems, safeText, webUrl, publicCode } = require('./runtime.cjs');
const { html } = require('./ui.cjs');

function createExtension(connector, dependencies = {}) {
  const vscode = dependencies.vscode || require('vscode');
  const name = connector === 'paseo' ? 'Paseo' : 'Omnigent';
  const prefix = `woow.${connector}`;
  let panel, output, emitter, busy = false, lastResult = { ok: true, phase: 'unknown' }, lastModels = [];
  function configuration() { return settingsFrom(vscode.workspace.getConfiguration(prefix)); }
  function state() {
    const result = publicStatus(lastResult, connector, configuration());
    if (!result.models.length) result.models = lastModels.map(m => ({ id: safeText(m.id), name: safeText(m.name), agent: safeText(m.agent) }));
    return result;
  }
  function render() { panel?.webview.postMessage({ type: 'status', state: state() }); emitter?.fire(); }
  function notice(text, error = false) { panel?.webview.postMessage({ type: 'notice', text, error }); }
  async function invoke(action, fields = {}) {
    const run = (dependencies.createRuntime || createRuntime)({ executable: configuration().runtimePath, onEvent: event => output?.appendLine(`${event.connector} ${event.action}: ${event.ok ? 'ok' : publicCode(event.code)}`) });
    return run({ connector, action, ...fields });
  }
  async function refresh() {
    lastResult = await invoke('status');
    render();
    return lastResult;
  }
  async function configure(provided) {
    let fields = provided;
    if (!fields) {
      const existing = configuration();
      const workspace = await vscode.window.showInputBox({ title: `${name}: workspace`, prompt: 'Absolute directory inside this code-server container', value: existing.workspace || '/workspace', ignoreFocusOut: true });
      if (workspace === undefined) return;
      const hostName = await vscode.window.showInputBox({ title: `${name}: host name`, value: existing.hostName || 'code-server', ignoreFocusOut: true });
      if (hostName === undefined) return;
      const key = connector === 'omnigent' ? 'server' : 'webUrl';
      const url = await vscode.window.showInputBox({ title: `${name}: ${connector === 'omnigent' ? 'server URL' : 'Web URL'}`, value: existing[key], ignoreFocusOut: true });
      if (url === undefined) return;
      fields = { workspace, hostName, [key]: url };
      if (connector === 'omnigent') {
        const browserUrl = await vscode.window.showInputBox({ title: 'Omnigent: browser Web URL (optional)', prompt: 'URL your browser can reach. Leave empty to open the server URL. No credentials, query, or fragment.', value: existing.webUrl, ignoreFocusOut: true });
        if (browserUrl === undefined) return;
        fields.webUrl = browserUrl;
      }
    }
    const normalized = configureFields(connector, fields);
    const { webUrl: localWebUrl, ...runtimeFields } = normalized;
    const result = await invoke('configure', runtimeFields);
    if (result.ok) {
      const config = vscode.workspace.getConfiguration(prefix);
      for (const [key, value] of Object.entries(normalized)) await config.update(key, value, vscode.ConfigurationTarget.Global);
      if (!localWebUrl) await config.update('webUrl', undefined, vscode.ConfigurationTarget.Global);
    }
    return result;
  }
  async function connect() {
    if (connector !== 'omnigent') return;
    const existing = configuration();
    if (!webUrl(existing.server, { server: true })) {
      const configured = await configure();
      if (!configured?.ok) return configured;
    }
    const username = await vscode.window.showInputBox({ title: 'Omnigent: username', prompt: 'Your account on the configured Omnigent server', ignoreFocusOut: true, validateInput: v => !v.trim() || v.length > 256 || /[\x00-\x1f]/.test(v) ? 'Enter a valid username.' : undefined });
    if (username === undefined) return;
    let password = await vscode.window.showInputBox({ title: 'Omnigent: password', password: true, ignoreFocusOut: true, prompt: 'Sent once to this deployment’s connector runtime; not saved in editor settings.' });
    if (password === undefined) return;
    try { return await invoke('connect', { server: configuration().server, username: username.trim(), password }); }
    finally { password = ''; }
  }
  async function verify() {
    const catalog = await invoke('models');
    if (!catalog.ok) return catalog;
    lastModels = modelItems(catalog);
    const selected = await vscode.window.showQuickPick([
      { label: 'Claude Code', engine: 'claude' }, { label: 'Codex', engine: 'codex' }, { label: 'Pi Agent', engine: 'pi' },
    ], { title: `${name}: choose an agent for a real conversation test`, ignoreFocusOut: true });
    if (!selected) return;
    const aliases = selected.engine === 'claude' ? ['claude', 'claude-code', 'claude_code'] : [selected.engine];
    const models = lastModels.filter(item => !item.agent || aliases.includes(item.agent.toLowerCase()));
    let model;
    if (models.length) {
      const item = await vscode.window.showQuickPick(models.map(m => ({ label: safeText(m.name), description: safeText(m.id), model: m.id })), { title: `${name}: model for ${selected.label}`, ignoreFocusOut: true });
      if (!item) return;
      model = item.model;
    } else {
      model = await vscode.window.showInputBox({ title: `${name}: model ID for ${selected.label}`, prompt: 'No model inventory was reported. Enter an authorized model ID, or leave empty to use the agent default.', ignoreFocusOut: true });
      if (model === undefined) return;
    }
    if (model && (model.length > 512 || /[\x00-\x1f]/.test(model))) throw new Error('Invalid model ID.');
    const result = await invoke('verify', { engine: selected.engine, ...(model ? { model } : {}) });
    if (result.ok) {
      const receipt = result.verification ?? result.acceptance ?? result;
      const verified = result.verified === true || receipt.requestedPassed === true || receipt.passed === true || receipt.status === 'passed' || result.verification?.ok === true;
      await vscode.window.showInformationMessage(verified ? `${name}: conversation verification passed.` : `${name}: verification request completed. The runtime has not reported a verified reply; inspect its verification status.`);
    }
    return result;
  }
  async function openWeb(pair = false) {
    let url;
    if (pair) {
      const response = await invoke('pair');
      if (!response.ok) return response;
      const data = response.data ?? response;
      url = webUrl(data.url ?? data.pairingUrl ?? data.pairUrl ?? data.pairing?.url ?? data.offer?.url);
      // Pairing carries authorization. Only the explicit configured Web origin or
      // official Paseo Web may receive it; never post this URL to a webview or log.
      const configured = webUrl(configuration().webUrl, { server: true });
      if (!url || !['https://app.paseo.sh', ...(configured ? [new URL(configured).origin] : [])].includes(new URL(url).origin)) return { ok: false, error: { code: 'INVALID_PAIRING_URL' } };
    } else {
      const config = configuration();
      url = webUrl(connector === 'omnigent' ? config.webUrl || config.server : config.webUrl, { server: true });
    }
    if (!url) return { ok: false, error: { code: 'WEB_URL_REQUIRED' } };
    const opened = await vscode.env.openExternal(vscode.Uri.parse(url));
    url = '';
    return opened ? { ok: true } : { ok: false, error: { code: 'BROWSER_OPEN_FAILED' } };
  }
  async function perform(action, fields) {
    if (!vscode.workspace.isTrusted) {
      await vscode.window.showErrorMessage('Trust this workspace before using connector controls.');
      return;
    }
    if (busy) { notice('An operation is already running.'); return; }
    busy = true;
    panel?.webview.postMessage({ type: 'busy', busy: true });
    let result;
    try {
      if (action === 'settings') {
        // Machine settings live in the container. The browser's local User tab
        // hides them, so opening the default Settings page shows no results.
        const remote = vscode.env.remoteName || (vscode.UIKind && vscode.env.uiKind === vscode.UIKind.Web);
        return await vscode.commands.executeCommand(remote ? 'workbench.action.openRemoteSettings' : 'workbench.action.openSettings', { query: `@ext:woowtech.${connector}` });
      }
      if (action === 'status') {
        result = await refresh();
        if (!panel) {
          const current = state();
          await vscode.window.showInformationMessage(`${name}: connection ${current.phase}; conversation ${current.verification}${current.error ? `; ${current.error}` : ''}.`);
        }
      }
      else if (action === 'configure') result = await configure(fields);
      else if (action === 'connect') result = await connect();
      else if (action === 'verify') result = await verify();
      else if (action === 'pair') result = await openWeb(true);
      else if (action === 'openWeb') result = await openWeb(false);
      else if (action === 'models') {
        result = await invoke('models');
        if (result.ok) {
          lastModels = modelItems(result);
          if (!panel) {
            if (lastModels.length) await vscode.window.showQuickPick(lastModels.map(model => ({ label: safeText(model.name), description: safeText(model.agent), detail: safeText(model.id) })), { title: `${name}: available models`, placeHolder: 'View inventory; change models in the Web conversation.', ignoreFocusOut: true });
            else await vscode.window.showInformationMessage(`${name}: the runtime has not reported a model inventory.`);
          }
        }
      } else if (['start', 'stop', 'restore', 'disconnect'].includes(action)) result = await invoke(action);
      else throw new Error('Unsupported action.');
      if (result && action !== 'status') await refresh();
      if (result?.ok === false && action !== 'status') await vscode.window.showErrorMessage(`${name}: ${publicCode(result.error?.code)}. Check configuration and runtime availability.`);
      return result;
    } catch (error) {
      // Only our validation errors are shown; runtime stderr is never forwarded.
      const message = error instanceof Error && /^(Invalid |Unknown configuration|Workspace must |Server must |Web URL must |Unsupported action)/.test(error.message) ? safeText(error.message) : 'Connector operation could not be completed.';
      notice(message, true);
      await vscode.window.showErrorMessage(message);
      return { ok: false, error: { code: 'CLIENT_ERROR' } };
    } finally {
      busy = false;
      panel?.webview.postMessage({ type: 'busy', busy: false });
      render();
      if (result) notice(result.ok ? (action === 'verify' ? 'Verification request finished. Check the recorded conversation status.' : 'Operation completed.') : `Operation failed: ${publicCode(result.error?.code)}`, !result.ok);
    }
  }
  function open() {
    if (panel) { panel.reveal(); return; }
    panel = vscode.window.createWebviewPanel(`${prefix}.connection`, `WOOW ${name}`, vscode.ViewColumn.One, { enableScripts: true, localResourceRoots: [], retainContextWhenHidden: false });
    panel.webview.html = html(connector);
    panel.webview.onDidReceiveMessage(message => {
      if (!validMessage(message)) return;
      if (connector !== 'paseo' && message.action === 'pair') return;
      if (connector !== 'omnigent' && ['connect', 'disconnect'].includes(message.action)) return;
      void perform(message.action, message.fields);
    });
    panel.onDidDispose(() => { panel = undefined; });
  }
  function activate(context) {
    output = vscode.window.createOutputChannel(`WOOW ${name}`);
    emitter = new vscode.EventEmitter();
    context.subscriptions.push(output, emitter);
    const actions = ['status', 'configure', 'start', 'stop', 'restore', 'models', 'verify', 'openWeb', 'settings', ...(connector === 'paseo' ? ['pair'] : ['connect', 'disconnect'])];
    context.subscriptions.push(vscode.commands.registerCommand(`${prefix}.open`, open));
    for (const action of actions) context.subscriptions.push(vscode.commands.registerCommand(`${prefix}.${action}`, () => perform(action)));
    const tree = {
      onDidChangeTreeData: emitter.event,
      getTreeItem: item => item,
      getChildren: () => {
        const current = state();
        return [
          { label: `Connection: ${current.phase}`, description: current.host, command: { command: `${prefix}.open`, title: 'Open connection' } },
          { label: `Conversation: ${current.verification}`, description: current.verifiedAt, command: { command: `${prefix}.verify`, title: 'Verify conversation' } },
          ...current.engines.map(engine => ({ label: engine.id, description: `installed ${engine.installed} · signed in ${engine.authenticated}` })),
          { label: 'Configure & connect', command: { command: `${prefix}.open`, title: 'Open connection' } },
          { label: 'Refresh status', command: { command: `${prefix}.status`, title: 'Refresh status' } },
        ];
      },
    };
    context.subscriptions.push(vscode.window.registerTreeDataProvider(`${prefix}.statusView`, tree));
    context.subscriptions.push(vscode.workspace.onDidChangeConfiguration(event => { if (event.affectsConfiguration(prefix)) render(); }));
    context.subscriptions.push({ dispose: () => { panel?.dispose(); panel = undefined; } });
    // Activation does not connect, restore, pair, or create a conversation.
    return { perform, refresh, getPublicState: state };
  }
  function deactivate() { panel?.dispose(); panel = undefined; }
  return { activate, deactivate };
}
module.exports = { createExtension };
