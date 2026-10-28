"""Data coordinator for Ha Health Record integration."""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

from ...const import device_id
from .const import AREA, DOMAIN

if TYPE_CHECKING:
    from .area import HealthArea

_LOGGER = logging.getLogger(__name__)


def signal_record_updated(member_id: str, type_id: str) -> str:
    """Return signal name for record update."""
    return f"{DOMAIN}_{AREA}_{member_id}_{type_id}_updated"


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
        """Convert to dictionary for storage.

        Carries the definition as well as the state. Before the merge the
        definition lived in the config entry's options and only the state was
        stored; a Member is no longer a config entry, so both belong here.
        """
        return {
            "type_id": self.type_id,
            "name": self.name,
            "unit": self.unit,
            "default_value": self.default_value,
            "default_value_mode": self.default_value_mode,
            "current_value": self.current_value,
            "current_note": self.current_note,
            "last_record": self.last_record.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RecordSet:
        """Build a record set, definition and state together, from storage."""
        record_set = cls(
            type_id=data["type_id"],
            name=data.get("name", data["type_id"]),
            unit=data.get("unit", ""),
            default_value=data.get("default_value", 0),
            default_value_mode=data.get("default_value_mode", "fixed"),
        )
        record_set.load_from_dict(data)
        return record_set

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

    def __init__(
        self,
        hass: HomeAssistant,
        area: HealthArea,
        member_id: str,
        member_name: str,
        note: str = "",
    ) -> None:
        """Initialize the coordinator for one Member.

        The coordinator no longer owns a Store. A Member used to be a config
        entry with a store file of its own; it is now a record inside the
        health Area's single store, and persistence is the Area's job.
        """
        self.hass = hass
        self.area = area

        # Records history storage (unified)
        self.records: list[dict[str, Any]] = []

        # Member info
        self.member_id: str = member_id
        self.member_name: str = member_name
        self.note: str = note

        # Record sets (unified)
        self.record_sets: dict[str, RecordSet] = {}

    def load_from_dict(self, data: dict[str, Any]) -> None:
        """Populate this Member from its slice of the Area store."""
        self.member_name = data.get("name", self.member_name)
        self.note = data.get("note", self.note)
        self.record_sets = {
            rs_data["type_id"]: RecordSet.from_dict(rs_data)
            for rs_data in data.get("record_sets", [])
        }
        self.records = data.get("records", [])

        _LOGGER.debug(
            "Loaded health data for member %s: %d record sets, %d records",
            self.member_id,
            len(self.record_sets),
            len(self.records),
        )

    @callback
    def _async_schedule_save(self) -> None:
        """Ask the Area to persist; the store covers every Member at once."""
        self.area.async_schedule_save()

    @callback
    def to_dict(self) -> dict[str, Any]:
        """Return this Member's slice of the Area store."""
        return {
            "name": self.member_name,
            "note": self.note,
            "record_sets": [
                record_set.to_dict() for record_set in self.record_sets.values()
            ],
            "records": self.records,
        }

    def get_device_info(self) -> DeviceInfo:
        """Return device info for this member."""
        return DeviceInfo(
            identifiers={(DOMAIN, device_id(AREA, self.member_id))},
            name=self.member_name,
            manufacturer="Woow HA Records",
            model="Health Member",
        )

    # ── Record Types ─────────────────────────────────────────────────

    def add_record_type(
        self,
        type_id: str,
        name: str,
        unit: str,
        default_value: float = 0,
        default_value_mode: str = "fixed",
    ) -> None:
        """Define a new Record Type for this Member.

        Record Types used to live in the config entry's options, so adding one
        meant rewriting the entry and reloading it. They are stored data now.
        """
        self.record_sets[type_id] = RecordSet(
            type_id=type_id,
            name=name,
            unit=unit,
            default_value=default_value,
            default_value_mode=default_value_mode,
        )
        self._async_schedule_save()
        self.area.async_notify_entities_changed()

    def update_record_type(self, type_id: str, **changes: Any) -> bool:
        """Change a Record Type's definition in place."""
        record_set = self.record_sets.get(type_id)
        if record_set is None:
            return False
        for field_name, value in changes.items():
            if value is not None and hasattr(record_set, field_name):
                setattr(record_set, field_name, value)
        self._async_schedule_save()
        self.area.async_notify_entities_changed()
        return True

    def delete_record_type(self, type_id: str) -> bool:
        """Remove a Record Type and every Record logged against it."""
        if self.record_sets.pop(type_id, None) is None:
            return False
        self.records = [r for r in self.records if r.get("record_type") != type_id]
        self._async_schedule_save()
        self.area.async_notify_entities_changed()
        return True

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
