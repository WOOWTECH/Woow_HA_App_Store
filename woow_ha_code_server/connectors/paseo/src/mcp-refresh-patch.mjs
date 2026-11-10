import fs from 'node:fs';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {assertSafePath, RuntimeError} from './state.mjs';
const helperSource = fs.readFileSync(new URL('./managed-mcp-config.mjs', import.meta.url), 'utf8');
const helperPath = 'node_modules/@getpaseo/server/dist/server/server/agent/woow-managed-mcp.mjs';
const sha = source => createHash('sha256').update(source).digest('hex');
// Pinned 0.11.2 user-initiated refresh: retain persistence, reject an active turn.
export const refreshRecipes = [
  {
    "path": "node_modules/@getpaseo/server/dist/server/server/agent/agent-manager.js",
    "before": "5baa385f48c1a06938ab3fcc073f4534fa0b04c1ec4a2c0228e653e929210450",
    "after": "68c9f64685ed40bb738c289b64b49839a605efcc26b70f680b446740630c5c43",
    "replacements": [
      [
        "import { projectTimelineRows }",
        "import { refreshedManagedConfig } from \"./woow-managed-mcp.mjs\";\nimport { projectTimelineRows }"
      ],
      [
        "        if (this.hasInFlightRun(agentId)) {\n            await this.cancelAgentRunBefore(agentId, \"reload\");",
        "        if (this.hasInFlightRun(agentId)) {\n            if (options?.requireIdle) throw new Error(\"SESSION_BUSY\");\n            await this.cancelAgentRunBefore(agentId, \"reload\");"
      ],
      [
        "        const handle = existing.persistence;\n        const provider = handle?.provider ?? existing.provider;",
        "        const handle = existing.persistence;\n        if (options?.requirePersistence && !handle) throw new Error(\"MCP_RESUME_UNAVAILABLE\");\n        const provider = handle?.provider ?? existing.provider;"
      ],
      [
        "        const refreshConfig = {\n            ...existing.config,",
        "        let refreshConfig = {\n            ...existing.config,"
      ],
      [
        "        const { storedConfig, launchConfig, paseoToolPolicy } = await this.prepareSessionConfig(refreshConfig, agentId);",
        "        if (options?.requireIdle && options?.requirePersistence) refreshConfig = refreshedManagedConfig(refreshConfig);\n        const { storedConfig, launchConfig, paseoToolPolicy } = await this.prepareSessionConfig(refreshConfig, agentId);"
      ],
      [
        "        const rehydrateFromDisk = options?.rehydrateFromDisk ?? false;",
        "        if (options?.requireIdle && (existing.pendingPermissions?.size || existing.pendingReplacement)) throw new Error(\"SESSION_BUSY\");\n        const rehydrateFromDisk = options?.rehydrateFromDisk ?? false;"
      ],
      [
        "        return this.trackAgentRegistrationOperation(this.runLifecycleMutation(agentId, () => this.reloadAgentSessionInternal(agentId, overrides, options)));",
        "        return this.trackAgentRegistrationOperation(this.runLifecycleMutation(agentId, async () => {\n            if (options?.requireIdle) {\n                this.woowMcpRefreshes ??= new Set();\n                this.woowMcpRefreshes.add(agentId);\n            }\n            try { return await this.reloadAgentSessionInternal(agentId, overrides, options); }\n            finally { if (options?.requireIdle) this.woowMcpRefreshes.delete(agentId); }\n        }));"
      ],
      [
        "    streamAgent(agentId, prompt, options) {\n        const existingAgent",
        "    streamAgent(agentId, prompt, options) {\n        if (this.woowMcpRefreshes?.has(agentId)) throw new Error(\"SESSION_BUSY\");\n        const existingAgent"
      ],
      [
        "    async closeReloadedSession(session, agentId) {\n        let operation",
        "    async closeReloadedSession(session, agentId) {\n        if (this.woowMcpRefreshes?.has(agentId)) {\n            // A timed-out close can still own the native writer. Keep this\n            // handle retired even after close settles, until explicit resume\n            // registers a different handle with the same native persistence.\n            this.woowMcpRetiredSessions ??= new WeakSet();\n            this.woowMcpRetiredSessions.add(session);\n        }\n        let operation"
      ],
      [
        "        const existingAgent = this.requireSessionAgent(agentId);\n        this.logger.trace",
        "        const existingAgent = this.requireSessionAgent(agentId);\n        if (this.woowMcpRetiredSessions?.has(existingAgent.session)) throw new Error(\"MCP_NATIVE_UNAVAILABLE\");\n        this.logger.trace"
      ]
    ]
  },
  {
    "path": "node_modules/@getpaseo/server/dist/server/server/session.js",
    "before": "f01a5c51771f8014cb1fcab99fdb33b42609ec14b3a0012cdfaa7713167bbde6",
    "after": "b672f54d0fb7dc06a9787a7fdc50f3067eb4c18b323b26577a7a2b481c304e3c",
    "replacements": [
      [
        "                await this.interruptAgentIfRunning(agentId);\n                snapshot = await this.agentManager.reloadAgentSession(agentId, undefined, {\n                    rehydrateFromDisk: true,\n                });",
        "                snapshot = await this.agentManager.reloadAgentSession(agentId, undefined, {\n                    rehydrateFromDisk: true,\n                    requireIdle: true,\n                    requirePersistence: true,\n                });"
      ],
      [
        "            else {\n                const record = await this.agentStorage.get(agentId);\n                if (!record) {\n                    throw new Error(`Agent not found: ${agentId}`);\n                }\n                const registeredProviderIds = this.providerSnapshotManager.listRegisteredProviderIds();\n                if (!isStoredAgentProviderAvailable(record, registeredProviderIds)) {\n                    throw new Error(`Agent ${agentId} references unavailable provider '${record.provider}'`);\n                }\n                if (!toAgentPersistenceHandle(registeredProviderIds, record.persistence)) {\n                    throw new Error(`Agent ${agentId} cannot be refreshed because it lacks persistence`);\n                }\n                // Share the loader's per-agent in-flight operation with timeline fetches.\n                // Unarchiving publishes the record before provider resume finishes, so\n                // the agent pane can otherwise race this request and resume it twice.\n                snapshot = await ensureAgentLoaded(agentId, {\n                    agentManager: this.agentManager,\n                    agentStorage: this.agentStorage,\n                    broadcastTimeline: true,\n                    logger: this.sessionLogger,\n                });\n            }\n",
        "            else {\n                // Open the original persisted conversation first. Do not use the\n                // legacy loader here: it can reintroduce stale managed config.\n                throw new Error(\"MCP_NATIVE_UNAVAILABLE\");\n            }\n"
      ]
    ]
  }
];
export function patchRefreshSource(source, recipe) {
  if (sha(source) === recipe.after) return source;
  if (sha(source) !== recipe.before) throw new RuntimeError('MCP_REFRESH_SOURCE_MISMATCH');
  for (const [before, after] of recipe.replacements) {
    if (source.split(before).length !== 2) throw new RuntimeError('MCP_REFRESH_ANCHOR_MISMATCH');
    source = source.replace(before, after);
  }
  if (sha(source) !== recipe.after) throw new RuntimeError('MCP_REFRESH_PATCH_MISMATCH');
  return source;
}
export function applyMcpRefreshPatch(root) {
  const prepared = refreshRecipes.map(recipe => {
    const file=path.join(root,recipe.path); assertSafePath(file);
    return [file,patchRefreshSource(fs.readFileSync(file,'utf8'),recipe)];
  });
  const helper = path.join(root,helperPath); assertSafePath(helper); fs.writeFileSync(helper,helperSource);
  for (const [file, source] of prepared) fs.writeFileSync(file,source);
}
export function mcpRefreshPatchReady(root) {
  try {return fs.readFileSync(path.join(root,helperPath),'utf8') === helperSource && refreshRecipes.every(recipe => sha(fs.readFileSync(path.join(root,recipe.path))) === recipe.after);}
  catch {return false;}
}
