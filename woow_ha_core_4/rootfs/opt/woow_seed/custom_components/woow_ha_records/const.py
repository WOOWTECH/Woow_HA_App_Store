"""Constants shared by every Area of the Woow HA Records integration.

One Home Assistant domain covers four Areas — finance, asset, health, note —
which share a runtime but never share data. Anything that needs to stay unique
across Areas (storage keys, service names, WebSocket commands, device
identifiers, entity unique IDs, bus events) is built from the helpers here so
the Area prefix can never be forgotten at a call site.
"""

from __future__ import annotations

from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "woow_ha_records"

AREA_FINANCE: Final = "finance"
AREA_ASSET: Final = "asset"
AREA_HEALTH: Final = "health"
AREA_NOTE: Final = "note"

AREAS: Final = (AREA_FINANCE, AREA_ASSET, AREA_HEALTH, AREA_NOTE)

# Union of the platforms the four Areas between them expose. The top-level
# platform modules fan each one out to whichever Areas implement it.
PLATFORMS: Final = [
    Platform.BUTTON,
    Platform.DATETIME,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TEXT,
]

STORAGE_VERSION: Final = 1

# Where each Area's panel bundle is served from, and the sidebar path it keeps.
# The paths predate the merge and are deliberately unchanged — users bookmark
# them and dashboards link to them.
FRONTEND_BASE_URL: Final = f"/{DOMAIN}/frontend"


def storage_key(area: str) -> str:
    """Return the Store key for an Area.

    Each Area keeps its own file. Finance transactions and health records are
    retained permanently, so a shared file would mean every note edit rewrites
    an ever-growing ledger.
    """
    return f"{DOMAIN}_{area}"


def service_name(area: str, verb: str) -> str:
    """Return the service name for an Area's verb, e.g. ``finance_add_transaction``.

    Four verbs collided across the pre-merge domains (``export_csv``,
    ``create_category``, ``delete_category``, ``list_categories``), so every
    service carries its Area.
    """
    return f"{area}_{verb}"


def ws_type(area: str, verb: str) -> str:
    """Return the WebSocket command type, e.g. ``woow_ha_records/finance/accounts``."""
    return f"{DOMAIN}/{area}/{verb}"


def event_type(area: str, name: str) -> str:
    """Return a bus event type, e.g. ``woow_ha_records_finance_transaction_added``."""
    return f"{DOMAIN}_{area}_{name}"


def signal_entities_changed(area: str) -> str:
    """Return the dispatcher signal an Area sends when its entity set changes.

    Structural edits (a Member added, a Record Type removed) used to reload the
    config entry to rebuild entities. With one entry covering four Areas that
    would blip the other three, and worse, a reload re-reads the store — which
    a debounced write may not have reached yet. The platforms listen for this
    instead.
    """
    return f"{DOMAIN}_{area}_entities_changed"


def device_id(area: str, record_id: str) -> str:
    """Return the device-registry identifier suffix for a record in an Area."""
    return f"{area}_{record_id}"


def unique_id(area: str, *parts: str) -> str:
    """Return an entity unique ID scoped to an Area.

    Pre-merge, finance and health unique IDs carried no domain prefix at all,
    so an Account and a Member sharing an ID would have collided on the sensor
    platform once they landed in one integration.
    """
    return "_".join((area, *parts))
