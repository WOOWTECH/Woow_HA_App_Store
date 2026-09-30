#!/usr/bin/env python3
"""The visitor-tracking URL: a page view stores the Canonical URL.

``woow_visitor_url`` ships inside the image and is named in
``server_wide_modules``, so Odoo imports it in every process and installs it
in no database. Both halves run here without a live Odoo: ``tracked_url.py``
imports only ``urllib.parse``, and the patch in ``__init__.py`` is applied to
a stand-in of the ``website.visitor`` class Odoo declares, carrying the
``request.httprequest.url`` this issue replaces.
"""
import ast
import importlib
import importlib.util
import re
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SERVER_ADDONS = ROOT / "rootfs/opt/woow-server-addons"
MODULE_NAME = "woow_visitor_url"
MODULE = SERVER_ADDONS / MODULE_NAME
MODEL_NAME = "website.visitor"
METHOD_NAME = "_handle_webpage_dispatch"

# Documentation hosts only. Under Ingress the Supervisor has already removed
# the Ingress prefix, so the path is right and only the scheme and host are
# the Home Assistant ones.
HA_BASE = "http://ha.example.test:8123"
PUBLIC_BASE = "https://shop.example.test"
# What the LAN tier reaches when public_url is set, so the Canonical URL is
# the Public origin and the request arrives somewhere else.
LAN_BASE = "http://192.0.2.10:8069"


def load_decision():
    spec = importlib.util.spec_from_file_location(
        MODULE_NAME + "_tracked_url", MODULE / "tracked_url.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# tracked_url.py has to be importable without Odoo; loading it here is the proof.
decision = load_decision()


# --- The decision itself -----------------------------------------------------

def test_an_ingress_request_is_stored_on_the_website_base() -> None:
    assert decision.tracked_url(f"{HA_BASE}/contactus", PUBLIC_BASE) == f"{PUBLIC_BASE}/contactus"


def test_the_query_string_is_kept_and_the_path_is_not_touched() -> None:
    url = f"{HA_BASE}/jobs/detail/2?enable_editor=1&x=a%20b"
    assert decision.tracked_url(url, PUBLIC_BASE) == (
        f"{PUBLIC_BASE}/jobs/detail/2?enable_editor=1&x=a%20b"
    )


def test_an_empty_base_leaves_the_path_and_query_with_no_host() -> None:
    assert decision.tracked_url(f"{HA_BASE}/contactus?x=1", "") == "/contactus?x=1"
    assert decision.tracked_url(f"{HA_BASE}/contactus", None) == "/contactus"


def test_a_request_already_on_the_base_is_stored_unchanged() -> None:
    url = f"{PUBLIC_BASE}/contactus?x=1"
    assert decision.tracked_url(url, PUBLIC_BASE) == url


def test_a_base_with_a_trailing_slash_makes_no_double_slash() -> None:
    assert decision.tracked_url(f"{HA_BASE}/contactus", PUBLIC_BASE + "/") == (
        f"{PUBLIC_BASE}/contactus"
    )
    # The website root is the case the Visitors screen shows most often.
    assert decision.tracked_url(f"{HA_BASE}/", PUBLIC_BASE + "/") == f"{PUBLIC_BASE}/"


def test_a_base_that_carries_a_path_keeps_it_in_front_of_the_request_path() -> None:
    # website.domain may name a sub-path; the reverse proxy in front of it
    # maps that path to Odoo's root, so the stored URL needs both halves.
    assert decision.tracked_url(f"{HA_BASE}/contactus", f"{PUBLIC_BASE}/shop/") == (
        f"{PUBLIC_BASE}/shop/contactus"
    )


def test_a_request_with_no_path_is_stored_as_the_root() -> None:
    assert decision.tracked_url(HA_BASE, PUBLIC_BASE) == f"{PUBLIC_BASE}/"


def test_the_stored_value_carries_neither_the_home_assistant_host_nor_a_token() -> None:
    # The four addresses the #144 crawl found stored on the Home Assistant
    # host, each read back through the decision.
    for path in ("/", "/contactus", "/jobs/woow-parity-job-1", "/a-fixture-page"):
        stored = decision.tracked_url(HA_BASE + path, PUBLIC_BASE)
        assert stored == PUBLIC_BASE + path
        assert "ha.example.test" not in stored
        assert "/api/hassio_ingress/" not in stored


def test_an_empty_request_url_is_handed_back_as_it_is() -> None:
    assert decision.tracked_url("", PUBLIC_BASE) == ""
    assert decision.tracked_url(None, PUBLIC_BASE) is None


# --- A stand-in Odoo, close enough to show the gap ---------------------------

_MISSING = object()


class cached_url:
    """``werkzeug.utils.cached_property``, which is what ``Request.url`` is.

    Transcribed from werkzeug 3: a data descriptor whose ``__get__`` reads
    the instance ``__dict__`` first, so a value written there wins over the
    computed one. werkzeug is not a static-tier dependency, and the patch
    leans on exactly this behaviour, so it is spelled out here.
    """

    def __init__(self, fget):
        self.fget = fget
        self.__name__ = fget.__name__

    def __get__(self, obj, owner=None):
        if obj is None:
            return self
        value = obj.__dict__.get(self.__name__, _MISSING)
        if value is _MISSING:
            value = self.fget(obj)
            obj.__dict__[self.__name__] = value
        return value

    def __set__(self, obj, value):
        obj.__dict__[self.__name__] = value

    def __delete__(self, obj):
        del obj.__dict__[self.__name__]


class HttpRequest:
    """Just enough of a werkzeug request: a lazily computed, cachable url."""

    def __init__(self, url):
        self.computed = url
        self.computations = 0

    @cached_url
    def url(self):
        self.computations += 1
        return self.computed


class Website:
    def __init__(self, base):
        self.base = base

    def get_base_url(self):
        return self.base


class OdooRequest:
    """``odoo.http.request``: the proxy every Odoo module imports once."""

    def __init__(self, httprequest=None, website=_MISSING):
        self.httprequest = httprequest
        if website is not _MISSING:
            self.website = website


class Page:
    def __init__(self, page_id):
        self.id = page_id


def odoo_website_visitor(request):
    """Odoo's ``website.visitor``, the tracked URL included.

    Transcribed from ``addons/website/models/website_visitor.py`` of Odoo
    18.0 (``_handle_webpage_dispatch``, line 288): the method reads
    ``request.httprequest.url``, puts it in ``website_track_values`` and
    hands those to ``_get_visitor_from_request``, which creates the
    ``website.track`` row. Returned are the class the patch works on and the
    list of track values it would have written.
    """
    tracks = []

    class WebsiteVisitor:
        _name = "website.visitor"
        tracks_seen = tracks

        def _get_visitor_from_request(self, force_create=False, force_track_values=None):
            tracks.append(dict(force_track_values or {}))
            return self

        def _handle_webpage_dispatch(self, website_page):
            url = request.httprequest.url
            website_track_values = {'url': url}
            if website_page:
                website_track_values['page_id'] = website_page.id

            self._get_visitor_from_request(
                force_create=True, force_track_values=website_track_values
            )
            return "dispatched"

    return WebsiteVisitor, tracks


def install_patch(declared, request):
    """Import the shipped ``__init__.py`` against a stand-in ``website.visitor``.

    The module patches at import time, so the import is the patch. The fake
    ``odoo`` packages and the module itself are removed from ``sys.modules``
    again, leaving the rest of the run untouched.
    """
    website_visitor = visitor_namespace(declared)

    http = types.ModuleType("odoo.http")
    http.request = request

    fakes = {
        "odoo.addons.website.models.website_visitor": website_visitor,
        "odoo.http": http,
    }
    for name in [
        "odoo", "odoo.addons", "odoo.addons.website", "odoo.addons.website.models",
    ]:
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


def visitor_namespace(declared):
    """Odoo's website_visitor module as the patch and the probe read it."""
    namespace = types.ModuleType("odoo.addons.website.models.website_visitor")

    class WebsiteTrack:
        _name = "website.track"

    class WebsiteVisitorView(declared):  # inherits the method, declares none
        _name = "website.visitor"

    namespace.WebsiteTrack = WebsiteTrack
    namespace.WebsiteVisitor = declared
    namespace.WebsiteVisitorView = WebsiteVisitorView
    return namespace


def ingress_request(path="/contactus", base=PUBLIC_BASE):
    return OdooRequest(HttpRequest(HA_BASE + path), Website(base))


# --- The stand-in earns its place -------------------------------------------

def test_the_stand_in_reproduces_the_gap_when_nothing_patches_it() -> None:
    request = ingress_request()
    visitor, tracks = odoo_website_visitor(request)
    assert visitor()._handle_webpage_dispatch(Page(7)) == "dispatched"
    assert tracks == [{"url": f"{HA_BASE}/contactus", "page_id": 7}]


# --- The patched dispatch ----------------------------------------------------

def test_an_ingress_page_view_is_stored_on_the_canonical_url() -> None:
    request = ingress_request()
    declared, tracks = odoo_website_visitor(request)
    install_patch(declared, request)
    assert declared()._handle_webpage_dispatch(Page(7)) == "dispatched"
    assert tracks == [{"url": f"{PUBLIC_BASE}/contactus", "page_id": 7}]


def test_a_visit_already_on_the_canonical_url_stores_what_it_stored_before() -> None:
    request = OdooRequest(HttpRequest(f"{PUBLIC_BASE}/contactus?x=1"), Website(PUBLIC_BASE))
    declared, tracks = odoo_website_visitor(request)
    install_patch(declared, request)
    declared()._handle_webpage_dispatch(None)
    assert tracks == [{"url": f"{PUBLIC_BASE}/contactus?x=1"}]


def test_a_lan_tier_visit_without_a_public_url_stores_what_it_stored_before() -> None:
    # public_url empty: the Canonical URL is the host's LAN address with the
    # published Odoo port, which is where the request already arrived.
    request = OdooRequest(HttpRequest(f"{LAN_BASE}/contactus"), Website(LAN_BASE))
    declared, tracks = odoo_website_visitor(request)
    install_patch(declared, request)
    declared()._handle_webpage_dispatch(None)
    assert tracks == [{"url": f"{LAN_BASE}/contactus"}]


def test_an_empty_canonical_url_stores_the_path_with_no_host() -> None:
    request = OdooRequest(HttpRequest(f"{HA_BASE}/contactus"), Website(""))
    declared, tracks = odoo_website_visitor(request)
    install_patch(declared, request)
    declared()._handle_webpage_dispatch(None)
    assert tracks == [{"url": "/contactus"}]


def test_a_request_carrying_no_website_stores_the_path_with_no_host() -> None:
    # Nothing in Odoo calls the method outside website's dispatch, where the
    # website is set; a caller that does gets a URL without a wrong host
    # rather than a traceback.
    request = OdooRequest(HttpRequest(f"{HA_BASE}/contactus"))
    declared, tracks = odoo_website_visitor(request)
    install_patch(declared, request)
    declared()._handle_webpage_dispatch(None)
    assert tracks == [{"url": "/contactus"}]


def test_the_request_url_is_the_canonical_one_only_while_the_dispatch_runs() -> None:
    request = ingress_request()
    declared, _ = odoo_website_visitor(request)
    install_patch(declared, request)
    seen = []

    original = declared._get_visitor_from_request

    def watching(self, force_create=False, force_track_values=None):
        seen.append(request.httprequest.url)
        return original(self, force_create=force_create, force_track_values=force_track_values)

    declared._get_visitor_from_request = watching
    declared()._handle_webpage_dispatch(None)
    assert seen == [f"{PUBLIC_BASE}/contactus"]
    # A url the request had not computed yet must not be left cached either:
    # reading it afterwards is what tells the rest of the response, and the
    # next handler on this request, the address the browser really used.
    assert "url" not in vars(request.httprequest)
    assert request.httprequest.url == f"{HA_BASE}/contactus"


def test_the_request_url_is_restored_when_the_dispatch_raises() -> None:
    request = ingress_request()
    declared, _ = odoo_website_visitor(request)
    install_patch(declared, request)

    def boom(self, force_create=False, force_track_values=None):
        raise RuntimeError("creating the visitor failed")

    declared._get_visitor_from_request = boom
    request.httprequest.url  # cached before the call, as a served request is
    with pytest.raises(RuntimeError):
        declared()._handle_webpage_dispatch(None)
    assert request.httprequest.url == f"{HA_BASE}/contactus"


def test_a_url_already_cached_on_the_request_is_put_back_exactly() -> None:
    request = ingress_request()
    declared, _ = odoo_website_visitor(request)
    install_patch(declared, request)
    assert request.httprequest.url == f"{HA_BASE}/contactus"
    assert request.httprequest.computations == 1
    declared()._handle_webpage_dispatch(None)
    assert vars(request.httprequest)["url"] == f"{HA_BASE}/contactus"
    # Restoring by writing the value back, not by recomputing it.
    assert request.httprequest.computations == 1


def test_a_request_whose_url_cannot_be_written_is_left_alone_and_reported(caplog) -> None:
    """A werkzeug that stops reading the instance dict would make the swap a
    silent no-op. The patch has to notice rather than store the old value
    while looking applied."""

    class ReadOnlyRequest:
        url = property(lambda self: f"{HA_BASE}/contactus")

    request = OdooRequest(ReadOnlyRequest(), Website(PUBLIC_BASE))
    declared, tracks = odoo_website_visitor(request)
    install_patch(declared, request)
    with caplog.at_level("WARNING"):
        declared()._handle_webpage_dispatch(None)
    assert tracks == [{"url": f"{HA_BASE}/contactus"}]
    assert any("url" in record.message for record in caplog.records)


def test_the_patch_is_applied_once_and_finds_the_class_that_declares_the_method() -> None:
    request = ingress_request()
    declared, tracks = odoo_website_visitor(request)
    module = install_patch(declared, request)
    assert module.visitor_class(visitor_namespace(declared)) is declared
    # A second pass over an already patched class must not wrap the wrapper.
    assert module.patch_dispatch(declared) is False
    declared()._handle_webpage_dispatch(None)
    assert tracks == [{"url": f"{PUBLIC_BASE}/contactus"}]


def test_the_patch_takes_the_last_class_that_declares_the_method() -> None:
    """Odoo builds a model from every class declaring its _name, later
    declarations overriding earlier ones; the last one is what the registry
    runs, so it is the one to wrap. A later class that only inherits the
    method changes nothing and is skipped."""
    request = ingress_request()
    first, _ = odoo_website_visitor(request)
    last, _ = odoo_website_visitor(request)
    module = install_patch(first, request)
    namespace = visitor_namespace(first)
    namespace.WebsiteVisitorLast = last
    assert module.visitor_class(namespace) is last


def test_a_website_visitor_module_declaring_nothing_is_a_moved_seam() -> None:
    request = ingress_request()
    declared, _ = odoo_website_visitor(request)
    module = install_patch(declared, request)
    namespace = types.ModuleType("odoo.addons.website.models.website_visitor")

    class WebsiteVisitor:
        _name = "website.visitor"

    namespace.WebsiteVisitor = WebsiteVisitor
    with pytest.raises(ImportError):
        module.visitor_class(namespace)


# --- What the image ships ----------------------------------------------------

def test_the_patch_is_applied_at_import_time_not_through_an_inherit() -> None:
    source = (MODULE / "__init__.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    # A server-wide module is installed in no database, so an ORM class --
    # an _inherit on website.visitor -- would never take effect here.
    assert not [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)], (
        "the module patches the website.visitor class; it must not declare an ORM class"
    )
    statements = [node for node in tree.body if not isinstance(node, ast.FunctionDef)]
    assert any(
        isinstance(call.func, ast.Name) and call.func.id == "patch_dispatch"
        for node in statements
        for call in ast.walk(node)
        if isinstance(call, ast.Call)
    ), "__init__.py must call patch_dispatch at module level"


def test_a_missing_website_addon_leaves_odoo_running() -> None:
    """The patch must not break an Odoo process that cannot import website."""
    source = (MODULE / "__init__.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    handlers = [
        handler
        for node in ast.walk(tree)
        if isinstance(node, ast.Try)
        for handler in node.handlers
    ]
    assert any(
        isinstance(handler.type, ast.Name) and handler.type.id == "ImportError"
        for handler in handlers
    ), "importing website has to be allowed to fail"


def test_the_manifest_declares_a_module_that_is_never_installed() -> None:
    manifest = ast.literal_eval((MODULE / "__manifest__.py").read_text(encoding="utf-8"))
    assert manifest["depends"] == ["base"]
    assert manifest["installable"] is True
    assert manifest["auto_install"] is False
    # Nothing to install: no models, no data, no views.
    assert "data" not in manifest
    assert manifest["category"] == "Hidden"
    assert manifest["license"] == "LGPL-3"


CONFIG_SCRIPT = ROOT / "rootfs/etc/cont-init.d/10-odoo-config.sh"


def test_odoo_imports_the_module_in_every_process() -> None:
    script = CONFIG_SCRIPT.read_text(encoding="utf-8")
    modules = re.search(r"^server_wide_modules = (.+)$", script, re.M)
    assert modules, "10-odoo-config.sh renders no server_wide_modules line"
    assert MODULE_NAME in modules.group(1).split(",")
    # Imported by name, so the directory holding it has to be on the path.
    base_addons = re.search(r'^BASE_ADDONS="([^"]+)"', script, re.M)
    assert base_addons and "/opt/woow-server-addons" in base_addons.group(1).split(",")


# --- The PR gate sees the patch in the built image ---------------------------
#
# The stand-in above never moves with upstream, so none of the tests above can
# notice a nightly that moves website.visitor._handle_webpage_dispatch, and
# nothing stops Odoo when the module does not apply: its server-wide loader
# logs the error and serves untouched. The build tier therefore starts Odoo in
# the image it just built and asks this probe whether the patch is on, the way
# ADR 0010 does for the Canonical URL guard.

PROBE = ROOT / "tests/in_image/visitor_url_applied.py"
CI_WORKFLOW = ROOT.parent / ".github/workflows/ci.yml"


def load_probe():
    spec = importlib.util.spec_from_file_location("visitor_url_applied", PROBE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def probe_report(namespace):
    import io

    out = io.StringIO()
    status = load_probe().main(namespace, out)
    return status, out.getvalue()


def visitor_declaring(dispatch):
    """A website.visitor stand-in whose dispatch is the given function."""
    return type("WebsiteVisitor", (), {"_name": MODEL_NAME, METHOD_NAME: dispatch})


def test_the_probe_reports_an_unpatched_dispatch() -> None:
    request = ingress_request()
    declared, _ = odoo_website_visitor(request)
    assert load_probe().patched(visitor_namespace(declared)) is False


def test_the_probe_reports_the_patch_once_it_is_applied() -> None:
    request = ingress_request()
    declared, _ = odoo_website_visitor(request)
    install_patch(declared, request)
    assert load_probe().patched(visitor_namespace(declared)) is True


def test_the_probe_reports_a_moved_seam_as_unpatched() -> None:
    """A nightly that takes the dispatch out of website_visitor leaves
    nothing to find."""
    namespace = types.ModuleType("odoo.addons.website.models.website_visitor")
    namespace.WebsiteVisitor = type("WebsiteVisitor", (), {"_name": MODEL_NAME})
    assert load_probe().patched(namespace) is False


def test_the_probe_asks_odoo_and_never_applies_the_patch_itself() -> None:
    """Importing the module from the probe would make the check pass by itself."""
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
    # The flag is the probe's only link to the module; both spell it the same.
    source = (MODULE / "__init__.py").read_text(encoding="utf-8")
    flag = re.search(r'^PATCHED_FLAG = "(\w+)"$', source, re.M)
    assert flag and load_probe().PATCHED_FLAG == flag.group(1)


def test_the_probe_reports_applied_with_status_zero_when_the_wrapper_fits() -> None:
    request = ingress_request()
    declared, _ = odoo_website_visitor(request)
    install_patch(declared, request)
    status, report = probe_report(visitor_namespace(declared))
    assert status == 0
    assert report.splitlines() == ["visitor-url: applied"]


def test_the_probe_reports_not_applied_with_a_non_zero_status() -> None:
    request = ingress_request()
    declared, _ = odoo_website_visitor(request)
    status, report = probe_report(visitor_namespace(declared))
    assert status != 0
    assert report.splitlines() == ["visitor-url: not applied"]


def test_the_probe_fails_when_upstream_no_longer_takes_what_the_wrapper_forwards() -> None:
    """A nightly changes the dispatch's parameters. The patch still installs
    and sets its flag, so the flag alone would pass, and every tracked page
    view would then raise TypeError."""

    def _handle_webpage_dispatch(self, website_page, response):
        return None

    visitor = visitor_declaring(_handle_webpage_dispatch)
    install_patch(visitor, ingress_request())
    status, report = probe_report(visitor_namespace(visitor))
    assert status != 0
    mismatch = [
        line for line in report.splitlines()
        if line.startswith("visitor-url: signature mismatch")
    ]
    assert len(mismatch) == 1
    assert "response" in mismatch[0] and "website_page" in mismatch[0]


def test_the_probe_fails_when_upstream_stops_taking_a_forwarded_parameter_by_position() -> None:
    """Same name, but website_page became keyword-only: the wrapper still
    forwards it by position, so the flag is on and the dispatch raises."""

    def _handle_webpage_dispatch(self, *, website_page=None):
        return None

    visitor = visitor_declaring(_handle_webpage_dispatch)
    install_patch(visitor, ingress_request())
    with pytest.raises(TypeError):
        visitor()._handle_webpage_dispatch(None)
    status, report = probe_report(visitor_namespace(visitor))
    assert status != 0
    assert "keyword-only" in report


def test_an_upstream_that_adds_an_optional_parameter_still_fits() -> None:
    """A trailing parameter with a default takes nothing away from the
    wrapper's call; that nightly must not be blocked."""

    def _handle_webpage_dispatch(self, website_page, response=None):
        return "dispatched"

    visitor = visitor_declaring(_handle_webpage_dispatch)
    install_patch(visitor, ingress_request())
    assert visitor()._handle_webpage_dispatch(None) == "dispatched"
    status, report = probe_report(visitor_namespace(visitor))
    assert status == 0
    assert report.splitlines() == ["visitor-url: applied"]


def test_the_probe_reads_the_wrapper_itself_not_a_signature_copied_from_upstream() -> None:
    """functools.wraps copies __dict__, so a __signature__ upstream carries
    would make inspect.signature describe upstream on both sides."""
    import inspect

    def _handle_webpage_dispatch(self, website_page, response):
        return None

    _handle_webpage_dispatch.__signature__ = inspect.signature(_handle_webpage_dispatch)
    visitor = visitor_declaring(_handle_webpage_dispatch)
    install_patch(visitor, ingress_request())
    status, report = probe_report(visitor_namespace(visitor))
    assert status != 0
    assert "signature mismatch" in report


def test_the_probe_checks_the_class_the_registry_resolves_not_the_first_one_flagged() -> None:
    """Upstream adds a later website.visitor class that redefines the
    dispatch. The patch went on the earlier one and the registry uses the
    later one: the Home Assistant host is back while a flag is still there
    to find."""
    request = ingress_request()
    declared, _ = odoo_website_visitor(request)
    install_patch(declared, request)
    namespace = visitor_namespace(declared)

    class WebsiteVisitorRedefined(declared):
        _name = MODEL_NAME

        def _handle_webpage_dispatch(self, website_page):
            return None

    namespace.WebsiteVisitorRedefined = WebsiteVisitorRedefined
    status, report = probe_report(namespace)
    assert status != 0
    assert report.splitlines() == ["visitor-url: not applied"]


def test_a_later_class_that_only_inherits_the_dispatch_keeps_the_patch() -> None:
    """WebsiteVisitorView declares no dispatch of its own and comes last in
    the namespace; the registry resolves the patched one through it."""
    request = ingress_request()
    declared, _ = odoo_website_visitor(request)
    install_patch(declared, request)
    namespace = visitor_namespace(declared)
    assert list(vars(namespace))[-1] == "WebsiteVisitorView"
    assert load_probe().patched(namespace) is True


def visitor_url_step():
    import yaml

    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    job = workflow["jobs"]["build-amd64"]
    steps = [step for step in job["steps"] if "visitor_url_applied" in step.get("run", "")]
    assert len(steps) == 1, "build (amd64) needs exactly one step running the visitor-url probe"
    return job, steps[0]["run"]


def test_the_probe_runs_on_the_build_that_every_pull_request_gets() -> None:
    job, _ = visitor_url_step()
    # The aarch64 build only runs on a version bump; an Odoo nightly bump
    # changes the Dockerfile, not the version, so it would never get there.
    assert "if" not in job, "build (amd64) must stay unconditional"


def test_the_probe_starts_odoo_in_the_image_this_pull_request_built() -> None:
    _, run = visitor_url_step()
    assert "woow-ha-odoo-amd64:ci" in run
    assert "shell" in run and "/usr/bin/odoo" in run
    # The patched class lives in website, so Odoo's own addons directory has
    # to be on the path the probe run uses.
    assert "/usr/lib/python3/dist-packages/odoo/addons" in run
    # The server-wide list is the one the add-on renders, read from the
    # shipped config script, never a copy that could drift.
    assert CONFIG_SCRIPT.relative_to(ROOT).as_posix() in run
    assert "server_wide_modules" in run


def test_the_probe_is_shown_to_go_red_without_the_module() -> None:
    _, run = visitor_url_step()
    assert "--load" in run
    assert run.count("check_visitor_url") >= 3, "one definition, the real run and the mutation"
    assert "::error::" in run and MODULE_NAME in run


def test_the_probe_step_cannot_run_forever() -> None:
    job, run = visitor_url_step()
    # A nightly that makes `odoo shell` wait on a database would otherwise
    # hold the job for GitHub's 360-minute default.
    assert job.get("timeout-minutes") == 30
    assert run.count("timeout -k 30 300 docker run") == 1


def test_the_probe_step_blames_the_container_when_the_probe_never_reports() -> None:
    _, run = visitor_url_step()
    # docker run failing (image missing, odoo crashing, the timeout) leaves
    # no `visitor-url:` line at all. That is reported as what it is, not as
    # the patch being missing.
    assert "grep -q '^visitor-url: '" in run
    assert "not the patch" in run.lower()
    # Both runs echo their output before anything judges it, so a container
    # failure on the mutation run leaves something to read as well.
    assert run.count('echo "${out}"') == 2
    assert "signature mismatch" in run
