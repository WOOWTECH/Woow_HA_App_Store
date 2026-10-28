"""Every write to the Permission store, and the announcement each one owes.

This module deliberately imports nothing from Home Assistant, for the reason
panel_policy.py gives: the decisions live in one place and can be unit tested
offline. Here the decision is *what a write does to the map, and what it says
it did*. Reaching the map off `hass`, persisting it and putting the
announcement on the event bus stay in `__init__.py`.

Every function takes the Permission store — the `{user_id: {resource_id:
level}}` map — mutates it in place, and returns the announcement that write
owes. There is no way to write the store without being handed something to
announce, which is the whole of issue #14: two of the five writes used to
return nothing, and the two were the revocations.

**The announcement is diagnostic, not a contract.** It says "the Permission
store has been written to, re-read it", and nothing more. Since v2.0.13 nothing
this integration ships even listens: the Filters that re-fetched on it are gone
and a live page hears about a Permission change over `panels_updated`, which
carries no payload to branch on. `action` is there so a reader of a trace can
tell the write paths apart, and the rest is detail for the same reader. ADR-0010 records that, and why a consumer must not start branching on
it.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping, MutableMapping

# The name an announcement goes out under. Nothing in this repo subscribes to
# it — not the Permission Manager panel, which updates its own state as it
# writes (ADR-0010), and not the frontend, which has had nothing on a page to
# update since v2.0.13. Spelt once anyway, so a rename cannot leave a listener
# behind on the old string.
EVENT_PERMISSION_MANAGER_UPDATED = "permission_manager_updated"

# The five write paths, as they name themselves in an announcement.
ACTION_SET = "set"
ACTION_BULK_SET = "bulk_set"
ACTION_REMOVE_USER = "remove_user"
ACTION_REMOVE_RESOURCE = "remove_resource"
ACTION_RESET_ALL = "reset_all"

# The Permission store: user id -> resource id -> Permission level.
Permissions = MutableMapping[str, MutableMapping[str, int]]

# A Permission level of `0` is Closed, not absent, so absence needs a sentinel
# of its own that no stored level can be mistaken for.
_MISSING = object()


def set_permission(
    permissions: Permissions, user_id: str, resource_id: str, level: int
) -> dict[str, Any]:
    """Set one user's Permission level on one Resource."""
    permissions.setdefault(user_id, {})[resource_id] = level
    return {
        "action": ACTION_SET,
        "user_id": user_id,
        "resource_id": resource_id,
        "level": level,
    }


def bulk_set_permissions(
    permissions: Permissions, entries: Iterable[Mapping[str, Any]]
) -> dict[str, Any]:
    """Apply many `set_permission`s, announcing once for the whole batch.

    An entry is `{"user_id", "resource_id", "level"}`. The caller validates
    them before calling: this applies what it is given.

    It goes through `set_permission` rather than spelling the write again, so a
    bulk set cannot come to mean something other than many single sets. The
    announcement each one returns is dropped: the batch has one of its own.
    """
    count = 0
    for entry in entries:
        set_permission(
            permissions, entry["user_id"], entry["resource_id"], entry["level"]
        )
        count += 1
    return {"action": ACTION_BULK_SET, "count": count}


def remove_user_permissions(permissions: Permissions, user_id: str) -> dict[str, Any]:
    """Drop every Permission level a user holds.

    `count` is how many Resources went with them.
    """
    removed = permissions.pop(user_id, {})
    return {
        "action": ACTION_REMOVE_USER,
        "user_id": user_id,
        "count": len(removed),
    }


def remove_resource_permissions(
    permissions: Permissions, resource_id: str
) -> dict[str, Any]:
    """Drop one Resource's Permission level from every user who holds one.

    `count` is how many users that was. The user's map is left in place even
    when it empties: a user with no levels and a user who is not in the store
    read the same way, and removing a Resource is not a statement about the
    user.
    """
    count = 0
    for user_perms in permissions.values():
        if user_perms.pop(resource_id, _MISSING) is not _MISSING:
            count += 1
    return {
        "action": ACTION_REMOVE_RESOURCE,
        "resource_id": resource_id,
        "count": count,
    }


def reset_all_permissions(permissions: Permissions) -> dict[str, Any]:
    """Empty the Permission store, in place.

    In place because a function handed the map cannot rebind the
    `hass.data[DOMAIN]["permissions"]` slot it came out of — and because
    clearing it keeps every holder of that map in step, rather than leaving
    them on a dict that is no longer the store. The service handler used to
    replace the slot instead, which was correct only for as long as it was the
    thing holding it.

    `count` is how many users were cleared.
    """
    count = len(permissions)
    permissions.clear()
    return {"action": ACTION_RESET_ALL, "count": count}
