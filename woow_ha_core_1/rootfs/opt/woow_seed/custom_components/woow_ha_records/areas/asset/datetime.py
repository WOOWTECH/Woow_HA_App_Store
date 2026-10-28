"""Datetime platform for Ha Asset Record.

Creates datetime entities for the ``purchase_at`` and ``warranty_until``
fields of each asset.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.components.datetime import DateTimeEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    ATTR_ASSET_ID,
    DOMAIN,
    FIELD_PURCHASE_AT,
    FIELD_WARRANTY_UNTIL,
)
from .coordinator import Asset, AssetCoordinator
from .entity import AssetEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_area(
    hass: HomeAssistant,
    coordinator: AssetCoordinator,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up datetime entities."""

    entities: list[AssetDateTimeEntity] = []
    for asset in coordinator.assets.values():
        entities.extend(_create_datetime_entities(coordinator, asset))

    async_add_entities(entities)

    # Listen for new assets
    @callback  # [M-08] Listener is called from the event loop.
    def _async_add_asset_entities() -> None:
        """Add entities for new assets."""
        # [M-09] Use entity registry for dedup instead of local list.
        ent_reg = er.async_get(hass)
        new_entities: list[AssetDateTimeEntity] = []

        for asset in coordinator.assets.values():
            for entity in _create_datetime_entities(coordinator, asset):
                if ent_reg.async_get_entity_id(
                    "datetime", DOMAIN, entity.unique_id
                ) is None:
                    new_entities.append(entity)

        if new_entities:
            async_add_entities(new_entities)

    coordinator.entry.async_on_unload(coordinator.add_listener(_async_add_asset_entities))


def _create_datetime_entities(
    coordinator: AssetCoordinator, asset: Asset
) -> list[AssetDateTimeEntity]:
    """Create datetime entities for an asset."""
    return [
        AssetDateTimeEntity(coordinator, asset, FIELD_PURCHASE_AT, "purchase_at"),
        AssetDateTimeEntity(coordinator, asset, FIELD_WARRANTY_UNTIL, "warranty_until"),
    ]


class AssetDateTimeEntity(AssetEntity, DateTimeEntity):
    """Datetime entity for asset dates.

    Tracks the purchase date or warranty expiry for an asset.

    Fields
        ``purchase_at``, ``warranty_until``

    Extra state attributes
        * ``asset_id`` (str) -- identifier of the parent asset.

    Unique ID pattern
        ``{asset_id}_{field_name}``
    """

    @property
    def native_value(self) -> datetime | None:
        """Return the current datetime value."""
        if self.field_name == FIELD_PURCHASE_AT:
            return self.asset.purchase_at
        if self.field_name == FIELD_WARRANTY_UNTIL:
            return self.asset.warranty_until
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        return {ATTR_ASSET_ID: self.asset.id}

    async def async_set_value(self, value: datetime) -> None:
        """Set the datetime value."""
        await self.coordinator.async_update_asset(
            self.asset.id, self.field_name, value
        )
