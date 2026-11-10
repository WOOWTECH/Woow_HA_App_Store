# Portable project-lab QA

Place this `harness/` directory next to the fifty `projects/`, `runtime.mjs`, and
`server.mjs` supplied by the project-lab suite. Canonical repository locations are
`qa/project-lab` for Podman/HA, `image/qa/project-lab` for the Kubernetes mirror,
and `code-server/qa/project-lab` where the PaaS repository nests code-server.
Paths are resolved relative to the harness, not the current working directory.
Node.js 22+, Python 3.10+, and Bash are required for the core checks.

```sh
bash harness/check.sh
node server.mjs
# In another terminal, after configuring the optional browser dependency:
node harness/browser-apps.cjs http://127.0.0.1:18750/ ci
```

`check.sh` checks exactly p01–p50, byte-identical per-project runtime copies,
the SSH transport unit regressions, all application fixtures and project test
runners, HTTP/UTF-8 regressions, packaging, execution of all fifty extracted
ZIPs, and the single-request optimization regression. A failed stage stops the
script with a nonzero exit. The browser driver waits up to 60 seconds for
`healthz` to report fifty projects, so CI may start the server immediately before
the browser command. Browser failures return nonzero too.

The original individual commands remain available:

```sh
node harness/test-all.mjs
node harness/runtime-tests.mjs
python3 harness/package.py
node harness/standalone.mjs
node harness/optimization-audit.mjs
python3 -B -m unittest discover -s harness/tests -p 'test_*.py'
```

Generated downloads go in `downloads/`; reports and check logs go in new
subdirectories of `evidence/`. CI should collect `evidence/**`. Packaging replaces
only generated ZIPs and `evidence/package-manifest.json`, after complete source
preflight. It never edits project source. It packages an explicit file allowlist,
not arbitrary adjacent JSON or text files. ZIP timestamps and member order are
fixed. The standalone check verifies archive and individual member hashes,
compares packaged app/fixture/test/runtime bytes with source, rejects unsafe ZIP
paths, and runs tests and live HTTP requests from clean extraction directories.
The suite runs trusted source code; process deadlines are not a security sandbox.

Optional path overrides: `QA_ROOT` selects a different suite; `QA_OUTPUT` selects
an existing parent for new report directories; `QA_CHECK_OUTPUT` selects a new
directory for a check run; `QA_PACKAGES` selects an artifact tree containing
`downloads/` and `evidence/package-manifest.json`. For separate packaging use
`python3 harness/package.py --root "$QA_ROOT" --output "$QA_PACKAGES"`;
the explicit output must not exist. Without these overrides, all original
commands work together using the suite's generated artifacts.

Browser QA is optional and uses `playwright-core` (the source kit used 1.61.1).
Install it in a tooling directory, then set `PLAYWRIGHT_MODULE` to its absolute
package directory and `CHROME_EXECUTABLE` to an existing Chrome/Chromium binary.
There is no dependency download, browser installation, persistent browser profile,
saved authentication state, screenshot or tracing step in these tools. The
browser sandbox is enabled; `QA_BROWSER_NO_SANDBOX=1` is an explicit operator
override for environments that cannot launch it. `QA_HEADED=1` opens a visible
browser. For an authenticated IDE proxy, set `QA_IDE_URL` and explicitly supply
`QA_IDE_PASSWORD` in the environment; no helper reads credentials from disk.

`browser-apps.cjs URL LABEL` retains all fifty applications, catalog search, two
positive fixtures per app, validation responses correlated with fresh requests,
malformed JSON with zero API requests, cleared stale results, local persistence,
reset, exported JSON, source ZIP hashes, and mobile-width assertions. Only
synthetic suite fixtures are entered. Reports from a private endpoint should be
reviewed before sharing; generated artifacts are not part of this source bundle.

For manual preview use `node harness/deploy.mjs`. It runs in the foreground,
defaults to `BIND=127.0.0.1 PORT=18750`, accepts `PORT=0`, creates `evidence/`,
and stops on Ctrl+C/SIGTERM. It takes a new source snapshot and can include ZIPs
when `QA_PACKAGES` is explicitly supplied. It never kills an existing PID, starts
a detached process, reaches a remote host, or edits existing project files.
The simple `node server.mjs` command also remains available for CI after packaging.

`optimization-audit.mjs` starts the real current runtime, makes one HTTP p33
conversion request, asserts its numerical result, and observes exactly one
`fs.stat` for `projects/p33/app.mjs`. Startup catalog work is excluded. There is
no private baseline fixture or claim that a code-server product issue was fixed.
`QA_RUNTIME` can select a runtime under review for this and the HTTP regression;
the runtime-copy contract always compares actual suite files.

The SSH fix lives in `ssh_transport.py`. It drains stdout and stderr while
sending binary stdin, bounds time and each output stream, preserves exit status,
and waits for EOF/closed plus empty buffers before completing. An early exit
status is insufficient. Offline tests exercise exact 2/4 MiB byte lengths and
SHA-256, delayed output after status, simultaneous stderr, partial stdin writes,
timeouts, output limits, quoting, and closed input. These are transport unit
tests; they do not substitute for application or live remote acceptance.

Optional live SSH requires an operator-installed Paramiko, an explicit known-hosts
file and either an explicit identity file or `--agent`. Host verification rejects
unknown keys; default key discovery, password files and SSH config discovery are
disabled. The remote machine must provide GNU `timeout` and Python 3 for the probe.

```sh
python3 -B harness/ssh_transport.py \
  --host "$QA_SSH_HOST" --user "$QA_SSH_USER" \
  --known-hosts "$QA_KNOWN_HOSTS" --identity "$QA_IDENTITY" test-output
```

The probe writes no remote files. `exec --timeout 30 -- COMMAND ARG...` is an
explicit general remote-command adapter; its effects are those of the supplied
command. Container/Kubernetes names and credentials are deliberately not inferred.
Use only authorized endpoints. Closing a channel alone cannot kill remote work;
the CLI wraps commands with the remote timeout. No live SSH claim is made by the
offline checks. See `OMISSIONS.md` for the mapping from the original lab harness.

The optional IDE adapter is `node harness/code-server-ui.cjs`. Supply
`QA_IDE_URL` and `QA_IDE_WORKSPACE` (the absolute suite path as seen inside the
IDE), plus `QA_IDE_PASSWORD` only when needed. Its default mode opens all fifty
`app.mjs` files and verifies both their active tab and exact project breadcrumb.
It does not infer a remote workspace or auto-approve workspace trust.

For saved-file and integrated-terminal checks, additionally set
`QA_IDE_EXERCISE=1` and `QA_IDE_LOCAL_WORKSPACE` to an explicit local mount of that
same IDE suite. The adapter creates a new `evidence/ide-fixture-*/notes.txt`, edits
and saves it through the UI, and verifies the fresh random marker through the
mount. It types a shell-quoted `ide-task.mjs` command into a new integrated
terminal and requires a receipt with the matching nonce, zero exit status, fifty
projects and fifty real project test runners. Existing source files are never
edited. The integrated terminal must use a POSIX shell with Node available.
Missing mount access is an unsupported environment for this optional exercise,
not a passing test. It may be necessary to unhide ignored `evidence/` files from
Quick Open in the operator's IDE settings. Trust is configured manually.

`QA_IDE_CONNECTOR_COMMAND` optionally names the installed connector's connection
panel command; the adapter then asserts its `#phase` is connected and its engine
rows/status control are ready. `QA_IDE_EXPECT_ENGINES` supplies comma-separated
expected engine labels. These selectors intentionally match the original
connector UI and may require an integration update for another extension version.

`omnigent-assertions.cjs` retains reusable assistant-only API/UI marker checks,
expected host/model checks, effective-model polling, and assistant link download
hash verification including popup downloads. Import these helpers into an
operator-owned adapter with an already authenticated `api(method,path)`, page and
browser context. Supply session IDs, expected marker/model/host and download URL
at runtime; no account values, prompts, session creation or approval automation
are included. The conversation page must already be open when invoking the
conversation helper. Its history query covers the most recent 100 items; older
markers require the operator adapter to provide appropriate pagination.

The optional live IDE and Omnigent adapters have syntax validation only in this
portable extraction; live acceptance requires an explicitly configured endpoint
and is not included in the core suite's passing result.
