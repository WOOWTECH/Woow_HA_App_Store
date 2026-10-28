"""Pure panel decisions, shared by discovery, the WebSocket API and the
listeners in __init__.py.

This module deliberately imports nothing from Home Assistant. Every decision
about which panels the Permission Manager offers, reports, or honours lives
here, so there is exactly one answer to each question and it can be unit
tested offline. Reading panels off `hass` stays in discovery.py.

Until v2.0.13 this module had a frontend counterpart, permission_policy.js, and
the two had to be kept saying the same thing. The Panel Gate reads its answer
from here and the browser is told nothing, so this is now the only spelling.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from .const import PERM_CLOSED, PREFIX_PANEL


def _panel_attr(panel: Any, name: str) -> Any:
    """Read one attribute off a panel, which may be a dict or an object."""
    if isinstance(panel, dict):
        return panel.get(name)
    return getattr(panel, name, None)


def is_unroutable_panel(panel: Any) -> bool:
    """Whether Home Assistant registers this panel but never routes to it.

    Home Assistant keeps a stub `lovelace` panel on instances that have no
    legacy overview dashboard. Its own ha-panel-lovelace does:

        const confMode = this.panel.config?.mode;
        if (!confMode) navigate("/home", {replace: true});

    so opening that panel sends the browser straight to the real default
    dashboard. A Permission level on it can never be honoured. The test is
    deliberately word-for-word Home Assistant's own, so the two cannot drift.
    """
    if _panel_attr(panel, "component_name") != "lovelace":
        return False
    config = _panel_attr(panel, "config")
    if not isinstance(config, dict):
        return True
    return not config.get("mode")


def unroutable_panel_ids(panels: Mapping[str, Any]) -> set[str]:
    """Panel ids that Home Assistant registers but never routes to."""
    return {
        panel_id
        for panel_id, panel in panels.items()
        if is_unroutable_panel(panel)
    }


# Panels Home Assistant ships for administrators only. A Permission level on
# one of them would be meaningless, so the matrix has never offered them.
ADMIN_ONLY_PANELS = frozenset({"developer-tools", "config", "profile"})

# Panels a non-administrator keeps whatever the Permission store says: their
# own account page, which is no Resource and which the Permission Manager
# panel has never offered a level on.
#
# This and ROUTER_FALLBACK_PANELS below had JavaScript twins until v2.0.13, and
# a test read both files because nothing made them agree at runtime: two layers
# disagreeing about which panels need no Permission would deny in one place
# what they allowed in the other. There is one layer now, and this is it.
ALWAYS_VISIBLE_PANELS = frozenset({"profile"})

# Panels kept for routing only. Home Assistant resolves its default panel as
# `panels[default] ?? panels.home ?? panels.notfound` and throws reading
# `.url_path` off the result when all three are gone — which is what filtering
# did to it. `notfound` is in Home Assistant's own FIXED_PANELS, so it never
# appears in a sidebar and keeping it costs nothing visible.
ROUTER_FALLBACK_PANELS = frozenset({"notfound"})

# The two above, together: the panels that need no Permission level. Named
# because it is also the whole of what a non-administrator receives when the
# Panel Gate is running and cannot answer — the degraded set is exactly "every
# panel that needs no Permission, and nothing that does", rather than a second
# list that could come to disagree with this one.
PANELS_WITHOUT_PERMISSION = ALWAYS_VISIBLE_PANELS | ROUTER_FALLBACK_PANELS


def admin_panel_resources(panels: Mapping[str, Any]) -> list[dict[str, str]]:
    """The panel Resources the permission matrix offers an administrator.

    The single source of the matrix's panel list. It excludes the panels
    Home Assistant keeps for administrators, and the panels it registers but
    never routes to — offering one of those would give the administrator a
    toggle that saves a level get_panel_permissions then drops.
    """
    unroutable = unroutable_panel_ids(panels)

    resources: list[dict[str, str]] = []
    for panel_id, panel in panels.items():
        if panel_id in ADMIN_ONLY_PANELS or panel_id in unroutable:
            continue

        title = _panel_attr(panel, "title")
        if not title:
            config = _panel_attr(panel, "config")
            if isinstance(config, dict):
                title = config.get("title")
        resources.append({
            "id": panel_id,
            "name": str(title or panel_id),
            "type": "panel",
        })
    return resources


def visible_panel_ids(
    panel_ids: Iterable[str],
    panels: Mapping[str, Any],
    user_permissions: Mapping[str, int] | None,
    is_admin: bool,
) -> set[str]:
    """The panel ids this user may receive. The whole decision, as a set.

    The one answer to "which panels may this user see", so that the Panel Gate
    deciding and get_panel_permissions reporting cannot drift apart. They did
    on the Gate's first spike run: a non-admin came back with the stub
    `lovelace` panel, because the Gate's own rule honoured a store row that
    get_panel_permissions has always dropped.

    The answer is a subset of `panel_ids`, never more: the caller says which
    panels are on the table — for the Gate, the panels Home Assistant itself
    computed for this user — and nothing here adds one back.

    :param panel_ids: the panel ids on offer to this user.
    :param panels: the registered panels, read for the unroutable verdict.
    :param user_permissions: this user's Permission store rows, keyed by
        Resource id (`panel_*`), as _get_user_permissions returns them.
    :param is_admin: an administrator is never filtered.
    """
    offered = set(panel_ids)
    if is_admin:
        return offered

    unroutable = unroutable_panel_ids(panels or {})
    permissions = user_permissions or {}

    visible: set[str] = set()
    for panel_id in offered:
        # A level on a panel Home Assistant never routes to can never be
        # honoured, so it is refused ahead of everything the store says. The
        # row itself is left alone: it comes back to life if the panel does.
        if panel_id in unroutable:
            continue
        if panel_id in PANELS_WITHOUT_PERMISSION:
            visible.add(panel_id)
            continue
        # Fail-secure: only an explicit level above Closed grants. Absent,
        # like Closed, is a refusal.
        if permissions.get(f"{PREFIX_PANEL}{panel_id}", PERM_CLOSED) > PERM_CLOSED:
            visible.add(panel_id)
    return visible


def deleted_dashboard_resource_id(
    url_path: str | None, panels: Mapping[str, Any]
) -> str | None:
    """The panel Resource a `lovelace_updated` event has left with nothing behind it.

    Home Assistant fires `lovelace_updated` with `{"url_path": ...}` and
    nothing else — the same payload on a save as on a delete, on every version
    from 2025.7 through 2026.7 and on dev. There is no `action` key, and until
    v2.0.14 this integration read one: `action == "delete"` was never true, so
    no deleted dashboard ever had its Permission rows removed (issue #8).

    What tells a delete from a save is the panel registry. Home Assistant's own
    `storage_dashboard_changed` calls `frontend.async_remove_panel` before the
    config it then deletes fires this event, so by the time it is read, a
    url_path with no panel behind it is a dashboard that is gone.

    Everything short of a certain deletion answers None and keeps the rows:

    * No `url_path` — the default dashboard's own config. Home Assistant goes
      on serving that dashboard from the same panel, so nothing disappeared.
    * No readable registry — `panels` is read off `hass.data`, where empty
      means "could not read it", not "Home Assistant has no panels". Reading a
      deletion out of that would erase every dashboard's Permissions on an
      ordinary save.

    :param url_path: the event's `url_path`, as Home Assistant sends it.
    :param panels: the registered panels, read after Home Assistant has removed
        the deleted one.
    :return: the `panel_*` Resource id to forget, or None to keep everything.
    """
    if not url_path:
        return None
    if not panels:
        return None
    if url_path in panels:
        return None
    return f"{PREFIX_PANEL}{url_path}"
