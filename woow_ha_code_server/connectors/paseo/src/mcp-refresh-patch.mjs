import fs from 'node:fs';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {assertSafePath, RuntimeError} from './state.mjs';

const sha = source => createHash('sha256').update(source).digest('hex');
const helperSource = fs.readFileSync(new URL('./managed-mcp-config.mjs', import.meta.url));
export const MCP_REFRESH_HELPER_PATH = 'node_modules/@getpaseo/server/dist/server/server/agent/woow-managed-mcp.mjs';
export const MCP_REFRESH_HELPER_SHA256 = '6d8e117a106874132fc5d41f9c5703d5d9adedb5e0ac5833183ed5c24dda02aa';
// Exact installed 0.17.5 SDK bytes. Ordinary refresh requests keep upstream's
// interrupt, workspace restore, unarchive and cold-load behavior unchanged.
export const refreshRecipes = [
  {
    "path": "node_modules/@getpaseo/server/dist/server/server/agent/agent-manager.js",
    "before": "77daa18e6f9ec944058b1a075cf8ba17f6ea0e9de2fe9e1aa7a689461f2b2a45",
    "after": "5145619c6444c10e0288b3281ef9eea943b634911bc1b779a722fa747b75ead0",
    "replacements": [
      [
        "import { continuesAssistantMessage, projectTimelineRows,",
        "import { refreshedManagedConfig } from \"./woow-managed-mcp.mjs\";\nimport { continuesAssistantMessage, projectTimelineRows,"
      ],
      [
        "        return this.trackAgentRegistrationOperation(this.runLifecycleMutation(agentId, () => this.reloadAgentSessionInternal(agentId, overrides, options)));",
        "        return this.trackAgentRegistrationOperation(this.runLifecycleMutation(agentId, async () => {\n            if (options?.managedMcpRefresh === true) options = { ...options, requireIdle: true, requirePersistence: true };\n            if (options?.requireIdle) {\n                this.woowMcpRefreshes ??= new Set();\n                this.woowMcpRefreshes.add(agentId);\n            }\n            try { return await this.reloadAgentSessionInternal(agentId, overrides, options); }\n            finally { if (options?.requireIdle) this.woowMcpRefreshes.delete(agentId); }\n        }));"
      ],
      [
        "        let existing = this.requireSessionAgent(agentId);\n        if (this.hasInFlightRun(agentId)) {",
        "        if (options?.managedMcpRefresh === true && (this.collectingRuntimes.has(agentId) || !this.agents.get(agentId)?.session || this.historySessions.has(this.agents.get(agentId).session))) throw new Error(\"MCP_NATIVE_UNAVAILABLE\");\n        let existing = this.requireSessionAgent(agentId);\n        if (this.hasInFlightRun(agentId)) {"
      ],
      [
        "        if (this.hasInFlightRun(agentId)) {\n            await this.cancelAgentRunBefore(agentId, \"reload\");",
        "        if (this.hasInFlightRun(agentId)) {\n            if (options?.requireIdle) throw new Error(\"SESSION_BUSY\");\n            await this.cancelAgentRunBefore(agentId, \"reload\");"
      ],
      [
        "        const rehydrateFromDisk = options?.rehydrateFromDisk ?? false;",
        "        if (options?.requireIdle && (!['idle', 'error'].includes(existing.lifecycle) || existing.archivedAt || existing.pendingPermissions?.size || existing.pendingReplacement || this.pendingCancellations.has(agentId))) throw new Error(\"SESSION_BUSY\");\n        const rehydrateFromDisk = options?.rehydrateFromDisk ?? false;"
      ],
      [
        "        const handle = existing.persistence;\n        const provider = handle?.provider ?? existing.provider;",
        "        const handle = existing.persistence;\n        if (options?.requirePersistence && (!handle || handle.provider !== existing.provider || typeof handle.sessionId !== \"string\" || !handle.sessionId.trim())) throw new Error(\"MCP_RESUME_UNAVAILABLE\");\n        const provider = handle?.provider ?? existing.provider;"
      ],
      [
        "        const refreshConfig = {\n            ...existing.config,",
        "        let refreshConfig = {\n            ...existing.config,"
      ],
      [
        "        const { storedConfig, launchConfig, paseoToolPolicy } = await this.prepareSessionConfig(refreshConfig, agentId, { env: existing.launchEnv });",
        "        if (options?.managedMcpRefresh === true) refreshConfig = refreshedManagedConfig(refreshConfig);\n        const { storedConfig, launchConfig, paseoToolPolicy } = await this.prepareSessionConfig(refreshConfig, agentId, { env: existing.launchEnv });"
      ],
      [
        "        const providerLaunchConfig = this.resolveReloadLaunchConfig(existing, launchConfig, launchContext);\n        let session;",
        "        const providerLaunchConfig = this.resolveReloadLaunchConfig(existing, launchConfig, launchContext);\n        // Launch preparation awaited disk/plugin work; recheck before touching the native writer.\n        if (options?.requireIdle && (this.hasInFlightRun(agentId) || !['idle', 'error'].includes(existing.lifecycle) || existing.archivedAt || existing.pendingPermissions?.size || existing.pendingReplacement || this.pendingCancellations.has(agentId))) throw new Error(\"SESSION_BUSY\");\n        let session;"
      ],
      [
        "    async closeReloadedSession(session, agentId) {\n        let operation",
        "    async closeReloadedSession(session, agentId) {\n        if (this.woowMcpRefreshes?.has(agentId)) {\n            // A deadline cannot release a native writer. Retire this handle even\n            // after a late close; only an explicit reload may register its replacement.\n            this.woowMcpRetiredSessions ??= new WeakSet();\n            this.woowMcpRetiredSessions.add(session);\n        }\n        let operation"
      ],
      [
        "    streamAgent(agentId, prompt, options, promptStart) {\n        if (this.collectingRuntimes.has(agentId)",
        "    streamAgent(agentId, prompt, options, promptStart) {\n        if (this.woowMcpRefreshes?.has(agentId)) throw new Error(\"SESSION_BUSY\");\n        if (this.woowMcpRetiredSessions?.has(this.agents.get(agentId)?.session)) throw new Error(\"MCP_NATIVE_UNAVAILABLE\");\n        if (this.collectingRuntimes.has(agentId)"
      ]
    ]
  },
  {
    "path": "node_modules/@getpaseo/server/dist/server/server/session.js",
    "before": "c0ac24ec4507d3e7eb0120e4f4279427393660d3fa33810770e940f91a1c8637",
    "after": "41d1e97651a01195963ae69a7189be5b218cbc9fd895305f4db50ee92a562328",
    "replacements": [
      [
        "    async handleRefreshAgentRequest(msg) {\n        const { agentId, requestId } = msg;",
        "    async handleRefreshAgentRequest(msg) {\n        const { agentId, requestId, managedMcpRefresh } = msg;"
      ],
      [
        "            await this.restoreOwningWorkspaceForLegacyAgentRefresh(agentId);\n            await unarchiveAgentState(this.agentStorage, this.agentManager, agentId);",
        "            if (managedMcpRefresh !== true) {\n                await this.restoreOwningWorkspaceForLegacyAgentRefresh(agentId);\n                await unarchiveAgentState(this.agentStorage, this.agentManager, agentId);\n            }"
      ],
      [
        "                await this.interruptAgentIfRunning(agentId);\n                snapshot = await this.agentManager.reloadAgentSession(agentId, undefined, {\n                    rehydrateFromDisk: true,\n                });",
        "                if (managedMcpRefresh !== true) await this.interruptAgentIfRunning(agentId);\n                snapshot = await this.agentManager.reloadAgentSession(agentId, undefined, {\n                    rehydrateFromDisk: true,\n                    ...(managedMcpRefresh === true ? { managedMcpRefresh: true, requireIdle: true, requirePersistence: true } : {}),\n                });"
      ],
      [
        "            else {\n                const record = await this.agentStorage.get(agentId);\n                if (!record) {\n                    throw new Error(`Agent not found: ${agentId}`);\n                }\n                const registeredProviderIds = this.providerSnapshotManager.listRegisteredProviderIds();",
        "            else {\n                if (managedMcpRefresh === true) throw new Error(\"MCP_NATIVE_UNAVAILABLE\");\n                const record = await this.agentStorage.get(agentId);\n                if (!record) {\n                    throw new Error(`Agent not found: ${agentId}`);\n                }\n                const registeredProviderIds = this.providerSnapshotManager.listRegisteredProviderIds();"
      ]
    ]
  },
  {
    "path": "node_modules/@getpaseo/client/dist/daemon-client.js",
    "before": "d7efa40a8cdf95270f394c597f41c538e3c70e5a082155df5e16b71a5dc05ae9",
    "after": "c7bb6b92338e80c606499767ad7d04c5a6b249f962695667e95272da1a92f942",
    "replacements": [
      [
        "    async refreshAgent(agentId, requestId) {",
        "    async refreshAgent(agentId, requestId, options) {"
      ],
      [
        "            type: \"refresh_agent_request\",\n            agentId,\n            requestId: resolvedRequestId,",
        "            type: \"refresh_agent_request\",\n            agentId,\n            requestId: resolvedRequestId,\n            ...(options?.managedMcpRefresh === true ? { managedMcpRefresh: true } : {}),"
      ]
    ]
  },
  {
    "path": "node_modules/@getpaseo/protocol/dist/messages.js",
    "before": "2e9e803262b323812db3c120f4feb2fe1c965f74f83ed12c687f2d96ccb566e9",
    "after": "f8f1f28c528c4f7b2e85d9f5b38d3d4f32a7b71288417580e9551d7e43f33f9e",
    "replacements": [
      [
        "export const RefreshAgentRequestMessageSchema = z.object({\n    type: z.literal(\"refresh_agent_request\"),\n    agentId: z.string(),\n    requestId: z.string(),\n});",
        "export const RefreshAgentRequestMessageSchema = z.object({\n    type: z.literal(\"refresh_agent_request\"),\n    agentId: z.string(),\n    requestId: z.string(),\n    managedMcpRefresh: z.literal(true).optional(),\n});"
      ]
    ]
  }
];
export const MCP_REFRESH_PATCH_ID = sha(JSON.stringify({version:'0.17.5',helper:MCP_REFRESH_HELPER_SHA256,files:refreshRecipes.map(({path,before,after})=>({path,before,after}))}));

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
  if (sha(helperSource) !== MCP_REFRESH_HELPER_SHA256) throw new RuntimeError('MCP_REFRESH_HELPER_MISMATCH');
  const prepared = refreshRecipes.map(recipe => {
    const file = path.join(root, recipe.path);
    if (!assertSafePath(file)?.isFile()) throw new RuntimeError('MCP_REFRESH_SOURCE_MISMATCH');
    const before = fs.readFileSync(file, 'utf8');
    return {file, before, after:patchRefreshSource(before, recipe)};
  });
  const helper = path.join(root, MCP_REFRESH_HELPER_PATH);
  assertSafePath(helper);
  // Validate every source and destination before modifying an inactive prepared release.
  if (!fs.existsSync(helper) || !fs.readFileSync(helper).equals(helperSource)) fs.writeFileSync(helper, helperSource, {mode:0o644});
  for (const {file,before,after} of prepared) if (before !== after) fs.writeFileSync(file, after);
}
export function mcpRefreshPatchReady(root) {
  try {
    const helper = path.join(root, MCP_REFRESH_HELPER_PATH);
    assertSafePath(helper);
    return sha(helperSource) === MCP_REFRESH_HELPER_SHA256 && sha(fs.readFileSync(helper)) === MCP_REFRESH_HELPER_SHA256 && refreshRecipes.every(recipe => {
      const file = path.join(root, recipe.path);
      assertSafePath(file);
      return sha(fs.readFileSync(file)) === recipe.after;
    });
  } catch { return false; }
}
