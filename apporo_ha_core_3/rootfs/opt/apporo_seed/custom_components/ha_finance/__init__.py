"""Ha Finance Record integration for Home Assistant.

Purpose
-------
Track personal finances with multiple accounts, transactions, and recurring
plans inside Home Assistant.

Architecture
------------
Multi-config-entry model -- each config entry represents one financial
account.  A single shared ``FinanceStore`` is created in ``async_setup``
(which runs once before any entries) and is reused by every entry's
coordinator.

Store pattern
~~~~~~~~~~~~~
``FinanceStore`` is instantiated in ``async_setup`` and stored in
``hass.data[DOMAIN]["store"]``.  The helper ``_get_or_create_store()``
ensures exactly one store exists regardless of call order.

Coordinator
~~~~~~~~~~~
One ``FinanceCoordinator`` per config entry.  Each coordinator references
the shared store and handles balance updates, transaction recording, and
recurring-plan execution for its account.

Platforms
~~~~~~~~~
Only the **sensor** platform is forwarded.  Per-account sensors include:
  * balance
  * last_transaction
  * last_note
  * last_time
  * plan sensors (one per recurring plan)

Panel / WebSocket
~~~~~~~~~~~~~~~~~
The sidebar panel and WebSocket commands are registered in ``async_setup``
(not ``async_setup_entry``), so they are set up exactly once and remain
available even when individual entries are reloaded.

Events
~~~~~~
* ``ha_finance_transaction_added``    -- a new transaction was recorded
* ``ha_finance_recurring_executed``   -- a recurring plan was executed
* ``ha_finance_balance_adjusted``     -- manual balance adjustment
* ``ha_finance_low_balance``          -- balance dropped below threshold

Configuration defaults
~~~~~~~~~~~~~~~~~~~~~~
* ``currency``               -- ``NTD``
* ``low_balance_threshold``  -- ``1000.0``
"""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.typing import ConfigType

from .const import CONF_ACCOUNT_ID, CONF_ACCOUNT_NAME, CONF_INITIAL_BALANCE, DOMAIN
from .coordinator import FinanceCoordinator
from .models import Account
from .panel import async_setup_panel
from .services import async_register_services
from .store import FinanceStore

_LOGGER = logging.getLogger(__name__)

# Keys for metadata stored in hass.data[DOMAIN]
_PANEL_REGISTERED_KEY = "_panel_registered"
_SERVICES_REGISTERED_KEY = "_services_registered"
_STORE_KEY = "store"

PLATFORMS_LIST: list[Platform] = [
    Platform.SENSOR,
]


def _get_or_create_store(hass: HomeAssistant) -> FinanceStore:
    """Get existing store or create a new one in hass.data."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if _STORE_KEY not in domain_data:
        domain_data[_STORE_KEY] = FinanceStore(hass)
    return domain_data[_STORE_KEY]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up Ha Finance domain — runs once before any config entries."""
    hass.data.setdefault(DOMAIN, {})

    # Register panel, WebSocket commands, and event listeners (once)
    await async_setup_panel(hass)
    hass.data[DOMAIN][_PANEL_REGISTERED_KEY] = True

    # Initialize shared store
    _get_or_create_store(hass)

    # Register HA services (once, in async_setup so they're available
    # even before any config entries exist — needed for add_account)
    async_register_services(hass)
    hass.data[DOMAIN][_SERVICES_REGISTERED_KEY] = True

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Ha Finance from a config entry."""
    store = hass.data[DOMAIN][_STORE_KEY]

    coordinator = FinanceCoordinator(hass, entry, store)
    await coordinator.async_setup()

    # Ensure account exists in storage
    account_id = entry.data[CONF_ACCOUNT_ID]
    account_name = entry.data[CONF_ACCOUNT_NAME]
    initial_balance = entry.data.get(CONF_INITIAL_BALANCE, 0.0)

    if coordinator.data.get_account(account_id) is None:
        account = Account(
            id=account_id,
            name=account_name,
            balance=initial_balance,
        )
        coordinator.data.add_account(account)
        await coordinator.store.async_save()
        await coordinator.async_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Register device
    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, account_id)},
        name=account_name,
        manufacturer="Ha Finance",
        model="Financial Account",
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS_LIST)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator: FinanceCoordinator = hass.data[DOMAIN][entry.entry_id]
    await coordinator.async_shutdown()

    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS_LIST):
        hass.data[DOMAIN].pop(entry.entry_id)

    # Note: panel and services are registered in async_setup (not
    # async_setup_entry), so they persist for the HA lifetime and are
    # NOT torn down when the last entry is removed.  This ensures
    # add_account remains callable even with zero accounts.

    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle removal of an entry."""
    account_id = entry.data[CONF_ACCOUNT_ID]

    # Try to get coordinator from hass.data first (if not yet unloaded)
    coordinator: FinanceCoordinator | None = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator:
        coordinator.data.remove_account(account_id)
        await coordinator.store.async_save()
    else:
        # Coordinator already unloaded, access store directly
        store = _get_or_create_store(hass)
        await store.async_load()
        store.data.remove_account(account_id)
        await store.async_save()
