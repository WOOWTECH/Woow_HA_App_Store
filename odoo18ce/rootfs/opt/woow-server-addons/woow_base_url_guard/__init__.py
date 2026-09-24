"""Server-wide module: Odoo never writes the Canonical URL by itself.

The generated ``/data/odoo.conf`` names this module in
``server_wide_modules``, so Odoo imports it in every process -- the HTTP
workers, cron and ``odoo shell`` -- and installs it in no database. An ORM
``_inherit`` would therefore never take effect; the guess is removed by
patching the ``res.users`` class as this module is imported, before any
registry is built.

The maintenance bootstrap stays the only writer of ``web.base.url``. An
operator writing it explicitly (Settings, RPC ``set_param``) is not
affected: only the automatic guess inside ``authenticate`` goes away.

See ``guard.py`` for the decision, which is pure and covered by the Static
tier.
"""
import functools
import logging

from odoo.addons.base.models import res_users

from .guard import guarded_authenticate

_logger = logging.getLogger(__name__)

GUARDED_FLAG = "_woow_base_url_guarded"


def users_class():
    """The class defining ``authenticate`` in Odoo's ``res.users`` module.

    The class name is not a stable API across Odoo versions while the model
    name and the classmethod are, so the class is found by what it declares
    rather than by what it is called.
    """
    for candidate in vars(res_users).values():
        if not isinstance(candidate, type):
            continue
        if getattr(candidate, "_name", None) == "res.users" and "authenticate" in vars(candidate):
            return candidate
    raise ImportError("no res.users class declaring authenticate; the base-URL guess is unguarded")


def patch_authenticate(users) -> bool:
    """Wrap ``users.authenticate``. False when it is already wrapped."""
    original = vars(users)["authenticate"].__func__
    if getattr(original, GUARDED_FLAG, False):
        return False

    @functools.wraps(original)
    def authenticate(cls, db, credential, user_agent_env):
        # functools.partial supplies the cls the original expects, so it
        # still reaches the registry class through cls.pool and cls._login.
        return guarded_authenticate(
            functools.partial(original, cls), db, credential, user_agent_env
        )

    setattr(authenticate, GUARDED_FLAG, True)
    users.authenticate = classmethod(authenticate)
    return True


if patch_authenticate(users_class()):
    _logger.info("res.users.authenticate guarded: Odoo will not guess web.base.url")
