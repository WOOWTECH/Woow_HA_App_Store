# Native OpenCode API BYOK — implementation plan

1. Select and lock an official Alpine-compatible OpenCode distribution; prove its accepted binary under UID 1001 on amd64/aarch64.
2. Add locked OpenCode packaging to the image and update smoke/CI checks for exact OpenCode presence and Pi absence.
3. Remove Pi, persistent-profile sidecar/bridge/routes, credentials persistence, and launcher third-peer logic; safely clean obsolete credentials.
4. Restore upstream browser-local API BYOK documentation/config contract and bump release to `0.1.4`.
5. Add deterministic mock-provider native `byok-opencode` streaming and no-leakage coverage, then run full local/container validation.
6. Independently review, merge, release both architectures, sync Store, update HAOS, and verify readiness through authenticated HA Ingress.
