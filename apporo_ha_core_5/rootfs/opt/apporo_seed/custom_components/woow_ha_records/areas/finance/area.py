"""The finance Area: Accounts, their Transactions, and their Recurring Plans.

An Account used to be a Home Assistant config entry even though every account
already lived in one shared store — the entry was a second, redundant ledger of
which accounts existed. Since the merge (ADR-0001) the store is the only record
of that, and `finance_add_account` is a write rather than a config flow.
"""

from __future__ import annotations

import hashlib
import logging
import re

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send

from ...const import signal_entities_changed
from .const import AREA, DEFAULT_LOW_BALANCE_THRESHOLD
from .coordinator import FinanceCoordinator
from .models import Account
from .store import FinanceStore

_LOGGER = logging.getLogger(__name__)


def generate_account_id(name: str) -> str:
    """Derive a stable Account id from a display name.

    Lived in the config flow while an Account was a config entry.
    """
    account_id = re.sub(r"[^a-zA-Z0-9_]", "_", name.lower())
    account_id = re.sub(r"_+", "_", account_id).strip("_")
    if not account_id:
        account_id = hashlib.md5(name.encode()).hexdigest()[:8]
    return account_id or "account"


class FinanceArea:
    """Owns the finance store and one coordinator per Account."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the Area."""
        self.hass = hass
        self.entry = entry
        self.store = FinanceStore(hass)
        self.accounts: dict[str, FinanceCoordinator] = {}

    async def async_load(self) -> None:
        """Load the store and bring up a coordinator per Account."""
        data = await self.store.async_load()
        for account_id in list(data.accounts):
            await self._async_start_coordinator(account_id)
        _LOGGER.debug("Loaded finance Area: %d accounts", len(self.accounts))

    async def _async_start_coordinator(
        self, account_id: str, *, during_entry_setup: bool = True
    ) -> FinanceCoordinator:
        """Create and start the coordinator for one Account."""
        coordinator = FinanceCoordinator(
            self.hass,
            self.entry,
            self.store,
            account_id,
            DEFAULT_LOW_BALANCE_THRESHOLD,
        )
        await coordinator.async_setup(during_entry_setup=during_entry_setup)
        self.accounts[account_id] = coordinator
        return coordinator

    async def async_shutdown(self) -> None:
        """Stop every coordinator's scheduled work."""
        for coordinator in self.accounts.values():
            await coordinator.async_shutdown()
        self.accounts.clear()

    @callback
    def async_notify_entities_changed(self) -> None:
        """Tell the finance platforms to reconcile their entities."""
        async_dispatcher_send(self.hass, signal_entities_changed(AREA))

    # ── Accounts ─────────────────────────────────────────────────────

    def get(self, account_id: str) -> FinanceCoordinator | None:
        """Return one Account's coordinator, or None if there is no such Account."""
        return self.accounts.get(account_id)

    async def async_add_account(
        self, account_id: str, name: str, initial_balance: float = 0.0
    ) -> FinanceCoordinator:
        """Create an Account and persist it."""
        self.store.data.add_account(
            Account(id=account_id, name=name, balance=initial_balance)
        )
        await self.store.async_save()
        coordinator = await self._async_start_coordinator(
            account_id, during_entry_setup=False
        )
        self.async_notify_entities_changed()
        return coordinator

    async def async_remove_account(self, account_id: str) -> bool:
        """Delete an Account and everything recorded against it."""
        coordinator = self.accounts.pop(account_id, None)
        if coordinator is None:
            return False
        await coordinator.async_shutdown()
        self.store.data.remove_account(account_id)
        await self.store.async_save()
        self.async_notify_entities_changed()
        return True
