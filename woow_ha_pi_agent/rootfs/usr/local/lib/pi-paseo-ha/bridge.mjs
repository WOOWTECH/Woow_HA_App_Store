import { loadPlugin } from './lifecycle.mjs';
import { pairUrl } from './ingress.mjs';

const clean = value => typeof value === 'string' ? value.replace(/[\x00-\x1f\x7f]/g, '').slice(0, 200) : null;
const providers = ['claude', 'codex', 'pi'];
const unavailable = { installed: false, enabled: false, phase: 'unavailable', providers: [] };
export function createPaseoBridge(load = loadPlugin) {
  async function snapshot(plugin) {
    if (!plugin) return unavailable;
    if (!plugin.enabled) return { ...unavailable, installed: true, phase: 'disabled', version: plugin.version };
    const state = await plugin.api.status();
    return { installed: true, enabled: true, version: plugin.version, phase: clean(state.phase),
      running: state.daemon?.running === true, webReady: state.webClient?.ready === true, webVersion: clean(state.webClient?.version),
      onboardingUrl: /^[a-zA-Z0-9-]{1,80}$/.test(state.onboardingSessionId || '') ? '/?session=' + state.onboardingSessionId : null,
      providers: (state.providers || []).filter(row => providers.includes(row.provider)).map(row => ({
        provider: row.provider, status: clean(row.status), chatVerified: row.chatVerified === true,
        modes: (row.modes || []).map(mode => ({ id: clean(mode.id), label: clean(mode.label) })),
      })) };
  }
  return {
    async read() { return snapshot(await load()); },
    async act(body, prefix) {
      const plugin = await load();
      if (!plugin?.enabled) throw Object.assign(new Error('Plugin unavailable'), { code: 'PLUGIN_UNAVAILABLE' });
      if (body.action === 'pair') return { url: pairUrl((await plugin.api.pair()).url, prefix) };
      if (body.action === 'start') await plugin.api.lifecycle({ action: 'enable', cwd: process.env.HOME }, plugin.hooks);
      else if (body.action === 'stop') await plugin.api.lifecycle({ action: 'stop' });
      else if (body.action === 'models' && providers.includes(body.provider)) {
        const rows = await plugin.api.listModels(body.provider);
        return { models: (Array.isArray(rows) ? rows : rows.models || []).map(row => ({ id: clean(row.id), label: clean(row.label || row.name || row.id) })) };
      } else throw Object.assign(new Error('Invalid action'), { code: 'INVALID_ACTION' });
      return snapshot(plugin);
    },
    async web(request) {
      const plugin = await load();
      if (!plugin?.enabled) return new Response('Paseo plugin is disabled', { status: 409 });
      return plugin.api.web(request);
    },
  };
}
