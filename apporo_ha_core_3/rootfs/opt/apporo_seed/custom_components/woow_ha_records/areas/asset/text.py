"""Text platform for Ha Asset Record.

Creates a text entity for the ``brand`` field of each asset.
Category is now managed by the independent Category CRUD system
(not as a free-text HA entity). Long-text fields (``manual_md``,
``maintenance_md``) are excluded because they exceed HA core's
255-character hard cap on TextEntity state.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.text import TextEntity, TextMode
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    ATTR_ASSET_ID,
    DOMAIN,
    FIELD_BRAND,
)
from .coordinator import Asset, AssetCoordinator
from .entity import AssetEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_area(
    hass: HomeAssistant,
    coordinator: AssetCoordinator,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up text entities."""

    entities: list[AssetTextEntity] = []
    for asset in coordinator.assets.values():
        entities.extend(_create_text_entities(coordinator, asset))

    async_add_entities(entities)

    # Listen for new assets
    @callback  # [M-08] Listener is called from the event loop.
    def _async_add_asset_entities() -> None:
        """Add entities for new assets."""
        # [M-09] Use entity registry for dedup instead of local list.
        ent_reg = er.async_get(hass)
        new_entities: list[AssetTextEntity] = []

        for asset in coordinator.assets.values():
            for entity in _create_text_entities(coordinator, asset):
                if ent_reg.async_get_entity_id(
                    "text", DOMAIN, entity.unique_id
                ) is None:
                    new_entities.append(entity)

        if new_entities:
            async_add_entities(new_entities)

    coordinator.entry.async_on_unload(coordinator.add_listener(_async_add_asset_entities))


def _create_text_entities(
    coordinator: AssetCoordinator, asset: Asset
) -> list[AssetTextEntity]:
    """Create text entities for an asset.

    Only brand is exposed as a text entity. Category is now managed
    by the independent Category CRUD system. manual_md and maintenance_md
    are long-text fields that exceed HA core's hard cap of 255 characters
    for TextEntity state.
    """
    return [
        AssetTextEntity(coordinator, asset, FIELD_BRAND, "brand"),
    ]


class AssetTextEntity(AssetEntity, TextEntity):
    """Text entity for asset text fields.

    Provides a text input for the ``brand`` field of an asset.
    Category is managed by the independent Category CRUD system.
    Max length is 255 characters, enforced by HA core.

    [L-05] Removed misleading _attr_native_max = 65535.
    HA core's TextEntity.max property hard-caps at MAX_LENGTH_STATE_STATE (255)
    regardless of what native_max is set to (see core text/__init__.py line 205).
    We rely on the default (255) which is correct for the brand field.
    """

    _attr_mode = TextMode.TEXT

    @property
    def native_value(self) -> str | None:
        """Return the current text value.

        [L-09] Return None instead of empty string for unset fields,
        which is the HA convention for "no value".
        """
        value = self._get_field_value()
        return value if value else None

    def _get_field_value(self) -> str:
        """Get the raw value for this field."""
        if self.field_name == FIELD_BRAND:
            return self.asset.brand
        return ""

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes.

        [L-08] Return type is dict[str, Any], not dict[str, str].
        """
        return {ATTR_ASSET_ID: self.asset.id}

    async def async_set_value(self, value: str) -> None:
        """Set the text value."""
        await self.coordinator.async_update_asset(
            self.asset.id, self.field_name, value
        )
