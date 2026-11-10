# WOOW Paseo

Connect this code-server deployment’s **Claude Code, Codex and Pi Agent** to Paseo. The extension provides a connection panel, native commands, agent/model inventory, and explicit real-conversation verification.

## Install

Install `woowtech.paseo-0.1.3.vsix` through **Extensions → … → Install from VSIX**, or run inside the container:

```sh
code-server --install-extension /opt/woow-connector-vsix/woowtech.paseo-0.1.3.vsix
```

This is a normal installed extension, not a built-in. It appears in **Extensions → Installed** with ID `woowtech.paseo`. It does not require a marketplace account or another gallery extension. The default marketplace has not been used to publish this package.

## Connect

1. Open **WOOW Paseo: Open Connection Panel** from the command palette, or select the Paseo icon in the activity bar.
2. Enter the container workspace and host name, then **Save configuration**.
3. Select **Start**, then **Pair with Paseo Web**. The pairing URL opens explicitly in your browser; complete pairing there.
4. In Paseo Web, select this host, choose Claude Code, Codex or Pi, then select an available model and start a conversation.
5. Use **Refresh models** to inspect the available inventory. **Verify a conversation** asks for an agent and model, then requests a real runtime verification. It may consume model quota. Each provider needs its own existing login in this deployment.

Change models within the selected agent’s Web conversation. A different agent may need a new conversation; this extension does not claim cross-agent context transfer. Switching the UI’s selected agent or seeing “online” does not prove that an assistant replied.

## Download workspace files

In the paired Paseo browser, open **Explorer → Files**, right-click a file,
and choose **Download**. ZIP files download through the same action even when
the file pane says **Binary preview unavailable**. Text files retain their
original bytes, including UTF-8 content.

Ask the agent to use workspace-relative links, such as
`[Download ZIP](downloads/all-projects.zip)`. The chat link opens the workspace
file; the Explorer **Download** action saves it. This uses Paseo's paired file
transport and does not require a code-server preview or an SSH tunnel.

For Home Assistant, a public `/<addon>/proxy/...` URL is not a substitute for a
workspace file link. Browsing an app through code-server's port preview uses the
normal authenticated HA ingress flow; downloading a workspace artifact can use
Paseo directly.

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

## Refresh shared tools in an existing conversation

Select **Refresh shared MCP** in the connection panel or command palette and enter the original conversation ID. The action synchronizes shared definitions, including removals, and keeps the same conversation and native persistence. Busy conversations are refused without interruption. Errors remain visible; success means configuration reload/resume was accepted, not that a model has executed a tool.

Paseo resumes the saved Claude/Codex/Pi session only when idle. Open an unloaded original conversation first. An older daemon must be upgraded by an operator after its sessions are idle; this action never restarts the daemon.
