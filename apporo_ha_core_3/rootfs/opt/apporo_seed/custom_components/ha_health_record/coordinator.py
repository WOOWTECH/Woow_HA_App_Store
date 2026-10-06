"""Data coordinator for Ha Health Record integration."""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_MEMBER_ID,
    CONF_MEMBER_NAME,
    CONF_RECORD_NAME,
    CONF_RECORD_SETS,
    CONF_RECORD_TYPE,
    CONF_RECORD_UNIT,
    DOMAIN,
    STORAGE_KEY,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)

SAVE_DELAY = 1  # seconds -- batches rapid operations into a single write


def signal_record_updated(member_id: str, type_id: str) -> str:
    """Return signal name for record update."""
    return f"{DOMAIN}_{member_id}_{type_id}_updated"


@dataclass
class Record:
    """Represents a single health record entry."""

    value: float | None = None
    note: str = ""
    timestamp: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "value": self.value,
            "note": self.note,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Record:
        """Create from dictionary.

        Accepts both ``value`` and legacy ``amount`` keys for backward
        compatibility during migration.
        """
        timestamp = None
        if data.get("timestamp"):
            timestamp = dt_util.parse_datetime(data["timestamp"])
        value = data.get("value") if data.get("value") is not None else data.get("amount")
        return cls(
            value=value,
            note=data.get("note", ""),
            timestamp=timestamp,
        )


@dataclass
class RecordSet:
    """Represents a record set configuration (one type of measurement)."""

    type_id: str
    name: str
    unit: str
    default_value: float = 0
    default_value_mode: str = "fixed"  # "fixed" or "last_value"
    current_value: float | None = None
    current_note: str = ""
    last_record: Record = field(default_factory=Record)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "current_value": self.current_value,
            "current_note": self.current_note,
            "last_record": self.last_record.to_dict(),
        }

    def load_from_dict(self, data: dict[str, Any]) -> None:
        """Load state from dictionary.

        Accepts both ``current_value`` and legacy ``current_amount`` keys.
        """
        self.current_value = (
            data.get("current_value")
            if data.get("current_value") is not None
            else data.get("current_amount")
        )
        self.current_note = data.get("current_note", "")
        if data.get("last_record"):
            self.last_record = Record.from_dict(data["last_record"])


class HealthRecordCoordinator:
    """Coordinator for managing health record data."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        self.hass = hass
        self.entry = entry

        # Records history storage (unified)
        self.records: list[dict[str, Any]] = []

        # Member info
        self.member_id: str = entry.data[CONF_MEMBER_ID]
        self.member_name: str = entry.data[CONF_MEMBER_NAME]

        # Storage - unique per member
        self._store: Store[dict[str, Any]] = Store(
            hass,
            STORAGE_VERSION,
            f"{STORAGE_KEY}_{self.member_id}",
            atomic_writes=True,
        )

        # Record sets (unified)
        self.record_sets: dict[str, RecordSet] = {}

        record_sets_config = entry.options.get(CONF_RECORD_SETS, [])
        if not record_sets_config:
            # Fall back to old v1 format in entry.options
            for act in entry.options.get("activity_sets", []):
                record_sets_config.append({
                    CONF_RECORD_TYPE: act.get("activity_type", ""),
                    CONF_RECORD_NAME: act.get("activity_name", ""),
                    CONF_RECORD_UNIT: act.get("activity_unit", ""),
                })
            for grw in entry.options.get("growth_sets", []):
                record_sets_config.append({
                    CONF_RECORD_TYPE: grw.get("growth_type", ""),
                    CONF_RECORD_NAME: grw.get("growth_name", ""),
                    CONF_RECORD_UNIT: grw.get("growth_unit", ""),
                })

        for rs_data in record_sets_config:
            type_id = rs_data[CONF_RECORD_TYPE]
            self.record_sets[type_id] = RecordSet(
                type_id=type_id,
                name=rs_data[CONF_RECORD_NAME],
                unit=rs_data[CONF_RECORD_UNIT],
                default_value=rs_data.get("default_value", 0),
                default_value_mode=rs_data.get("default_value_mode", "fixed"),
            )

    async def async_load(self) -> None:
        """Load data from storage."""
        data = await self._store.async_load()
        if data is None:
            _LOGGER.debug("No stored data for member %s", self.member_id)
            return

        # Detect v1 format and migrate
        if "activity_sets" in data or "growth_sets" in data:
            _LOGGER.info(
                "Detected v1 storage format for member %s, migrating to v2",
                self.member_id,
            )
            data = self._migrate_v1_to_v2(data)

        # Load record set states
        record_sets_data = data.get("record_sets", {})
        for type_id, record_set in self.record_sets.items():
            if type_id in record_sets_data:
                record_set.load_from_dict(record_sets_data[type_id])

        # Load records history
        self.records = data.get("records", [])

        _LOGGER.debug(
            "Loaded health record data for member %s: %d record sets, %d records",
            self.member_id,
            len(self.record_sets),
            len(self.records),
        )

    @staticmethod
    def _migrate_v1_to_v2(data: dict[str, Any]) -> dict[str, Any]:
        """Migrate v1 storage format to v2.

        v1 had separate activity_sets/growth_sets and activity_records/growth_records.
        v2 unifies them into record_sets and records.
        """
        migrated_record_sets: dict[str, Any] = {}
        migrated_records: list[dict[str, Any]] = []

        # Migrate activity_sets state
        for type_id, aset_data in data.get("activity_sets", {}).items():
            migrated_record_sets[type_id] = {
                "current_value": aset_data.get("current_amount"),
                "current_note": aset_data.get("current_note", ""),
                "last_record": {},
            }
            if aset_data.get("last_record"):
                lr = aset_data["last_record"]
                migrated_record_sets[type_id]["last_record"] = {
                    "value": lr.get("amount"),
                    "note": lr.get("note", ""),
                    "timestamp": lr.get("timestamp"),
                }

        # Migrate growth_sets state
        for type_id, gset_data in data.get("growth_sets", {}).items():
            migrated_record_sets[type_id] = {
                "current_value": gset_data.get("current_value"),
                "current_note": gset_data.get("current_note", ""),
                "last_record": {},
            }
            if gset_data.get("last_record"):
                lr = gset_data["last_record"]
                migrated_record_sets[type_id]["last_record"] = {
                    "value": lr.get("value"),
                    "note": lr.get("note", ""),
                    "timestamp": lr.get("timestamp"),
                }

        # Migrate activity_records
        for rec in data.get("activity_records", []):
            migrated_records.append({
                "id": rec.get("id", uuid.uuid4().hex),
                "record_type": rec.get("activity_type", ""),
                "record_name": rec.get("activity_name", ""),
                "value": rec.get("amount"),
                "unit": rec.get("unit", ""),
                "note": rec.get("note", ""),
                "timestamp": rec.get("timestamp", ""),
            })

        # Migrate growth_records
        for rec in data.get("growth_records", []):
            migrated_records.append({
                "id": rec.get("id", uuid.uuid4().hex),
                "record_type": rec.get("growth_type", ""),
                "record_name": rec.get("growth_name", ""),
                "value": rec.get("value"),
                "unit": rec.get("unit", ""),
                "note": rec.get("note", ""),
                "timestamp": rec.get("timestamp", ""),
            })

        # Sort merged records by timestamp
        migrated_records.sort(key=lambda r: r.get("timestamp", ""))

        return {
            "record_sets": migrated_record_sets,
            "records": migrated_records,
        }

    @callback
    def _async_schedule_save(self) -> None:
        """Schedule a delayed save to storage."""
        self._store.async_delay_save(self._data_to_save, SAVE_DELAY)

    @callback
    def _data_to_save(self) -> dict[str, Any]:
        """Return data to save to storage."""
        return {
            "record_sets": {
                type_id: record_set.to_dict()
                for type_id, record_set in self.record_sets.items()
            },
            "records": self.records,
        }

    def get_device_info(self) -> DeviceInfo:
        """Return device info for this member."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.member_id)},
            name=self.member_name,
            manufacturer="Ha Health Record",
            model="Family Member",
        )

    # ── Helpers ──────────────────────────────────────────────────────

    def _recalculate_current_value(self, type_id: str) -> None:
        """Recalculate current_value for a record set from the latest record."""
        if type_id not in self.record_sets:
            return

        # Find all records for this type, pick the most recent by timestamp
        latest_value: float | None = None
        latest_ts: datetime | None = None
        for record in self.records:
            if record.get("record_type") != type_id:
                continue
            try:
                record_time = dt_util.parse_datetime(record["timestamp"])
            except (ValueError, TypeError):
                continue
            if record_time is None:
                continue
            # Ensure timezone-aware for safe comparison
            record_time = dt_util.as_utc(record_time)
            if latest_ts is None or record_time > latest_ts:
                latest_ts = record_time
                latest_value = record.get("value")

        self.record_sets[type_id].current_value = latest_value

    # ── Unified CRUD methods ────────────────────────────────────────

    def set_record_value(self, type_id: str, value: float | None) -> None:
        """Set the current value for a record set."""
        if type_id in self.record_sets:
            self.record_sets[type_id].current_value = value

    def set_record_note(self, type_id: str, note: str) -> None:
        """Set the current note for a record set."""
        if type_id in self.record_sets:
            self.record_sets[type_id].current_note = note

    @callback
    def log_record(self, type_id: str, timestamp: datetime | None = None) -> Record | None:
        """Log a record and return it."""
        if type_id not in self.record_sets:
            return None

        record_set = self.record_sets[type_id]
        record_timestamp = timestamp or dt_util.now()
        record = Record(
            value=record_set.current_value,
            note=record_set.current_note,
            timestamp=record_timestamp,
        )
        record_set.last_record = record

        # Add to records history
        self.records.append({
            "id": uuid.uuid4().hex,
            "record_type": type_id,
            "record_name": record_set.name,
            "value": record_set.current_value,
            "unit": record_set.unit,
            "note": record_set.current_note,
            "timestamp": record_timestamp.isoformat(),
        })

        # Schedule save
        self._async_schedule_save()

        # Notify sensor to update
        async_dispatcher_send(
            self.hass,
            signal_record_updated(self.member_id, type_id),
        )

        return record

    def get_record_set(self, type_id: str) -> RecordSet | None:
        """Get a record set by type."""
        return self.record_sets.get(type_id)

    def get_records_in_range(self, start_time: datetime, end_time: datetime) -> list[dict[str, Any]]:
        """Get all records in a time range."""
        results: list[dict[str, Any]] = []

        for record in self.records:
            try:
                record_time = dt_util.parse_datetime(record["timestamp"])
                if record_time is None:
                    continue
                # Ensure timezone-aware for safe comparison
                record_time = dt_util.as_utc(record_time)
                if start_time <= record_time <= end_time:
                    type_id = record["record_type"]
                    rs = self.record_sets.get(type_id)
                    entry = {
                        "member_id": self.member_id,
                        "member_name": self.member_name,
                        "record_type": type_id,
                        "record_name": rs.name if rs else record.get("record_name", type_id),
                        "value": record["value"],
                        "unit": rs.unit if rs else record.get("unit", ""),
                        "note": record.get("note", ""),
                        "timestamp": record["timestamp"],
                    }
                    if "id" in record:
                        entry["id"] = record["id"]
                    results.append(entry)
            except (ValueError, TypeError):
                continue

        return results

    def delete_record(
        self,
        type_id: str,
        timestamp: str,
        record_id: str | None = None,
    ) -> bool:
        """Delete a record by UUID or type+timestamp fallback."""
        for i, record in enumerate(self.records):
            # Match by UUID first (preferred), fall back to type+timestamp
            if record_id and record.get("id") == record_id:
                del self.records[i]
                self._recalculate_current_value(type_id)
                self._async_schedule_save()
                return True
            if not record_id and record["record_type"] == type_id and record["timestamp"] == timestamp:
                del self.records[i]
                self._recalculate_current_value(type_id)
                self._async_schedule_save()
                return True
        return False

    def update_record(
        self,
        type_id: str,
        timestamp: str,
        value: float | None = None,
        note: str | None = None,
        new_timestamp: str | None = None,
        record_id: str | None = None,
    ) -> bool:
        """Update a record by UUID or type+timestamp fallback."""
        for record in self.records:
            matched = False
            if record_id and record.get("id") == record_id:
                matched = True
            elif not record_id and record["record_type"] == type_id and record["timestamp"] == timestamp:
                matched = True

            if matched:
                if value is not None:
                    record["value"] = value
                if note is not None:
                    record["note"] = note
                if new_timestamp is not None:
                    record["timestamp"] = new_timestamp
                self._recalculate_current_value(type_id)
                self._async_schedule_save()
                return True
        return False
