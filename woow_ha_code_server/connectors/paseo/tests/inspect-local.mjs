// Read-only companion to the browser journey. Run in the SAME deployment as
// the tested daemon; remote callers can wrap this JSON stdin/stdout entrypoint.
import { pathToFileURL } from 'node:url';
import { withClient } from '../src/runtime.mjs';
import { assistantEntries, latestAssistantCursor } from '../src/chat-result.mjs';

export async function inspect(input) {
  if (!/^[A-Za-z0-9_-]{8,100}$/.test(input?.agentId || '')) return { ok: false, code: 'INVALID_AGENT_ID' };
  return withClient(async client => {
    const found = await client.fetchAgent({ agentId: input.agentId });
    if (!found?.agent) return { ok: false, code: 'AGENT_NOT_FOUND' };
    const agent = found.agent;
    if (input.archiveOnly) return { ok: true, archived: !!agent.archivedAt };
    const entries = await assistantEntries(client, input.agentId);
    return { ok: true, provider: agent.provider, model: agent.runtimeInfo?.model || null, cursor: latestAssistantCursor(entries), assistantMarkerMatched: typeof input.marker === 'string' && input.marker.length > 10 && (entries.at(-1)?.item.text || '').includes(input.marker) };
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    let bytes = 0, input = '';
    for await (const chunk of process.stdin) { bytes += chunk.length; if (bytes > 8192) throw new Error(); input += chunk; }
    process.stdout.write(JSON.stringify(await inspect(JSON.parse(input))) + '\n');
  } catch { process.stdout.write(JSON.stringify({ ok: false, code: 'INSPECTION_FAILED' }) + '\n'); process.exitCode = 1; }
}
