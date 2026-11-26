import { loadPlugin } from './lifecycle.mjs';
import { pairUrl, connectionTargets, targetId } from './ingress.mjs';

const clean = value => typeof value === 'string' ? value.replace(/[\x00-\x1f\x7f]/g, '').slice(0, 200) : null;
const providers = ['claude', 'codex', 'pi'];
const unavailable = { installed: false, enabled: false, phase: 'unavailable', providers: [] };
const failure = code => Object.assign(new Error(code), { code });
export function createPaseoBridge(load = loadPlugin) {
  let mutationInProgress = false;
  async function snapshot(plugin) {
    if (!plugin) return unavailable;
    if (!plugin.enabled) return { ...unavailable, installed: true, phase: 'disabled', version: plugin.version };
    const state = await plugin.api.status();
    const selectedTarget = targetId(state.settings?.target);
    return { installed: true, enabled: true, version: plugin.version, phase: clean(state.phase),
      selectedTarget, activeTarget: state.activeTarget == null ? null : targetId(state.activeTarget),
      configurationPending: state.configurationPending === true,
      targetSelectionAvailable: typeof plugin.api.saveConfig === 'function' && connectionTargets.every(target =>
        state.connectionTargets?.some(item => item.id === target.id)),
      connectionTargets, settings: { target: selectedTarget },
      running: state.daemon?.running === true,
      reachable: state.daemon?.reachable === true,
      providers: (state.providers || []).filter(row => providers.includes(row.provider)).map(row => ({
        provider: row.provider, status: clean(row.status), chatVerified: row.chatVerified === true,
        modes: (row.modes || []).map(mode => ({ id: clean(mode.id), label: clean(mode.label) })),
      })) };
  }
  return {
    async read() { return snapshot(await load()); },
    async act(body) {
      // Two HA settings pages must not change the saved brand between another
      // page's start precheck and its lifecycle receipt. Refuse concurrent
      // writes instead of queuing a mutation after its browser has timed out.
      const mutation = ['save', 'start', 'stop'].includes(body.action);
      if (mutation && mutationInProgress) throw failure('STATE_BUSY');
      if (mutation) mutationInProgress = true;
      try {
        const plugin = await load();
        if (!plugin?.enabled) throw failure('PLUGIN_UNAVAILABLE');
        if (body.action === 'save') {
          // Only the target is accepted and forwarded. The plugin keeps every saved
          // setting that a save leaves out, so this page cannot change the display
          // name or agentCollaboration (0.1.22+, off by default; no switch here yet).
          if (Object.keys(body).some(key => !['action', 'target'].includes(key)) || !Object.hasOwn(body, 'target')) throw failure('INVALID_SETTINGS');
          const target = targetId(body.target);
          if (!(await snapshot(plugin)).targetSelectionAvailable) throw failure('TARGET_SELECTION_UNSUPPORTED');
          await plugin.api.saveConfig({ target });
        } else if (body.action === 'pair') {
          const before = await snapshot(plugin);
          const target = body.target === undefined ? before.selectedTarget : targetId(body.target);
          if (before.configurationPending || target !== before.selectedTarget) throw failure('CONFIGURATION_PENDING');
          const paired = await plugin.api.pair();
          const after = await snapshot(plugin);
          if (after.configurationPending || after.selectedTarget !== target || (paired.target ?? 'paseo') !== target) throw failure('CONFIGURATION_PENDING');
          return { url: pairUrl(paired.url, target), target };
        } else if (body.action === 'start') {
          const before = await snapshot(plugin);
          if (before.configurationPending && before.running) throw failure('CONFIGURATION_PENDING');
          if (body.target !== undefined && targetId(body.target) !== before.selectedTarget) throw failure('CONFIGURATION_PENDING');
          const result = await plugin.api.lifecycle({ action: 'enable', cwd: process.env.HOME });
          // enable schedules the supervisor; its immediate snapshot can still say
          // disabled. Preserve the receipt so the page follows the actual startup.
          const after = await snapshot(plugin);
          if (after.selectedTarget !== before.selectedTarget) throw failure('CONFIGURATION_PENDING');
          return { ...after, startScheduled: result?.scheduled === true };
        }
        else if (body.action === 'stop') await plugin.api.lifecycle({ action: 'stop' });
        else if (body.action === 'models' && providers.includes(body.provider)) {
          const rows = await plugin.api.listModels(body.provider);
          return { models: (Array.isArray(rows) ? rows : rows.models || []).map(row => ({ id: clean(row.id), label: clean(row.label || row.name || row.id) })) };
        } else throw failure('INVALID_ACTION');
        return await snapshot(plugin);
      } finally { if (mutation) mutationInProgress = false; }
    },
  };
}
