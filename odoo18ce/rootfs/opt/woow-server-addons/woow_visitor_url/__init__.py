"""Server-wide module: a page view records the Canonical URL.

The generated ``/data/odoo.conf`` names this module in
``server_wide_modules``, so Odoo imports it in every process -- the HTTP
workers, cron and ``odoo shell`` -- and installs it in no database. An ORM
``_inherit`` would therefore never take effect; the tracked URL is replaced
by patching the ``website.visitor`` class as this module is imported, before
any registry is built. ``woow_base_url_guard`` is the precedent and this
module keeps its shape; the two have different jobs, so they stay apart.

Importing ``website`` here is what makes the patch visible to the Build
tier's probe, and it is the cost of it: every Odoo process now has
``website``'s Python imported, whether or not any database has the module
installed. Importing is not installing -- the patched class is only reached
through a registry that has ``website`` in it -- and a build that cannot
import it at all logs one line and serves untouched rather than failing to
start.

See ``tracked_url.py`` for the decision, which is pure and covered by the
Static tier.
"""
import functools
import logging

from odoo.http import request

from .tracked_url import tracked_url

_logger = logging.getLogger(__name__)

PATCHED_FLAG = "_woow_visitor_url_patched"
MODEL = "website.visitor"
METHOD = "_handle_webpage_dispatch"
# What Odoo hands the dispatch is an ``odoo.http.HTTPRequest``, not the
# werkzeug request it wraps: for every name in ``HTTPREQUEST_ATTRIBUTES`` --
# ``url`` among them -- Odoo installs on the wrapper a plain ``property`` whose
# getter and setter reach the wrapped request (``make_request_wrap_methods``).
# A plain ``property`` is a data descriptor that never reads the instance
# ``__dict__``, so the url is replaced by assigning to it: the wrapper forwards
# the assignment, and werkzeug's ``cached_property`` -- which the wrapped
# request's ``url`` is -- fills its cache from it. Both shapes answer to an
# assignment; only the werkzeug one answers to a ``__dict__`` write, which is
# why this module's first version was applied on the host and did nothing.
URL_ATTRIBUTE = "url"


def visitor_class(website_visitor):
    """The class whose ``_handle_webpage_dispatch`` the registry runs.

    The last class in Odoo's ``website_visitor`` module that declares the
    method: Odoo builds a model from every class declaring its ``_name``,
    later declarations overriding earlier ones, so wrapping an earlier one
    would leave the registry running the unwrapped method. The class name is
    not a stable API across Odoo versions while the model name and the
    method are, so the class is found by what it declares.
    """
    resolved = None
    for candidate in vars(website_visitor).values():
        if not isinstance(candidate, type) or getattr(candidate, "_name", None) != MODEL:
            continue
        if METHOD in vars(candidate):
            resolved = candidate
    if resolved is None:
        raise ImportError(
            f"no {MODEL} class declaring {METHOD}; visitor tracking is unpatched"
        )
    return resolved


def website_base():
    """The Canonical URL of the website this request is on, or ``""``.

    ``website.get_base_url()`` is the website's ``domain`` when it is set and
    the frozen ``web.base.url`` otherwise. Nothing in Odoo dispatches a
    tracked page outside website's own routing, where the website is set; a
    caller that does gets a URL without a host rather than a traceback.
    """
    website = getattr(request, "website", None)
    return website.get_base_url() if website else ""


def swap_url(httprequest, value):
    """Make ``httprequest.url`` read as ``value``.

    Returns ``(None, True)`` when it took, and ``(reason, landed)`` when it did
    not: ``reason`` is a phrase naming what happened and ``landed`` says
    whether the assignment itself was accepted, which is what decides whether
    there is anything on the request to put back. An assignment that raised
    left nothing; one that was accepted and reads back as something else left
    that something else.

    Assignment is what reaches both shapes of request -- Odoo's wrapper and the
    werkzeug request it wraps -- and the value is read back afterwards, because
    a request that accepts the assignment and still reports the old address
    would leave this patch looking applied while storing the address the
    request arrived on. That is what issue #160 was reopened over.

    Nothing a request's own ``url`` does is allowed to reach the browser as a
    500: a page view is not worth a failed response, so every way this can go
    wrong comes back as a reason for the caller to log.
    """
    try:
        setattr(httprequest, URL_ATTRIBUTE, value)
    except Exception as exc:
        return f"assigning it raised {exc!r}", False
    try:
        read_back = getattr(httprequest, URL_ATTRIBUTE)
    except Exception as exc:
        return f"reading it back raised {exc!r}", True
    if read_back != value:
        return f"it reads back as {read_back!r}", True
    return None, True


def reads_url(httprequest, otherwise):
    """What the request's ``url`` reads as, or ``otherwise`` when asking raises.

    Used to say what this page view is about to record, which is the request's
    own answer and not what it was asked to hold.
    """
    try:
        return getattr(httprequest, URL_ATTRIBUTE)
    except Exception:
        return otherwise


def restore_url(httprequest, arrived, was_cached) -> None:
    """Put the address the browser really used back on the request.

    The rest of the response, and the next handler on this request, must see
    that one. A werkzeug request that had not computed its url before the
    dispatch is left with nothing cached, which is how it arrived; Odoo's
    wrapper has no deleter for a forwarded attribute, so there the arrived
    value is written back instead -- the same address, now cached.

    Called only when a value really did land on the request, so a request that
    will not take its own address back is left reading something else for the
    whole of the rest of the response, which is wrong for every handler after
    this one, and is reported. This runs in a ``finally``, where an exception
    of its own would replace whatever the dispatch was already raising, so
    nothing escapes it.
    """
    if not was_cached:
        try:
            delattr(httprequest, URL_ATTRIBUTE)
            return
        except Exception:
            pass
    refused, _ = swap_url(httprequest, arrived)
    if refused is None:
        return
    _logger.warning(
        "the request's url was replaced for this page view and could not be put back, so the "
        "rest of this response reads it as something other than %s: %s, on %s.%s",
        arrived, refused,
        type(httprequest).__module__, type(httprequest).__qualname__,
    )


def dispatch_on_the_canonical_url(original, self, website_page):
    """Run Odoo's dispatch with the request's ``url`` reading as what to store.

    Upstream builds the ``website.track`` values itself and reads the URL out
    of the request while doing it, so the thinnest patch is to hand it a
    request whose ``url`` is already the Canonical one and to put the address
    the browser really used back afterwards -- the rest of the response, and
    the next handler on this request, must still see that one.
    """
    httprequest = getattr(request, "httprequest", None)
    if httprequest is None:
        return original(self, website_page)

    # Whether the url was cached is read before anything looks at it:
    # werkzeug caches Request.url on first read, and a request this patch
    # rewrites has to come out of it exactly as it went in. Odoo's wrapper
    # holds no url in its own ``__dict__``, so this reads False there, which
    # is what sends the restore down the write-it-back path.
    was_cached = URL_ATTRIBUTE in getattr(httprequest, "__dict__", {})
    arrived = httprequest.url
    stored = tracked_url(arrived, website_base())
    if stored == arrived:
        return original(self, website_page)

    refused, landed = swap_url(httprequest, stored)
    if refused is not None:
        # A request whose url refuses the assignment, or goes on reading as
        # something other than what it was given, would make the swap a silent
        # no-op: the page view is then recorded on whatever the request does
        # read, and said so, rather than looking corrected. A value that landed
        # is put back first -- and reported if it will not go -- while an
        # assignment that raised left nothing to put back and nothing to say
        # about putting it back.
        if landed:
            restore_url(httprequest, arrived, was_cached)
        _logger.warning(
            "the request's url could not be replaced, so this page view records %s: "
            "%s, on %s.%s",
            reads_url(httprequest, arrived), refused,
            type(httprequest).__module__, type(httprequest).__qualname__,
        )
        return original(self, website_page)

    try:
        return original(self, website_page)
    finally:
        restore_url(httprequest, arrived, was_cached)


def patch_dispatch(visitor) -> bool:
    """Wrap ``visitor._handle_webpage_dispatch``. False when already wrapped."""
    original = vars(visitor)[METHOD]
    if getattr(original, PATCHED_FLAG, False):
        return False

    @functools.wraps(original)
    def _handle_webpage_dispatch(self, website_page):
        return dispatch_on_the_canonical_url(original, self, website_page)

    setattr(_handle_webpage_dispatch, PATCHED_FLAG, True)
    setattr(visitor, METHOD, _handle_webpage_dispatch)
    return True


try:
    from odoo.addons.website.models import website_visitor
except ImportError:
    # No website on this addons path: there is no visitor tracking to correct
    # and no reason to stop the process.
    _logger.info("website is not importable here; visitor tracking is left as it is")
else:
    if patch_dispatch(visitor_class(website_visitor)):
        _logger.info(
            "%s.%s patched: a page view records the Canonical URL", MODEL, METHOD
        )
