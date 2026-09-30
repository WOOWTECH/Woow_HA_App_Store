"""Is ``website.visitor._handle_webpage_dispatch`` patched in this Odoo? Issue #160.

The build tier pipes this file into ``odoo shell`` in the image it just
built, with no database: by then Odoo's own loader has imported the
server-wide modules the add-on configures. When ``woow_visitor_url`` cannot
find its seam, or cannot import ``website`` at all, that loader only logs it
and carries on, so asking Odoo whether the patch is on is the one check that
goes red. The probe never imports the module itself -- that would apply the
patch and pass by itself.

What the flag alone would not prove, the same two things ADR 0010's
amendment named for the Canonical URL guard (issue #121):

* the class the module patched is the last one in ``website_visitor``
  declaring ``_handle_webpage_dispatch``. Odoo builds a model from every
  class declaring its ``_name``, later declarations overriding earlier ones,
  so within that module the last declaration is the one the registry runs.
  Overrides in other modules are not read here: the tracked URL is built in
  ``website_visitor``, and an override elsewhere reaches it through
  ``super()``;
* the wrapper still fits upstream. ``functools.wraps`` keeps the original
  under ``__wrapped__``; if a nightly changed its parameters the patch still
  installs and every tracked page view raises ``TypeError``.

Prints one of ``visitor-url: applied``, ``visitor-url: not applied`` or
``visitor-url: signature mismatch (...)``. Exit status 0 only for the first.
"""
import inspect
import sys

# Set by woow_visitor_url on the dispatch it installs.
PATCHED_FLAG = "_woow_visitor_url_patched"
MODEL = "website.visitor"
METHOD = "_handle_webpage_dispatch"


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


def main(website_visitor, out=sys.stdout) -> int:
    if not patched(website_visitor):
        print("visitor-url: not applied", file=out)
        return 1
    mismatch = signature_mismatch(website_visitor)
    if mismatch is not None:
        print(f"visitor-url: signature mismatch ({mismatch})", file=out)
        return 1
    print("visitor-url: applied", file=out)
    return 0


if __name__ == "__main__":
    from odoo.addons.website.models import website_visitor

    sys.exit(main(website_visitor))
