"""Is ``website.visitor._handle_webpage_dispatch`` patched in this Odoo? Issue #160.

The build tier pipes this file into ``odoo shell`` in the image it just
built, with no database: by then Odoo's own loader has imported the
server-wide modules the add-on configures. When ``woow_visitor_url`` cannot
find its seam, or cannot import ``website`` at all, that loader only logs it
and carries on, so asking Odoo whether the patch is on is the one check that
goes red. The probe never imports the module itself -- that would apply the
patch and pass by itself.

What the flag alone would not prove -- the two things ADR 0010's amendment
named for the Canonical URL guard (issue #121), and the one the reopened #160
adds:

* the class the module patched is the last one in ``website_visitor``
  declaring ``_handle_webpage_dispatch``. Odoo builds a model from every
  class declaring its ``_name``, later declarations overriding earlier ones,
  so within that module the last declaration is the one the registry runs.
  Overrides in other modules are not read here: the tracked URL is built in
  ``website_visitor``, and an override elsewhere reaches it through
  ``super()``;
* the wrapper still fits upstream. ``functools.wraps`` keeps the original
  under ``__wrapped__``; if a nightly changed its parameters the patch still
  installs and every tracked page view raises ``TypeError``;
* the url replacement the patch performs takes on the request Odoo builds.
  This is the half issue #160 was reopened over: the flag was on the host and
  every Ingress page view still recorded the Home Assistant host, because
  ``odoo.http.HTTPRequest`` forwards ``url`` through a plain ``property`` that
  never reads the instance ``__dict__``. A flag cannot see that; building this
  image's own ``request`` and having the module replace the url on it can.

Prints one of ``visitor-url: applied``, ``visitor-url: not applied``,
``visitor-url: signature mismatch (...)``, ``visitor-url: url not replaceable
(...)``, ``visitor-url: url not put back (...)`` or ``visitor-url: url swap
unprovable (...)``. Exit status 0 only for the first.
"""
import inspect
import sys

# Set by woow_visitor_url on the dispatch it installs.
PATCHED_FLAG = "_woow_visitor_url_patched"
MODEL = "website.visitor"
METHOD = "_handle_webpage_dispatch"
# The attribute the patch replaces for the length of one dispatch, and the one
# it reads off Odoo's request to get at it.
URL_ATTRIBUTE = "url"
HTTPREQUEST_ATTRIBUTE = "httprequest"
# A complete, minimal WSGI environ: enough for werkzeug to compute a url and
# for Odoo's wrapper to be built over it, with no server, no database and no
# request behind it. The port is not the scheme's default, so the url werkzeug
# computes from it carries one and cannot be mistaken for the replacement.
PROBE_ENVIRON = {
    "wsgi.url_scheme": "http",
    "REQUEST_METHOD": "GET",
    "SERVER_NAME": "probe.invalid",
    "SERVER_PORT": "8069",
    "SCRIPT_NAME": "",
    "PATH_INFO": "/probe",
    "QUERY_STRING": "",
}
# What the probe asks the module to put on that request, and what it asks to
# have put back afterwards. The replacement carries a path and a query because
# a real tracked URL does, and it is already percent-encoded because a real one
# always is: ``tracked_url`` splices the base in front of the path and query
# werkzeug reports, and werkzeug reports those encoded. Asking for a value the
# module could never produce would red a build over a request that merely
# normalises what it is handed, which is not something this patch needs.
REPLACEMENT = "https://canonical.invalid/probe/page?woow=1&x=a%20b"
# The three ways the round trip can fail, kept apart because the build step says
# something different about each: a request that changed shape and tells nothing
# about the patch, a page view that would record the Home Assistant host, and a
# page view recorded right on a request left reading the Canonical URL for the
# rest of its response. ``url_swap`` below says which is which.
UNPROVABLE = "url swap unprovable"
NOT_REPLACEABLE = "url not replaceable"
NOT_PUT_BACK = "url not put back"
# The module Odoo's server-wide loader has already imported, and the function in
# it that replaces a request's url. Read out of ``sys.modules`` and never
# imported: importing it would apply the patch and make the flag above pass by
# itself. Driving the module's own function is what keeps this from proving a
# copy of the mechanism instead of the mechanism -- a copy is what the flag was.
PATCH_MODULE = "odoo.addons.woow_visitor_url"
SWAP_FUNCTION = "swap_url"
RESTORE_FUNCTION = "restore_url"


def registry_visitor(website_visitor):
    """The class whose ``_handle_webpage_dispatch`` the registry's
    ``website.visitor`` runs, among those declared in Odoo's
    ``website_visitor`` module.

    The last class in module order that declares the method in its own
    namespace: Odoo's model class puts later declarations ahead of earlier
    ones in its MRO. A class that only inherits the method changes nothing
    and is skipped. None when nothing in the module declares it, which is
    the seam having moved out of the module.
    """
    resolved = None
    for candidate in vars(website_visitor).values():
        if not isinstance(candidate, type) or getattr(candidate, "_name", None) != MODEL:
            continue
        if METHOD in vars(candidate):
            resolved = candidate
    return resolved


def patched(website_visitor) -> bool:
    """True when the registry's dispatch is the patched one."""
    visitor = registry_visitor(website_visitor)
    return visitor is not None and getattr(vars(visitor)[METHOD], PATCHED_FLAG, False)


def forwarded_names(wrapper):
    """The positional parameters the wrapper declares, after ``self``.

    Read from the code object: ``functools.wraps`` copies the original's
    ``__dict__`` onto the wrapper, and a ``__signature__`` in there would
    make ``inspect.signature`` describe the original instead of the wrapper.
    """
    code = wrapper.__code__
    return list(code.co_varnames[1:code.co_argcount])


def upstream_fit(forwarded, original):
    """A sentence naming how the original does not take what the wrapper
    forwards by position, or None when every call the wrapper makes is one
    the original accepts.

    Each forwarded name has to be the original's next positional parameter
    (same name, same order, accepted by position). Parameters the original
    takes beyond those have to be optional, or it would want more than the
    wrapper sends.
    """
    positional = (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    upstream = list(inspect.signature(original).parameters.values())[1:]

    def describe(p):
        if p.kind is p.VAR_POSITIONAL:
            return f"*{p.name}"
        if p.kind is p.VAR_KEYWORD:
            return f"**{p.name}"
        name = p.name if p.default is p.empty else f"{p.name}={p.default!r}"
        return f"{name} (keyword-only)" if p.kind is p.KEYWORD_ONLY else name

    taken = [describe(p) for p in upstream]
    described = (
        f"wrapper forwards {forwarded} by position, upstream {METHOD} takes {taken}"
    )
    for index, name in enumerate(forwarded):
        if index >= len(upstream):
            return described
        parameter = upstream[index]
        if parameter.name != name or parameter.kind not in positional:
            return described
    for parameter in upstream[len(forwarded):]:
        if parameter.kind in positional and parameter.default is parameter.empty:
            return described
        if parameter.kind is parameter.KEYWORD_ONLY and parameter.default is parameter.empty:
            return described
    return None


def signature_mismatch(website_visitor):
    """A sentence naming the mismatch between the wrapper and upstream, or None."""
    wrapper = vars(registry_visitor(website_visitor))[METHOD]
    original = getattr(wrapper, "__wrapped__", None)
    if original is None:
        return f"the patched {METHOD} keeps no __wrapped__ original to compare against"
    return upstream_fit(forwarded_names(wrapper), original)


def probe_request(http):
    """``(request, None)``, or ``(None, sentence)`` saying why it cannot be built.

    The two steps Odoo's WSGI application takes: the werkzeug request is
    wrapped in an ``odoo.http.HTTPRequest``, and that wrapper is handed to
    ``odoo.http.Request``, which is the object every module reads as
    ``odoo.http.request``. Building both is what lets the swap below run on
    the expression the patch evaluates -- ``request.httprequest`` -- rather
    than on a class this file names. Nothing here needs a database, a session
    or the network, and every step is reported rather than raised, because a
    probe that dies prints no ``visitor-url:`` line and the build then blames
    the container instead of what it found.
    """
    for attribute in ("HTTPRequest", "Request"):
        if not hasattr(http, attribute):
            return None, f"odoo.http has no {attribute}; the request it builds cannot be read here"
    # Each step is named for itself: a nightly whose HTTPRequest wants more
    # than an environ is not its Request wanting more than an HTTPRequest, and
    # the build step promises to name what it could not read.
    try:
        httprequest = http.HTTPRequest(dict(PROBE_ENVIRON))
    except Exception as exc:
        return None, f"odoo.http.HTTPRequest could not be built over a bare environ: {exc!r}"
    try:
        return http.Request(httprequest), None
    except Exception as exc:
        return None, f"odoo.http.Request could not be built over an HTTPRequest: {exc!r}"


def loaded(function):
    """``(function, None)`` for one of the module's own functions, or
    ``(None, sentence)`` when it is not there to drive.

    Odoo imported the module before this probe ran, or ``patched()`` above
    would already have reported the dispatch unpatched; so the module is in
    ``sys.modules`` and is read from there rather than imported.
    """
    module = sys.modules.get(PATCH_MODULE)
    if module is None:
        return None, f"{PATCH_MODULE} is not in sys.modules, so its {function} cannot be driven"
    attribute = getattr(module, function, None)
    if not callable(attribute):
        return None, f"{PATCH_MODULE} has no callable {function} to drive"
    return attribute, None


def url_swap(http):
    """``(None, None)`` when the url replacement the patch performs takes here,
    and ``(verdict, sentence)`` when it does not.

    The verdict tells apart the three ways this can fail, because they mean
    different things to whoever reads the build:

    * ``"url swap unprovable"`` -- the replacement could not be performed. This
      Odoo's ``odoo.http`` no longer has what the probe reads, its request
      cannot be built over a bare environ, its url cannot be read, or the
      module's own function is not where this reads it. A nightly changed a
      shape; nothing is known about the patch.
    * ``"url not replaceable"`` -- it was performed and the url did not change,
      so a page view would record the address the request arrived on. This is
      the 0.4.6 defect, and the half issue #160 was reopened over.
    * ``"url not put back"`` -- the replacement took and the address the
      request arrived on did not come back, so the page view is right and every
      handler after it on that request reads the Canonical URL instead. The
      module writes that address back rather than dropping a cache entry,
      because a forwarded attribute has no deleter, which makes this the other
      half that depends on the request's shape.

    ``http`` is Odoo's ``odoo.http``. What the dispatch reads is
    ``request.httprequest``, an ``odoo.http.HTTPRequest``: a wrapper that
    installs one plain ``property`` per forwarded attribute, ``url`` included,
    whose getter and setter reach the werkzeug request it wraps
    (``make_request_wrap_methods``). The module replaces that attribute, so
    this builds the request over a bare environ, hands it to the module's own
    replacement and then to its restore, and reads the url back itself after
    each -- a function that reported success without changing anything would
    not get past the reading.

    What it does not read is Odoo's WSGI application putting that wrapper on
    the request in the first place. If a nightly interposes something else
    there, this stays green and the module's own read-back guard catches it at
    runtime -- a warning per page view, which is what the host logged on 0.4.6.
    """
    swap, undrivable = loaded(SWAP_FUNCTION)
    if undrivable is not None:
        return UNPROVABLE, undrivable
    restore, unrestorable = loaded(RESTORE_FUNCTION)
    if unrestorable is not None:
        return UNPROVABLE, unrestorable
    request, unbuildable = probe_request(http)
    if unbuildable is not None:
        return UNPROVABLE, unbuildable
    try:
        httprequest = getattr(request, HTTPREQUEST_ATTRIBUTE)
    except Exception as exc:
        return UNPROVABLE, (
            f"{type(request).__module__}.{type(request).__qualname__}."
            f"{HTTPREQUEST_ATTRIBUTE} could not be read: {exc!r}"
        )
    name = (
        f"request.{HTTPREQUEST_ATTRIBUTE} "
        f"({type(httprequest).__module__}.{type(httprequest).__qualname__})"
    )
    try:
        arrived = getattr(httprequest, URL_ATTRIBUTE)
    except Exception as exc:
        return UNPROVABLE, f"{name}.{URL_ATTRIBUTE} could not be read: {exc!r}"
    try:
        refused, _ = swap(httprequest, REPLACEMENT)
    except Exception as exc:
        return UNPROVABLE, f"{PATCH_MODULE}.{SWAP_FUNCTION} raised on {name}: {exc!r}"
    try:
        replaced = getattr(httprequest, URL_ATTRIBUTE)
    except Exception as exc:
        return UNPROVABLE, f"{name}.{URL_ATTRIBUTE} could not be read back: {exc!r}"
    # Both readings count. The module says whether the replacement took, which
    # is what decides whether a page view records the arrived address; and the
    # url is read here as well, because a module reporting success and changing
    # nothing is the 0.4.6 defect.
    if refused is not None or replaced != REPLACEMENT:
        return NOT_REPLACEABLE, (
            f"{PATCH_MODULE}.{SWAP_FUNCTION} was asked for {REPLACEMENT!r} on {name} and "
            f"reported {refused!r}; it arrived as {arrived!r} and reads back {replaced!r}. "
            "A page view would record the address the request arrived on"
        )
    # The way back is the other half that depends on the request's shape: the
    # module writes the arrived address again, because a forwarded attribute
    # has no deleter. `was_cached` is False, which is what the dispatch reads
    # for Odoo's wrapper -- it keeps no url in its own __dict__.
    try:
        restore(httprequest, arrived, False)
    except Exception as exc:
        return UNPROVABLE, f"{PATCH_MODULE}.{RESTORE_FUNCTION} raised on {name}: {exc!r}"
    try:
        put_back = getattr(httprequest, URL_ATTRIBUTE)
    except Exception as exc:
        return UNPROVABLE, f"{name}.{URL_ATTRIBUTE} could not be read after the restore: {exc!r}"
    if put_back != arrived:
        return NOT_PUT_BACK, (
            f"{PATCH_MODULE}.{RESTORE_FUNCTION} left {name}.{URL_ATTRIBUTE} reading "
            f"{put_back!r} instead of the {arrived!r} it arrived as. The page view would be "
            "right and the rest of the response would read the Canonical URL"
        )
    return None, None


def main(website_visitor, http, out=sys.stdout) -> int:
    if not patched(website_visitor):
        print("visitor-url: not applied", file=out)
        return 1
    mismatch = signature_mismatch(website_visitor)
    if mismatch is not None:
        print(f"visitor-url: signature mismatch ({mismatch})", file=out)
        return 1
    verdict, sentence = url_swap(http)
    if verdict is not None:
        print(f"visitor-url: {verdict} ({sentence})", file=out)
        return 1
    print("visitor-url: applied", file=out)
    return 0


if __name__ == "__main__":
    import odoo.http
    from odoo.addons.website.models import website_visitor

    sys.exit(main(website_visitor, odoo.http))
