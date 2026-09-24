#!/usr/bin/env python3
"""The base-URL guard: Odoo never writes the Canonical URL by itself.

``woow_base_url_guard`` ships inside the image and is named in
``server_wide_modules``, so Odoo imports it in every process and installs it
in no database. Both halves run here without a live Odoo: ``guard.py``
imports nothing, and the patch in ``__init__.py`` is applied to a stand-in
of the ``res.users`` class Odoo declares, carrying the guess this issue
removes.
"""
import ast
import importlib
import importlib.util
import re
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER_ADDONS = ROOT / "rootfs/opt/woow-server-addons"
MODULE_NAME = "woow_base_url_guard"
MODULE = SERVER_ADDONS / MODULE_NAME

BASE_URL_KEY = "web.base.url"
FREEZE_KEY = "web.base.url.freeze"
# What Odoo derives from an Ingress request: the Home Assistant host, never
# the Canonical URL. Documentation host only.
BASE_LOCATION = "http://ha.example.test:8123"
CREDENTIAL = {"login": "admin", "type": "password", "password": "static-tier-placeholder"}
# Identity, not equality, is asserted on this: the guard hands back whatever
# Odoo returned, untouched.
AUTH_INFO = {"uid": 2, "auth_method": "password", "mfa": "default"}


def load_guard():
    spec = importlib.util.spec_from_file_location(MODULE_NAME + "_guard", MODULE / "guard.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# guard.py has to be importable without Odoo; loading it here is the proof.
guard = load_guard()


class FakeConfigParameters:
    """Just enough ``ir.config_parameter`` to observe the guess."""

    def __init__(self, params=None):
        self.params = dict(params or {})
        self.writes = []

    def get_param(self, key, default=False):
        return self.params.get(key, default)

    def set_param(self, key, value):
        self.writes.append((key, value))
        self.params[key] = value


def odoo_users(params=None):
    """Odoo res.users, guess included, as two classes and a parameter store.

    Transcribed from the source read on the `.6` host (18.0 nightly
    20260914): once ``_login`` has succeeded for a ``base.group_system``
    user, a ``base_location`` in ``user_agent_env`` is written into
    ``web.base.url`` unless ``web.base.url.freeze`` is set.

    Odoo declares one class and builds a subclass of it per database; only
    that subclass carries ``pool``, and the original reaches it through the
    ``cls`` it is called with. Returned are the declared class (what the
    guard patches), the registry subclass (what callers use) and the
    parameter store.
    """
    icp = FakeConfigParameters(params)
    calls = []

    class Users:
        _name = "res.users"
        pool = None
        calls_seen = calls
        config_parameters = icp

        @classmethod
        def authenticate(cls, db, credential, user_agent_env):
            assert cls.pool is not None, "authenticate must run on the registry class"
            calls.append((db, credential, user_agent_env))
            if user_agent_env and user_agent_env.get("base_location"):
                if not icp.get_param(FREEZE_KEY):
                    icp.set_param(BASE_URL_KEY, user_agent_env["base_location"])
            return AUTH_INFO

    class Registry(Users):
        pool = object()

    return Users, Registry, icp


def install_guard(declared):
    """Import the shipped ``__init__.py`` against a stand-in ``res.users``.

    The module patches at import time, so the import is the patch. The fake
    ``odoo`` package and the module itself are removed from ``sys.modules``
    again, leaving the rest of the run untouched.
    """
    res_users = types.ModuleType("odoo.addons.base.models.res_users")

    class Groups:  # a class in the same namespace that is not res.users
        _name = "res.groups"

    class UsersView(declared):  # inherits authenticate, declares none
        _name = "res.users"

    res_users.Groups = Groups
    res_users.Users = declared
    res_users.UsersView = UsersView

    fakes = {"odoo.addons.base.models.res_users": res_users}
    for name in ["odoo", "odoo.addons", "odoo.addons.base", "odoo.addons.base.models"]:
        fakes[name] = types.ModuleType(name)
    sys.modules.update(fakes)
    sys.path.insert(0, str(SERVER_ADDONS))
    try:
        return importlib.import_module(MODULE_NAME)
    finally:
        sys.path.remove(str(SERVER_ADDONS))
        for name in list(sys.modules):
            if name in fakes or name == MODULE_NAME or name.startswith(MODULE_NAME + "."):
                del sys.modules[name]


def ingress_env():
    return {"interactive": True, "base_location": BASE_LOCATION}


# --- The stand-in earns its place -------------------------------------------

def test_the_stand_in_reproduces_the_gap_when_nothing_guards_it() -> None:
    _, registry, icp = odoo_users()
    assert registry.authenticate("odoo_test", CREDENTIAL, ingress_env()) is AUTH_INFO
    assert icp.writes == [(BASE_URL_KEY, BASE_LOCATION)]


def test_the_stand_in_respects_the_freeze_like_odoo_does() -> None:
    _, registry, icp = odoo_users({FREEZE_KEY: True})
    registry.authenticate("odoo_test", CREDENTIAL, ingress_env())
    assert icp.writes == []


# --- The patched login path --------------------------------------------------

def test_the_patched_login_writes_no_base_url_and_returns_the_auth_info_unchanged() -> None:
    declared, registry, icp = odoo_users()
    install_guard(declared)
    # A database created between two starts carries no freeze; the guess
    # still never happens.
    result = registry.authenticate("odoo_test", CREDENTIAL, ingress_env())
    assert icp.writes == []
    assert icp.params == {}
    assert result is AUTH_INFO


def test_the_patched_login_delegates_everything_but_the_guess_input() -> None:
    declared, registry, _ = odoo_users()
    install_guard(declared)
    registry.authenticate("odoo_test", CREDENTIAL, user_agent_env=ingress_env())
    (db, credential, user_agent_env), = declared.calls_seen
    assert db == "odoo_test"
    assert credential is CREDENTIAL
    # The rest of the environment reaches Odoo untouched: auth_totp reads
    # `interactive` from it.
    assert user_agent_env == {"interactive": True}


def test_the_patch_is_applied_once_and_finds_the_class_that_declares_the_method() -> None:
    declared, registry, _ = odoo_users()
    module = install_guard(declared)
    assert module.users_class() is declared
    # A second pass over an already guarded class must not wrap the wrapper.
    assert module.patch_authenticate(declared) is False
    registry.authenticate("odoo_test", CREDENTIAL, ingress_env())
    assert declared.config_parameters.writes == []


# --- The decision itself -----------------------------------------------------

def test_the_guard_leaves_the_caller_environment_alone() -> None:
    env = ingress_env()
    assert guard.without_base_location(env) == {"interactive": True}
    assert env == ingress_env(), "the caller dict must not be mutated"


def test_an_environment_without_a_base_location_passes_through_untouched() -> None:
    env = {"interactive": True}
    assert guard.without_base_location(env) is env
    assert guard.without_base_location({}) == {}
    assert guard.without_base_location(None) is None


def test_an_empty_base_location_is_still_dropped() -> None:
    # Odoo skips the guess for a falsy base_location, so this only has to
    # stay harmless -- the key is gone either way.
    assert guard.without_base_location({"base_location": ""}) == {}


# --- What the image ships ----------------------------------------------------

def test_the_patch_is_applied_at_import_time_not_through_an_inherit() -> None:
    source = (MODULE / "__init__.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    # A server-wide module is installed in no database, so an ORM class --
    # an _inherit on res.users -- would never take effect here.
    assert not [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)], (
        "the guard patches the res.users class; it must not declare an ORM class"
    )
    assert "classmethod(" in source, "authenticate is a classmethod and has to stay one"
    # The patch runs while the module is imported, not from a hook that only
    # a database install would reach: a statement, not just a definition,
    # has to call it.
    statements = [node for node in tree.body if not isinstance(node, ast.FunctionDef)]
    assert any(
        isinstance(call.func, ast.Name) and call.func.id == "patch_authenticate"
        for node in statements
        for call in ast.walk(node)
        if isinstance(call, ast.Call)
    ), "__init__.py must call patch_authenticate at module level"


def test_the_manifest_declares_a_module_that_is_never_installed() -> None:
    manifest = ast.literal_eval((MODULE / "__manifest__.py").read_text(encoding="utf-8"))
    assert manifest["depends"] == ["base"]
    assert manifest["installable"] is True
    assert manifest["auto_install"] is False
    # Nothing to install: no models, no data, no views.
    assert "data" not in manifest
    assert manifest["category"] == "Hidden"
    assert manifest["license"] == "LGPL-3"


# --- The PR gate sees the patch in the built image (issue #88) ---------------
#
# The stand-in above never moves with upstream, so none of the tests above
# can notice a nightly that moves res.users.authenticate. And the guard's
# ImportError does not stop Odoo: its server-wide loader logs the error and
# serves unguarded. The build tier therefore starts Odoo in the image it just
# built and asks this probe whether the patch is on.

PROBE = ROOT / "tests/in_image/base_url_guard_applied.py"
CI_WORKFLOW = ROOT.parent / ".github/workflows/ci.yml"
CONFIG_SCRIPT = ROOT / "rootfs/etc/cont-init.d/10-odoo-config.sh"


def load_probe():
    spec = importlib.util.spec_from_file_location("base_url_guard_applied", PROBE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def res_users_namespace(declared):
    """Odoo's res_users module as the probe reads it."""
    namespace = types.ModuleType("odoo.addons.base.models.res_users")

    class Groups:
        _name = "res.groups"

    class UsersView(declared):
        _name = "res.users"

    namespace.Groups = Groups
    namespace.Users = declared
    namespace.UsersView = UsersView
    return namespace


def test_the_probe_reports_an_unguarded_authenticate() -> None:
    declared, _, _ = odoo_users()
    assert load_probe().guarded(res_users_namespace(declared)) is False


def test_the_probe_reports_the_patch_once_the_guard_is_applied() -> None:
    declared, _, _ = odoo_users()
    install_guard(declared)
    assert load_probe().guarded(res_users_namespace(declared)) is True


def test_the_probe_reports_a_moved_seam_as_unguarded() -> None:
    """A nightly that takes authenticate out of res_users leaves nothing to find."""
    namespace = types.ModuleType("odoo.addons.base.models.res_users")

    class Users:
        _name = "res.users"

    namespace.Users = Users
    assert load_probe().guarded(namespace) is False


def test_the_probe_asks_odoo_and_never_applies_the_guard_itself() -> None:
    """Importing the guard from the probe would make the check pass by itself."""
    tree = ast.parse(PROBE.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    } | {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert not [name for name in imported if MODULE_NAME in name]
    # The flag is the probe's only link to the guard; both spell it the same.
    source = (MODULE / "__init__.py").read_text(encoding="utf-8")
    flag = re.search(r'^GUARDED_FLAG = "(\w+)"$', source, re.M)
    assert flag and load_probe().GUARDED_FLAG == flag.group(1)


def guard_step():
    import yaml

    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    job = workflow["jobs"]["build-amd64"]
    steps = [step for step in job["steps"] if "base_url_guard_applied" in step.get("run", "")]
    assert len(steps) == 1, "build (amd64) needs exactly one step running the guard probe"
    return job, steps[0]["run"]


def test_the_guard_probe_runs_on_the_build_that_every_pull_request_gets() -> None:
    job, _ = guard_step()
    # The aarch64 build only runs on a version bump; an Odoo nightly bump
    # changes the Dockerfile, not the version, so it would never get there.
    assert "if" not in job, "build (amd64) must stay unconditional"
    assert "load: true" in CI_WORKFLOW.read_text(encoding="utf-8")


def test_the_guard_probe_starts_odoo_in_the_image_this_pull_request_built() -> None:
    _, run = guard_step()
    assert "woow-ha-odoo-amd64:ci" in run
    assert "shell" in run and "/usr/bin/odoo" in run
    # The server-wide list is the one the add-on renders, read from the
    # shipped config script, never a copy that could drift.
    assert CONFIG_SCRIPT.relative_to(ROOT).as_posix() in run
    assert "server_wide_modules" in run


def test_the_guard_probe_is_shown_to_go_red_without_the_guard() -> None:
    _, run = guard_step()
    # The mutation: the same run with the guard left out of --load must fail.
    assert "--load" in run
    assert run.count("check_guard") >= 3, "one definition, the real run and the mutation"
    assert "::error::" in run and "guard" in run.lower()


# --- The gate proves more than the flag (issue #121) --------------------------
#
# The flag says the guard installed. It does not say the wrapper still fits
# upstream's authenticate, nor that the class it patched is the one the
# registry resolves. Either lets a nightly merge green with the guess back
# or every login broken.

def probe_report(namespace):
    import io

    out = io.StringIO()
    status = load_probe().main(namespace, out)
    return status, out.getvalue()


def flagged(function) -> bool:
    # The probe's spelling is asserted equal to the guard's above.
    return getattr(function, load_probe().GUARDED_FLAG, False)


def users_declaring(authenticate):
    """A res.users stand-in whose authenticate is the given function."""
    return type("Users", (), {"_name": "res.users", "authenticate": classmethod(authenticate)})


def test_the_probe_reports_applied_with_status_zero_when_the_wrapper_fits() -> None:
    declared, _, _ = odoo_users()
    install_guard(declared)
    status, report = probe_report(res_users_namespace(declared))
    assert status == 0
    assert report.splitlines() == ["base-url-guard: applied"]


def test_the_probe_reports_not_applied_with_a_non_zero_status() -> None:
    declared, _, _ = odoo_users()
    status, report = probe_report(res_users_namespace(declared))
    assert status != 0
    assert report.splitlines() == ["base-url-guard: not applied"]


def test_the_probe_fails_when_upstream_no_longer_takes_what_the_wrapper_forwards() -> None:
    """A nightly changes authenticate's parameters. The guard still installs
    and sets its flag, so the flag alone would pass, and every login would
    then raise TypeError. The probe has to read the upstream signature."""

    def authenticate(cls, db, credential, user_agent_env, request_context):
        return AUTH_INFO

    users = users_declaring(authenticate)
    install_guard(users)
    assert flagged(users.authenticate)
    status, report = probe_report(res_users_namespace(users))
    assert status != 0
    lines = report.splitlines()
    mismatch = [line for line in lines if line.startswith("base-url-guard: signature mismatch")]
    assert len(mismatch) == 1
    assert "request_context" in mismatch[0] and "user_agent_env" in mismatch[0]
    assert "base-url-guard: applied" not in lines


def test_the_probe_fails_when_upstream_stops_taking_a_forwarded_parameter_by_position() -> None:
    """Same names, but user_agent_env became keyword-only: the wrapper still
    forwards it by position, so the flag is on and the login raises."""

    def authenticate(cls, db, credential, *, user_agent_env=None):
        return AUTH_INFO

    users = users_declaring(authenticate)
    install_guard(users)
    with __import__("pytest").raises(TypeError):
        users.authenticate("odoo_test", CREDENTIAL, ingress_env())
    status, report = probe_report(res_users_namespace(users))
    assert status != 0
    assert "keyword-only" in report


def test_an_upstream_that_adds_an_optional_parameter_still_fits() -> None:
    """A trailing parameter with a default takes nothing away from the
    wrapper's call; that nightly must not be blocked."""

    def authenticate(cls, db, credential, user_agent_env, request_context=None):
        return AUTH_INFO

    users = users_declaring(authenticate)
    install_guard(users)
    assert users.authenticate("odoo_test", CREDENTIAL, ingress_env()) is AUTH_INFO
    status, report = probe_report(res_users_namespace(users))
    assert status == 0
    assert report.splitlines() == ["base-url-guard: applied"]


def test_the_probe_reads_the_wrapper_itself_not_a_signature_copied_from_upstream() -> None:
    """functools.wraps copies __dict__, so a __signature__ upstream carries
    would make inspect.signature describe upstream on both sides."""
    import inspect

    def authenticate(cls, db, credential, user_agent_env, request_context):
        return AUTH_INFO

    authenticate.__signature__ = inspect.signature(authenticate)
    users = users_declaring(authenticate)
    install_guard(users)
    assert flagged(users.authenticate)
    status, report = probe_report(res_users_namespace(users))
    assert status != 0
    assert "signature mismatch" in report


def test_the_probe_checks_the_class_the_registry_resolves_not_the_first_one_flagged() -> None:
    """Upstream adds a later res.users class that redefines authenticate. The
    guard patched the earlier one and the registry uses the later one: the
    guess is back while a flag is still there to find."""
    declared, _, _ = odoo_users()
    install_guard(declared)
    namespace = res_users_namespace(declared)

    class UsersRedefined(declared):
        _name = "res.users"

        @classmethod
        def authenticate(cls, db, credential, user_agent_env):
            return AUTH_INFO

    namespace.UsersRedefined = UsersRedefined
    assert flagged(namespace.Users.authenticate)
    status, report = probe_report(namespace)
    assert status != 0
    assert report.splitlines() == ["base-url-guard: not applied"]


def test_a_later_class_that_only_inherits_authenticate_keeps_the_guard() -> None:
    """UsersView declares no authenticate of its own, and comes last in the
    namespace; the registry resolves the patched one through it."""
    declared, _, _ = odoo_users()
    install_guard(declared)
    namespace = res_users_namespace(declared)
    assert list(vars(namespace))[-1] == "UsersView"
    assert load_probe().guarded(namespace) is True


def test_the_guard_probe_step_cannot_run_forever() -> None:
    job, run = guard_step()
    # A nightly that makes `odoo shell` wait on a database would otherwise
    # hold the job for GitHub's 360-minute default.
    assert job.get("timeout-minutes") == 30
    assert run.count("timeout -k 30 300 docker run") == 1, "the one docker run goes through a timeout"


def test_the_guard_probe_step_blames_the_container_when_the_probe_never_reports() -> None:
    _, run = guard_step()
    # docker run failing (image missing, odoo crashing, the timeout) leaves
    # no `base-url-guard:` line at all. That is reported as what it is, not
    # as the guard being missing.
    assert "grep -q '^base-url-guard: '" in run
    assert "not the guard" in run.lower()
    # Both runs echo their output before anything judges it, so a container
    # failure on the mutation run leaves something to read as well.
    assert run.count('echo "${out}"') == 2
    assert run.index('echo "${out}"', run.index("without_guard}\")")) < run.rindex("probe_reported")
    # A wrapper that no longer fits upstream gets its own error.
    assert "signature mismatch" in run
    assert run.count("::error::") >= 5
