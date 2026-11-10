import { RuntimeError } from './state.mjs';

const idPattern = /^[A-Za-z0-9_-]{8,128}$/;
const supported = new Set(['claude', 'codex', 'pi']);
const idle = agent => ['idle', 'error'].includes(agent?.status) && !agent.archivedAt && !agent.activeTurnId && !(agent.pendingPermissions?.length);
const sameNative = (a, b) => a?.provider === b?.provider && typeof a?.sessionId === 'string' && a.sessionId === b?.sessionId;
const refreshErrors = new Set(['SESSION_BUSY', 'MCP_RESUME_UNAVAILABLE', 'MCP_NATIVE_UNAVAILABLE', 'MCP_CONFIG_INVALID']);

function refreshErrorCode(error) {
  if (refreshErrors.has(error?.message)) return error.message;
  if (error?.requestType !== 'refresh_agent_request') return 'MCP_RELOAD_FAILED';
  if (refreshErrors.has(error?.code)) return error.code;
  // Paseo 0.11.2's DaemonRpcError keeps the generic RPC code and appends
  // routing metadata to message. Accept only its exact allowlisted forms;
  // never forward arbitrary error text, request IDs, or nested diagnostics.
  if (error?.name === 'DaemonRpcError' && error.code === 'agent_refresh_failed') {
    for (const code of refreshErrors) {
      if (error.message === `${code} requestType=refresh_agent_request code=agent_refresh_failed`) return code;
    }
  }
  return 'MCP_RELOAD_FAILED';
}

export async function refreshSharedMcp(client, agentId, sync) {
  if (!idPattern.test(agentId || '')) throw new RuntimeError('INVALID_SESSION_ID');
  const before = (await client.fetchAgent({ agentId }))?.agent;
  if (!before || !supported.has(before.provider)) throw new RuntimeError('MCP_REFRESH_UNSUPPORTED');
  if (!before.persistence) throw new RuntimeError('MCP_RESUME_UNAVAILABLE');
  if (!idle(before)) throw new RuntimeError('SESSION_BUSY');
  const synchronized = await sync();
  // The patched daemon repeats the busy check inside its lifecycle mutation.
  // A turn racing the client-side check is refused, never interrupted.
  let response;
  try { response = await client.refreshAgent(agentId); }
  catch (error) {
    throw new RuntimeError(refreshErrorCode(error));
  }
  if (response?.agentId !== agentId) throw new RuntimeError('MCP_REFRESH_UNCONFIRMED');
  const after = (await client.fetchAgent({ agentId }))?.agent;
  if (!after || after.id !== before.id || after.provider !== before.provider || !sameNative(after.persistence, before.persistence))
    throw new RuntimeError('MCP_REFRESH_UNCONFIRMED');
  return { sessionId: agentId, engine: before.provider,
    refresh: { state: 'resumed', method: 'native-resume', historyPreserved: true,
      configurationHash: synchronized.configurationHash, toolsVerified: false } };
}
