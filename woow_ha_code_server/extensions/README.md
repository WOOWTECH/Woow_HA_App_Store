# WOOW code-server connector extensions

Two independently installable workspace-host extensions: `woowtech.paseo` and `woowtech.omnigent`. Sources shared under `shared/` are copied into each package by the build; VSIX files have no runtime npm dependencies and no gallery dependencies.

## Build, test, package

Requires Node 22+, npm, and Python 3 for deterministic ZIP timestamps. Packaging pins `@vscode/vsce` 4.1.0 and its `minimatch` dependency to 11.0.1 (the patched glob-amplification release), with integrity-pinned transitive versions in `package-lock.json`.

```sh
npm ci --ignore-scripts --prefix extensions
npm test --prefix extensions
npm run package --prefix extensions
(cd extensions/dist && sha256sum --check SHA256SUMS)
```

`extensions/dist/` contains two `.vsix` files, `SHA256SUMS`, and `manifest.json` with this top-level array schema:

```json
[
  {"id":"woowtech.paseo","version":"0.1.4","file":"woowtech.paseo-0.1.4.vsix","sha256":"<sha256>"},
  {"id":"woowtech.omnigent","version":"0.1.4","file":"woowtech.omnigent-0.1.4.vsix","sha256":"<sha256>"}
]
```

`SOURCE_DATE_EPOCH` defaults to a fixed source epoch; set it to a chosen release commit timestamp if needed. Repeating package with the same source, lockfile and epoch must produce identical checksums. Generated packages/output and `node_modules` are ignored by Git.

The deployment installer can copy this directory to `/opt/woow-connector-vsix` and install both into the user's extension directory. Respect explicit uninstall and manually installed newer versions. This package does not edit startup installation receipts or run itself on the host.

## Runtime contract

Each action executes the machine-scoped absolute executable (default `/usr/local/bin/woow-connectors`) with `shell:false`, no arguments, one JSON object through stdin, and one JSON result on stdout. Passwords only occur in the connect request's stdin. Stderr is drained but never forwarded to editor logs because third-party tools can print credentials.

Requests are flat, not wrapped in `fields`:

```json
{"connector":"paseo","action":"configure","workspace":"/workspace","hostName":"code-server"}
{"connector":"omnigent","action":"configure","workspace":"/workspace","hostName":"code-server","server":"https://omnigent.example.org/"}
{"connector":"omnigent","action":"connect","server":"https://omnigent.example.org/","username":"operator","password":"<transient>"}
{"connector":"paseo","action":"verify","engine":"codex","model":"<selected-id>"}
```

Other actions: `status`, `start`, `stop`, `restore`, `models`; Paseo `pair`; Omnigent `disconnect`. Default timeout 45s, start/restore 130s, models/connect 180s, verify 420s; output maximum 2 MiB. Timed-out children receive SIGTERM then SIGKILL. The runtime must coordinate its own long-lived daemon, independent of the short-lived CLI or extension host.

Responses require `{ok:boolean}`. Errors use `{ok:false,error:{code:"UPPER_SNAKE_CASE",message:"..."}}`. The client only renders the code, not arbitrary error message/stderr. A nonzero exit cannot return success.

The renderer tolerates absent fields, a `data` wrapper, and arrays/maps for engines/models. Preferred public status:

```json
{
  "ok": true,
  "phase": "online",
  "host": {"id":"host-id","name":"code-server"},
  "mode": "connector-managed",
  "workspace": "/workspace",
  "server": "https://omnigent.example.org/",
  "engines": [{"id":"claude","installed":true,"authenticated":true,"version":"2.1.285"}],
  "models": [{"agent":"claude","id":"model-id","name":"Model name"}],
  "verification": {"ok":true,"at":"2026-11-10T00:00:00Z"}
}
```

Missing auth/installation/verification data remains unknown/unverified. Model inventory may also be under each engine's `models`. For verification the UI sends `engine` (`claude`, `codex`, `pi`) and optional `model`. The runtime should return explicit top-level `verified`, `verification.ok`, `verification.passed`, or `verification.status:"passed"` (also accepts Paseo `acceptance.requestedPassed`/`passed`) and persist that receipt for a subsequent status request. An explicit top-level `verified:false` takes precedence over old receipts; the runtime owns validation against the current host, CLI versions and shared tools. Merely `{ok:true}` means the request completed, not that an assistant replied.

Paseo pair responds with `{ok:true,url:"https://app.paseo.sh/#<private-offer>"}` (also accepts `pairingUrl`, `pairUrl`, `pairing.url`, `offer.url`). This URL is never sent to the webview or output channel; only the explicit command opens it. Only the official origin or the user's explicitly configured Paseo Web origin is accepted. The local `webUrl` editor setting is not sent to runtime configure or connect. Omnigent has separate machine-scoped `server` (container/backend reachability) and optional `webUrl` (browser reachability) settings; Open Web selects `webUrl || server`. Both configuration URLs and normal Open Web calls reject URL userinfo, query strings, fragments, and control characters. Explicit HTTP private/loopback URLs are supported. Omnigent credentials remain bound to `server`; browser opening forwards no authentication material.

## Tests and remaining deployment evidence

`tests/` exercises command handlers with a fake VS Code API and subprocess boundary: no automatic connection, top-level dispatch, masked transient password, no secrets in logs/settings/public state, repository override rejection, bounded errors, pairing origin validation, no online-to-verified inference, and strict webview actions/CSP.

These tests do not replace installation in the real code-server browser, HA Ingress, Podman or PaaS, nor authenticated chats/model switching/skill/MCP execution. Deployment tests must supply that evidence.

## Reference architecture

The implementation uses public [VS Code workspace extension host](https://code.visualstudio.com/api/advanced-topics/extension-host), [manifest](https://code.visualstudio.com/api/references/extension-manifest), and [webview APIs](https://code.visualstudio.com/api/extension-guides/webview). Existing connector source snapshots and licenses are recorded in the repository's `docs/research/code-server-connectors-sources.json`; no reference plugin source is copied into these VSIX files.

Native settings open the container’s Remote settings in code-server, where machine-scoped connector fields are visible. In desktop VS Code without a remote host, they open User settings.
