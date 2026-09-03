# Changelog

## 0.1.1

- Fix HA Ingress boot hanging forever at `Loading OpenDesign…`: include `text/javascript` in nginx response filtering and prefix both escaped RSC chunk references and Turbopack's runtime `/_next/` asset base.
- Make the real-browser container smoke wait for the OpenDesign client to finish booting, so asset-only ingress checks cannot regress silently.
- Rewrite dynamically assigned iframe `src` values before navigation, keeping previews inside the authenticated ingress prefix.

## 0.1.0

- Initial standalone Home Assistant add-on for pinned OpenDesign 0.21.1.
- Add amd64/aarch64 Ingress-only metadata, cold backup, sidebar entry, and watchdog.
- Persist daemon state at `/data/opendesign`; keep provider credentials browser-local.
- Add unprivileged nginx ingress adaptation for static paths, API requests, SSE, WebSocket, history, workers, and dynamic assets.
- Add system Chromium, Playwright 1.55.0, Noto CJK/emoji fonts, and an injected Node headless renderer.
- Support PNG/JPEG, screenshot PDF, screenshot PPTX, ordinary page/deck/slide/stitch/pagination capture; reject editable PPTX explicitly.
- Add watchdog process launcher, static/unit tests, and validation-gated multi-architecture GHCR workflow.
- Harden renderer output confinement against symlinked output/export roots and block model-authored renderer traffic from HA/private/link-local/loopback networks except the exact OpenDesign origin.
- Bridge HA browser PDF and PNG/JPEG actions to the working screenshot binary endpoints; remove the misleading desktop vector-PDF injection.
- Bound launcher shutdown with a five-second TERM grace followed by KILL/reap.
- Gate the architecture matrix on a real amd64 container smoke test covering health, restart persistence, UID/paths, local-runtime absence, installed Chromium rendering, and upstream image/PDF/PPTX assembly without BYOK.
- Block renderer WebSockets before page creation; serialize render jobs; add absolute abortable deadlines plus slide, aggregate pixel/output-byte, remote-byte, and remote-fetch concurrency limits; stitch slides without concurrent file loading.
- Preserve complete `Request` semantics when redirecting browser PDF exports.
- Exercise injected ingress/export scripts in Chromium through a Supervisor-style path-stripping proxy, including fetch, XHR, SSE, WebSocket, PDF, and image actions.
- Pin the upstream multi-architecture image by digest, pin GitHub Actions by commit, explicitly install/check bash, and publish architecture version tags only from an exactly matching release tag.
- Split non-release builds from release publishing so PR/main jobs retain only `contents: read`; add a release-only, fail-closed GHCR preflight that prevents overwriting either architecture version tag. Partial releases now require a version bump.
- Hold the remote-resource semaphore across DNS policy evaluation and pinned fetch completion, with an instrumented resolver-concurrency regression test.
- Assert in the Chromium ingress smoke that custom `Request` headers survive the Supervisor-style proxy during PDF export.
- Use and verify the upstream image's absolute `/usr/local/bin/npm` path so reduced build environments cannot lose npm from `PATH`.
- Keep Supervisor `build.yaml` on the supported `0.21.1` tag syntax (digest syntax is silently replaced by the default HA base), while retaining digest pins in Dockerfile and CI/release builds.
- Start a minimal root PID 1 to prepare HA's root-owned `/data` mount, then drop nginx and OpenDesign to UID/GID 1001 with `su-exec`; verify ownership and child UIDs in container smoke tests.
- Route nginx errors to its inherited `stderr` descriptor and disable access-log reopening after the UID drop, matching HA Supervisor's protected log pipes.
- Preserve all slide siblings during capture so structural CSS selectors such as `:first-of-type` and `:last-of-type` render distinct slides instead of duplicating the last slide's styling.
- Harden the container browser harness against dangling proxy sockets and verify fixture creation through OpenDesign's file API plus real two-color deck output.
- Reject symbolic links during privileged `/data` preparation and use no-follow ownership changes, preventing persisted state from redirecting root startup operations outside the add-on data tree.
- Make the CI browser smoke observe blob-anchor clicks instead of unreliable GitHub-hosted Playwright download events; binary endpoint checks and HAOS acceptance still verify real downloaded files.
- Serialize browser-bridge and renderer Chromium acceptance on small CI runners: deterministic binary stubs verify the bridge first, then a fresh container process namespace runs real image/PDF/PPTX endpoints.
- Give every Chromium launch an ephemeral writable HOME/XDG profile, preventing Alpine crashpad state from leaking across render jobs or persisted `/data` volumes.
- Query GHCR release-tag availability with GET instead of HTTP/2 HEAD, avoiding curl error 18 on bodyless manifest responses while preserving fail-closed status handling.
