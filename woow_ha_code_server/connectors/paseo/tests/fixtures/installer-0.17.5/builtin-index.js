import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
export const builtinPlugins = [
    "antigravity-provider",
    "claude-usage-source",
    "codex-usage-source",
    "copilot-usage-source",
    "cursor-usage-source",
    "fx-provider",
    "goose-provider",
    "grok-usage-source",
    "hermes-provider",
    "hoplite-provider",
    "kimi-usage-source",
    "minimax-usage-source",
    "muse-provider",
    "opencode-go-usage-source",
    "openrouter-host-usage-source",
    "worktree-include",
    "zai-usage-source",
];
export function resolveBuiltinPluginsRoot(moduleUrl = import.meta.url) {
    const moduleDir = path.dirname(fileURLToPath(moduleUrl));
    const archiveSegment = `${path.sep}app.asar${path.sep}`;
    const archiveIndex = moduleDir.indexOf(archiveSegment);
    if (archiveIndex !== -1) {
        // esbuild runs outside Electron's filesystem shim and cannot read archive entries.
        return path.join(moduleDir.slice(0, archiveIndex), "builtin-plugins");
    }
    const candidates = [
        path.resolve(moduleDir, "..", "..", "..", "builtin-plugins"),
        path.resolve(moduleDir, "..", "..", "..", "..", "..", "..", "plugins"),
    ];
    return candidates.find((candidate) => existsSync(candidate)) ?? candidates[0];
}
export class BuiltinPluginLoader {
    constructor(root = resolveBuiltinPluginsRoot(), list = builtinPlugins) {
        this.root = root;
        this.list = list;
        this.ids = new Set(list);
    }
    async load(start) {
        for (const id of this.list) {
            await start({ id, directory: path.join(this.root, id) });
        }
    }
}
//# sourceMappingURL=index.js.map