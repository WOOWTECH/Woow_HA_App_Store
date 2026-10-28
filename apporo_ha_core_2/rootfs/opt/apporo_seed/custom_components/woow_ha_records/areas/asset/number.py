"""Number platform for Ha Asset Record.

Creates one number entity per asset for tracking its monetary value.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    ATTR_ASSET_ID,
    DOMAIN,
    FIELD_VALUE,
    VALUE_MAX,
    VALUE_MIN,
    VALUE_STEP,
)
from .coordinator import Asset, AssetCoordinator
from .entity import AssetEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_area(
    hass: HomeAssistant,
    coordinator: AssetCoordinator,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up number entities."""

    entities: list[AssetNumberEntity] = []
    for asset in coordinator.assets.values():
        entities.append(_create_number_entity(coordinator, asset))

    async_add_entities(entities)

    # Listen for new assets
    @callback  # [M-08] Listener is called from the event loop.
    def _async_add_asset_entities() -> None:
        """Add entities for new assets."""
        # [M-09] Use entity registry for dedup instead of local list.
        ent_reg = er.async_get(hass)
        new_entities: list[AssetNumberEntity] = []

        for asset in coordinator.assets.values():
            entity = _create_number_entity(coordinator, asset)
            if ent_reg.async_get_entity_id(
                "number", DOMAIN, entity.unique_id
            ) is None:
                new_entities.append(entity)

        if new_entities:
            async_add_entities(new_entities)

    coordinator.entry.async_on_unload(coordinator.add_listener(_async_add_asset_entities))


def _create_number_entity(
    coordinator: AssetCoordinator, asset: Asset
) -> AssetNumberEntity:
    """Create number entity for an asset."""
    return AssetNumberEntity(coordinator, asset, FIELD_VALUE, "value")


class AssetNumberEntity(AssetEntity, NumberEntity):
    """Number entity for asset value.

    State
        Monetary value of the asset.

    Range
        ``VALUE_MIN`` to ``VALUE_MAX``, step ``VALUE_STEP`` (0.01).

    Unit
        ``"$"``

    Mode
        ``BOX`` (free numeric input).

    Extra state attributes
        * ``asset_id`` (str) -- identifier of the parent asset.

    Unique ID pattern
        ``{asset_id}_value``
    """

    _attr_native_min_value = VALUE_MIN
    _attr_native_max_value = VALUE_MAX
    _attr_native_step = VALUE_STEP  # [L-07] 0.01 to allow decimal values
    _attr_mode = NumberMode.BOX
    # [L-06] Provide a unit of measurement for the value entity.
    # Using a generic currency symbol; can be made configurable per-asset later.
    _attr_native_unit_of_measurement = "$"

    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        return self.asset.value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        return {ATTR_ASSET_ID: self.asset.id}

    async def async_set_native_value(self, value: float) -> None:
        """Set the value."""
        await self.coordinator.async_update_asset(
            self.asset.id, self.field_name, value
        )
