"""Is ``res.users.authenticate`` guarded in this Odoo process? Issues #88, #121.

The build tier pipes this file into ``odoo shell`` in the image it just
built, with no database: by then Odoo's own loader has imported the
server-wide modules the add-on configures. When ``woow_base_url_guard``
cannot find its seam it raises ``ImportError``, and that loader only logs
it and carries on, so asking Odoo whether the patch is on is the one check
that goes red. The probe never imports the guard itself -- that would apply
the patch and pass by itself.

Two things the flag alone does not prove (issue #121):

* the class the guard patched is the last one in ``res_users`` declaring
  ``authenticate``. Odoo builds a model from every class declaring its
  ``_name``, later declarations overriding earlier ones, so within that
  module the last declaration is the one the registry runs. A later class
  the guard never saw carries the guess back, flag or no flag. Overrides in
  other modules are not read here: the guess lives in ``res_users``, and an
  override elsewhere reaches it through ``super()``;
* the wrapper still fits upstream. ``functools.wraps`` keeps the original
  under ``__wrapped__``; if a nightly changed its parameters the guard still
  installs and every login raises ``TypeError``.

Prints one of ``base-url-guard: applied``, ``base-url-guard: not applied``
or ``base-url-guard: signature mismatch (...)``. Exit status 0 only for the
first.
"""
import inspect
import sys

# Set by woow_base_url_guard on the authenticate it installs.
GUARDED_FLAG = "_woow_base_url_guarded"
MODEL = "res.users"
METHOD = "authenticate"


def registry_users(res_users):
    """The class whose ``authenticate`` the registry's ``res.users`` runs,
    among those declared in Odoo's ``res_users`` module.

    The last class in module order that declares the method in its own
    namespace: Odoo's model class puts later declarations ahead of earlier
    ones in its MRO. A class that only inherits the method changes nothing
    and is skipped. None when nothing in the module declares it, which is
    the seam having moved out of the module.
    """
    resolved = None
    for candidate in vars(res_users).values():
        if not isinstance(candidate, type) or getattr(candidate, "_name", None) != MODEL:
            continue
        if METHOD in vars(candidate):
            resolved = candidate
    return resolved


def guarded(res_users) -> bool:
    """True when the registry's ``authenticate`` is the guarded one."""
    users = registry_users(res_users)
    return users is not None and getattr(users.authenticate, GUARDED_FLAG, False)


def forwarded_names(wrapper):
    """The positional parameters the wrapper declares, after the class one.

    Read from the code object: ``functools.wraps`` copies the original's
    ``__dict__`` onto the wrapper, and a ``__signature__`` in there would make
    ``inspect.signature`` describe the original instead of the wrapper.
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
    described = f"wrapper forwards {forwarded} by position, upstream authenticate takes {taken}"
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


def signature_mismatch(res_users):
    """A sentence naming the mismatch between the wrapper and upstream, or None."""
    users = registry_users(res_users)
    wrapper = vars(users)[METHOD].__func__
    original = getattr(wrapper, "__wrapped__", None)
    if original is None:
        return "the guarded authenticate keeps no __wrapped__ original to compare against"
    return upstream_fit(forwarded_names(wrapper), original)


def main(res_users, out=sys.stdout) -> int:
    if not guarded(res_users):
        print("base-url-guard: not applied", file=out)
        return 1
    mismatch = signature_mismatch(res_users)
    if mismatch is not None:
        print(f"base-url-guard: signature mismatch ({mismatch})", file=out)
        return 1
    print("base-url-guard: applied", file=out)
    return 0


if __name__ == "__main__":
    from odoo.addons.base.models import res_users

    sys.exit(main(res_users))
