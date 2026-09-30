"""The decision behind the tracked visitor URL, with nothing from Odoo in it.

Odoo's visitor tracking stores the address the request arrived on:
``website.visitor._handle_webpage_dispatch`` puts ``request.httprequest.url``
into the ``website.track`` row it creates. Under Ingress that address is the
Home Assistant host -- the add-on runs Odoo with ``proxy_mode``, and the
Ingress listener forwards the Home Assistant host as ``X-Forwarded-Host``.
The Supervisor has already removed the Ingress prefix, so the path is right
and only the scheme and host are wrong. The Website -> Visitors screen then
lists addresses that cannot open the page (``U-C5``, root cause ``RC-9``).

The stored URL is therefore rebuilt on the website's Canonical URL, which is
what ``website.get_base_url()`` returns: the website's ``domain`` when set,
else the frozen ``web.base.url``. The base may carry a path -- a website
published under a sub-path -- so it is kept in front of the request's own
path, and a trailing slash on it never becomes a double slash.

No Ingress prefix reaches here: the listener sets no ``X-Forwarded-Prefix``,
so the path werkzeug reports never carries the Ingress token.

This file imports nothing from Odoo, so tests/test_visitor_url.py drives the
whole decision without a live Odoo.
"""
from urllib.parse import urlsplit


def path_and_query(request_url):
    """The request's path and query string, with no scheme and no host.

    A request with no path at all is the website root, so it reads as ``/``;
    a fragment is never sent to a server and is not carried over.
    """
    parts = urlsplit(request_url)
    path = parts.path or "/"
    return f"{path}?{parts.query}" if parts.query else path


def tracked_url(request_url, website_base):
    """The URL visitor tracking should store for this request.

    ``website_base`` is the website's Canonical URL. Empty means the add-on
    has written none yet: the path and query are then stored on their own,
    with no host, which is wrong for nobody. A request that already arrived
    on the base comes back unchanged, and an empty request URL is handed
    back as it is.
    """
    if not request_url:
        return request_url
    return (website_base or "").rstrip("/") + path_and_query(request_url)
