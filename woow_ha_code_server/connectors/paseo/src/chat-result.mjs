import { providerReplyError } from './provider-reply.mjs';

export async function assistantEntries(client, agentId) {
  const timeline = await client.fetchAgentTimeline(agentId, { limit: 50 });
  return (timeline.entries || []).filter(entry => entry.item?.type === 'assistant_message' && entry.item.text?.trim());
}

// A bounded timeline window can retain the same length after a new turn.
// Paseo sequence ranges and turn IDs identify messages independently of text.
export function latestAssistantCursor(entries) {
  const entry = entries.at(-1);
  return entry ? JSON.stringify([entry.turnId, entry.seqStart, entry.seqEnd, entry.timestamp]) : null;
}

export async function chatResult(client, agentId, provider, model, timeoutMs, previousCursor = null) {
  const turn = await client.waitForFinish(agentId, timeoutMs);
  const entries = turn.status === 'timeout' ? [] : await assistantEntries(client, agentId);
  const hasNewReply = entries.length > 0 && latestAssistantCursor(entries) !== previousCursor;
  const reply = hasNewReply ? String(entries.at(-1).item.text) : '';
  const errorCode = providerReplyError(reply);
  const status = turn.status === 'timeout' ? 'pending' : turn.status === 'permission' ? 'permission_required' : turn.status === 'idle' && reply && !errorCode ? 'completed' : 'error';
  return { agentId, provider, model, reply, status, ...(errorCode ? { code: errorCode } : {}) };
}
