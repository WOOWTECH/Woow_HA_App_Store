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
# werkzeug's Request.url is a cached_property, so a value written into the
# instance dict is the one every later read returns.
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
    # rewrites has to come out of it exactly as it went in.
    cached = vars(httprequest)
    was_cached = URL_ATTRIBUTE in cached
    arrived = httprequest.url
    stored = tracked_url(arrived, website_base())
    if stored == arrived:
        return original(self, website_page)

    cached[URL_ATTRIBUTE] = stored
    try:
        if httprequest.url != stored:
            # A werkzeug whose Request.url no longer reads the instance dict
            # would make this a silent no-op, storing the old address while
            # the patch still looks applied.
            _logger.warning(
                "the request's url could not be replaced, so this page view records %s; "
                "werkzeug's Request.url is no longer a cached_property", arrived
            )
        return original(self, website_page)
    finally:
        if was_cached:
            cached[URL_ATTRIBUTE] = arrived
        else:
            cached.pop(URL_ATTRIBUTE, None)


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
