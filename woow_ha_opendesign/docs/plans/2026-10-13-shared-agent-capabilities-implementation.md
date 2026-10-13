# Shared Agent Capabilities Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the four bundled CLIs discover the same persistent skills, MCP server catalog, portable plugin capabilities, and project files in the Home Assistant OpenDesign add-on.

**Architecture:** Keep a canonical store below `/data/opendesign/shared`. At startup, validate the store and expose Agent Skills via supported symlink discovery paths, generate native MCP configuration for each agent while preserving unmanaged settings, and expose a common workspace directory to the add-on user. Native plugins remain agent-specific; portable bundles declare supported adapters and are enabled only for runtimes that have an implementation. A CLI command reports paths and synchronization status without exposing secrets.

**Tech Stack:** Bash launcher, Node.js ESM using built-in modules, JSON manifests, existing Node test harness, Home Assistant add-on Docker image.

---

### Task 1: Document compatibility and shared-store contract

**Files:**
- Create: `docs/plans/2026-10-13-shared-agent-capabilities-implementation.md`
- Create: `docs/shared-agent-capabilities.md`
- Modify: `README_zh-TW.md`

**Steps:**
1. Record the capability matrix: Agent Skills and project files are portable; MCP definitions require per-agent translation and credentials remain local; plugin hooks/packages are native and need explicit adapters.
2. Define persistent paths and ownership under `/data/opendesign/shared`, first-run migration behavior, and safe handling of existing user config.
3. Document supported CLI paths and the `ha-opendesign-agents status` diagnostic output.
4. Completion: docs state exactly what synchronizes and what remains adapter-specific.

### Task 2: Add shared-store initializer and status command

**Files:**
- Create: `rootfs/opt/ha-opendesign/shared-agents.mjs`
- Create: `rootfs/usr/local/bin/ha-opendesign-agents`
- Modify: `Dockerfile`
- Modify: `rootfs/usr/local/bin/ha-opendesign`
- Test: `tests/shared-agents.test.mjs`
- Modify: `tests/run.sh`

**Steps:**
1. Add tests for fresh initialization, existing path preservation, invalid/symlink path rejection, and idempotent repeated startup.
2. Implement initializer using explicit allowlisted directories and symlinks; never replace a real user directory or follow an existing symlink outside the shared root.
3. Initialize only the shared root and standard capabilities directory at startup, then drop privileges and launch OpenDesign as before.
4. Add a status command that prints active canonical paths and which runtime links/configs exist; redact all environment values.
5. Completion: startup is idempotent and diagnostics contain no credentials.

### Task 3: Synchronize Agent Skills and shared instruction files

**Files:**
- Modify: `rootfs/opt/ha-opendesign/shared-agents.mjs`
- Test: `tests/shared-agents.test.mjs`
- Modify: `docs/shared-agent-capabilities.md`

**Steps:**
1. Add tests that canonical skills are discoverable under each runtime’s documented location and edits through any linked path update the canonical file.
2. Wire shared skills into Claude Code, Codex, Pi, and OpenCode supported global skill directories using links that do not disturb existing user data.
3. Provide one shared `AGENTS.md` context file through the common workspace root; document that agent-specific context files keep native precedence.
4. Completion: all four skill discovery paths resolve to the same canonical skill directories, and project files are shared when launched from the common workspace.

### Task 4: Translate shared MCP catalog into native runtime configuration

**Files:**
- Modify: `rootfs/opt/ha-opendesign/shared-agents.mjs`
- Test: `tests/shared-agents.test.mjs`
- Modify: `docs/shared-agent-capabilities.md`

**Steps:**
1. Define a versioned common MCP schema for stdio and HTTP servers with arguments, optional non-secret headers, and enabled state. Authentication values remain in each runtime's own login or environment mechanism.
2. Test native generation for Claude JSON, Codex TOML, Pi JSON, and OpenCode JSON; test preservation of existing unrelated entries, deterministic output, invalid input rejection, and secret redaction.
3. Generate only the add-on-managed server block/file atomically; preserve user-owned settings and credentials; never enable an untrusted command by copying from project content.
4. Completion: the same catalog produces valid native configurations for all four runtimes without clobbering user settings.

### Task 5: Define portable plugin bundles and native adapter boundary

**Files:**
- Modify: `rootfs/opt/ha-opendesign/shared-agents.mjs`
- Create: `docs/shared-plugin-manifest.schema.json`
- Test: `tests/shared-agents.test.mjs`
- Modify: `docs/shared-agent-capabilities.md`

**Steps:**
1. Specify a manifest whose portable components can include Agent Skills and MCP entries, plus explicit per-runtime native adapter declarations.
2. Test that an unsupported native plugin is reported as unsupported and never copied into another runtime’s executable plugin folder.
3. Implement discovery/status for adapters while leaving agent-native plugin install/enable lifecycle to its owning CLI.
4. Completion: shared portable components synchronize and incompatible native plugin code is never falsely treated as cross-compatible.

### Task 6: Verify image, upgrade persistence, GUI entry and publish readiness

**Files:**
- Modify as needed: `tests/container-smoke.sh`, `tests/container-smoke.test.mjs`, `README_zh-TW.md`, `CHANGELOG.md`, `config.yaml`, `Dockerfile`

**Steps:**
1. Run the full repository validation suite and build the add-on image for available architecture(s).
2. Run container-level checks against a fresh data volume and an upgrade-like existing volume, verifying links, MCP files, ownership, CLI versions, and repeated startup.
3. Through the Home Assistant GUI path, open the add-on Local Agent interface and confirm capability discovery/status for all four installed CLIs; keep provider-auth failure separately reported until each CLI is authenticated.
4. Bump release version, build/push through the repository’s established workflow only after verification, and deploy the candidate to the authorized HA instance if reachable.
5. Completion: record exact test output, image/tag/commit, GUI results, and any remaining authentication or upstream UI limitation without marking unverified behavior complete.
