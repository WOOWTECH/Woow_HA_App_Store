"""The integration's runtime state, and how service handlers reach it.

There is one config entry covering all four Areas, so each Area's live objects
hang off a single record stored on that entry. Service handlers only receive a
`ServiceCall`, so the same record is mirrored into ``hass.data[DOMAIN]``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN

if TYPE_CHECKING:
    from .areas.asset.coordinator import AssetCoordinator
    from .areas.finance.store import FinanceStore
    from .areas.health.area import HealthArea
    from .areas.note.store import HaNoteRecordStore


@dataclass
class WoowRecordsData:
    """Live state for every Area."""

    finance: FinanceStore
    asset: AssetCoordinator
    health: HealthArea
    note: HaNoteRecordStore


def get_data(hass: HomeAssistant) -> WoowRecordsData:
    """Return the runtime state, or raise if the integration is not loaded."""
    data = hass.data.get(DOMAIN)
    if data is None:
        raise HomeAssistantError(
            f"{DOMAIN} is not loaded — add the integration before calling its services"
        )
    return data
