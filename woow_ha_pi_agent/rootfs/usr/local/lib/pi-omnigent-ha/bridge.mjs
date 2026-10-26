// Safe view/action bridge adapted from pi-omnigent-plugin v0.3.11 (MIT).
// Upstream source: integrations/pi-web/adapter.patch, lib/omnigent-runtime.ts.
import { loadPlugin } from './lifecycle.mjs';
import fs from 'node:fs';
import path from 'node:path';
const record = (value) => value && typeof value === "object" && !Array.isArray(value) ? value : {};
const text = (value) => typeof value === "string" ? value.replace(/[\x00-\x1f\x7f]/g, "").slice(0, 256) : null;
const code = (value) => typeof value === "string" && /^[A-Z_0-9]{1,64}$/.test(value) ? value : null;
function safeServer(value) {
    if (typeof value !== "string")
        return null;
    try {
        const url = new URL(value);
        return ["https:", "http:"].includes(url.protocol) && !url.username && !url.password && !url.search && !url.hash ? url.href.replace(/\/+$/, "") : null;
    }
    catch {
        return null;
    }
}
const emptyView = (installed = false) => ({ installed, active: false, version: null, phase: "unavailable", server: null,
    loginConfirmed: false, host: { id: null, name: null, connected: false }, engines: [], onboardingUrl: null });
function localRecord(file) {
    let fd;
    try {
        fd = fs.openSync(file, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW | fs.constants.O_NONBLOCK);
        const stat = fs.fstatSync(fd);
        if (!stat.isFile() || (stat.mode & 0o777) !== 0o600 || stat.uid !== process.getuid() || stat.size > 1024 * 1024) throw new Error('Unsafe plugin metadata');
        const value = JSON.parse(fs.readFileSync(fd, 'utf8'));
        if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Invalid plugin metadata');
        return value;
    } catch (error) { if (error.code === 'ENOENT') return null; throw error; }
    finally { if (fd !== undefined) fs.closeSync(fd); }
}
/** The same operations the installed plugin exposes, projected to safe UI data. */
export function createOmnigentBridge(load = loadPlugin) {
    async function snapshot(plugin) {
        const lifecycle = await plugin.lifecycle();
        if (!lifecycle.active)
            return { ...emptyView(true), version: plugin.version, phase: "disabled" };
        const current = await plugin.runtime.status();
        const host = record(current.host);
        const catalog = current.loginConfirmed === true && host.connected === true ? await plugin.runtime.catalog() : {};
        const catalogEngines = record(record(catalog.data).engines);
        const engines = record(current.engines), proofs = record(current.verification);
        const onboard = plugin.onboarding();
        const sessionId = typeof onboard.sessionId === "string" && /^[a-zA-Z0-9-]{1,80}$/.test(onboard.sessionId) ? onboard.sessionId : null;
        return { installed: true, active: true, version: plugin.version, phase: text(current.phase) || "unknown",
            server: safeServer(current.server), loginConfirmed: current.loginConfirmed === true,
            host: { id: text(host.id), name: text(host.name), connected: host.connected === true },
            onboardingUrl: sessionId ? `/?session=${encodeURIComponent(sessionId)}` : null,
            engines: ["claude", "codex", "pi"].map(key => {
                const engine = record(engines[key]), proof = record(proofs[key]), inventory = record(catalogEngines[key]);
                return { key, installed: engine.available === true, version: text(engine.version),
                    configured: typeof engine.configured === "boolean" ? engine.configured : text(engine.configured),
                    ready: inventory.ready === true, verified: proof.ok === true && proof.cleanup === "stopped" && proof.hostId === host.id && proof.server === current.server && (!proof.cliVersion || proof.cliVersion === engine.version),
                    reason: code(proof.reason), models: (Array.isArray(inventory.models) ? inventory.models : []).flatMap(value => {
                        const model = record(value), id = text(model.id);
                        return id ? [{ id, label: text(model.displayName) || id }] : [];
                    }) };
            }) };
    }
    return {
        async onboarding() {
            const none = { sessionId: null, pending: false };
            try {
                const plugin = await load();
                if (!plugin) return none;
                const lifecycle = await plugin.lifecycle();
                if (lifecycle.active !== true || lifecycle.registered !== true) return none;
                const { stateDir } = plugin.locations();
                const current = localRecord(path.join(stateDir, 'state.json'));
                // Missing state is a registered cold boot, not permission to open
                // an old conversation. Wait for explicit enabled saved state.
                if (!current) return { sessionId: null, pending: true };
                if (current.enabled !== true || current.nativeActive === false || !["new", "installing", "needs-login", "needs-verification", "error"].includes(current.phase)) return none;
                const onboard = localRecord(path.join(stateDir, 'onboarding.json'));
                if (!onboard) return { sessionId: null, pending: true };
                const id = onboard.sessionId;
                return typeof id === 'string' && /^[a-zA-Z0-9-]{1,80}$/.test(id) ? { sessionId: id, pending: true } : none;
            } catch { return none; }
        },
        async read() { const plugin = await load(); return plugin ? snapshot(plugin) : emptyView(); },
        async act(body) {
            const plugin = await load();
            if (!plugin || !(await plugin.lifecycle()).active)
                throw Object.assign(new Error("Plugin unavailable"), { code: "PLUGIN_UNAVAILABLE" });
            let result;
            if (body.action === "connect") {
                if (typeof body.server !== "string" || !body.server.trim() || body.server.length > 2048 || !safeServer(body.server.trim())
                    || typeof body.username !== "string" || !body.username.trim() || body.username.length > 256
                    || typeof body.password !== "string" || !body.password || body.password.length > 4096) {
                    throw Object.assign(new Error("Missing setup fields"), { code: "INVALID_SETUP" });
                }
                result = await plugin.runtime.initialize({ server: body.server.trim(), username: body.username.trim(), password: body.password, verify: false });
            }
            else if (body.action === "verify") {
                const engine = typeof body.engine === "string" && ["claude", "codex", "pi"].includes(body.engine) ? body.engine : undefined;
                if (body.engine !== undefined && !engine)
                    throw Object.assign(new Error("Invalid engine"), { code: "INVALID_ENGINE" });
                if (body.model !== undefined && (typeof body.model !== "string" || body.model.length > 256 || !engine))
                    throw Object.assign(new Error("Invalid model"), { code: "INVALID_MODEL" });
                result = await plugin.runtime.verify({ ...(engine ? { engine } : {}), ...(body.model ? { model: body.model } : {}) });
            }
            else if (body.action === "disconnect" && body.confirm === true)
                result = await plugin.runtime.disconnect();
            else
                throw Object.assign(new Error("Unsupported action"), { code: "INVALID_ACTION" });
            if (result.ok === true && ["connect", "disconnect"].includes(String(body.action))) {
                // Refresh only the plugin's saved setup conversation; that helper skips
                // an active model turn. A UI sync failure cannot undo a successful login.
                try {
                    await plugin.refreshOnboarding?.();
                }
                catch { }
            }
            // A targeted verification can succeed while other installed engines still
            // keep the overall setup in needs-verification. Report the operation's
            // result from this call's receipt, without changing global readiness.
            let operationOk = result.ok === true;
            let operationCode = code(record(result.error).code);
            if (body.action === "verify" && typeof body.engine === "string" && result.verification && !result.busy) {
                const proof = record(record(result.verification)[body.engine]);
                operationOk = proof.ok === true && proof.reply === "OMNIGENT_CONNECTION_OK" && proof.cleanup === "stopped"
                    && (body.model === undefined || proof.model === body.model);
                if (!operationOk)
                    operationCode = code(proof.reason) || operationCode;
            }
            if (body.action === "verify" && !operationOk && !operationCode && result.phase === "needs-verification")
                operationCode = "INCOMPLETE_CHAT_VERIFICATION";
            if (operationOk)
                operationCode = null;
            // Never project raw adapter messages, connection payloads or login inputs.
            return { ...await snapshot(plugin), operation: { ok: operationOk, code: operationCode } };
        },
    };
}
