# Manual gate: ACP chat webview under HA ingress (P32/P33)

A browser-only check. No mutation to the add-on's config; safe to run any time.

**Why manual:** CI can build the image and run the s6 startup chain against a mock Supervisor (see `docs/ARCHITECTURE.md` for what that already verifies), but it cannot open a real browser against a real Home Assistant ingress session. This procedure is the last mile.

**Why a Markdown preview stands in for the ACP panel:** every `type: webview` contribution in code-server/VS Code — regardless of which extension owns it — is delivered through the identical mechanism: a sandboxed iframe pointed at a webview-host document, which registers a ServiceWorker to serve its own resources. A working Markdown preview under the real ingress path proves that mechanism end to end, which is the thing that was actually in question (see `PARITY_CONTRACT.md`'s webview gate verdict). It is not a substitute for eventually looking at the real ACP panel too — just the cheaper, zero-setup way to close 95% of the risk first.

## Steps

1. Open the add-on's Web UI from the Home Assistant sidebar (the ingress-panel toggle is auto-enabled by `init-woow` on first boot).
2. In the workbench, open any file, then open the Command Palette (`Ctrl+Shift+P` / `Cmd+Shift+P`) and run **Markdown: Open Preview** (works on any file — code-server will preview it as Markdown regardless of extension, or open/create a `.md` file first if you want a cleaner render).
3. Open DevTools (`F12`) → **Application** tab → **Service Workers** (left sidebar, under Application).
4. Expect **one registration** with:
   - **Scope**: ending in `.../stable-<commit>/static/out/vs/workbench/contrib/webview/browser/pre/` (the commit hash matches `code-server --version`'s second field, `de89acbcdce9d9b870008a270c9f6466993d91f4` for 4.135.0).
   - **Status**: `activated and is running` (or `activated`).
5. Confirm the preview pane actually shows rendered content (not a blank iframe).

## Reading the result

- **All of the above true → PASS.** The ACP chat panel will render the same way — no further action needed. This add-on ships as designed (F0).
- **ServiceWorker never reaches `activated`, or DevTools Console shows `SecurityError` mentioning ServiceWorker or a certificate** → the secure-context assumption failed for your setup (unusual — your Home Assistant origin should be `https://` with a browser-trusted cert already, per `PARITY_CONTRACT.md`). Follow the F2 fallback in `DOCS.md` (set `direct_password`, map port 1338, front it with your own trusted-cert tunnel).
- **Preview pane loads but stays blank with no console error** → check the add-on's own logs for `init-woow` errors first; the workbench itself may not have started cleanly.
- **Everything above passes but the ACP panel specifically is blank** → confirm `pi login` has been run (an unauthenticated agent may render an empty/error panel rather than nothing — see `DOCS.md`'s First Run section) before assuming this is a webview problem at all.

Either way, the terminal `pi` task (`Tasks: Run Task` → `pi`, seeded automatically into `.vscode/tasks.json`, F1) works regardless of this gate's outcome — this is the guaranteed-working surface.
