# Woow HA OpenDesign

## Configuration

This add-on intentionally has no options. Configure providers in the OpenDesign UI, not in Home Assistant.

Use **HA Persistent BYOK Profiles** in OpenDesign Settings. Profiles are stored at `/data/opendesign/credentials/byok-profiles.json` with restrictive ownership/modes, survive restart, and are included in Home Assistant cold backups. Every HA administrator with access to this add-on may view/manage complete keys; backup access is provider-key access.

## Access and persistence

Use **Open Web UI** or the **OpenDesign** sidebar item. The service is ingress-only and has no published LAN port.

Projects, the OpenDesign database, application configuration, connector data, and generated state are stored beneath `/data/opendesign`. The add-on requests cold backup so this directory is captured while the service is stopped.

## Exports

| Format | Support |
|---|---|
| Standalone HTML | Supported by OpenDesign |
| Project ZIP | Supported by OpenDesign |
| PNG / JPEG | Supported; the HA image dialog is bridged to `/export/image` |
| Screenshot PDF | Supported; the HA PDF action is bridged to the binary `/export/pdf-image` download |
| Screenshot PPTX | Supported; choose screenshot mode for one full-slide image per PowerPoint slide |
| Editable PPTX | **Unsupported**; the renderer returns an explicit error |

The add-on does not inject the desktop vector-PDF exporter: upstream's browser client interprets that endpoint as a desktop save and would download nothing. The narrow HA bridge instead redirects the existing browser PDF request to the screenshot PDF endpoint and triggers a normal browser download. The image bridge intercepts only PNG/JPEG saves; other upstream browser formats retain their upstream behavior.

Rendering is serialized and bounded by an absolute two-minute deadline, 64 slides, aggregate pixel/output-byte limits, canonical output-path confinement, capped remote-resource concurrency/bytes, and a network policy. Each remote-resource permit is held from DNS policy evaluation through pinned fetch completion, preventing model-authored HTML from starting unbounded DNS lookups. CJK and color emoji fonts are installed in the image. Oversized decks and pages fail with a bounded-size error instead of exhausting add-on memory. Renderer documents can load inline `data:`/`blob:` resources, project assets from the exact OpenDesign origin, and public HTTP(S) resources after DNS/IP validation and pinned connection. WebSockets are disabled; Supervisor, link-local, private, CGNAT, and other loopback destinations are blocked to keep model-authored HTML from reaching the HA network.

## Runtime ownership and release policy

The container starts a minimal root PID 1 because Home Assistant mounts `/data` as root at runtime. It creates and assigns only add-on-owned directories, then launches OpenDesign, nginx, and the loopback profile sidecar through `su-exec` as UID/GID 1001.

CI validates and smokes every build before architecture work. Pull requests and `main` build without pushing under `contents: read`; only an exact `v<config-version>` tag starts a publisher with `packages: write`. Its preflight fails closed unless both architecture version tags are absent from GHCR. Version tags are immutable: a partial architecture release cannot be retried over the same version and requires a version bump plus a new matching Git tag. Dockerfile and CI/release inputs pin the upstream digest; `build.yaml` uses the `0.21.1` tag because Supervisor's local builder rejects digest syntax there and otherwise silently substitutes its default base image.

## Pi Local CLI profiles

The image bundles locked Pi `0.84.4`; OpenDesign uses its native Pi RPC Local CLI integration. Select one active persistent profile in Settings. Its model is authoritative for new runs. Supported profile protocols are Anthropic, OpenAI, Google, and OpenAI-compatible (bearer or `api-key` authentication). Delete/replace a profile to rotate a key; a deletion affects new runs only.

## Troubleshooting

- **Stuck at “Loading OpenDesign…”:** reload without cache and confirm the add-on is at least 0.1.1. The Next/Turbopack runtime and escaped RSC chunk references both require ingress-prefix rewriting; the container browser smoke locks this boot path down.
- **Settings or Design systems changes the URL but not the page:** update to at least 0.1.2. OpenDesign route logic must see logical paths without HA's transport-only ingress prefix.
- **Blank page or missing assets:** restart the add-on, then reload the HA page without cache. Report the missing root-relative URL and add-on logs; ingress adaptation is coupled to the pinned OpenDesign version.
- **Generation cannot authenticate:** check the active HA Persistent BYOK Profile and provider/model endpoint in Settings.
- **Key disappeared:** reload Settings; profiles survive browser clearing and HA restart, but a deleted profile must be recreated or restored from an authorised cold backup.
- **Editable PPTX fails:** expected. Choose the screenshot/image PPTX mode.
- **Image/PDF export says renderer failed:** check logs for Chromium errors and reduce page dimensions/length.
- **Watchdog restart:** if nginx or OpenDesign exits, the launcher deliberately stops its peer and exits so Supervisor can restart the complete pair.
