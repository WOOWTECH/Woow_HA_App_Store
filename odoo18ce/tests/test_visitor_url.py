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
import contextlib
import importlib
import importlib.util
import re
import sys
import types
import urllib.parse
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


@contextlib.contextmanager
def loader_has(module):
    """The module in ``sys.modules`` under the name Odoo's server-wide loader
    gives it, which is where the probe reads its url replacement.

    ``install_patch`` deliberately leaves nothing behind and the probe
    deliberately imports nothing, so a test that runs the probe bridges the two
    here -- ``loader_has(install_patch(...))`` is both halves at once.
    """
    name = load_probe().PATCH_MODULE
    sys.modules[name] = module
    try:
        yield module
    finally:
        del sys.modules[name]


def patch_module(swap_url=None, restore_url=None):
    """A stand-in for the loaded module, carrying the two functions the probe
    drives. Each defaults to what the shipped one does on a request that takes
    an assignment, so a test replaces only the half it is about.
    """
    module = types.ModuleType(load_probe().PATCH_MODULE)
    module.swap_url = swap_url or _assigning_swap
    module.restore_url = restore_url or _assigning_restore
    return module


def _assigning_swap(httprequest, value):
    setattr(httprequest, "url", value)
    return None, True


def _assigning_restore(httprequest, arrived, was_cached):
    setattr(httprequest, "url", arrived)


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


def odoo_request_class():
    """``odoo.http.Request``, as far as the probe reads it.

    Transcribed from ``odoo/http.py`` of Odoo 18.0 (``class Request``): the
    application builds the ``HTTPRequest`` wrapper and hands it in, and the
    request keeps it under ``httprequest``, which is the expression every
    module -- this patch included -- reads.
    """

    class Request:
        def __init__(self, httprequest):
            self.httprequest = httprequest

    return Request


def odoo_http_module(httprequest_class=None, request_class=None):
    """Odoo's ``odoo.http`` as the probe reads it: the two classes in it."""
    module = types.ModuleType("odoo.http")
    module.HTTPRequest = httprequest_class or odoo_http_request_class()
    module.Request = request_class or odoo_request_class()
    return module


def probe_report(namespace, http=None):
    import io

    out = io.StringIO()
    status = load_probe().main(namespace, http or odoo_http_module(), out)
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
    with loader_has(install_patch(declared, request)):
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
    with loader_has(install_patch(visitor, ingress_request())):
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


# --- The request Odoo really hands the patch (#160, reopened) ---------------
#
# Every stand-in above puts a werkzeug request behind ``request.httprequest``,
# whose ``url`` is a ``cached_property`` reading the instance ``__dict__``.
# Odoo 18 hands the patch no such object. ``odoo.http.HTTPRequest`` *wraps* a
# werkzeug request and, for every name in ``HTTPREQUEST_ATTRIBUTES`` -- ``url``
# among them -- installs on itself a plain ``property`` whose getter and setter
# delegate to the wrapped one (``odoo/http.py``, ``make_request_wrap_methods``).
# A plain ``property`` is a data descriptor that never reads the instance
# ``__dict__``, so the swap this module performs writes a dead entry into the
# wrapper and the dispatch stores the address the request arrived on -- which
# is what ``test_a_request_whose_url_cannot_be_written_is_left_alone_and_
# reported`` above calls a request that cannot be written, and what the Live
# rerun on 0.4.6 measured as ``U-C5`` still being a ``GAP``.
#
# Read on the deployed image (add-on ``1b7b4ce7_odoo18ce`` 0.4.6, werkzeug
# 2.2.2): ``vars(odoo.http.HTTPRequest)["url"]`` is a ``builtins.property``
# with a getter and a setter and no deleter; the instance-dict write is a
# no-op; ``httprequest.url = value`` does take, because Odoo's own setter
# reaches werkzeug's ``cached_property.__set__`` on the wrapped request, and
# assigning the arrived value back restores it. The host's Odoo log carries
# this module's own warning on every Ingress page view of that rerun.


def werkzeug_url(environ):
    """werkzeug's ``Request.url``, computed from a WSGI environ as it does.

    Enough of ``werkzeug.sansio.utils.get_current_url`` for an environ with
    no ``HTTP_HOST``: the scheme, the server name with its port unless that
    port is the scheme's default, the script root, the path and the query.
    """
    scheme, port = environ["wsgi.url_scheme"], environ["SERVER_PORT"]
    host = environ["SERVER_NAME"]
    if (scheme, port) not in (("http", "80"), ("https", "443")):
        host = f"{host}:{port}"
    url = f"{scheme}://{host}{environ.get('SCRIPT_NAME', '')}{environ['PATH_INFO']}"
    query = environ.get("QUERY_STRING")
    return f"{url}?{query}" if query else url


def odoo_http_request_class():
    """``odoo.http.HTTPRequest``: plain properties over a werkzeug request.

    Transcribed from ``odoo/http.py`` of Odoo 18.0 (``class HTTPRequest``,
    ``make_request_wrap_methods`` and ``HTTPREQUEST_ATTRIBUTES``): the class
    is built over a WSGI environ, wraps the werkzeug request it makes from it,
    and reads every forwarded attribute off -- and writes it onto -- that
    request. Name mangling makes the attribute ``_HTTPRequest__wrapped``
    there and here.
    """

    class HTTPRequest:
        def __init__(self, environ):
            self.__wrapped = HttpRequest(werkzeug_url(environ))

    for attr in ("url", "path", "query_string", "host"):
        def getter(self, attr=attr):
            return getattr(self._HTTPRequest__wrapped, attr)

        def setter(self, value, attr=attr):
            return setattr(self._HTTPRequest__wrapped, attr, value)

        setattr(HTTPRequest, attr, property(getter, setter))

    return HTTPRequest


def odoo_http_request(wrapped):
    """The wrapper Odoo builds, over a given werkzeug stand-in.

    Upstream's constructor makes its own werkzeug request out of an environ,
    which is what ``odoo_http_request_class()`` does; a test that needs a
    particular werkzeug stand-in behind the wrapper puts it there instead.
    """
    httprequest = object.__new__(odoo_http_request_class())
    httprequest._HTTPRequest__wrapped = wrapped
    return httprequest


def ingress_request_as_odoo_builds_it(path="/contactus", base=PUBLIC_BASE):
    return OdooRequest(odoo_http_request(HttpRequest(HA_BASE + path)), Website(base))


def test_the_stand_in_is_the_shape_odoo_hands_the_patch() -> None:
    """The wrapper's ``url`` is a plain property: written through, not cached."""
    httprequest = odoo_http_request(HttpRequest(HA_BASE + "/contactus"))
    descriptor = vars(type(httprequest))["url"]
    assert type(descriptor) is property
    assert descriptor.fget is not None and descriptor.fset is not None
    # No deleter, so the swap cannot be undone with ``del`` either.
    assert descriptor.fdel is None
    vars(httprequest)["url"] = f"{PUBLIC_BASE}/contactus"
    assert httprequest.url == f"{HA_BASE}/contactus"
    httprequest.url = f"{PUBLIC_BASE}/contactus"
    assert httprequest.url == f"{PUBLIC_BASE}/contactus"
    httprequest.url = f"{HA_BASE}/contactus"
    assert httprequest.url == f"{HA_BASE}/contactus"


def test_a_page_view_records_the_canonical_url_on_the_request_odoo_builds() -> None:
    request = ingress_request_as_odoo_builds_it()
    declared, tracks = odoo_website_visitor(request)
    install_patch(declared, request)
    declared()._handle_webpage_dispatch(Page(7))
    assert tracks == [{"url": f"{PUBLIC_BASE}/contactus", "page_id": 7}]
    # The rest of the response, and the next handler on this request, still
    # see the address the browser really used.
    assert request.httprequest.url == f"{HA_BASE}/contactus"


# --- The swap a flag cannot see (#160, reopened) -----------------------------
#
# The two tests above prove the replacement takes on the request Odoo really
# builds. These say what it leaves behind on that request, what happens when a
# future Odoo stops accepting it, and how the build tier sees either -- because
# on 0.4.6 the Build tier called the patch applied while the swap was a no-op,
# and only the Live tier noticed.


def test_the_swap_writes_no_dead_entry_into_the_wrappers_own_dict() -> None:
    """Writing into the wrapper's ``__dict__`` is the defect, not the fix: a
    plain ``property`` is a data descriptor, so such an entry is read by
    nobody and left behind for whatever does read the dict."""
    request = ingress_request_as_odoo_builds_it()
    declared, _ = odoo_website_visitor(request)
    install_patch(declared, request)
    seen = []

    original = declared._get_visitor_from_request

    def watching(self, force_create=False, force_track_values=None):
        seen.append((request.httprequest.url, "url" in vars(request.httprequest)))
        return original(self, force_create=force_create, force_track_values=force_track_values)

    declared._get_visitor_from_request = watching
    declared()._handle_webpage_dispatch(None)
    assert seen == [(f"{PUBLIC_BASE}/contactus", False)]
    assert "url" not in vars(request.httprequest)


def test_the_arrived_url_is_put_back_on_the_wrapper_when_the_dispatch_raises() -> None:
    request = ingress_request_as_odoo_builds_it()
    declared, _ = odoo_website_visitor(request)
    install_patch(declared, request)

    def boom(self, force_create=False, force_track_values=None):
        raise RuntimeError("creating the visitor failed")

    declared._get_visitor_from_request = boom
    with pytest.raises(RuntimeError):
        declared()._handle_webpage_dispatch(None)
    assert request.httprequest.url == f"{HA_BASE}/contactus"


def test_a_url_that_reads_back_as_it_arrived_is_reported_and_stored_as_it_arrived(caplog) -> None:
    """A request that accepts the assignment and goes on reporting the old
    address is the same silent no-op as one that refuses it: what must not
    happen is a page view stored on the Home Assistant host while the patch
    looks applied, which is how 0.4.6 shipped."""

    class SwallowingRequest:
        url = property(lambda self: self.arrived, lambda self, value: None)

        def __init__(self, url):
            self.arrived = url

    request = OdooRequest(SwallowingRequest(f"{HA_BASE}/contactus"), Website(PUBLIC_BASE))
    declared, tracks = odoo_website_visitor(request)
    install_patch(declared, request)
    with caplog.at_level("WARNING"):
        declared()._handle_webpage_dispatch(None)
    assert tracks == [{"url": f"{HA_BASE}/contactus"}]
    assert any("reads back" in record.message for record in caplog.records)
    assert request.httprequest.url == f"{HA_BASE}/contactus"


def test_a_url_whose_setter_raises_anything_at_all_leaves_the_response_standing(caplog) -> None:
    """A page view is not worth a failed response: whatever a request's own
    ``url`` raises, the dispatch runs and the view is stored as it arrived."""

    class AngryRequest:
        def _refuse(self, value):
            raise ValueError("this request will not be rewritten")

        url = property(lambda self: f"{HA_BASE}/contactus", _refuse)

    request = OdooRequest(AngryRequest(), Website(PUBLIC_BASE))
    declared, tracks = odoo_website_visitor(request)
    install_patch(declared, request)
    with caplog.at_level("WARNING"):
        assert declared()._handle_webpage_dispatch(Page(7)) == "dispatched"
    assert tracks == [{"url": f"{HA_BASE}/contactus", "page_id": 7}]
    # The reason is the one that happened, named, not a guess at which of the
    # ways it could fail did.
    reported = [record.message for record in caplog.records]
    assert any("ValueError" in message and "will not be rewritten" in message for message in reported)


class OneWayRequest:
    """A request that takes the first assignment and refuses every later one."""

    url = property(lambda self: self.read, lambda self, value: self._write(value))

    def __init__(self, url):
        self.read = url
        self.written = 0

    def _write(self, value):
        self.written += 1
        if self.written > 1:
            raise ValueError("no second assignment")
        self.read = value


def test_a_url_that_will_not_be_put_back_does_not_replace_what_the_dispatch_raised() -> None:
    """The restore runs in a finally. An exception of its own there would hide
    the dispatch's, which is the one worth reading."""
    request = OdooRequest(OneWayRequest(f"{HA_BASE}/contactus"), Website(PUBLIC_BASE))
    declared, _ = odoo_website_visitor(request)
    install_patch(declared, request)

    def boom(self, force_create=False, force_track_values=None):
        raise RuntimeError("creating the visitor failed")

    declared._get_visitor_from_request = boom
    with pytest.raises(RuntimeError, match="creating the visitor failed"):
        declared()._handle_webpage_dispatch(None)


def test_a_url_left_on_the_request_after_the_page_view_is_reported(caplog) -> None:
    """A request that takes the replacement and refuses to take its own address
    back reads as the Canonical URL for the whole of the rest of the response.
    The page view is right and everything after it is wrong, which is the one
    outcome that must not be silent."""
    request = OdooRequest(OneWayRequest(f"{HA_BASE}/contactus"), Website(PUBLIC_BASE))
    declared, tracks = odoo_website_visitor(request)
    install_patch(declared, request)
    with caplog.at_level("WARNING"):
        declared()._handle_webpage_dispatch(Page(7))
    assert tracks == [{"url": f"{PUBLIC_BASE}/contactus", "page_id": 7}]
    assert request.httprequest.url == f"{PUBLIC_BASE}/contactus"
    reported = [record.message for record in caplog.records]
    assert len(reported) == 1
    assert "could not be put back" in reported[0]
    assert f"{HA_BASE}/contactus" in reported[0] and "no second assignment" in reported[0]


def test_a_replacement_that_never_landed_is_reported_once_and_not_twice(caplog) -> None:
    """The refused forward path puts back whatever an assignment may have
    landed, and says nothing about having done it: nothing was replaced, so
    "it was replaced and could not be put back" would be the opposite of what
    happened, and a second warning per page view would be noise."""

    class ReadOnlyRequest:
        url = property(lambda self: f"{HA_BASE}/contactus")

    request = OdooRequest(ReadOnlyRequest(), Website(PUBLIC_BASE))
    declared, tracks = odoo_website_visitor(request)
    install_patch(declared, request)
    with caplog.at_level("WARNING"):
        declared()._handle_webpage_dispatch(None)
    assert tracks == [{"url": f"{HA_BASE}/contactus"}]
    reported = [record.message for record in caplog.records]
    assert len(reported) == 1
    assert "could not be replaced" in reported[0]
    assert "could not be put back" not in reported[0]


def test_a_replacement_that_landed_and_will_not_go_is_reported_as_both(caplog) -> None:
    """A refusal is not proof that nothing landed: a request whose setter takes
    the value, whose getter does not echo it, and which refuses a second write
    keeps the replacement. The page view is then recorded on what the request
    really reads -- which the warning names, rather than naming the address it
    arrived on -- and the request being left holding it is its own line."""

    class OneWayTransforming:
        url = property(lambda self: self.held, lambda self, value: self._write(value))

        def __init__(self, url):
            self.held = url
            self.written = 0

        def _write(self, value):
            if self.written:
                raise ValueError("no second assignment")
            self.written += 1
            self.held = value + "#transformed"

    request = OdooRequest(OneWayTransforming(f"{HA_BASE}/contactus"), Website(PUBLIC_BASE))
    declared, tracks = odoo_website_visitor(request)
    install_patch(declared, request)
    with caplog.at_level("WARNING"):
        declared()._handle_webpage_dispatch(None)
    left = f"{PUBLIC_BASE}/contactus#transformed"
    assert tracks == [{"url": left}]
    assert request.httprequest.url == left
    reported = [record.message for record in caplog.records]
    assert len(reported) == 2
    left_behind = [line for line in reported if "could not be put back" in line]
    recorded = [line for line in reported if "could not be replaced" in line]
    assert len(left_behind) == 1 and f"{HA_BASE}/contactus" in left_behind[0]
    # The page view is named for what it really records, not for the address
    # the request arrived on.
    assert len(recorded) == 1 and left in recorded[0]


def test_the_reason_the_swap_was_refused_is_the_one_reported() -> None:
    """Three shapes of refusal, three readings: one raised and left nothing on
    the request, one took the value and reads back as the address it arrived
    on, and one took it. Reporting any of them as another is how the 0.4.6 log
    read -- it named werkzeug, and werkzeug was not the problem."""
    request = ingress_request()
    declared, _ = odoo_website_visitor(request)
    module = install_patch(declared, request)

    class Raising:
        def _refuse(self, value):
            raise AttributeError("read-only")

        url = property(lambda self: f"{HA_BASE}/", _refuse)

    class Swallowing:
        url = property(lambda self: f"{HA_BASE}/", lambda self, value: None)

    raised, landed = module.swap_url(Raising(), PUBLIC_BASE)
    assert "assigning it raised" in raised
    # Nothing landed on a request that refused the assignment, so there is
    # nothing on it to put back and nothing to report about putting it back.
    assert landed is False
    assert module.swap_url(Swallowing(), PUBLIC_BASE) == (
        f"it reads back as {HA_BASE + '/'!r}", True
    )
    assert module.swap_url(HttpRequest(f"{HA_BASE}/"), PUBLIC_BASE) == (None, True)


def test_what_the_page_view_really_records_is_what_the_warning_names() -> None:
    """``reads_url`` answers with the request's own reading, and with the
    arrived address only when the request will not give one."""
    request = ingress_request()
    declared, _ = odoo_website_visitor(request)
    module = install_patch(declared, request)

    class Unreadable:
        @property
        def url(self):
            raise RuntimeError("this request will not say what it holds")

    assert module.reads_url(HttpRequest(f"{HA_BASE}/"), "fallback") == f"{HA_BASE}/"
    assert module.reads_url(Unreadable(), "fallback") == "fallback"


# --- The build tier performs the swap, it does not read a flag ---------------


def read_only_url(environ):
    """A request class whose ``url`` refuses every assignment."""

    class HTTPRequest:
        url = property(lambda self: werkzeug_url(environ))

        def __init__(self, environ):
            self.environ = environ

    return HTTPRequest


def test_the_probe_environ_names_an_address_that_is_not_the_replacement() -> None:
    """The swap would prove nothing if the request already read as the value
    the probe assigns."""
    probe = load_probe()
    assert werkzeug_url(probe.PROBE_ENVIRON) != probe.REPLACEMENT
    assert probe.PROBE_ENVIRON["SERVER_PORT"] not in ("80", "443")


def test_the_replacement_the_probe_asks_for_is_shaped_like_a_tracked_url() -> None:
    """A path and a query, because a real tracked URL has both -- and already
    percent-encoded, because a real one always is: ``tracked_url`` splices the
    base in front of the path and query werkzeug reports, and werkzeug reports
    those encoded. A gate asking for a value the module could never produce
    would red a build over a request that merely normalises what it is handed,
    which takes nothing away from this patch."""
    replacement = load_probe().REPLACEMENT
    parts = urllib.parse.urlsplit(replacement)
    assert parts.scheme and parts.netloc
    assert parts.path not in ("", "/") and parts.query
    # `%` is safe so an already-encoded value is left alone; a raw space in it
    # would not be.
    assert replacement == urllib.parse.quote(replacement, safe=":/?&=%")
    assert decision.tracked_url(f"{HA_BASE}{parts.path}?{parts.query}", "https://canonical.invalid") == (
        replacement
    )


def test_the_probe_performs_the_swap_on_the_request_odoo_builds() -> None:
    request = ingress_request()
    declared, _ = odoo_website_visitor(request)
    with loader_has(install_patch(declared, request)):
        assert load_probe().url_swap(odoo_http_module()) == (None, None)


def test_the_probe_fails_when_the_url_takes_no_assignment() -> None:
    probe, request = load_probe(), ingress_request()
    declared, _ = odoo_website_visitor(request)
    http = odoo_http_module(read_only_url(probe.PROBE_ENVIRON))
    with loader_has(install_patch(declared, request)):
        verdict, sentence = probe.url_swap(http)
    assert verdict == probe.NOT_REPLACEABLE
    # The module reported the assignment being refused, and the probe read the
    # url itself rather than taking that report for the answer.
    assert "assigning it raised" in sentence and "reads back" in sentence


def test_the_probe_fails_when_the_url_reads_back_as_the_address_it_arrived_on() -> None:
    """The 0.4.6 defect, in the shape the build tier would now see it: the
    assignment is accepted and changes nothing."""

    class HTTPRequest:
        url = property(lambda self: self.arrived, lambda self, value: None)

        def __init__(self, environ):
            self.arrived = werkzeug_url(environ)

    probe, request = load_probe(), ingress_request()
    declared, _ = odoo_website_visitor(request)
    with loader_has(install_patch(declared, request)):
        verdict, sentence = probe.url_swap(odoo_http_module(HTTPRequest))
    assert verdict == probe.NOT_REPLACEABLE
    assert "reads back" in sentence
    assert probe.REPLACEMENT in sentence


def test_the_probe_fails_when_the_request_class_cannot_be_built_over_an_environ() -> None:
    """A nightly whose HTTPRequest wants more than an environ leaves the swap
    unproven, which is not the same as proven and must not pass -- and is not
    the same as the patch being broken either, so it gets the other verdict."""

    class HTTPRequest:
        def __init__(self, environ, session):
            self.environ = environ

    probe, request = load_probe(), ingress_request()
    declared, _ = odoo_website_visitor(request)
    with loader_has(install_patch(declared, request)):
        verdict, sentence = probe.url_swap(odoo_http_module(HTTPRequest))
    assert verdict == probe.UNPROVABLE
    # Named for the class that would not build, not for the one built over it.
    assert sentence.startswith("odoo.http.HTTPRequest could not be built over a bare environ")


def test_the_probe_names_a_request_that_will_not_take_the_wrapper() -> None:
    """The other construction, reported as itself: the wrapper built and the
    request Odoo puts it in did not."""

    class Request:
        def __init__(self, httprequest, session):
            self.httprequest = httprequest

    probe, ingress = load_probe(), ingress_request()
    declared, _ = odoo_website_visitor(ingress)
    with loader_has(install_patch(declared, ingress)):
        verdict, sentence = probe.url_swap(odoo_http_module(request_class=Request))
    assert verdict == probe.UNPROVABLE
    assert sentence.startswith("odoo.http.Request could not be built over an HTTPRequest")


def test_the_probe_reports_an_odoo_http_that_no_longer_has_what_it_reads() -> None:
    """A renamed or removed class must come back as a sentence. Raising here
    would leave the probe printing no visitor-url: line at all, and the build
    step then blames the container rather than what the probe found."""
    probe, request = load_probe(), ingress_request()
    declared, _ = odoo_website_visitor(request)
    with loader_has(install_patch(declared, request)):
        for missing in ("HTTPRequest", "Request"):
            http = odoo_http_module()
            delattr(http, missing)
            assert probe.url_swap(http) == (
                probe.UNPROVABLE,
                f"odoo.http has no {missing}; the request it builds cannot be read here",
            )


def test_the_probe_swaps_through_the_request_and_not_through_a_class_it_names() -> None:
    """A nightly whose Request keeps something else under httprequest: the
    wrapper class is still replaceable and the expression the patch evaluates
    is not, which is the reading that matters."""

    class Request:
        def __init__(self, httprequest):
            self.httprequest = _ReadOnlyHttprequest(httprequest.url)

    probe, ingress = load_probe(), ingress_request()
    declared, _ = odoo_website_visitor(ingress)
    with loader_has(install_patch(declared, ingress)):
        verdict, sentence = probe.url_swap(odoo_http_module(request_class=Request))
    assert verdict == probe.NOT_REPLACEABLE
    assert "_ReadOnlyHttprequest" in sentence


class _ReadOnlyHttprequest:
    """Whatever a future Request might put there, refusing the swap."""

    url = property(lambda self: self.arrived)

    def __init__(self, url):
        self.arrived = url


def test_the_probe_reports_an_unreplaceable_url_with_a_non_zero_status() -> None:
    request = ingress_request()
    declared, _ = odoo_website_visitor(request)
    probe = load_probe()
    http = odoo_http_module(read_only_url(probe.PROBE_ENVIRON))
    with loader_has(install_patch(declared, request)):
        status, report = probe_report(visitor_namespace(declared), http)
    assert status != 0
    assert len(report.splitlines()) == 1
    assert report.startswith(f"visitor-url: {probe.NOT_REPLACEABLE} (")


def test_the_probe_reports_a_swap_it_could_not_perform_with_a_non_zero_status() -> None:
    request = ingress_request()
    declared, _ = odoo_website_visitor(request)
    http = odoo_http_module()
    delattr(http, "Request")
    with loader_has(install_patch(declared, request)):
        status, report = probe_report(visitor_namespace(declared), http)
    assert status != 0
    assert len(report.splitlines()) == 1
    assert report.startswith(f"visitor-url: {load_probe().UNPROVABLE} (")


def test_the_probe_drives_the_modules_own_functions_and_names_them_as_it_does() -> None:
    """The probe reads them out of ``sys.modules`` by name; the names have to be
    the ones Odoo's loader and the shipped module use, or the probe reports a
    module that is there as missing."""
    probe = load_probe()
    assert probe.PATCH_MODULE == f"odoo.addons.{MODULE_NAME}"
    source = (MODULE / "__init__.py").read_text(encoding="utf-8")
    defined = [
        node.name for node in ast.parse(source).body if isinstance(node, ast.FunctionDef)
    ]
    assert probe.SWAP_FUNCTION in defined
    assert probe.RESTORE_FUNCTION in defined


def test_the_probe_reports_a_module_it_cannot_drive_rather_than_importing_one() -> None:
    """Importing the module here is what the probe must never do -- it would
    apply the patch and pass by itself -- so a module that is not already
    loaded is reported, not fetched."""
    probe = load_probe()
    assert MODULE_NAME not in sys.modules and probe.PATCH_MODULE not in sys.modules
    verdict, sentence = probe.url_swap(odoo_http_module())
    assert verdict == probe.UNPROVABLE
    assert "not in sys.modules" in sentence
    # Still absent: reading it is all the probe did.
    assert probe.PATCH_MODULE not in sys.modules


def test_the_probe_reports_a_module_whose_functions_are_not_where_it_reads_them() -> None:
    probe = load_probe()
    for function in (probe.SWAP_FUNCTION, probe.RESTORE_FUNCTION):
        module = patch_module()
        delattr(module, function)
        with loader_has(module):
            verdict, sentence = probe.url_swap(odoo_http_module())
        assert verdict == probe.UNPROVABLE
        assert f"no callable {function}" in sentence


def test_the_probe_reports_a_replacement_that_raises_rather_than_dying_with_it() -> None:
    probe = load_probe()

    def swap_url(httprequest, value):
        raise RuntimeError("the replacement itself is broken")

    with loader_has(patch_module(swap_url=swap_url)):
        verdict, sentence = probe.url_swap(odoo_http_module())
    assert verdict == probe.UNPROVABLE
    assert "RuntimeError" in sentence and "broken" in sentence


def test_the_probe_does_not_ignore_the_modules_word_either() -> None:
    """A replacement that leaves the right value and reports a refusal: the
    module records the arrived address whenever it refuses, so the page view
    goes on the Home Assistant host and the probe has to say so."""
    probe = load_probe()

    def swap_url(httprequest, value):
        setattr(httprequest, "url", value)
        return "it reads back as something else", True

    with loader_has(patch_module(swap_url=swap_url)):
        verdict, sentence = probe.url_swap(odoo_http_module())
    assert verdict == probe.NOT_REPLACEABLE
    assert "it reads back as something else" in sentence


def test_the_probe_fails_when_the_url_comes_back_changed_at_all() -> None:
    """A request that stores what it is handed and reads back something else --
    here the query dropped. The page view would not carry the address asked
    for, whatever the module reported about the assignment."""

    class HTTPRequest:
        url = property(
            lambda self: self.read.split("?")[0],
            lambda self, value: setattr(self, "read", value),
        )

        def __init__(self, environ):
            self.read = werkzeug_url(environ)

    probe = load_probe()
    with loader_has(patch_module()):
        verdict, sentence = probe.url_swap(odoo_http_module(HTTPRequest))
    assert verdict == probe.NOT_REPLACEABLE
    assert "?woow=1" not in sentence.split("reads back")[1]


def test_the_probe_does_not_take_the_modules_word_for_the_replacement() -> None:
    """A replacement that reports success and changes nothing is exactly the
    0.4.6 defect, so the probe reads the url back itself."""
    probe = load_probe()
    nothing = lambda httprequest, value: (None, True)  # "it took", and it did not
    with loader_has(patch_module(swap_url=nothing)):
        verdict, sentence = probe.url_swap(odoo_http_module())
    assert verdict == probe.NOT_REPLACEABLE
    assert werkzeug_url(probe.PROBE_ENVIRON) in sentence
    assert "None" in sentence


def test_the_probe_fails_when_the_arrived_url_does_not_come_back() -> None:
    """The other half that depends on the request's shape. A page view stored
    on the Canonical URL and a request left reading it for the rest of the
    response is a different defect from the 0.4.6 one, and gets its own
    verdict."""
    probe = load_probe()
    with loader_has(patch_module(restore_url=lambda *args: None)):
        verdict, sentence = probe.url_swap(odoo_http_module())
    assert verdict == probe.NOT_PUT_BACK
    assert probe.REPLACEMENT in sentence
    assert werkzeug_url(probe.PROBE_ENVIRON) in sentence


def test_the_probe_reports_a_restore_that_raises_rather_than_dying_with_it() -> None:
    probe = load_probe()

    def restore_url(httprequest, arrived, was_cached):
        raise RuntimeError("the way back is broken")

    with loader_has(patch_module(restore_url=restore_url)):
        verdict, sentence = probe.url_swap(odoo_http_module())
    assert verdict == probe.UNPROVABLE
    assert "RuntimeError" in sentence and "way back" in sentence


def test_the_probe_drives_the_restore_the_way_the_dispatch_does() -> None:
    """Odoo's wrapper keeps no url in its own ``__dict__``, so the dispatch
    always reads ``was_cached`` False for it; the probe has to hand the restore
    the same thing, or it exercises a path the real request never takes."""
    seen = []
    probe = load_probe()

    def restore_url(httprequest, arrived, was_cached):
        seen.append(was_cached)
        setattr(httprequest, "url", arrived)

    with loader_has(patch_module(restore_url=restore_url)):
        assert probe.url_swap(odoo_http_module()) == (None, None)
    assert seen == [False]


def test_the_probe_reports_a_url_that_was_not_put_back_with_a_non_zero_status() -> None:
    request = ingress_request()
    declared, _ = odoo_website_visitor(request)
    probe = load_probe()
    install_patch(declared, request)
    with loader_has(patch_module(restore_url=lambda *args: None)):
        status, report = probe_report(visitor_namespace(declared))
    assert status != 0
    assert len(report.splitlines()) == 1
    assert report.startswith(f"visitor-url: {probe.NOT_PUT_BACK} (")


def test_the_probe_reports_a_request_that_no_longer_carries_an_httprequest() -> None:
    """A nightly that renames what the patch reads off the request. Raising
    here would print no visitor-url: line at all, and the build step would
    blame the container for exactly the shape change the unprovable verdict
    exists to name."""

    class Request:
        def __init__(self, httprequest):
            self.wrapped = httprequest  # not where the patch looks

    probe = load_probe()
    with loader_has(patch_module()):
        verdict, sentence = probe.url_swap(odoo_http_module(request_class=Request))
    assert verdict == probe.UNPROVABLE
    assert f"{probe.HTTPREQUEST_ATTRIBUTE} could not be read" in sentence


def test_the_probe_reads_odoos_own_request_class_and_builds_none_of_its_own() -> None:
    """The class under test has to come from the Odoo being probed, or the
    check proves something about this file instead."""
    tree = ast.parse(PROBE.read_text(encoding="utf-8"))
    main = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "main"
    )
    assert [argument.arg for argument in main.args.args[:2]] == ["website_visitor", "http"]
    entry = tree.body[-1]
    assert isinstance(entry, ast.If)
    imported = {
        alias.name
        for node in ast.walk(entry)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert "odoo.http" in imported
    assert not [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]


def test_the_build_step_tells_a_broken_swap_from_one_it_could_not_perform() -> None:
    """Three probe verdicts, three messages: a page view would record the Home
    Assistant host, a page view would be right and the rest of its response
    wrong, or this Odoo changed shape and nothing is known about the patch. One
    message for all of them is the container-versus-patch conflation
    `probe_reported` exists to avoid."""
    probe, (_, run) = load_probe(), visitor_url_step()
    for verdict in (probe.NOT_REPLACEABLE, probe.NOT_PUT_BACK, probe.UNPROVABLE):
        assert f"^visitor-url: {verdict}" in run, verdict
    assert run.count("::error::") == run.count("exit 1") >= 6
