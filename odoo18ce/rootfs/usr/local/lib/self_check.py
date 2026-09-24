#!/usr/bin/env python3
"""The start-time self-check: is the database manager closed to the tunnel?
(issue #79, ADR 0005).

The Perimeter check used to look at the Public origin from outside, every
night, from a control group. ADR 0005 retires that schedule and puts this in
its place: when the add-on starts it requests its own database-manager route
the way the Cloudflare tunnel does -- from the container's add-on-network
address, on its own published port, with the public host as `Host` when
`public_url` is set -- and refuses to start on any answer but the one the
restricted tier gives.

That answer depends on the shape of the install (`10-odoo-config.sh`, the
`geo` and `map` blocks of the nginx template):

- **With `public_url`** the tunnel's Host matches, the gate says `public`,
  and `location ^~ /web/database/` returns `404`.
- **Without it** no off-LAN caller is recognised, and every request is
  answered with the deny status, `503`.

Everything else fails: a `200` is the database manager reached from the
tunnel's path, a 5xx is a gateway that is not serving, and no answer at all
is what nginx's `444` looks like from the caller (a wrong `Host` with
`public_url` set) as much as a listener that is not there.

The request must not go over loopback. `127.0.0.0/8` is LAN tier in the
template, so a loopback request would reach the database manager on every
correct install and prove nothing. The add-on-network address is carved out
of the LAN tier by the same `geo` block the tunnel meets, so sourcing the
request from it exercises the real rule instead of a test path (ADR 0005,
"Considered options"). The container learns that address from the
Supervisor; the s6 service passes it in.

`self_check_verdict` is the table and is pure; `probe` is the one call that
reaches the network; `main` joins them, and on fail sends the notification
through the same adapter the Rewrite scan uses (issue #78). Stopping the
container is the s6 service's job, not this module's.
"""
from __future__ import annotations

import argparse
import http.client
import ipaddress
from pathlib import Path
import sys
from typing import Callable

# `notify` ships beside this module in `rewrite_apply`. Imported by name
# rather than by path so the Static tier, which loads these modules out of the
# repository, gets one copy of each; and only when a check has failed, so the
# check itself never depends on the Rewrite scan importing cleanly (ADR 0009:
# the scan must never be what stops the add-on).
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

#: The database manager's route. Any path under `/web/database/` meets the
#: same location; this is the one an operator would open.
ROUTE = "/web/database/manager"
#: The origin listener, the port the tunnel reaches and the host publishes.
ORIGIN_PORT = 8069
#: The public shape: `location ^~ /web/database/` for a non-LAN caller.
PUBLIC_STATUS = 404
#: `DENY_STATUS` in `10-odoo-config.sh` when `public_url` is not set.
DENY_STATUS = 503
#: One request, one answer. A listener that takes longer than this is not
#: one the tunnel would be served by either.
PROBE_TIMEOUT_SECONDS = 10

NOTIFICATION_ID = "odoo18ce_self_check_failed"


def self_check_verdict(status: int | None, public_url_set: bool) -> bool:
    """True when the route answered the way the restricted tier must.

    `status` is the HTTP status, or None when there was no answer.
    """
    if status is None:
        return False
    return status == (PUBLIC_STATUS if public_url_set else DENY_STATUS)


def public_host(public_url: str) -> str:
    """The Host the tunnel presents, cut from `public_url` the way
    `10-odoo-config.sh` cuts it for the nginx `map`: after the scheme, up to
    the first slash. Empty when `public_url` is.
    """
    if not public_url:
        return ""
    return public_url.split("://", 1)[-1].split("/", 1)[0]


def usable_address(address: str) -> bool:
    """An address the check may source its request from.

    Empty is what a bashio read gives when the Supervisor has no answer;
    `0.0.0.0` is the Supervisor's own placeholder before it has seen the
    container on the network, and a socket bound to it is loopback in
    practice; 127.0.0.0/8 and ::1 are loopback outright. All of them are
    LAN tier to nginx, where the database manager answers on every correct
    install. A string that is not an address at all is passed on: `probe`
    reports it as no answer.
    """
    if not address:
        return False
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return True
    return not (parsed.is_unspecified or parsed.is_loopback)


def probe(address: str, host: str, *, port: int = ORIGIN_PORT,
          timeout: float = PROBE_TIMEOUT_SECONDS) -> int | None:
    """GET the route on `address:port`, sourced from `address`.

    Returns the status, or None when nothing answered: a refused or reset
    connection, a timeout, or a connection nginx closed without a response.
    """
    connection = http.client.HTTPConnection(
        address, port, timeout=timeout, source_address=(address, 0),
    )
    try:
        connection.request("GET", ROUTE, headers={"Host": host or address})
        return connection.getresponse().status
    except (OSError, http.client.HTTPException, ValueError):
        # ValueError covers a Host or address http.client cannot encode.
        # That is a failed check to report, never a traceback that skips
        # the notification.
        return None
    finally:
        connection.close()


def describe(status: int | None) -> str:
    return "no answer" if status is None else str(status)


def expected(public_url_set: bool) -> str:
    if public_url_set:
        return f"{PUBLIC_STATUS} (public_url is set)"
    return f"{DENY_STATUS} (no public_url)"


def failure_notification(status: int | None, public_url_set: bool, detail: str) -> tuple[str, str]:
    """The title and body the operator sees next to the stopped add-on."""
    title = "Woow Odoo: start-time self-check failed"
    body = (
        f"The add-on requested its own database-manager route `{ROUTE}` the "
        "way the Cloudflare tunnel reaches it and got "
        f"{describe(status)}, where {expected(public_url_set)} was expected. "
        "The add-on has stopped so the database manager is not exposed.\n\n"
        f"{detail}\n\n"
        "Check `public_url` and `lan_networks`, then start the add-on again."
    )
    return title, body


def main(argv=None, prober: Callable = probe, notifier: Callable | None = None,
         out: Callable[[str], None] = print,
         log: Callable[[str], None] = lambda text: print(text, file=sys.stderr)) -> int:
    """Run the self-check once. Prints one line; exits 0 on pass, 1 on fail.

    The line goes to `out` and the s6 service logs it at info or error
    level; anything the notifier has to say goes to `log`.
    """
    parser = argparse.ArgumentParser(
        prog="odoo-self-check",
        description="Request the database-manager route the way the "
                    "Cloudflare tunnel does and say whether it is closed.",
    )
    parser.add_argument("--address", default="",
                        help="the container's add-on-network address, from the Supervisor")
    parser.add_argument("--public-url", default="",
                        help="the public_url option, empty when unset")
    parser.add_argument("--port", type=int, default=ORIGIN_PORT)
    arguments = parser.parse_args(argv)

    public_url_set = bool(arguments.public_url)
    host = public_host(arguments.public_url)
    if usable_address(arguments.address):
        status = prober(arguments.address, host, port=arguments.port)
        where = f"http://{arguments.address}:{arguments.port}{ROUTE}"
        if host:
            where += f" with Host {host}"
    else:
        # Loopback is LAN tier and would pass on every correct install, so
        # there is no address to fall back to — and `0.0.0.0`, the
        # Supervisor's placeholder for a container it has not seen on the
        # network, connects to loopback too.
        status = None
        where = (f"{ROUTE}, not requested: the Supervisor reported no "
                 f"add-on-network address ({arguments.address or 'empty'}), "
                 "and loopback is LAN tier")

    if self_check_verdict(status, public_url_set):
        out(f"Self-check: {where} answered {status}, the restricted tier; "
            "the database manager is closed to the tunnel")
        return 0

    detail = f"Requested {where}: {describe(status)}, expected {expected(public_url_set)}."
    out(f"Self-check failed: {detail} The add-on stops.")
    try:
        if notifier is None:
            import rewrite_apply  # noqa: PLC0415 - see the note at the top
            notifier = rewrite_apply.notify
        notifier(failure_notification(status, public_url_set, detail),
                 notification_id=NOTIFICATION_ID, log=log, source="Self-check")
    except Exception as error:      # noqa: BLE001 - the stop must not depend on it
        log(f"Self-check: the notification could not be sent: {error}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
