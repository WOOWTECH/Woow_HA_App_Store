"""Sensor entities for Ha Finance Record integration.

Creates multiple sensor entities per financial account:

- BalanceDisplaySensor: current account balance
- LastTransactionSensor: amount of the most recent transaction
- LastNoteSensor: note from the most recent transaction
- LastTimeSensor: timestamp of the most recent transaction
- PlanNextDateSensor: next execution date for each recurring plan
- PlanLastExecutedSensor: last execution time for each recurring plan

All sensors update via the FinanceCoordinator (no polling).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import CONF_ACCOUNT_ID, CONF_CURRENCY, DEFAULT_CURRENCY, DOMAIN
from .coordinator import FinanceCoordinator

if TYPE_CHECKING:
    from .models import Account


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities."""
    coordinator: FinanceCoordinator = hass.data[DOMAIN][entry.entry_id]
    account_id = entry.data[CONF_ACCOUNT_ID]

    entities: list[SensorEntity] = [
        BalanceDisplaySensor(coordinator, account_id),
        LastTransactionSensor(coordinator, account_id),
        LastNoteSensor(coordinator, account_id),
        LastTimeSensor(coordinator, account_id),
    ]

    # Add recurring plan sensors
    if coordinator.account:
        for plan_id in coordinator.account.recurring_plans:
            entities.append(PlanNextDateSensor(coordinator, account_id, plan_id))
            entities.append(PlanLastExecutedSensor(coordinator, account_id, plan_id))

    async_add_entities(entities)

    # Register listener for new plans
    @callback
    def async_add_plan_entities() -> None:
        """Add entities for new recurring plans."""
        if not coordinator.account:
            return
        existing_plan_ids = {
            e.plan_id
            for e in entities
            if isinstance(e, (PlanNextDateSensor, PlanLastExecutedSensor))
        }
        new_entities: list[SensorEntity] = []
        for plan_id in coordinator.account.recurring_plans:
            if plan_id not in existing_plan_ids:
                new_entities.append(PlanNextDateSensor(coordinator, account_id, plan_id))
                new_entities.append(
                    PlanLastExecutedSensor(coordinator, account_id, plan_id)
                )
        if new_entities:
            async_add_entities(new_entities)
            entities.extend(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(async_add_plan_entities))


class FinanceSensorBase(CoordinatorEntity[FinanceCoordinator], SensorEntity):
    """Base class for finance sensor entities.

    Extends ``CoordinatorEntity[FinanceCoordinator]`` and ``SensorEntity``
    to provide shared ``device_info``, a unique-ID prefix based on
    ``account_id``, ``has_entity_name = True``, and ``should_poll = False``
    (inherited from ``CoordinatorEntity``).
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: FinanceCoordinator,
        account_id: str,
    ) -> None:
        """Initialize the sensor entity."""
        super().__init__(coordinator)
        self._account_id = account_id

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._account_id)},
        )

    @property
    def account(self) -> Account | None:
        """Get the account."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get_account(self._account_id)


class BalanceDisplaySensor(FinanceSensorBase):
    """Sensor showing the current account balance.

    State
        Current account balance (float), with ``state_class = TOTAL``.

    Icon
        ``mdi:cash``

    Unit
        Account currency (from config entry options, default NTD).

    Translation key
        ``balance_display``
    """

    _attr_icon = "mdi:cash"
    _attr_translation_key = "balance_display"
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(self, coordinator: FinanceCoordinator, account_id: str) -> None:
        """Initialize balance display sensor."""
        super().__init__(coordinator, account_id)
        self._attr_unique_id = f"{account_id}_balance_display"
        # Get currency from config entry options, default to NTD
        currency = coordinator.config_entry.options.get(CONF_CURRENCY, DEFAULT_CURRENCY)
        self._attr_native_unit_of_measurement = currency

    @property
    def native_value(self) -> float | None:
        """Return the balance."""
        account = self.account
        if account is None:
            return None
        return account.balance


class LastTransactionSensor(FinanceSensorBase):
    """Sensor showing the amount of the most recent transaction.

    State
        Amount of the most recent transaction (float), or ``None`` if no
        transactions exist.

    Icon
        ``mdi:cash-fast``

    Unit
        Account currency (from config entry options, default NTD).

    Translation key
        ``last_transaction``
    """

    _attr_icon = "mdi:cash-fast"
    _attr_translation_key = "last_transaction"

    def __init__(self, coordinator: FinanceCoordinator, account_id: str) -> None:
        """Initialize last transaction sensor."""
        super().__init__(coordinator, account_id)
        self._attr_unique_id = f"{account_id}_last_transaction"
        # Get currency from config entry options, default to NTD
        currency = coordinator.config_entry.options.get(CONF_CURRENCY, DEFAULT_CURRENCY)
        self._attr_native_unit_of_measurement = currency

    @property
    def native_value(self) -> float | None:
        """Return the last transaction amount."""
        account = self.account
        if account is None:
            return None
        last_tx = account.last_transaction
        if last_tx is None:
            return None
        return last_tx.amount


class LastNoteSensor(FinanceSensorBase):
    """Sensor showing the note text from the most recent transaction.

    State
        Note text (str) from the most recent transaction, or ``None`` if
        no transactions exist.

    Icon
        ``mdi:note-text-outline``

    Unit
        None.

    Translation key
        ``last_note``
    """

    _attr_icon = "mdi:note-text-outline"
    _attr_translation_key = "last_note"

    def __init__(self, coordinator: FinanceCoordinator, account_id: str) -> None:
        """Initialize last note sensor."""
        super().__init__(coordinator, account_id)
        self._attr_unique_id = f"{account_id}_last_note"

    @property
    def native_value(self) -> str | None:
        """Return the last transaction note."""
        account = self.account
        if account is None:
            return None
        last_tx = account.last_transaction
        if last_tx is None:
            return None
        return last_tx.note


class LastTimeSensor(FinanceSensorBase):
    """Sensor showing the timestamp of the most recent transaction.

    State
        Timestamp of the most recent transaction as a ``datetime`` object.

    Device class
        ``SensorDeviceClass.TIMESTAMP``

    Icon
        ``mdi:clock-outline``

    Translation key
        ``last_time``
    """

    _attr_icon = "mdi:clock-outline"
    _attr_translation_key = "last_time"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: FinanceCoordinator, account_id: str) -> None:
        """Initialize last time sensor."""
        super().__init__(coordinator, account_id)
        self._attr_unique_id = f"{account_id}_last_time"

    @property
    def native_value(self) -> datetime | None:
        """Return the last transaction time."""
        account = self.account
        if account is None:
            return None
        last_tx = account.last_transaction
        if last_tx is None:
            return None
        try:
            return datetime.fromisoformat(last_tx.timestamp)
        except (ValueError, TypeError):
            return None


class PlanNextDateSensor(FinanceSensorBase):
    """Sensor showing the next scheduled execution date of a recurring plan.

    One entity is created per recurring plan.

    State
        Next scheduled execution date (``date`` object).

    Device class
        ``SensorDeviceClass.DATE``

    Icon
        ``mdi:calendar-arrow-right``

    Translation key
        ``plan_next_date`` with placeholder ``{title}`` (plan title).
    """

    _attr_icon = "mdi:calendar-arrow-right"
    _attr_translation_key = "plan_next_date"
    _attr_device_class = SensorDeviceClass.DATE

    def __init__(
        self, coordinator: FinanceCoordinator, account_id: str, plan_id: str
    ) -> None:
        """Initialize plan next date sensor."""
        super().__init__(coordinator, account_id)
        self.plan_id = plan_id
        self._attr_unique_id = f"{account_id}_{plan_id}_next_date"
        self._update_translation_placeholders()

    def _update_translation_placeholders(self) -> None:
        """Update translation placeholders from plan title."""
        account = self.account
        if account and self.plan_id in account.recurring_plans:
            plan = account.recurring_plans[self.plan_id]
            self._attr_translation_placeholders = {"title": plan.title}
        else:
            self._attr_translation_placeholders = {"title": self.plan_id}

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._update_translation_placeholders()
        super()._handle_coordinator_update()

    @property
    def native_value(self) -> date | None:
        """Return the next execution date."""
        account = self.account
        if account is None:
            return None
        plan = account.recurring_plans.get(self.plan_id)
        if plan is None or plan.next_date is None:
            return None
        try:
            parsed = dt_util.parse_datetime(plan.next_date)
            return parsed.date() if parsed else None
        except (ValueError, TypeError):
            return None


class PlanLastExecutedSensor(FinanceSensorBase):
    """Sensor showing the last execution timestamp of a recurring plan.

    One entity is created per recurring plan.

    State
        Timestamp of the last execution (``datetime``), or ``None`` if
        the plan has never been executed.

    Device class
        ``SensorDeviceClass.TIMESTAMP``

    Icon
        ``mdi:calendar-check``

    Translation key
        ``plan_last_executed`` with placeholder ``{title}`` (plan title).
    """

    _attr_icon = "mdi:calendar-check"
    _attr_translation_key = "plan_last_executed"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(
        self, coordinator: FinanceCoordinator, account_id: str, plan_id: str
    ) -> None:
        """Initialize plan last executed sensor."""
        super().__init__(coordinator, account_id)
        self.plan_id = plan_id
        self._attr_unique_id = f"{account_id}_{plan_id}_last_executed"
        self._update_translation_placeholders()

    def _update_translation_placeholders(self) -> None:
        """Update translation placeholders from plan title."""
        account = self.account
        if account and self.plan_id in account.recurring_plans:
            plan = account.recurring_plans[self.plan_id]
            self._attr_translation_placeholders = {"title": plan.title}
        else:
            self._attr_translation_placeholders = {"title": self.plan_id}

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._update_translation_placeholders()
        super()._handle_coordinator_update()

    @property
    def native_value(self) -> datetime | None:
        """Return the last executed time."""
        account = self.account
        if account is None:
            return None
        plan = account.recurring_plans.get(self.plan_id)
        if plan is None or plan.last_executed is None:
            return None
        try:
            return dt_util.parse_datetime(plan.last_executed)
        except (ValueError, TypeError):
            return None
