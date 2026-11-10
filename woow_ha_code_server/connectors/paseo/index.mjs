import * as runtime from './src/runtime.mjs';
import { RuntimeError } from './src/state.mjs';

export const allowedActions = Object.freeze(['status', 'configure', 'start', 'stop', 'restore', 'models', 'verify', 'pair', 'chat', 'continue', 'switchModel', 'archive', 'diagnostics']);

export function normalizeRequest(request) {
  const result = { ...request };
  const alias = name => ['claude-code', 'claude_code'].includes(name) ? 'claude' : name;
  if (request.engine !== undefined) {
    if (request.provider !== undefined && alias(request.provider) !== alias(request.engine)) throw new RuntimeError('PROVIDER_SELECTION_CONFLICT');
    result.provider = alias(request.engine);
  } else if (request.provider !== undefined) result.provider = alias(request.provider);
  if (result.provider !== undefined && !['claude', 'codex', 'pi'].includes(result.provider)) throw new RuntimeError('INVALID_PROVIDER');
  if (request.action === 'verify' && result.provider && request.providers !== undefined && (!Array.isArray(request.providers) || request.providers.length !== 1 || alias(request.providers[0]) !== result.provider)) throw new RuntimeError('PROVIDER_SELECTION_CONFLICT');
  if (request.action === 'verify' && request.model !== undefined) {
    if (!result.provider || typeof request.model !== 'string' || !request.model) throw new RuntimeError('INVALID_MODEL');
    if (request.models?.[result.provider] !== undefined && request.models[result.provider] !== request.model) throw new RuntimeError('MODEL_SELECTION_CONFLICT');
    result.models = { ...request.models, [result.provider]: request.model };
  }
  return result;
}

function snapshot(value) {
  if (!value || !value.daemon) return value;
  const { state, ...publicValue } = value;
  return {
    ...publicValue,
    settings: { cwd: state?.settings?.cwd || null, displayName: state?.settings?.displayName || '', port: state?.port || null },
    verification: state?.acceptance || null,
    modelSwitches: state?.modelSwitches || [],
    online: value.daemon.reachable === true,
  };
}

export async function handle(request) {
  try {
    if (!request || typeof request !== 'object' || Array.isArray(request) || !allowedActions.includes(request.action)) throw new RuntimeError('INVALID_ACTION');
    request = normalizeRequest(request);
    if (request.timeoutMs !== undefined && (!Number.isInteger(request.timeoutMs) || request.timeoutMs < 1000 || request.timeoutMs > 600000)) throw new RuntimeError('INVALID_TIMEOUT');
    let result;
    switch (request.action) {
      case 'status': result = await runtime.status(); break;
      case 'diagnostics': result = await runtime.diagnose(); break;
      case 'configure': result = await runtime.configure(request.settings ? { ...request.settings } : request); break;
      case 'start': result = await runtime.activate(); break;
      case 'stop': result = await runtime.deactivate(); break;
      case 'restore': result = await runtime.restore(); break;
      case 'pair': result = await runtime.pair(); break;
      case 'models': result = request.provider ? await runtime.listModels(request.provider) : { providers: await Promise.all(['claude', 'codex', 'pi'].map(async provider => {
        try { return await runtime.listModels(provider); }
        catch (error) { return { provider, models: [], error: { code: /^[A-Z][A-Z0-9_]{0,63}$/.test(error.code || '') ? error.code : 'PROVIDER_MODELS_UNAVAILABLE' } }; }
      })) }; break;
      case 'verify': {
        result = await runtime.acceptance({ ...request, providers: request.providers || (request.provider ? [request.provider] : undefined) });
        result.ok = result.requestedPassed === true;
        if (!result.ok) result.error = { code: 'MODEL_VERIFICATION_FAILED', message: 'One or more requested agents did not complete both verified turns and cleanup.' };
        break;
      }
      case 'chat': result = await runtime.createChat(request); break;
      case 'continue': result = await runtime.continueChat(request); break;
      case 'switchModel': result = await runtime.switchModel(request); break;
      case 'archive': result = await runtime.archiveChat(request); break;
    }
    if (result?.status === 'error' || result?.status === 'permission_required') {
      result.ok = false;
      const code = result.code || (result.status === 'permission_required' ? 'PERMISSION_REQUIRED' : 'CHAT_FAILED');
      result.error = { code, message: code };
    }
    return { ok: true, connector: 'paseo', ...snapshot(result) };
  } catch (error) {
    const code = error instanceof RuntimeError || /^[A-Z][A-Z0-9_]{0,63}$/.test(error?.code || '') ? error.code : 'PASEO_RUNTIME_FAILED';
    // Never include arbitrary subprocess/SDK error text: it may contain tokens.
    return { ok: false, connector: 'paseo', error: { code, message: code === 'RUNTIME_MISSING' ? 'The pinned Paseo 0.11.2 runtime is missing or failed integrity checks.' : code } };
  }
}
