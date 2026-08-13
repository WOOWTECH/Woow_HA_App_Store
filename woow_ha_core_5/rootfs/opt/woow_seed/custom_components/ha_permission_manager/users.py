"""User discovery for ha_permission_manager."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


@dataclass
class User:
    """Represents a Home Assistant user."""
    id: str
    name: str
    is_admin: bool


async def discover_users(hass: HomeAssistant) -> list[User]:
    """Discover all non-system users."""
    users = []
    for user in await hass.auth.async_get_users():
        # Skip system-generated users
        if user.system_generated:
            continue

        # Use HA's built-in is_admin property (handles is_owner + admin group check)
        is_admin = user.is_admin

        users.append(
            User(
                id=user.id,
                name=user.name or "Unknown",
                is_admin=is_admin,
            )
        )

    _LOGGER.debug(
        "Discovered %d users (%d admins)",
        len(users),
        sum(1 for u in users if u.is_admin)
    )
    return users


def get_admin_user_ids(users: list[User]) -> set[str]:
    """Get IDs of all admin users."""
    return {user.id for user in users if user.is_admin}
