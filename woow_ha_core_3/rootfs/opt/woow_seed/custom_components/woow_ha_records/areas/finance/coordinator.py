"""Data coordinator for Ha Finance Record integration."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any, Callable

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    DEFAULT_LOW_BALANCE_THRESHOLD,
    DOMAIN,
    EVENT_BALANCE_ADJUSTED,
    EVENT_LOW_BALANCE,
    EVENT_RECURRING_EXECUTED,
    EVENT_TRANSACTION_ADDED,
    FREQUENCY_DAILY,
    FREQUENCY_MONTHLY,
    FREQUENCY_WEEKLY,
    FREQUENCY_YEARLY,
    TRANSACTION_ADJUSTMENT,
    TRANSACTION_RECURRING,
)
from .models import Account, FinanceData, RecurringPlan, Transaction
from .store import FinanceStore

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

# Note labels for transactions (kept in code for simplicity, could be made configurable)
NOTE_AUTO_SUFFIX = " (Auto)"
NOTE_BALANCE_ADJUSTMENT = "Balance Adjustment"


def get_coordinator_for_account(
    hass: HomeAssistant, account_id: str
) -> FinanceCoordinator | None:
    """Return the coordinator for one Account, or None."""
    from ...runtime import get_data

    return get_data(hass).finance.get(account_id)


class FinanceCoordinator(DataUpdateCoordinator[FinanceData]):
    """Coordinator for managing finance data and recurring plans."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        store: FinanceStore,
        account_id: str,
        low_balance_threshold: float = DEFAULT_LOW_BALANCE_THRESHOLD,
    ) -> None:
        """Initialize the coordinator for one Account.

        An Account used to be a config entry, so the id and the low-balance
        threshold were read off it. They are passed in now — *entry* is the
        integration's single entry and identifies nothing in particular.
        """
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=None,
            config_entry=entry,
        )
        self.store = store
        self._account_id: str = account_id
        self._unsub_time_change: Callable[[], None] | None = None
        self._low_balance_threshold: float = low_balance_threshold

    @property
    def account_id(self) -> str:
        """Get the account ID for this coordinator."""
        return self._account_id

    @property
    def account(self) -> Account | None:
        """Get the current account."""
        if self.data is None:
            return None
        return self.data.get_account(self._account_id)

    async def _async_update_data(self) -> FinanceData:
        """Fetch data from storage."""
        return await self.store.async_load()

    async def async_setup(self, *, during_entry_setup: bool = True) -> None:
        """Set up the coordinator.

        ``async_config_entry_first_refresh`` may only be called while the entry
        is still setting up. Accounts created later — through a service or the
        panel — start their coordinator against an already-loaded entry, and
        take a plain refresh instead.
        """
        if during_entry_setup:
            await self.async_config_entry_first_refresh()
        else:
            await self.async_refresh()
        # Schedule daily check for recurring plans at midnight
        self._unsub_time_change = async_track_time_change(
            self.hass, self._async_check_recurring_plans, hour=0, minute=0, second=0
        )

    async def async_shutdown(self) -> None:
        """Shutdown the coordinator."""
        if self._unsub_time_change:
            self._unsub_time_change()
            self._unsub_time_change = None

    @callback
    def _async_check_recurring_plans(self, now: datetime) -> None:
        """Check and execute recurring plans."""
        self.hass.async_create_task(self._async_execute_recurring_plans())

    async def _async_execute_recurring_plans(self) -> None:
        """Execute all due recurring plans."""
        account = self.account
        if account is None:
            return

        today = dt_util.now().date()

        for plan_id, plan in list(account.recurring_plans.items()):
            if not plan.active:
                continue

            if plan.next_date is None:
                # Calculate initial next_date
                plan.next_date = self._calculate_next_date(plan, today).isoformat()
                continue

            parsed = dt_util.parse_datetime(plan.next_date)
            next_date = parsed.date() if parsed else today
            if today >= next_date:
                # Execute the plan
                await self._execute_plan(account, plan)

        await self.store.async_save()
        await self.async_refresh()

    async def _execute_plan(self, account: Account, plan: RecurringPlan) -> None:
        """Execute a single recurring plan."""
        transaction = Transaction.create(
            amount=plan.amount,
            note=f"{plan.title}{NOTE_AUTO_SUFFIX}",
            transaction_type=TRANSACTION_RECURRING,
            plan_id=plan.id,
        )
        account.add_transaction(transaction)
        plan.last_executed = dt_util.now().isoformat()
        plan.next_date = self._calculate_next_date(
            plan, dt_util.now().date() + timedelta(days=1)
        ).isoformat()

        # Fire event
        self.hass.bus.async_fire(
            EVENT_RECURRING_EXECUTED,
            {
                "account": account.id,
                "plan_id": plan.id,
                "title": plan.title,
                "amount": plan.amount,
            },
        )
        _LOGGER.info(
            "Executed recurring plan %s for account %s: %s",
            plan.title,
            account.id,
            plan.amount,
        )

        # Check for low balance after recurring execution
        self._check_low_balance(account)

    def _calculate_next_date(
        self, plan: RecurringPlan, from_date: date
    ) -> date:
        """Calculate the next execution date for a plan."""
        if plan.frequency == FREQUENCY_DAILY:
            return from_date

        if plan.frequency == FREQUENCY_WEEKLY:
            # day is 1-7 (Monday-Sunday)
            day = max(1, min(plan.day, 7))  # Validate day range
            days_ahead = day - from_date.isoweekday()
            if days_ahead <= 0:
                days_ahead += 7
            return from_date + timedelta(days=days_ahead)

        if plan.frequency == FREQUENCY_MONTHLY:
            # day is 1-28
            day = max(1, min(plan.day, 28))  # Validate day range
            next_date = from_date.replace(day=day)
            if next_date <= from_date:
                # Move to next month
                if from_date.month == 12:
                    next_date = from_date.replace(year=from_date.year + 1, month=1, day=day)
                else:
                    next_date = from_date.replace(month=from_date.month + 1, day=day)
            return next_date

        if plan.frequency == FREQUENCY_YEARLY:
            # day is 1-28, month is 1-12
            day = max(1, min(plan.day, 28))
            month = max(1, min(getattr(plan, "month", 1), 12))
            try:
                next_date = from_date.replace(month=month, day=day)
            except ValueError:
                # Handle invalid date combinations (e.g., Feb 30)
                next_date = from_date.replace(month=month, day=min(day, 28))
            if next_date <= from_date:
                next_date = next_date.replace(year=from_date.year + 1)
            return next_date

        return from_date

    def _check_low_balance(self, account: Account) -> None:
        """Check and fire low balance event if needed."""
        if account.balance < self._low_balance_threshold:
            self.hass.bus.async_fire(
                EVENT_LOW_BALANCE,
                {
                    "account": account.id,
                    "balance": account.balance,
                    "threshold": self._low_balance_threshold,
                },
            )
            _LOGGER.info(
                "Low balance alert for account %s: %s (threshold: %s)",
                account.id,
                account.balance,
                self._low_balance_threshold,
            )

    # Account operations
    async def async_add_transaction(
        self, amount: float, note: str, transaction_type: str = "manual"
    ) -> Transaction | None:
        """Add a transaction to the account."""
        account = self.account
        if account is None:
            return None

        transaction = Transaction.create(
            amount=amount,
            note=note,
            transaction_type=transaction_type,
        )
        account.add_transaction(transaction)
        await self.store.async_save()

        # Fire event
        self.hass.bus.async_fire(
            EVENT_TRANSACTION_ADDED,
            {
                "account": account.id,
                "amount": amount,
                "note": note,
                "type": transaction_type,
            },
        )

        # Check for low balance
        self._check_low_balance(account)

        await self.async_refresh()
        return transaction

    async def async_adjust_balance(self, new_balance: float) -> None:
        """Adjust the account balance."""
        account = self.account
        if account is None:
            return

        old_balance = account.balance
        diff = new_balance - old_balance

        if diff != 0:
            transaction = Transaction.create(
                amount=diff,
                note=NOTE_BALANCE_ADJUSTMENT,
                transaction_type=TRANSACTION_ADJUSTMENT,
            )
            account.add_transaction(transaction)
            await self.store.async_save()

            # Fire event
            self.hass.bus.async_fire(
                EVENT_BALANCE_ADJUSTED,
                {
                    "account": account.id,
                    "old_balance": old_balance,
                    "new_balance": new_balance,
                    "diff": diff,
                },
            )

            # Check for low balance
            self._check_low_balance(account)

            await self.async_refresh()

    # Recurring plan operations
    async def async_add_recurring_plan(
        self,
        plan_id: str,
        title: str,
        amount: float,
        frequency: str,
        day: int,
        month: int = 1,
        active: bool = True,
    ) -> None:
        """Add a recurring plan."""
        account = self.account
        if account is None:
            return

        plan = RecurringPlan(
            id=plan_id,
            title=title,
            amount=amount,
            frequency=frequency,
            day=day,
            month=month,
            active=active,
        )
        plan.next_date = self._calculate_next_date(
            plan, dt_util.now().date()
        ).isoformat()

        account.add_recurring_plan(plan)
        await self.store.async_save()
        await self.async_refresh()

    async def async_update_recurring_plan(
        self, plan_id: str, **kwargs: Any
    ) -> bool:
        """Update a recurring plan.

        Returns True if the plan was found and updated, False otherwise.
        """
        account = self.account
        if account is None:
            return False

        plan = account.recurring_plans.get(plan_id)
        if plan is None:
            return False

        for key, value in kwargs.items():
            if hasattr(plan, key):
                setattr(plan, key, value)

        # Recalculate next_date if frequency, day, or month changed
        if "frequency" in kwargs or "day" in kwargs or "month" in kwargs:
            plan.next_date = self._calculate_next_date(
                plan, dt_util.now().date()
            ).isoformat()

        await self.store.async_save()
        await self.async_refresh()
        return True

    async def async_remove_recurring_plan(self, plan_id: str) -> None:
        """Remove a recurring plan."""
        account = self.account
        if account is None:
            return

        account.remove_recurring_plan(plan_id)
        await self.store.async_save()

        # Clean up associated entities from entity registry
        await self._async_cleanup_plan_entities(plan_id)

        await self.async_refresh()

    async def _async_cleanup_plan_entities(self, plan_id: str) -> None:
        """Remove sensor entities associated with a deleted recurring plan."""
        entity_registry = er.async_get(self.hass)
        account_id = self._account_id

        # Only sensor entities remain for plans
        sensor_suffixes = ["_next_date", "_last_executed"]

        for suffix in sensor_suffixes:
            unique_id = f"{account_id}_{plan_id}{suffix}"
            entity_id = entity_registry.async_get_entity_id(
                "sensor", DOMAIN, unique_id
            )
            if entity_id:
                entity_registry.async_remove(entity_id)
                _LOGGER.debug("Removed entity %s for deleted plan %s", entity_id, plan_id)

    async def async_set_plan_active(self, plan_id: str, active: bool) -> None:
        """Set the active state of a recurring plan."""
        await self.async_update_recurring_plan(plan_id, active=active)
