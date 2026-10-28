# Omnigent release-channel validation (2026-10-26)

This records the additional source checks after the packaging patch. It is not image or production acceptance.

- `tests/run.sh`: 71 Node cases, 27 existing MCP unit cases, 5 provider-fixture cases and 26 import-core checks passed; pin-core passed.
- Pinned shellcheck 0.11.0 was run separately against every script in `tests/run.sh`; passed after fixing an unused smoke-loop variable.
- Actual nginx `-t` passed with a read-only nginx rootfs and an isolated generated configuration. This checks syntax, not Supervisor routing.
- Native host shutdown budget: launcher 35 seconds, outer Supervisor/Docker deadline 45 seconds. The core must implement the corresponding bounded daemon cleanup.
- Authenticated smoke now requires private local provider files in addition to Omnigent credentials; legacy Omnigent state and symlinks are rejected before container creation. No live credentials were committed.

## Merged source validation

The feature branch now incorporates HA main 0.2.8 (`28e5a3cabb5852391173cfc65645f80d6dd3e400`) and reserves candidate version 0.2.10. The previous 0.2.8 Omnigent candidate passed full container smoke, but another 0.2.8 change merged first and omitted the HA Omnigent plugin. This next-version source must pass its own image, Ingress and real HA checks. The existing MCP/import checks, real nginx syntax check and nine credential-permission cases remain in the suite.

## Remaining release gates

The w2.10 core target is `20261027.1127` (`sha256:c8cd57f0…`); its Gitea candidate passed the installed-SDK suite and isolated PaaS Pi/OpenCode conversations, but public promotion is pending. The earlier w2.8 core is historical HA RC evidence. The branch-only HA candidate workflow must publish an exact-source image and pass container smoke after the public core import. Then verify actual HA upgrade, fresh GUI login, four-engine replies/stops, disable/re-enable, restart and cold restore. Provider credential transfer uses only a dedicated test key on the owned isolated HA. Before the stable PR merges, check its own container and Ingress tests. Finally verify Store/Local Download notifications and matching source/image/catalog receipts. Source checks alone do not satisfy these gates.
