# Shared MCP artifact consumption

The core package remains 0.21.0 and the WOOW build is `mcp.1`. The release input
is the combined `candidate-image.json` from
`woow-mcp-candidate-server-kubernetes-<runId>-<runAttempt>`, produced by
[the core artifact workflow](https://github.com/WOOWTECH/omnigent/blob/main/docs/WOOW_MCP_ARTIFACT.md).

Import the real receipt after both candidate architectures pass:

```sh
python3 omnigent/build/mcp_artifact.py pin \
  --receipt /path/to/candidate-image.json \
  --output omnigent/build/artifact-pin.json \
  --dockerfile omnigent/Dockerfile
python3 omnigent/build/mcp_artifact.py validate \
  --receipt omnigent/build/artifact-pin.json
```

The pin records the public `wheelImage` digest, source commit, exact wheel and
UI hashes, architecture digests and CI run/attempt. Null fields deliberately
block builds. Never substitute a source tree hash for a source commit, invent a
digest, or use the unpublished snapshot receipt as a release pin. Verify the
candidate digest can be pulled anonymously before accepting it.

The Dockerfile copies `/opt/woow-artifact/` from that image into Alpine. It does
not run the source image's binaries. It checks the reviewed pin and executes the
shared `verify.py` against the actual receipt, content manifest, embedded source
identity, migration, built UI and inherited security markers. UI hashes use the
producer's canonical JSON mapping of wheel UI paths to each file's SHA-256.

The existing Alpine/PyPI dependency assembly runs first. The verified wheel is
then installed with `--no-deps --no-index --force-reinstall`; `pip check` and the
shared runtime verifier must pass. No later PyPI reinstall may replace it. The
Alpine dependency resolution is unchanged and is not a fully locked dependency
set; both architecture builds and the Store vulnerability comparison are required.

The image retains `/opt/woow-artifact/WOOW_BUILD_RECEIPT.json`,
`WOOW_CONTENT_MANIFEST.json`, `verify.py`, and the portable wheel.
`/usr/share/omnigent/artifact-pin.json` is the add-on's reviewed input.
`org.opencontainers.image.revision` must equal that receipt's `sourceCommit`.

The import command also sets Dockerfile defaults for Supervisor source builds.
CI supplies `OMNIGENT_WHEEL_IMAGE` and `OMNIGENT_SOURCE_COMMIT` from the pin.
Local builds use the same defaults and the normal architecture base image. A build argument that differs from the reviewed pin is rejected.

## Validation

```sh
sh omnigent/tests/test-admin-password.sh
python3 -m unittest discover -s omnigent/tests -p 'test_mcp*.py' -v
python3 .claude/skills/omnigent-upgrade/scripts/addon-preflight.py 0.21.0 \
  --to-wheel /path/to/omnigent-0.21.0-py3-none-any.whl \
  --receipt omnigent/build/artifact-pin.json
python3 omnigent/tests/test-upgrade-runtime.py \
  --old-python /path/to/published-venv/bin/python \
  --new-python /path/to/candidate-venv/bin/python \
  --state omnigent/.local/upgrade-evidence
```

Preflight may inspect an unpublished producer receipt with `--allow-snapshot`
for local coupling analysis. That mode prints its unpublished status and does
not change Docker/CI release validation. Re-run with the final pin before release.

The proxy tests require nginx (`NGINX_BINARY` can select an unpacked binary).
They exercise methods, headers, SSE delivery, encoded paths and log hygiene.
The runtime harness starts both real servers with synthetic accounts and SQLite,
then checks data preservation, MCP create/revoke, process restart persistence and
a negative control with an altered expected file hash. All processes stop before it exits.
Its private state contains synthetic passwords and URLs; publish only report JSON.

These local tests do not replace the two Alpine image builds, the required
`Upgrade comparison / compare` PostgreSQL runtime/data checks, or H3 on HAOS:
Ingress navigation, public HTTPS MCP/Pi client, aarch64 runtime, and cold
backup/restore. Keep the PR review prefix until the designated reviewer merges.
Do not create `upgrade-notes.yaml` unless the comparison report requires it.
