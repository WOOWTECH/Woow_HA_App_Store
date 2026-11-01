#!/usr/bin/env python3
"""Give Omnigent's pre-launch Pi model picker something to list.

Omnigent's "Configure Pi" dialog asks the host for the models a Pi session may
start with. With no omnigent-managed provider configured the launched Pi runs
on its own login, and upstream answers that case from
`pi_own_login_model_options()`: Pi's `models-store.json` catalog filtered to
providers that have an `auth.json` entry.

That pair misses the documented way to add a gateway. `models-store.json` is
only written for providers whose catalog Pi refreshes **over the network**, so
a compatible endpoint declared in `models.json` (LiteLLM, Ollama, vLLM, any
OpenAI-compatible proxy) is in neither file: the dialog then offers only
"Default" and the user cannot pick a model at all. Observed in the field on
PaaS tenants whose Pi models come from the pi-web Models page.

The installed Pi CLI already knows the answer (`pi --list-models`), so this
patch routes the empty case there instead of giving up.

Two details of that CLI matter. With nothing configured it prints a "No models
available. Use /login ..." notice on STDOUT with exit code 0 instead of a table;
only the rows after the `provider  model ...` header are models, otherwise the
notice would be read as a model called `No/models` and the picker would offer
an entry that cannot start. And it is given 12 seconds, not 30: the host RPC
that asks (omnigent server/routes/hosts.py, _MODEL_OPTIONS_TIMEOUT_S) is cut
off at 15, so a slower CLI should mean an empty picker, not an HTTP 504.

Why a runtime patch and not a chart value or an image layer: omnigent lives in
a venv that is either `uv tool install`-ed into $HOME (on the PVC, so no image
layer can carry it) or baked at /opt/omnigent; upstream exposes no hook for
this. Applying it on every start is what keeps it from being lost — including
after `uv tool upgrade`.

It is deliberately unconditional-but-idempotent: it REPLACES both functions
with the canonical text below rather than only filling in a missing one, so a
fleet that has accumulated divergent hand-edits converges. Guards:

  * a version gate — patch only the omnigent releases this was validated
    against, so a future release that fixes this upstream (or moves the code)
    is left alone and reported instead of silently re-patched;
  * the pristine file is kept as `.orig` on first run;
  * the result must parse and must still define both functions, or the
    original is put back.

It never fails the pod: every abnormal path logs and exits 0.

History: the 0.12.0 edition of this patch replaced `pi_native_model_options()`,
which returned [] outright. 0.16.0 added `pi_own_login_model_options()` as its
own fallback, so the smaller, more precise target is that function — the
managed path and its new live-listing logic are left untouched.
"""

from __future__ import annotations

import argparse
import ast
import glob
import os
import shutil
import sys

# Lifted from the build proven in this fleet, re-aimed at 0.16.0's own
# fallback. Keep it in sync with EXPECTED_VERSIONS: it reuses module globals
# (`subprocess`, `_LOGGER`, `Path`, `_global_pi_agent_dir`, `_read_json_object`,
# `_is_str_object_dict`) that upstream is free to rename between releases,
# which is exactly what the version gate protects.
CANONICAL = '''\
def pi_own_login_model_options(agent_dir: Path | None = None) -> list[dict[str, object]]:
    """Enumerate the models Pi's own login can use (the unmanaged fallback).

    Upstream reads Pi's ``models-store.json`` filtered to providers with an
    ``auth.json`` entry. Pi only writes that store for providers whose catalog
    it refreshes over the network, so a compatible endpoint declared in
    ``models.json`` -- the documented way to add a gateway -- appears in
    neither file and the picker comes up empty. When the file pair yields
    nothing, ask the installed Pi CLI, which already knows.

    :param agent_dir: Pi agent dir override (tests); defaults to the host's
        own Pi agent dir.
    :returns: Picker options shaped like :func:`pi_native_model_options`,
        qualified as ``provider/model`` -- the reference form Pi's ``--model``
        resolves natively against its own providers.
    """
    root = agent_dir if agent_dir is not None else _global_pi_agent_dir()
    logged_in = set(_read_json_object(root / "auth.json"))
    options: dict[str, dict[str, object]] = {}
    for provider_id, payload in _read_json_object(root / "models-store.json").items():
        if provider_id not in logged_in or not _is_str_object_dict(payload):
            continue
        models = payload.get("models")
        for model in models if isinstance(models, list) else []:
            if not _is_str_object_dict(model):
                continue
            model_id = model.get("id")
            if not isinstance(model_id, str) or not model_id:
                continue
            qualified = f"{provider_id}/{model_id}"
            name = model.get("name")
            options[qualified] = {
                "id": qualified,
                "model": qualified,
                "displayName": name if isinstance(name, str) and name else model_id,
            }
    if not options:
        return _ambient_pi_model_options(agent_dir)
    return [options[model_id] for model_id in sorted(options)]


def _ambient_pi_model_options(agent_dir: Path | None = None) -> list[dict[str, object]]:
    """List models exposed by Pi's own configured providers, without launching one.

    Only the rows after the ``provider  model ...`` header are models. With
    nothing configured Pi prints a "No models available" notice instead of a
    table (on stdout, exit code 0), which has no header and must not become a
    model. Total by contract: a missing CLI, a failure, a timeout or output that
    is not Pi's table yields ``[]``.
    """
    import os as _os
    import re as _re

    env = None if agent_dir is None else {**_os.environ, "PI_CODING_AGENT_DIR": str(agent_dir)}
    try:
        result = subprocess.run(
            ["pi", "--list-models"],
            capture_output=True,
            text=True,
            errors="replace",
            # `pi --list-models` measures 1-5s here. The host RPC that asks is cut
            # off at 15s (omnigent server/routes/hosts.py), so stay clear of it:
            # a slow CLI then means an empty picker, not an HTTP 504.
            timeout=12,
            check=False,
            stdin=subprocess.DEVNULL,
            env=env,
        )
    except (OSError, subprocess.SubprocessError):
        _LOGGER.info("pi-native: could not run `pi --list-models` for the model picker")
        return []
    if result.returncode != 0:
        _LOGGER.info("pi-native: `pi --list-models` failed; leaving the model picker empty")
        return []

    provider_ids = _re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
    options: dict[str, dict[str, object]] = {}
    in_table = False
    for line in result.stdout.splitlines():
        columns = line.split()
        if not in_table:
            in_table = columns[:2] == ["provider", "model"]
            continue
        # Skips blanks, a ``-----`` separator row and any trailing diagnostics.
        if len(columns) < 2 or not provider_ids.fullmatch(columns[0]):
            continue
        qualified = f"{columns[0]}/{columns[1]}"
        options[qualified] = {
            "id": qualified,
            "model": qualified,
            "displayName": columns[1],
        }
    return [options[model_id] for model_id in sorted(options)]
'''

ANCHOR = "pi_own_login_model_options"
TARGETS = (ANCHOR, "_ambient_pi_model_options")

# Where the module lives, newest layout first. 0.16.0 moved it into a package;
# 0.12.x kept it flat.
MODULE_PATHS = (
    os.path.join("omnigent", "harnesses", "pi_native", "credentials.py"),
    os.path.join("omnigent", "pi_native_credentials.py"),
)

# Roots to search when --tool-dir is not given (or finds nothing): the baked
# PaaS venv, the uv tool install, and the native installer's bundled copy.
DEFAULT_ROOTS = (
    "/opt/omnigent/venv",
    os.path.expanduser("~/.local/share/uv/tools/omnigent"),
    os.path.expanduser("~/.local/share/pi-agent/data/omnigent-plugin/uv/tools/omnigent"),
)


def log(msg: str) -> None:
    print(f"[omnigent-model-options-patch] {msg}", flush=True)


def find_site_packages(root: str) -> str | None:
    """Return omnigent's site-packages, whichever CPython built the env."""
    hits = sorted(glob.glob(os.path.join(root, "lib", "python3.*", "site-packages")))
    return hits[-1] if hits else None


def installed_version(site_packages: str) -> str | None:
    for path in glob.glob(os.path.join(site_packages, "omnigent-*.dist-info")):
        name = os.path.basename(path)
        return name[len("omnigent-") : -len(".dist-info")]
    return None


def find_module(site_packages: str) -> str | None:
    for relative in MODULE_PATHS:
        candidate = os.path.join(site_packages, relative)
        if os.path.isfile(candidate):
            return candidate
    return None


def spans(source: str) -> dict[str, tuple[int, int]]:
    """Map each target function to its 1-based inclusive line span."""
    found: dict[str, tuple[int, int]] = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef) and node.name in TARGETS:
            found[node.name] = (node.lineno, node.end_lineno or node.lineno)
    return found


def splice(source: str, found: dict[str, tuple[int, int]]) -> str:
    """Replace the target functions with CANONICAL, keeping one copy in place."""
    lines = source.splitlines()
    anchor = found[ANCHOR]
    # Drop the extra function first so the anchor's indices stay valid, and eat
    # the blank lines that used to separate it from its neighbour.
    for name, (start, end) in sorted(found.items(), key=lambda kv: -kv[1][0]):
        if name == ANCHOR:
            continue
        while start > 1 and not lines[start - 2].strip():
            start -= 1
        del lines[start - 1 : end]
    lines[anchor[0] - 1 : anchor[1]] = CANONICAL.rstrip("\n").splitlines()
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tool-dir",
        action="append",
        default=[],
        help="omnigent venv root; repeatable. Defaults are searched when omitted or unmatched.",
    )
    parser.add_argument(
        "--site-packages",
        help="patch the omnigent in this site-packages directly (build-time use)",
    )
    parser.add_argument(
        "--expected-version",
        action="append",
        default=[],
        help="only patch these omnigent versions; anything else is reported and skipped",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit non-zero when the patch does not apply (build-time use)",
    )
    args = parser.parse_args()

    # At runtime an unapplied patch is a degraded picker, never a dead pod, so
    # every path exits 0. A build must fail loudly instead: --strict.
    def give_up(message: str) -> int:
        log(message)
        return 1 if args.strict else 0

    expected = args.expected_version or ["0.16.0"]

    if args.site_packages:
        site_packages = args.site_packages if os.path.isdir(args.site_packages) else None
        if site_packages is None:
            return give_up(f"{args.site_packages} is not a directory — nothing to patch")
    else:
        roots = [*args.tool_dir, *DEFAULT_ROOTS]
        site_packages = None
        for root in roots:
            site_packages = find_site_packages(root)
            if site_packages:
                log(f"found omnigent under {root}")
                break
        if site_packages is None:
            return give_up(f"no omnigent install under any of {roots} — nothing to patch")

    version = installed_version(site_packages)
    if version not in expected:
        return give_up(
            f"omnigent {version or 'unknown'} is installed but this patch was validated "
            f"against {expected} — SKIPPING. Re-check whether the Pi model picker still "
            f"needs it, then bump omnigent.modelOptionsPatch.expectedVersion."
        )

    target = find_module(site_packages)
    if target is None:
        return give_up(f"pi_native credentials module not found under {site_packages}")

    try:
        original = open(target, encoding="utf-8").read()
    except OSError as exc:
        return give_up(f"cannot read {target}: {exc}")

    try:
        found = spans(original)
    except SyntaxError as exc:
        return give_up(f"{target} does not parse ({exc}) — leaving it alone")
    if ANCHOR not in found:
        return give_up(f"{ANCHOR}() is gone from this build — leaving it alone")

    patched = splice(original, found)
    if patched == original:
        log("already canonical — no change")
        return 0

    # A baked venv (PaaS bakes omnigent at /opt as root while the container
    # runs as uid 1000) is read-only: there is nothing to do at runtime and the
    # hook must not take the pod down over it. Patch such an image at BUILD
    # time instead.
    backup = target + ".orig"
    try:
        if not os.path.exists(backup):
            shutil.copy2(target, backup)
            log(f"kept the pristine file as {os.path.basename(backup)}")
    except OSError as exc:
        return give_up(f"cannot write beside {target} ({exc}) — read-only install, patch it at build time")

    tmp = target + ".patch-tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(patched)
    except OSError as exc:
        return give_up(f"cannot write {tmp} ({exc}) — read-only install, patch it at build time")
    try:
        rewritten = spans(open(tmp, encoding="utf-8").read())
        if set(rewritten) != set(TARGETS):
            raise ValueError(f"expected both functions, got {sorted(rewritten)}")
    except (SyntaxError, ValueError) as exc:
        os.unlink(tmp)
        return give_up(f"patched file rejected ({exc}) — original left in place")
    try:
        os.replace(tmp, target)
    except OSError as exc:
        os.unlink(tmp)
        return give_up(f"cannot replace {target} ({exc}) — original left in place")

    # A stale .pyc would keep serving the old body. mtime invalidation already
    # covers this; dropping the cache makes it certain and costs one import.
    stem = os.path.splitext(os.path.basename(target))[0]
    for cached in glob.glob(os.path.join(os.path.dirname(target), "__pycache__", f"{stem}.*.pyc")):
        try:
            os.unlink(cached)
        except OSError:
            pass

    log(f"patched {target} (omnigent {version})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
