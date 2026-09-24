"""The decision behind the base-URL guard, with nothing from Odoo in it.

Odoo derives ``web.base.url`` from the request an administrator logged in
from: ``res.users.authenticate`` writes ``user_agent_env['base_location']``
into the parameter whenever ``web.base.url.freeze`` is unset. In this add-on
that value is never the Canonical URL -- through Ingress it is the Home
Assistant host -- and a database created between two starts has no freeze
yet, so the first admin login fills it in wrongly.

Dropping ``base_location`` before Odoo sees it removes the guess and leaves
everything else about the login untouched: the guess is the only thing Odoo
reads that key for, while ``interactive`` and the rest of the environment
still reach ``_login``.

This file imports nothing, so tests/test_base_url_guard.py drives the whole
path without a live Odoo.
"""
BASE_LOCATION_KEY = "base_location"


def without_base_location(user_agent_env):
    """Return ``user_agent_env`` without the key Odoo would guess from.

    The caller's dictionary is never mutated, and an environment that
    carries no ``base_location`` is passed through as it is.
    """
    if not user_agent_env or BASE_LOCATION_KEY not in user_agent_env:
        return user_agent_env
    guarded = dict(user_agent_env)
    del guarded[BASE_LOCATION_KEY]
    return guarded


def guarded_authenticate(original, db, credential, user_agent_env):
    """Call Odoo's ``authenticate`` with the guess input removed.

    ``original`` is Odoo's own classmethod, already bound to its class, so
    whatever it returns is handed back untouched.
    """
    return original(db, credential, without_base_location(user_agent_env))
