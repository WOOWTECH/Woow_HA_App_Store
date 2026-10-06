"""Storage management for Ha Finance Record integration."""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from homeassistant.helpers.storage import Store

from .const import STORAGE_KEY, STORAGE_VERSION
from .models import FinanceData

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class FinanceStore:
    """Class to manage finance data storage.

    A single instance should be created per integration setup and stored
    in hass.data[DOMAIN]["store"] to be shared across all config entries.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the store."""
        self._hass = hass
        self._store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._data: FinanceData | None = None
        self._data_lock = asyncio.Lock()

    @property
    def data(self) -> FinanceData:
        """Get the current data."""
        if self._data is None:
            self._data = FinanceData()
        return self._data

    async def async_load(self) -> FinanceData:
        """Load data from storage."""
        async with self._data_lock:
            if self._data is not None:
                return self._data
            stored_data = await self._store.async_load()
            if stored_data is None:
                self._data = FinanceData()
            else:
                self._data = FinanceData.from_dict(stored_data)
            _LOGGER.debug("Loaded finance data: %s accounts", len(self._data.accounts))
            return self._data

    async def async_save(self) -> None:
        """Save data to storage."""
        async with self._data_lock:
            if self._data is not None:
                await self._store.async_save(self._data.to_dict())
                _LOGGER.debug("Saved finance data")

    async def async_remove(self) -> None:
        """Remove all stored data."""
        async with self._data_lock:
            await self._store.async_remove()
            self._data = FinanceData()
            _LOGGER.debug("Removed all finance data")
