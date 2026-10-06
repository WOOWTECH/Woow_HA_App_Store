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
from collections import defaultdict
from datetime import datetime
import io
import logging
import uuid
from typing import Any

from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr

from .const import (
    CONF_ACCOUNT_ID,
    CONF_ACCOUNT_NAME,
    CONF_INITIAL_BALANCE,
    DOMAIN,
)
from .coordinator import FinanceCoordinator, get_coordinator_for_account
from .models import RecurringPlan, Transaction

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_store(hass: HomeAssistant):
    """Get the shared finance store from hass.data."""
    domain_data = hass.data.get(DOMAIN, {})
    store = domain_data.get("store")
    if store is not None:
        return store
    raise ServiceValidationError(
        "Finance integration not configured — no store available",
        translation_domain=DOMAIN,
        translation_key="not_configured",
    )


def _valid_amount(value: Any) -> float:
    """Validate that value is a finite number, reject NaN/Infinity."""
    import math

    try:
        fval = float(value)
    except (TypeError, ValueError) as exc:
        raise ServiceValidationError(
            f"Invalid amount: {value!r}",
            translation_domain=DOMAIN,
            translation_key="invalid_amount",
        ) from exc
    if not math.isfinite(fval):
        raise ServiceValidationError(
            f"Amount must be a finite number, got {value!r}",
            translation_domain=DOMAIN,
            translation_key="invalid_amount",
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
        translation_key="account_not_found",
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
            translation_key="account_not_found",
            translation_placeholders={"account_id": account_id},
        )
    return store, account


# ---------------------------------------------------------------------------
# Query handlers — SupportsResponse.ONLY
# ---------------------------------------------------------------------------


async def handle_get_accounts(call: ServiceCall) -> ServiceResponse:
    """Return every registered account (id, name, balance, notes)."""
    hass = call.hass
    store = _get_store(hass)
    await store.async_load()

    accounts = [
        {
            "id": account.id,
            "name": account.name,
            "balance": account.balance,
            "notes": account.notes,
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
            translation_key="account_not_found",
            translation_placeholders={"account_id": account_id},
        )

    return {
        "account": {
            "id": account.id,
            "name": account.name,
            "balance": account.balance,
            "notes": account.notes,
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
            translation_key="account_not_found",
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
            translation_key="account_not_found",
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
                translation_key="account_not_found",
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
            translation_key="transaction_failed",
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
            translation_key="account_not_found",
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
            translation_key="transaction_not_found",
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
            translation_key="account_not_found",
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
            translation_key="transaction_not_found",
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
                translation_key="account_not_found",
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
                translation_key="account_not_found",
                translation_placeholders={"account_id": account_id},
            )
        plan = account.recurring_plans.get(plan_id)
        if plan is None:
            raise ServiceValidationError(
                f"Plan '{plan_id}' not found",
                translation_domain=DOMAIN,
                translation_key="plan_not_found",
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
                translation_key="plan_not_found",
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
                translation_key="account_not_found",
                translation_placeholders={"account_id": account_id},
            )
        if plan_id not in account.recurring_plans:
            raise ServiceValidationError(
                f"Plan '{plan_id}' not found",
                translation_domain=DOMAIN,
                translation_key="plan_not_found",
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
                translation_key="plan_not_found",
                translation_placeholders={"plan_id": plan_id},
            )
        await coordinator.async_remove_recurring_plan(plan_id)

    return {"success": True}


# ---------------------------------------------------------------------------
# Account Management — SupportsResponse.OPTIONAL
# ---------------------------------------------------------------------------


async def handle_add_account(call: ServiceCall) -> ServiceResponse:
    """Create a new financial account via config flow."""
    hass = call.hass
    name = call.data["name"].strip()
    initial_balance = _valid_amount(call.data.get("initial_balance", 0.0))

    if not name:
        raise ServiceValidationError(
            "Account name cannot be empty",
            translation_domain=DOMAIN,
            translation_key="invalid_name",
        )

    # Check for duplicate name (case-insensitive) in existing accounts
    store = _get_store(hass)
    await store.async_load()
    for existing in store.data.accounts.values():
        if existing.name.lower() == name.lower():
            raise ServiceValidationError(
                f"Account with name '{name}' already exists",
                translation_domain=DOMAIN,
                translation_key="duplicate_name",
                translation_placeholders={"name": name},
            )

    try:
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "ws_panel"},
            data={"name": name, "initial_balance": initial_balance},
        )
    except Exception:
        _LOGGER.exception("Failed to create account via config flow")
        raise ServiceValidationError(
            "Failed to create account",
            translation_domain=DOMAIN,
            translation_key="create_failed",
            translation_placeholders={"reason": "config flow error"},
        )

    if result.get("type") != FlowResultType.CREATE_ENTRY:
        reason = result.get("reason", "unknown")
        raise ServiceValidationError(
            f"Failed to create account: {reason}",
            translation_domain=DOMAIN,
            translation_key="create_failed",
            translation_placeholders={"reason": reason},
        )

    entry = result.get("result")
    account_id = entry.data.get(CONF_ACCOUNT_ID, "") if entry else ""
    account_name = entry.data.get(CONF_ACCOUNT_NAME, name) if entry else name

    return {
        "success": True,
        "account_id": account_id,
        "name": account_name,
    }


async def handle_update_account(call: ServiceCall) -> ServiceResponse:
    """Rename or annotate an existing account."""
    hass = call.hass
    account_id = call.data["account_id"]

    store = _get_store(hass)
    await store.async_load()

    account = store.data.get_account(account_id)
    if account is None:
        raise ServiceValidationError(
            f"Account '{account_id}' not found",
            translation_domain=DOMAIN,
            translation_key="account_not_found",
            translation_placeholders={"account_id": account_id},
        )

    if "name" in call.data:
        name = call.data["name"].strip()
        if not name:
            raise ServiceValidationError(
                "Account name cannot be empty",
                translation_domain=DOMAIN,
                translation_key="invalid_name",
            )
        # Check duplicate (case-insensitive, excluding self)
        for existing in store.data.accounts.values():
            if existing.id != account_id and existing.name.lower() == name.lower():
                raise ServiceValidationError(
                    f"Account with name '{name}' already exists",
                    translation_domain=DOMAIN,
                    translation_key="duplicate_name",
                    translation_placeholders={"name": name},
                )
        account.name = name

    if "notes" in call.data:
        account.notes = call.data["notes"]

    await store.async_save()

    # Sync to config entry and device registry if name changed
    if "name" in call.data:
        for entry in hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ACCOUNT_ID) == account_id:
                new_data = dict(entry.data)
                new_data[CONF_ACCOUNT_NAME] = account.name
                hass.config_entries.async_update_entry(
                    entry, title=account.name, data=new_data
                )
                device_reg = dr.async_get(hass)
                device = device_reg.async_get_device(
                    identifiers={(DOMAIN, account_id)}
                )
                if device:
                    device_reg.async_update_device(device.id, name=account.name)
                break

    # Refresh coordinator if available
    coordinator = get_coordinator_for_account(hass, account_id)
    if coordinator:
        await coordinator.async_refresh()

    return {"success": True}


async def handle_delete_account(call: ServiceCall) -> ServiceResponse:
    """Delete an account and all its data."""
    hass = call.hass
    account_id = call.data["account_id"]

    # Find the config entry
    entry_to_remove = None
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.data.get(CONF_ACCOUNT_ID) == account_id:
            entry_to_remove = entry
            break

    if entry_to_remove is None:
        raise ServiceValidationError(
            f"Account '{account_id}' not found",
            translation_domain=DOMAIN,
            translation_key="account_not_found",
            translation_placeholders={"account_id": account_id},
        )

    try:
        await hass.config_entries.async_remove(entry_to_remove.entry_id)
    except Exception:
        _LOGGER.exception(
            "Failed to remove config entry for account %s", account_id
        )
        raise ServiceValidationError(
            f"Failed to delete account '{account_id}'",
            translation_domain=DOMAIN,
            translation_key="delete_failed",
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
            translation_key="account_not_found",
            translation_placeholders={"account_id": account_id},
        )

    await coordinator.async_adjust_balance(new_balance)

    return {"success": True}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

_SERVICE_HANDLERS = {
    # Query — ONLY
    "get_accounts": (handle_get_accounts, SupportsResponse.ONLY),
    "get_account": (handle_get_account, SupportsResponse.ONLY),
    "get_chart_data": (handle_get_chart_data, SupportsResponse.ONLY),
    "export_csv": (handle_export_csv, SupportsResponse.ONLY),
    # Transaction CRUD — OPTIONAL
    "add_transaction": (handle_add_transaction, SupportsResponse.OPTIONAL),
    "update_transaction": (handle_update_transaction, SupportsResponse.OPTIONAL),
    "delete_transaction": (handle_delete_transaction, SupportsResponse.OPTIONAL),
    # Recurring Plans — OPTIONAL
    "add_plan": (handle_add_plan, SupportsResponse.OPTIONAL),
    "update_plan": (handle_update_plan, SupportsResponse.OPTIONAL),
    "delete_plan": (handle_delete_plan, SupportsResponse.OPTIONAL),
    # Account Management — OPTIONAL
    "add_account": (handle_add_account, SupportsResponse.OPTIONAL),
    "update_account": (handle_update_account, SupportsResponse.OPTIONAL),
    "delete_account": (handle_delete_account, SupportsResponse.OPTIONAL),
    "adjust_balance": (handle_adjust_balance, SupportsResponse.OPTIONAL),
}


def async_register_services(hass: HomeAssistant) -> None:
    """Register all ha_finance services."""
    for name, (handler, response_type) in _SERVICE_HANDLERS.items():
        hass.services.async_register(
            DOMAIN,
            name,
            handler,
            supports_response=response_type,
        )
    _LOGGER.debug("Registered %d services for %s", len(_SERVICE_HANDLERS), DOMAIN)


def async_unregister_services(hass: HomeAssistant) -> None:
    """Remove all ha_finance services."""
    for name in _SERVICE_HANDLERS:
        hass.services.async_remove(DOMAIN, name)
    _LOGGER.debug("Unregistered services for %s", DOMAIN)
