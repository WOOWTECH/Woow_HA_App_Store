# HA exec-boundary regression sources

These two **unmodified installed upstream scripts** were recovered from
`recovery/focused-source.json` in the 2026-10-11 HA recovery evidence (outside
this repository). Joining the captured source lines with LF and a final LF
reproduces the receipt's SHA256 exactly. They are not synthetic shell fixtures
and were not taken from Hermes 0.21.6.

- Add-on: 0.1.6; observed installed Hermes runtime: 0.21.0.
- Product baseline commit: `514dca9488522a278ea1ecf2ba950838643048cc`.
- Unchanged Dockerfile base:
  `docker.io/nousresearch/hermes-agent:v2026.8.31@sha256:64923faeae267792bf9bf87fe3b4c4869e35004e360c7df01730ad801b74d524`.
- Original paths: `/opt/hermes/docker/<filename>`.

| File | SHA256 |
| --- | --- |
| `hermes-exec-shim.sh` | `57637e73c8db76aa84a38e4a2edb1b155bfd86a2e89a8d4c38c4546ee1175985` |
| `main-wrapper.sh` | `d01d7ece5198f79496cf8ce64552665699995f0bf2cabbac78205b6b1779fb9b` |

The build patch requires these exact original bytes (or the exact fully patched
form), and unique anchors. Both files are validated before either is written.
A future base change must be reviewed and these sources/hashes/tests refreshed;
a comment-only drift also fails closed. Existing Podman vendor files are untouched.

## Boundary and checks

The shim clears `SUPERVISOR_TOKEN` and `HASSIO_TOKEN` immediately after `set -e`,
before its missing-binary, non-root, root opt-out and privilege-drop branches.
The main wrapper clears them before the `with-contenv` helper exec **and again
after re-entry**, because the helper can reload them from its environment dir.
All routing/drop/exit logic and other environment values remain upstream's.

`00-woow-options` is unchanged: its Supervisor bootstrap calls still precede the
existing removal of both s6 token envfiles. Do not move cleanup before bootstrap.
This patch applies to exec boundaries, not to the initialization scripts.

From the repository root:

```sh
# Expected RED on the original source (sentinel token propagation):
python3 hermes/test/test-exec-boundary.py --unpatched
# Expected GREEN; also run by the existing unit-test workflow:
python3 hermes/test/test-exec-boundary.py
```

Tests patch the real captured source, parse/run it with `/bin/sh`, and relocate
only fixed filesystem paths to a temporary sandbox. External `id`, s6 helpers,
venv activation and final executables are doubles; no entire shell body is
mocked. UID branches are simulated, **not kernel privilege-drop proofs**.
The helper double intentionally reintroduces both sentinel tokens to verify the
second cleanup. Tests check root/non-root/opt-out, routing, empty/quoted argv,
exit codes, absent tokens, provider/custom environment preservation, unsupported
UID and missing-helper failures, drift rejection, complete idempotence, and
all-files preflight. Environments are built from synthetic values, not inherited
from the test runner. Docker build also verifies the exact patch and shell syntax.

## Limits / separate gates

The recovery evidence found **no Supervisor/HASSIO token in normal UID10000 s6
agent services**. This change closes Docker-exec environment inheritance; it is
not evidence of an active-agent leak. Existing live evidence of denied access to
PID1 environ/options is not repeated by these tests. Unsetting a child environment
does not isolate same-UID process environments, provider files, arbitrary root
exec, or direct invocations bypassing the wrappers.

API-enforced no-tools is a **separate, still-open gate**, not satisfied by this
patch. Bootstrap curl's Authorization-in-argv window is also deferred. Full
image boot, actual s6 UID/capability behavior, UI, model/provider integration and
HA deployment are not established by these local tests. Do not deploy or send
paid/tool-capable requests based solely on this regression suite.
