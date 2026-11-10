# WOOW 50-project application and acceptance lab

This suite publishes the functional prototypes and regression fixes exercised in
Podman, PaaS and the Home Assistant code-server add-on on 2026-11-10. All fifty
applications are version 1.1.0. Inputs are synthetic; each application README
states its behavior and limitations.

## Run locally or from the code-server terminal

Use Node.js 22+ and Python 3. Application execution needs no npm install, model
account, SSH access or external service.

```sh
cd qa/project-lab # Podman / HA repository
# K3s mirror: cd image/qa/project-lab
# PaaS source: cd code-server/qa/project-lab
bash harness/check.sh
node server.mjs
```

The preview binds to `127.0.0.1:18750`. Open that address locally or use your
existing authenticated code-server port proxy (`proxy/18750/`). To bind another
interface, set `BIND` explicitly and provide appropriate access control. These
are manually started previews; this suite does not enable a permanent service.

```sh
python3 harness/package.py
node harness/standalone.mjs
cd projects/p33
npm test
npm start
```

`downloads/all-projects.zip` contains fifty nested project ZIPs, with instructions
for extracting and running each one. `npm start` defaults to port 18750; choose a
different `PORT` when running multiple applications. Packaging does not modify
project sources. Generated downloads and execution evidence stay untracked.

## Regression coverage

- 510 expected-result/error fixtures and all 50 project-specific test programs.
- Actual HTTP requests, UTF-8 characters split across byte chunks, malformed JSON,
  content type, size limits and route validation.
- An instrumented HTTP request verifies one application file check, preserving
  the improvement from 50 checks. This is not a latency claim.
- All 50 downloaded ZIPs are extracted, tested and served independently.
- Browser checks require fresh API responses and independently expected output;
  saved inputs, error states, result downloads and ZIP hashes are checked.
- SSH transfer helpers retain the EOF/exit-status/stream-draining fix, with
  deterministic regressions for late stdout/stderr and timeouts.

See `harness/README.md` for browser, IDE and optional remote connection settings.
No credential files, original session transcripts or private infrastructure
addresses are included. Real model/IDE integrations require your own authorized
service and accounts; local CI does not claim to authenticate those services.

## Historical deployment evidence and limits

[`reports/acceptance-2026-11-10.json`](reports/acceptance-2026-11-10.json) records
the completed three-platform exercise. The catalogue is in
[`reports/project-catalog.json`](reports/project-catalog.json). These historical
results are separate from the fresh run's generated `evidence/` files.

The Omnigent native TXT/CSV download HTTP 500 remains an upstream product issue;
ZIP delivery is the tested workaround. This source export does not patch
Omnigent itself. The 50 Containerfiles are provided, but only the independent
Node processes were executed for all projects, not 50 image builds. The earlier
model exercise split projects across Claude Code, Codex and Pi; Pi performed the
same-conversation model switch and redeployment. External MCP services were not
all retested in this round.

## Repository scope

The same suite is maintained in the Podman, HA and K3s GitHub repositories and
the PaaS Gitea image-source repository. It is an opt-in source/QA suite and is not
copied into the base code-server image or enabled at startup. Consequently this
change does not change image tags, chart versions or production template pins.
Clone/download the repository in code-server to use the suite.
