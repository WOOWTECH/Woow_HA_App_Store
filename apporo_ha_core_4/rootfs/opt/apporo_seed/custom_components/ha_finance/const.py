"""Constants for Ha Finance Record integration."""
from typing import Final

DOMAIN: Final = "ha_finance"
STORAGE_KEY: Final = "ha_finance"
STORAGE_VERSION: Final = 1

# Config keys
CONF_ACCOUNT_NAME: Final = "account_name"
CONF_ACCOUNT_ID: Final = "account_id"
CONF_INITIAL_BALANCE: Final = "initial_balance"

# Frequency options
FREQUENCY_DAILY: Final = "daily"
FREQUENCY_WEEKLY: Final = "weekly"
FREQUENCY_MONTHLY: Final = "monthly"
FREQUENCY_YEARLY: Final = "yearly"

FREQUENCY_OPTIONS: Final = [
    FREQUENCY_DAILY,
    FREQUENCY_WEEKLY,
    FREQUENCY_MONTHLY,
    FREQUENCY_YEARLY,
]

# Transaction types
TRANSACTION_MANUAL: Final = "manual"
TRANSACTION_RECURRING: Final = "recurring"
TRANSACTION_ADJUSTMENT: Final = "adjustment"

# Events
EVENT_TRANSACTION_ADDED: Final = "ha_finance_transaction_added"
EVENT_RECURRING_EXECUTED: Final = "ha_finance_recurring_executed"
EVENT_BALANCE_ADJUSTED: Final = "ha_finance_balance_adjusted"
EVENT_LOW_BALANCE: Final = "ha_finance_low_balance"

# Defaults
DEFAULT_BALANCE: Final = 0.0
DEFAULT_LOW_BALANCE_THRESHOLD: Final = 1000.0

# Config keys for account settings
CONF_LOW_BALANCE_THRESHOLD: Final = "low_balance_threshold"
CONF_CURRENCY: Final = "currency"
DEFAULT_CURRENCY: Final = "NTD"

# Recurring plan month (for yearly)
CONF_PLAN_MONTH: Final = "plan_month"
