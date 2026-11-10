# WOOW Omnigent

Connect this code-server deployment’s **Claude Code, Codex and Pi Agent** to Omnigent. The extension provides a connection panel, native commands, agent/model inventory, and explicit real-conversation verification.

## Install

Install `woowtech.omnigent-0.1.3.vsix` through **Extensions → … → Install from VSIX**, or run inside the container:

```sh
code-server --install-extension /opt/woow-connector-vsix/woowtech.omnigent-0.1.3.vsix
```

This is a normal installed extension, not a built-in. It appears in **Extensions → Installed** with ID `woowtech.omnigent`. It does not require a marketplace account or another gallery extension. The default marketplace has not been used to publish this package.

## Connect

1. Open **WOOW Omnigent: Open Connection Panel** from the command palette, or select the Omnigent icon in the activity bar.
2. Enter the container workspace and host name, then **Save configuration**.
3. Enter the Omnigent **server URL reachable from the container**. If your browser needs a different address, also set **Browser Web URL**. Save configuration, then select **Sign in & connect**. Username and password are requested through native editor prompts; the password is masked.
4. In Omnigent Web, select this host/workspace and choose Claude Code, Codex or Pi, then select an available model and start a conversation.
5. Use **Refresh models** to inspect the available inventory. **Verify a conversation** asks for an agent and model, then requests a real runtime verification. It may consume model quota. Each provider needs its own existing login in this deployment.

Change models within the selected agent’s Web conversation. A different agent may need a new conversation; this extension does not claim cross-agent context transfer. Switching the UI’s selected agent or seeing “online” does not prove that an assistant replied.

## Separate backend and browser URLs

For Podman, `server` may be `http://omnigent-server:8000` while `webUrl` is a public HTTPS hostname or an explicitly forwarded browser-loopback URL. For PaaS, `server` may use a `*.svc.cluster.local` hostname while `webUrl` is the external Ingress address. **Open Omnigent Web** opens `webUrl` when set and falls back to `server` when empty. Changing `webUrl` does not change the server receiving login credentials.

Both settings accept HTTP(S), including explicit private/loopback HTTP endpoints, and reject URL usernames/passwords, query strings and fragments. The extension never appends credentials or tokens when opening the browser.

## Runtime requirement

The matching **WOOW connector runtime must be installed in the same code-server container**. The default executable is `/usr/local/bin/woow-connectors`; the VSIX contains the UI/client, not the Paseo daemon or Omnigent SDK. A missing runtime reports `RUNTIME_UNAVAILABLE` and cannot connect. Use the WOOW code-server image with connector support, or have the deployment administrator install its matching runtime bundle.

The extension runs in the Node workspace extension host. Its executable override is an absolute, machine-scoped setting. Configuration from a repository cannot override it. Apply changes to workspace/host/server settings through **Configure Workspace** or **Save configuration**.

The runtime receives one JSON object on standard input; no shell, password argument, workspace task, or remote script is executed by the extension. All operations have bounded timeouts. Diagnostic output records action names and result codes only.

## Skills, MCP and private state

Agent sessions must use the deployment’s existing `/data/pi-agent/skills` and `/data/pi-agent/shared/mcp.json` (or the deployment’s configured equivalents). The extension does not duplicate provider credentials, install a second agent CLI, or edit skill/MCP files. Runtime verification and tool-side evidence determine whether a specific remote session really used shared tools.

Provider authentication, Omnigent tokens and daemon state stay with this deployment’s runtime. Passwords never enter editor settings, command arguments, output logs, or persistent webview state. Pairing links are authorization material and are opened only by the explicit pairing command.

## Lifecycle

Opening or installing this extension does not start a connection or create a chat. Closing a browser tab, reloading the editor, or deactivating the UI does not stop a confirmed background host. Select **Stop** before disabling or uninstalling if you also want to stop the background connection. Omnigent additionally offers **Sign Out and Disconnect**. Recovery and manual-stop persistence are managed by the runtime.

## Status meanings

- **Connection** is the runtime’s reported state, or `unknown` if it has not reported one.
- **Conversation: unverified** means there is no recorded successful real reply.
- **Conversation: passed** requires an explicit verification record from the runtime. It does not imply every model, model switch, skill or MCP tool has passed.
- **Unknown** installation/login/model fields remain unknown; the UI does not infer them from host connectivity.

The command palette exposes configuration, status, models, start/stop, restore, Web opening, and verification without requiring the connection panel.

## License and implementation

MIT, Copyright 2026 WOOWTECH. This VS Code client is an independent implementation against the `woow-connectors` JSON contract. Existing WOOW Pi/Hermes/OD integrations informed the architecture; their host-specific UI code is not bundled in this extension. Runtime dependency licenses and provenance belong to the separately packaged runtime.
