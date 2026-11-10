# WOOW Omnigent connector runtime

This adapter implements `handle(request)` for the parent JSON CLI. It does not
install Pi extensions, change the provider account, or install extra engine CLIs.

Build the private runtime with:

```sh
connectors/omnigent/install-runtime.sh /opt/woow-connectors/omnigent/runtime
```

Requires Python 3.12+ and `uv` (or a working Python venv/pip). All Python packages
are hash pinned in `requirements.lock`, reusing the PaaS code-server 0.16.0 lock.
The build patches private session skills/MCP inheritance, then removes the unused
Claude SDK bundled executable; the deployment must supply Claude/Codex/Pi and tmux.
The root CLI location is controlled by the parent, not this adapter.

The runtime chooser uses `WOOW_OMNIGENT_PYTHON`, then `OG_PYTHON`, then the existing
PaaS `/opt/omnigent/tools/omnigent/bin/python`, then `./runtime/bin/python`. Explicit
paths are deployment environment, never request fields. On PaaS, patch the existing
runtime at image build using its Python and `patch-runtime.py`; do not install or
start a second host. Export `WOOW_OMNIGENT_SHARED_TOOLS=1` in the deployment environment
so the existing kit and every native runner inherit the shared-tools patch.

For PaaS, the preferred scoped integration is to put
`python3 /opt/woow-connectors/omnigent/kit-entry.py` **before** the existing
`omnigent-host-entry` in code-server's entrypoint (after dumb-init). It prepares a
private temporary overlay of the mounted canonical kit and exports `OG_KIT_DIR`
to the existing launcher and product. Only the overlay supervisor is patched;
canonical chart sources, ConfigMaps, other charts and host identity do not change.
The owned supervisor copy gains owner-write permission so a non-root image can
patch a ConfigMap projected with mode `0555`; the mounted source remains read-only.
Unknown source hashes fall back to the original kit with pause unsupported.
It also adds shared-tools names to `OG_PASSTHROUGH` so native runners inherit the
same engine homes. There is still exactly one supervisor.

For an intentional canonical upgrade, `python3 patch-kit.py /staging/supervisor.sh`
can instead transform the 88e37186 source before the normal chart sync process.
The optional pause contract introduces
`OG_PAUSE_FILE` (default `$OG_STATE_DIR/connector-paused`), writes `state: paused` only
after the kit has stopped its own child, and survives container restart. The adapter
reports `pauseSupported: false` / `PAUSE_UNSUPPORTED` on an unpatched kit, instead of
killing a process which the watchdog would restart. Both patchers fail on unexpected
source hashes and validate their receipts when reapplied.

State is private beneath `$WOOW_CONNECTOR_DATA_DIR/omnigent` or
`$PI_AGENT_DATA_DIR/connectors/omnigent`. On Podman/HA the SDK lives below this state's
`sdk/`; on PaaS it uses the kit's existing `OG_CONFIG_HOME`/`OG_DATA_DIR`.
Passwords travel through stdin only and are never written by the adapter. SDK tokens
stay in the same deployment's official SDK store. `stop` retains those tokens;
`disconnect` clears only the selected server's SDK token and retains the host ID.

Actions: `configure`, `connect`, `status`, `models`, `verify`, `stop`, `start`,
`restore`, `disconnect`. Configuration accepts `server`, `workspace`, `hostName`;
connect also accepts `username`, `password`. `verify` accepts `engine` (claude,
codex, pi), optional `model` from the live catalogue and `timeoutSeconds` bounded
to 180 seconds by the controller. It creates its own verification session, checks
**assistant** output, and stops that session. It does not declare tool use, model
switching or a multi-turn test successful; parent end-to-end tests cover those.

For end-to-end clients, `chat {engine,model?,prompt}` creates an owned session and
sends one message. `continue {sessionId,prompt}` sends another; `switchModel
{sessionId,model}` uses the live catalogue and PATCHes the same session, then reads
back its effective model. `session {sessionId}` returns only assistant messages
and effective model; `archive {sessionId}` stops and archives that owned session.
These transport calls never claim a model reply from a user echo: `replyVerified`
remains false for the caller to make its own turn-specific assertions. Remote IDs
not created by this connector are rejected. No permission policy is bypassed.

Explicit HTTP URLs are permitted for loopback, RFC1918, Tailscale CGNAT/IPv6 ULA,
`*.svc.cluster.local`, `omnigent-server`, and `host.containers.internal`. Public
endpoints require HTTPS; TLS certificate verification is never disabled and URLs
containing credentials, query strings or fragments are rejected. Nothing silently
downgrades an HTTPS URL or selects a private URL for the user.

`restore` with no saved successful authority is a no-op; a persisted `stop` prevents
periodic restoration. `start` resumes an existing receipt; it does not log in.
Receipt identity binds server, host, workspace and SDK state roots. Remote owner
identity is checked before starting. Mutations use a cross-process `flock`; status
and catalogue remain available during a verification. PaaS host name/workspace
must match the kit environment. A configured but stopped kit is never replaced by
a private connector host.

New native Codex sessions retain the copied `config.toml` (MCP) and symlink shared
skills; session `/model` changes stay private. Managed Pi sessions inherit the
deployment agent directory's settings plus skills/extensions/prompts/MCP. Claude
continues to use the deployment `CLAUDE_CONFIG_DIR`. Changes to MCP require a new
agent session. Provider auth is not copied between deployments.

With the shared-tools flag enabled, Pi's model picker also includes custom
providers from the deployment's `models.json`, filtered to providers present in
its native `auth.json`. This supports authenticated OpenAI-compatible gateways
such as LiteLLM even when `models-store.json` has no built-in model catalogue.
Model IDs retain the full `provider/model` path, including nested model IDs.
Custom entries extend the built-in catalogue and override duplicate display
names; URLs and credentials are never included in catalogue responses.

The connector and scoped PaaS entry overlay set `DISABLE_AUTOUPDATER=1` and
explicitly forward it through the host/runner environment allowlist. The image
owns the pinned native CLIs. Without this forwarding, a native Claude session
can start its npm self-updater even though the host itself inherited the flag,
temporarily remove the CLI from PATH, and replace the pinned version. Regression
coverage exercises the actual Omnigent 0.16.0 runner environment filter and also
checks that unrelated environment secrets remain filtered.

Tests: `python3 -m unittest discover -s connectors/omnigent/tests -p 'test_*.py'`
and `node --test connectors/omnigent/tests/*.test.mjs`. These tests are isolated;
they do not authenticate to a live server or count as real model acceptance.
Run the Python suite with the **installed private runtime's Python** to exercise
real SDK session-home inheritance. Set `WOOW_TEST_KIT_SOURCE` to a read-only
canonical kit path to include real supervisor pause/restart/recovery tests using
that kit's fake CLI and HTTP server. Both optional suites clearly report skips
when their runtime/source fixture is unavailable.

## Provenance

- `vendor/controller.py`: MIT, WOOWTECH/pi-omnigent-plugin commit
  `3243b231c9862f36d480c5144775f585c1305207`, `src/omnigent.py`, SHA-256
  `252b2a3aa75ec53402c437af1c6331d6a18e4078d5cdd96dc111577b1ccf7b88`.
  Copied unchanged; see `vendor/LICENSE.pi-omnigent`. The subclass replaces Pi's
  lifecycle without importing its Node package manager or SDK.
- `requirements.lock`: PaaS `paas-odoo-ci` code-server image source `c93004ec`,
  SHA-256 `74e3f6298ce131bc987b5800a7c8fadab62223fe55d5faa47772787bd9320e50`.
- Runtime patch targets are distributed by pinned Omnigent 0.16.0; no SDK source
  is vendored. Exact original hashes and transformations are in `patch-runtime.py`.
- Kit patch targets canonical `woow-paas-charts/shared/omnigent-host/supervisor.sh`
  SHA-256 `88e3718688edc48cee39d4c323520eb5c0165e6796e683fee3e267676015870c`.
  No chart source is vendored or directly edited by this scoped implementation.
