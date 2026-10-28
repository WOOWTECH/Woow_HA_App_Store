"""Home Assistant service handlers for ha_finance.

Exposes 14 services that mirror the existing WebSocket API, allowing
automations, scripts, and AI agents to interact with finance records
via ``hass.services.async_call()``.

Query services (get_accounts, get_account, get_chart_data, export_csv) use
``SupportsResponse.ONLY`` — callers must request a response.

Write services use ``SupportsResponse.OPTIONAL`` — callers may
optionally receive a response dict.
"""

from __future__ import annotations

import csv
import io
import logging
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any

import voluptuous as vol
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from ...const import device_id
from ...runtime import get_data
from .area import FinanceArea, generate_account_id
from .const import (
    AREA,
    DOMAIN,
)
from .coordinator import FinanceCoordinator, get_coordinator_for_account
from .models import RecurringPlan, Transaction

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _area(hass: HomeAssistant) -> FinanceArea:
    """Return the finance Area."""
    return get_data(hass).finance


def _get_store(hass: HomeAssistant):
    """Return the shared finance store."""
    return _area(hass).store


def _valid_amount(value: Any) -> float:
    """Validate that value is a finite number, reject NaN/Infinity."""
    import math

    try:
        fval = float(value)
    except (TypeError, ValueError) as exc:
        raise ServiceValidationError(
            f"Invalid amount: {value!r}",
            translation_domain=DOMAIN,
            translation_key="finance.invalid_amount",
        ) from exc
    if not math.isfinite(fval):
        raise ServiceValidationError(
            f"Amount must be a finite number, got {value!r}",
            translation_domain=DOMAIN,
            translation_key="finance.invalid_amount",
        )
    return fval


def _get_coordinator(
    hass: HomeAssistant, account_id: str
) -> FinanceCoordinator:
    """Find a coordinator by account_id, raise on miss."""
    coord = get_coordinator_for_account(hass, account_id)
    if coord is not None:
        return coord
    raise ServiceValidationError(
        f"Account '{account_id}' not found or not loaded",
        translation_domain=DOMAIN,
        translation_key="finance.account_not_found",
        translation_placeholders={"account_id": account_id},
    )


def _get_account_from_store(hass: HomeAssistant, account_id: str):
    """Get an account from the store, raise on miss."""
    store = _get_store(hass)
    account = store.data.get_account(account_id)
    if account is None:
        raise ServiceValidationError(
            f"Account '{account_id}' not found",
            translation_domain=DOMAIN,
            translation_key="finance.account_not_found",
            translation_placeholders={"account_id": account_id},
        )
    return store, account


# ---------------------------------------------------------------------------
# Query handlers — SupportsResponse.ONLY
# ---------------------------------------------------------------------------


async def handle_get_accounts(call: ServiceCall) -> ServiceResponse:
    """Return every registered account (id, name, balance, note)."""
    hass = call.hass
    store = _get_store(hass)
    await store.async_load()

    accounts = [
        {
            "id": account.id,
            "name": account.name,
            "balance": account.balance,
            "note": account.note,
        }
        for account in store.data.accounts.values()
    ]

    return {"accounts": accounts}


async def handle_get_account(call: ServiceCall) -> ServiceResponse:
    """Return full account detail with transactions and recurring plans."""
    hass = call.hass
    account_id = call.data["account_id"]

    store = _get_store(hass)
    await store.async_load()

    account = store.data.get_account(account_id)
    if account is None:
        raise ServiceValidationError(
            f"Account '{account_id}' not found",
            translation_domain=DOMAIN,
            translation_key="finance.account_not_found",
            translation_placeholders={"account_id": account_id},
        )

    return {
        "account": {
            "id": account.id,
            "name": account.name,
            "balance": account.balance,
            "note": account.note,
            "transactions": [tx.to_dict() for tx in account.transactions],
            "recurring_plans": {
                plan_id: plan.to_dict()
                for plan_id, plan in account.recurring_plans.items()
            },
        }
    }


async def handle_get_chart_data(call: ServiceCall) -> ServiceResponse:
    """Return monthly income/expense chart data for an account."""
    hass = call.hass
    account_id = call.data["account_id"]
    months = call.data.get("months", 6)

    store = _get_store(hass)
    await store.async_load()

    account = store.data.get_account(account_id)
    if account is None:
        raise ServiceValidationError(
            f"Account '{account_id}' not found",
            translation_domain=DOMAIN,
            translation_key="finance.account_not_found",
            translation_placeholders={"account_id": account_id},
        )

    # Group transactions by month
    months_data: dict[str, dict[str, float]] = defaultdict(
        lambda: {"income": 0.0, "expenses": 0.0}
    )

    for tx in account.transactions:
        try:
            tx_date = datetime.fromisoformat(tx.timestamp)
            month_key = tx_date.strftime("%Y-%m")

            if tx.amount >= 0:
                months_data[month_key]["income"] += tx.amount
            else:
                months_data[month_key]["expenses"] += abs(tx.amount)
        except (ValueError, TypeError):
            continue

    # Sort by month descending, take N, then reverse to oldest-first
    sorted_months = sorted(months_data.keys(), reverse=True)[:months]
    sorted_months.reverse()

    chart_data = [
        {
            "month": month,
            "income": round(months_data[month]["income"], 2),
            "expenses": round(months_data[month]["expenses"], 2),
        }
        for month in sorted_months
    ]

    return {"data": chart_data}


async def handle_export_csv(call: ServiceCall) -> ServiceResponse:
    """Export all transactions for an account as CSV text."""
    hass = call.hass
    account_id = call.data["account_id"]

    store = _get_store(hass)
    await store.async_load()

    account = store.data.get_account(account_id)
    if account is None:
        raise ServiceValidationError(
            f"Account '{account_id}' not found",
            translation_domain=DOMAIN,
            translation_key="finance.account_not_found",
            translation_placeholders={"account_id": account_id},
        )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["timestamp", "amount", "note", "type", "plan_id"])

    for tx in sorted(account.transactions, key=lambda t: t.timestamp):
        writer.writerow([
            tx.timestamp,
            tx.amount,
            tx.note,
            tx.type,
            tx.plan_id or "",
        ])

    return {
        "csv_content": output.getvalue(),
        "account_name": account.name,
        "transaction_count": len(account.transactions),
    }


# ---------------------------------------------------------------------------
# Transaction CRUD — SupportsResponse.OPTIONAL
# ---------------------------------------------------------------------------


async def handle_add_transaction(call: ServiceCall) -> ServiceResponse:
    """Add a transaction (income/expense) to an account."""
    hass = call.hass
    account_id = call.data["account_id"]
    amount = _valid_amount(call.data["amount"])
    note = call.data.get("note", "")
    transaction_type = call.data.get("transaction_type", "manual")

    coordinator = get_coordinator_for_account(hass, account_id)
    transaction: Transaction | None = None

    if coordinator is None:
        # Fall back to direct store access
        store = _get_store(hass)
        await store.async_load()
        account = store.data.get_account(account_id)
        if account is None:
            raise ServiceValidationError(
                f"Account '{account_id}' not found",
                translation_domain=DOMAIN,
                translation_key="finance.account_not_found",
                translation_placeholders={"account_id": account_id},
            )
        transaction = Transaction.create(
            amount=amount, note=note, transaction_type=transaction_type
        )
        account.add_transaction(transaction)
        await store.async_save()
    else:
        transaction = await coordinator.async_add_transaction(
            amount=amount, note=note, transaction_type=transaction_type
        )

    if transaction is None:
        raise ServiceValidationError(
            "Failed to create transaction",
            translation_domain=DOMAIN,
            translation_key="finance.transaction_failed",
        )

    return {"success": True, "transaction": transaction.to_dict()}


async def handle_update_transaction(call: ServiceCall) -> ServiceResponse:
    """Update an existing transaction's amount and/or note."""
    hass = call.hass
    account_id = call.data["account_id"]
    transaction_id = call.data["transaction_id"]

    store = _get_store(hass)
    await store.async_load()

    account = store.data.get_account(account_id)
    if account is None:
        raise ServiceValidationError(
            f"Account '{account_id}' not found",
            translation_domain=DOMAIN,
            translation_key="finance.account_not_found",
            translation_placeholders={"account_id": account_id},
        )

    # Find the transaction
    transaction = None
    for tx in account.transactions:
        if tx.id == transaction_id:
            transaction = tx
            break

    if transaction is None:
        raise ServiceValidationError(
            f"Transaction '{transaction_id}' not found",
            translation_domain=DOMAIN,
            translation_key="finance.transaction_not_found",
            translation_placeholders={"transaction_id": transaction_id},
        )

    # Update balance if amount changed
    if "amount" in call.data:
        old_amount = transaction.amount
        new_amount = _valid_amount(call.data["amount"])
        account.balance += (new_amount - old_amount)
        transaction.amount = new_amount

    if "note" in call.data:
        transaction.note = call.data["note"]

    await store.async_save()

    # Refresh coordinator if available
    coordinator = get_coordinator_for_account(hass, account_id)
    if coordinator:
        await coordinator.async_refresh()

    return {"success": True}


async def handle_delete_transaction(call: ServiceCall) -> ServiceResponse:
    """Delete a transaction and revert its balance change."""
    hass = call.hass
    account_id = call.data["account_id"]
    transaction_id = call.data["transaction_id"]

    store = _get_store(hass)
    await store.async_load()

    account = store.data.get_account(account_id)
    if account is None:
        raise ServiceValidationError(
            f"Account '{account_id}' not found",
            translation_domain=DOMAIN,
            translation_key="finance.account_not_found",
            translation_placeholders={"account_id": account_id},
        )

    # Find and remove transaction
    transaction = None
    for i, tx in enumerate(account.transactions):
        if tx.id == transaction_id:
            transaction = tx
            account.transactions.pop(i)
            break

    if transaction is None:
        raise ServiceValidationError(
            f"Transaction '{transaction_id}' not found",
            translation_domain=DOMAIN,
            translation_key="finance.transaction_not_found",
            translation_placeholders={"transaction_id": transaction_id},
        )

    # Reverse the balance change
    account.balance -= transaction.amount
    await store.async_save()

    # Refresh coordinator if available
    coordinator = get_coordinator_for_account(hass, account_id)
    if coordinator:
        await coordinator.async_refresh()

    return {"success": True}


# ---------------------------------------------------------------------------
# Recurring Plans — SupportsResponse.OPTIONAL
# ---------------------------------------------------------------------------


async def handle_add_plan(call: ServiceCall) -> ServiceResponse:
    """Create a new recurring plan for an account."""
    hass = call.hass
    account_id = call.data["account_id"]
    title = call.data["title"]
    amount = _valid_amount(call.data["amount"])
    frequency = call.data["frequency"]
    day = call.data["day"]
    month = call.data.get("month", 1)
    active = call.data.get("active", True)

    plan_id = f"plan_{uuid.uuid4().hex[:8]}"
    coordinator = get_coordinator_for_account(hass, account_id)

    if coordinator is None:
        # Fall back to direct store access
        store = _get_store(hass)
        await store.async_load()
        account = store.data.get_account(account_id)
        if account is None:
            raise ServiceValidationError(
                f"Account '{account_id}' not found",
                translation_domain=DOMAIN,
                translation_key="finance.account_not_found",
                translation_placeholders={"account_id": account_id},
            )
        plan = RecurringPlan(
            id=plan_id,
            title=title,
            amount=amount,
            frequency=frequency,
            day=day,
            month=month,
            active=active,
        )
        account.add_recurring_plan(plan)
        await store.async_save()
    else:
        await coordinator.async_add_recurring_plan(
            plan_id=plan_id,
            title=title,
            amount=amount,
            frequency=frequency,
            day=day,
            month=month,
            active=active,
        )

    return {"success": True, "plan_id": plan_id}


async def handle_update_plan(call: ServiceCall) -> ServiceResponse:
    """Update an existing recurring plan."""
    hass = call.hass
    account_id = call.data["account_id"]
    plan_id = call.data["plan_id"]

    # Extract update fields
    update_fields: dict[str, Any] = {}
    for field in ("title", "amount", "frequency", "day", "month", "active"):
        if field in call.data:
            update_fields[field] = call.data[field]
    if "amount" in update_fields:
        update_fields["amount"] = _valid_amount(update_fields["amount"])

    coordinator = get_coordinator_for_account(hass, account_id)

    if coordinator is None:
        # Fall back to direct store access
        store = _get_store(hass)
        await store.async_load()
        account = store.data.get_account(account_id)
        if account is None:
            raise ServiceValidationError(
                f"Account '{account_id}' not found",
                translation_domain=DOMAIN,
                translation_key="finance.account_not_found",
                translation_placeholders={"account_id": account_id},
            )
        plan = account.recurring_plans.get(plan_id)
        if plan is None:
            raise ServiceValidationError(
                f"Plan '{plan_id}' not found",
                translation_domain=DOMAIN,
                translation_key="finance.plan_not_found",
                translation_placeholders={"plan_id": plan_id},
            )
        for key, value in update_fields.items():
            setattr(plan, key, value)
        await store.async_save()
    else:
        updated = await coordinator.async_update_recurring_plan(
            plan_id, **update_fields
        )
        if not updated:
            raise ServiceValidationError(
                f"Plan '{plan_id}' not found",
                translation_domain=DOMAIN,
                translation_key="finance.plan_not_found",
                translation_placeholders={"plan_id": plan_id},
            )

    return {"success": True}


async def handle_delete_plan(call: ServiceCall) -> ServiceResponse:
    """Delete a recurring plan."""
    hass = call.hass
    account_id = call.data["account_id"]
    plan_id = call.data["plan_id"]

    coordinator = get_coordinator_for_account(hass, account_id)

    if coordinator is None:
        # Fall back to direct store access
        store = _get_store(hass)
        await store.async_load()
        account = store.data.get_account(account_id)
        if account is None:
            raise ServiceValidationError(
                f"Account '{account_id}' not found",
                translation_domain=DOMAIN,
                translation_key="finance.account_not_found",
                translation_placeholders={"account_id": account_id},
            )
        if plan_id not in account.recurring_plans:
            raise ServiceValidationError(
                f"Plan '{plan_id}' not found",
                translation_domain=DOMAIN,
                translation_key="finance.plan_not_found",
                translation_placeholders={"plan_id": plan_id},
            )
        account.remove_recurring_plan(plan_id)
        await store.async_save()
    else:
        account = coordinator.account
        if account is None or plan_id not in account.recurring_plans:
            raise ServiceValidationError(
                f"Plan '{plan_id}' not found",
                translation_domain=DOMAIN,
                translation_key="finance.plan_not_found",
                translation_placeholders={"plan_id": plan_id},
            )
        await coordinator.async_remove_recurring_plan(plan_id)

    return {"success": True}


# ---------------------------------------------------------------------------
# Account Management — SupportsResponse.OPTIONAL
# ---------------------------------------------------------------------------


async def handle_add_account(call: ServiceCall) -> ServiceResponse:
    """Create an Account.

    Used to start a config flow and wait for the entry; an Account is a store
    record now (ADR-0001).
    """
    hass = call.hass
    name = call.data["name"].strip()
    initial_balance = _valid_amount(call.data.get("initial_balance", 0.0))

    if not name:
        raise ServiceValidationError(
            "Account name cannot be empty",
            translation_domain=DOMAIN,
            translation_key="finance.invalid_name",
        )

    area = _area(hass)
    for existing in area.store.data.accounts.values():
        if existing.name.lower() == name.lower():
            raise ServiceValidationError(
                f"Account with name '{name}' already exists",
                translation_domain=DOMAIN,
                translation_key="finance.duplicate_name",
                translation_placeholders={"name": name},
            )

    account_id = generate_account_id(name)
    if area.get(account_id) is not None:
        raise ServiceValidationError(
            f"Account id '{account_id}' already exists",
            translation_domain=DOMAIN,
            translation_key="finance.duplicate_name",
            translation_placeholders={"name": name},
        )

    await area.async_add_account(account_id, name, initial_balance)
    return {"success": True, "account_id": account_id, "name": name}


async def handle_update_account(call: ServiceCall) -> ServiceResponse:
    """Rename or annotate an existing account."""
    hass = call.hass
    account_id = call.data["account_id"]

    area = _area(hass)
    account = area.store.data.get_account(account_id)
    if account is None:
        raise ServiceValidationError(
            f"Account '{account_id}' not found",
            translation_domain=DOMAIN,
            translation_key="finance.account_not_found",
            translation_placeholders={"account_id": account_id},
        )

    if "name" in call.data:
        name = call.data["name"].strip()
        if not name:
            raise ServiceValidationError(
                "Account name cannot be empty",
                translation_domain=DOMAIN,
                translation_key="finance.invalid_name",
            )
        for existing in area.store.data.accounts.values():
            if existing.id != account_id and existing.name.lower() == name.lower():
                raise ServiceValidationError(
                    f"Account with name '{name}' already exists",
                    translation_domain=DOMAIN,
                    translation_key="finance.duplicate_name",
                    translation_placeholders={"name": name},
                )
        account.name = name

        device_reg = dr.async_get(hass)
        device = device_reg.async_get_device(
            identifiers={(DOMAIN, device_id(AREA, account_id))}
        )
        if device:
            device_reg.async_update_device(device.id, name=name)

    if "note" in call.data:
        account.note = call.data["note"]

    await area.store.async_save()

    coordinator = area.get(account_id)
    if coordinator is not None:
        await coordinator.async_refresh()

    return {"success": True}


async def handle_delete_account(call: ServiceCall) -> ServiceResponse:
    """Delete an Account and everything recorded against it."""
    hass = call.hass
    account_id = call.data["account_id"]

    if not await _area(hass).async_remove_account(account_id):
        raise ServiceValidationError(
            f"Account '{account_id}' not found",
            translation_domain=DOMAIN,
            translation_key="finance.account_not_found",
            translation_placeholders={"account_id": account_id},
        )

    return {"success": True}


async def handle_adjust_balance(call: ServiceCall) -> ServiceResponse:
    """Set the absolute balance for an account."""
    hass = call.hass
    account_id = call.data["account_id"]
    new_balance = _valid_amount(call.data["new_balance"])

    coordinator = get_coordinator_for_account(hass, account_id)
    if coordinator is None:
        raise ServiceValidationError(
            f"Account '{account_id}' not found or not loaded",
            translation_domain=DOMAIN,
            translation_key="finance.account_not_found",
            translation_placeholders={"account_id": account_id},
        )

    await coordinator.async_adjust_balance(new_balance)

    return {"success": True}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

# Field names, requiredness and types mirror this Area's WebSocket commands;
# ``services.yaml`` is the reference where no command covers the operation.
# What those commands also check and this deliberately does not is the value
# domain — ``vol.In`` on ``frequency``, ``vol.Range`` on ``day`` and
# ``month``. Rejecting a *value* the service accepts today is a different
# change from rejecting a *field* it should never have accepted, which is all
# issue #44 asked for; the amount fields still reach ``_valid_amount``, which
# reports NaN and Infinity in the caller's language.
#
# No optional field carries a ``default=`` either. Handlers read absence with
# ``"field" in call.data`` and treat it as "leave unchanged", so a
# default would turn every omitted field into an explicit overwrite — on the
# update verbs that silently rewrites data the caller never mentioned.
SERVICE_HANDLERS = {
    # Query — ONLY
    "get_accounts": (
        handle_get_accounts,
        SupportsResponse.ONLY,
        vol.Schema({}),
    ),
    "get_account": (
        handle_get_account,
        SupportsResponse.ONLY,
        vol.Schema({vol.Required("account_id"): cv.string}),
    ),
    "get_chart_data": (
        handle_get_chart_data,
        SupportsResponse.ONLY,
        vol.Schema(
            {
                vol.Required("account_id"): cv.string,
                vol.Optional("months"): vol.Coerce(int),
            }
        ),
    ),
    "export_csv": (
        handle_export_csv,
        SupportsResponse.ONLY,
        vol.Schema({vol.Required("account_id"): cv.string}),
    ),
    # Transaction CRUD — OPTIONAL
    "add_transaction": (
        handle_add_transaction,
        SupportsResponse.OPTIONAL,
        vol.Schema(
            {
                vol.Required("account_id"): cv.string,
                vol.Required("amount"): vol.Coerce(float),
                vol.Optional("note"): cv.string,
                vol.Optional("transaction_type"): cv.string,
            }
        ),
    ),
    "update_transaction": (
        handle_update_transaction,
        SupportsResponse.OPTIONAL,
        vol.Schema(
            {
                vol.Required("account_id"): cv.string,
                vol.Required("transaction_id"): cv.string,
                vol.Optional("amount"): vol.Coerce(float),
                vol.Optional("note"): cv.string,
            }
        ),
    ),
    "delete_transaction": (
        handle_delete_transaction,
        SupportsResponse.OPTIONAL,
        vol.Schema(
            {
                vol.Required("account_id"): cv.string,
                vol.Required("transaction_id"): cv.string,
            }
        ),
    ),
    # Recurring Plans — OPTIONAL
    "add_plan": (
        handle_add_plan,
        SupportsResponse.OPTIONAL,
        vol.Schema(
            {
                vol.Required("account_id"): cv.string,
                vol.Required("title"): cv.string,
                vol.Required("amount"): vol.Coerce(float),
                vol.Required("frequency"): cv.string,
                vol.Required("day"): vol.Coerce(int),
                vol.Optional("month"): vol.Coerce(int),
                vol.Optional("active"): cv.boolean,
            }
        ),
    ),
    "update_plan": (
        handle_update_plan,
        SupportsResponse.OPTIONAL,
        vol.Schema(
            {
                vol.Required("account_id"): cv.string,
                vol.Required("plan_id"): cv.string,
                vol.Optional("title"): cv.string,
                vol.Optional("amount"): vol.Coerce(float),
                vol.Optional("frequency"): cv.string,
                vol.Optional("day"): vol.Coerce(int),
                vol.Optional("month"): vol.Coerce(int),
                vol.Optional("active"): cv.boolean,
            }
        ),
    ),
    "delete_plan": (
        handle_delete_plan,
        SupportsResponse.OPTIONAL,
        vol.Schema(
            {
                vol.Required("account_id"): cv.string,
                vol.Required("plan_id"): cv.string,
            }
        ),
    ),
    # Account Management — OPTIONAL
    "add_account": (
        handle_add_account,
        SupportsResponse.OPTIONAL,
        vol.Schema(
            {
                vol.Required("name"): cv.string,
                vol.Optional("initial_balance"): vol.Coerce(float),
            }
        ),
    ),
    "update_account": (
        handle_update_account,
        SupportsResponse.OPTIONAL,
        vol.Schema(
            {
                vol.Required("account_id"): cv.string,
                vol.Optional("name"): cv.string,
                vol.Optional("note"): cv.string,
            }
        ),
    ),
    "delete_account": (
        handle_delete_account,
        SupportsResponse.OPTIONAL,
        vol.Schema({vol.Required("account_id"): cv.string}),
    ),
    "adjust_balance": (
        handle_adjust_balance,
        SupportsResponse.OPTIONAL,
        vol.Schema(
            {
                vol.Required("account_id"): cv.string,
                vol.Required("new_balance"): vol.Coerce(float),
            }
        ),
    ),
}
