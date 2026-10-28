"""Data models for Ha Finance Record integration."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from homeassistant.util import dt as dt_util

from .const import (
    FREQUENCY_MONTHLY,
    TRANSACTION_MANUAL,
)


@dataclass
class Transaction:
    """Represents a financial transaction."""

    id: str
    amount: float
    note: str
    timestamp: str
    type: str  # manual, recurring, adjustment
    plan_id: str | None = None

    @classmethod
    def create(
        cls,
        amount: float,
        note: str,
        transaction_type: str = TRANSACTION_MANUAL,
        plan_id: str | None = None,
    ) -> Transaction:
        """Create a new transaction with auto-generated ID and timestamp."""
        return cls(
            id=f"tx_{uuid.uuid4().hex[:8]}",
            amount=amount,
            note=note,
            timestamp=dt_util.utcnow().isoformat(),
            type=transaction_type,
            plan_id=plan_id,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "id": self.id,
            "amount": self.amount,
            "note": self.note,
            "timestamp": self.timestamp,
            "type": self.type,
            "plan_id": self.plan_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Transaction:
        """Create from dictionary."""
        return cls(
            id=data["id"],
            amount=data["amount"],
            note=data["note"],
            timestamp=data["timestamp"],
            type=data["type"],
            plan_id=data.get("plan_id"),
        )


@dataclass
class RecurringPlan:
    """Represents a recurring financial plan."""

    id: str
    title: str
    amount: float
    frequency: str  # daily, weekly, monthly, yearly
    day: int
    month: int = 1  # For yearly frequency (1-12)
    active: bool = True
    last_executed: str | None = None
    next_date: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "title": self.title,
            "amount": self.amount,
            "frequency": self.frequency,
            "day": self.day,
            "month": self.month,
            "active": self.active,
            "last_executed": self.last_executed,
            "next_date": self.next_date,
        }

    @classmethod
    def from_dict(cls, plan_id: str, data: dict[str, Any]) -> RecurringPlan:
        """Create from dictionary."""
        return cls(
            id=plan_id,
            title=data["title"],
            amount=data["amount"],
            frequency=data.get("frequency", FREQUENCY_MONTHLY),
            day=data.get("day", 1),
            month=data.get("month", 1),
            active=data.get("active", True),
            last_executed=data.get("last_executed"),
            next_date=data.get("next_date"),
        )


@dataclass
class Account:
    """Represents a financial account."""

    id: str
    name: str
    balance: float = 0.0
    note: str = ""
    transactions: list[Transaction] = field(default_factory=list)
    recurring_plans: dict[str, RecurringPlan] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "name": self.name,
            "balance": self.balance,
            "note": self.note,
            "transactions": [tx.to_dict() for tx in self.transactions],
            "recurring_plans": {
                plan_id: plan.to_dict()
                for plan_id, plan in self.recurring_plans.items()
            },
        }

    @classmethod
    def from_dict(cls, account_id: str, data: dict[str, Any]) -> Account:
        """Create from dictionary.

        ``note`` was spelled ``notes`` before ADR-0002. A store written then
        still loads, and heals on its next save.
        """
        transactions = [
            Transaction.from_dict(tx_data)
            for tx_data in data.get("transactions", [])
        ]
        recurring_plans = {
            plan_id: RecurringPlan.from_dict(plan_id, plan_data)
            for plan_id, plan_data in data.get("recurring_plans", {}).items()
        }
        return cls(
            id=account_id,
            name=data["name"],
            balance=data.get("balance", 0.0),
            note=data.get("note", data.get("notes", "")),
            transactions=transactions,
            recurring_plans=recurring_plans,
        )

    @property
    def last_transaction(self) -> Transaction | None:
        """Get the most recent transaction."""
        if not self.transactions:
            return None
        return self.transactions[-1]

    def add_transaction(self, transaction: Transaction) -> None:
        """Add a transaction and update balance.

        Transactions are kept permanently; nothing is ever trimmed.
        """
        self.balance += transaction.amount
        self.transactions.append(transaction)

    def add_recurring_plan(self, plan: RecurringPlan) -> None:
        """Add a recurring plan."""
        self.recurring_plans[plan.id] = plan

    def remove_recurring_plan(self, plan_id: str) -> None:
        """Remove a recurring plan."""
        if plan_id in self.recurring_plans:
            del self.recurring_plans[plan_id]


@dataclass
class FinanceData:
    """Root data structure for all finance data."""

    accounts: dict[str, Account] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "accounts": {
                account_id: account.to_dict()
                for account_id, account in self.accounts.items()
            }
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FinanceData:
        """Create from dictionary."""
        accounts = {
            account_id: Account.from_dict(account_id, account_data)
            for account_id, account_data in data.get("accounts", {}).items()
        }
        return cls(accounts=accounts)

    def get_account(self, account_id: str) -> Account | None:
        """Get an account by ID."""
        return self.accounts.get(account_id)

    def add_account(self, account: Account) -> None:
        """Add an account."""
        self.accounts[account.id] = account

    def remove_account(self, account_id: str) -> None:
        """Remove an account."""
        if account_id in self.accounts:
            del self.accounts[account_id]
