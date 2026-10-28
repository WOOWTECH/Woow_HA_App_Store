"""Home Assistant service handlers for ha_health_record.

Exposes 12 services that mirror the existing WebSocket API, allowing
automations, scripts, and AI agents to interact with health records
via ``hass.services.async_call()``.

Query services (get_members, get_records, export_csv) use
``SupportsResponse.ONLY`` — callers must request a response.

Write services use ``SupportsResponse.OPTIONAL`` — callers may
optionally receive a response dict.
"""

from __future__ import annotations

import csv
import io
import logging
import math
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
from homeassistant.util import dt as dt_util

from ...runtime import get_data
from .area import HealthArea
from .const import (
    DOMAIN,
    EVENT_RECORD_LOGGED,
)
from .coordinator import HealthRecordCoordinator

_LOGGER = logging.getLogger(__name__)

def _area(hass: HomeAssistant) -> HealthArea:
    """Return the health Area."""
    return get_data(hass).health


def _get_all_coordinators(hass: HomeAssistant) -> list[HealthRecordCoordinator]:
    """Return every Member's coordinator."""
    return list(_area(hass).members.values())


def _get_coordinator(hass: HomeAssistant, member_id: str) -> HealthRecordCoordinator:
    """Find a coordinator by *member_id*, raise on miss."""
    coordinator = _area(hass).get(member_id)
    if coordinator is None:
        raise ServiceValidationError(
            f"Member '{member_id}' not found",
            translation_domain=DOMAIN,
            translation_key="health.member_not_found",
            translation_placeholders={"member_id": member_id},
        )
    return coordinator


def _valid_float(value: Any) -> float:
    """Validate float, rejecting NaN and Infinity."""
    result = vol.Coerce(float)(value)
    if math.isnan(result) or math.isinf(result):
        raise vol.Invalid("NaN and Infinity are not allowed")
    return result


def _parse_iso(value: str, field: str = "timestamp") -> datetime:
    """Parse ISO 8601 string, raise ServiceValidationError on failure.

    Always returns a timezone-aware datetime to avoid naive/aware comparison bugs.
    """
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt_util.as_utc(parsed)
    except (ValueError, AttributeError) as exc:
        raise ServiceValidationError(
            f"Invalid datetime for '{field}': {value!r}",
            translation_domain=DOMAIN,
            translation_key="health.invalid_datetime",
            translation_placeholders={"field": field, "value": str(value)},
        ) from exc


# ---------------------------------------------------------------------------
# Query handlers — SupportsResponse.ONLY
# ---------------------------------------------------------------------------


async def handle_get_members(call: ServiceCall) -> ServiceResponse:
    """Return every registered member with their record-set metadata."""
    hass = call.hass
    members: list[dict[str, Any]] = []

    for coordinator in _get_all_coordinators(hass):
        member: dict[str, Any] = {
            "id": coordinator.member_id,
            "name": coordinator.member_name,
            "note": coordinator.note,
            "record_sets": [
                {
                    "type": s.type_id,
                    "name": s.name,
                    "unit": s.unit,
                    "default_value": s.default_value,
                    "default_value_mode": s.default_value_mode,
                    "current_value": s.current_value,
                    "last_record": {
                        "value": s.last_record.value,
                        "note": s.last_record.note,
                        "timestamp": (
                            s.last_record.timestamp.isoformat()
                            if s.last_record.timestamp
                            else None
                        ),
                    }
                    if s.last_record
                    else None,
                }
                for s in coordinator.record_sets.values()
            ],
        }
        members.append(member)

    return {"members": members}


async def handle_get_records(call: ServiceCall) -> ServiceResponse:
    """Return health records across all members within a time range."""
    hass = call.hass
    start_time = _parse_iso(call.data["start_time"], "start_time")
    end_time = _parse_iso(call.data["end_time"], "end_time")

    records: list[dict[str, Any]] = []
    for coordinator in _get_all_coordinators(hass):
        records.extend(coordinator.get_records_in_range(start_time, end_time))

    records.sort(key=lambda x: x["timestamp"], reverse=True)
    return {"records": records}


async def handle_export_csv(call: ServiceCall) -> ServiceResponse:
    """Export all records for a member as CSV text."""
    hass = call.hass
    member_id = call.data["member_id"]
    coordinator = _get_coordinator(hass, member_id)

    records = sorted(coordinator.records, key=lambda r: r.get("timestamp", ""))

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        ["timestamp", "record_type", "record_name", "value", "unit", "note"]
    )

    for record in records:
        type_id = record.get("record_type", "")
        rs = coordinator.record_sets.get(type_id)
        writer.writerow(
            [
                record.get("timestamp", ""),
                type_id,
                rs.name if rs else record.get("record_name", type_id),
                record.get("value", ""),
                rs.unit if rs else record.get("unit", ""),
                record.get("note", ""),
            ]
        )

    return {
        "csv_content": output.getvalue(),
        "member_name": coordinator.member_name,
        "record_count": len(records),
    }


# ---------------------------------------------------------------------------
# Record logging / CRUD — SupportsResponse.OPTIONAL
# ---------------------------------------------------------------------------


async def handle_log_record(call: ServiceCall) -> ServiceResponse:
    """Log a new health record for a member."""
    hass = call.hass
    member_id = call.data["member_id"]
    record_type = call.data["record_type"]
    value = call.data["value"]
    note = call.data.get("note", "")
    timestamp_str = call.data.get("timestamp")

    coordinator = _get_coordinator(hass, member_id)

    if record_type not in coordinator.record_sets:
        raise ServiceValidationError(
            f"Record type '{record_type}' not found for member '{member_id}'",
            translation_domain=DOMAIN,
            translation_key="health.record_type_not_found",
            translation_placeholders={
                "record_type": record_type,
                "member_id": member_id,
            },
        )

    # Validate value
    value = _valid_float(value)

    custom_timestamp = None
    if timestamp_str:
        custom_timestamp = _parse_iso(timestamp_str, "timestamp")

    coordinator.set_record_value(record_type, value)
    coordinator.set_record_note(record_type, note)
    record = coordinator.log_record(record_type, timestamp=custom_timestamp)

    if record is None:
        raise ServiceValidationError(
            "Failed to log record",
            translation_domain=DOMAIN,
            translation_key="health.log_failed",
        )

    # Fire event (same as WS handler)
    record_set = coordinator.get_record_set(record_type)
    hass.bus.async_fire(
        EVENT_RECORD_LOGGED,
        {
            "member_id": coordinator.member_id,
            "member_name": coordinator.member_name,
            "record_type": record_type,
            "record_name": record_set.name if record_set else record_type,
            "value": record.value,
            "unit": record_set.unit if record_set else "",
            "note": record.note,
            "timestamp": (
                record.timestamp.isoformat() if record.timestamp else None
            ),
        },
    )

    return {"success": True}


async def handle_update_record(call: ServiceCall) -> ServiceResponse:
    """Update an existing health record."""
    hass = call.hass
    member_id = call.data["member_id"]
    type_id = call.data["type_id"]
    timestamp = call.data["timestamp"]
    record_id = call.data.get("record_id")

    coordinator = _get_coordinator(hass, member_id)

    value = call.data.get("value")
    note = call.data.get("note")
    new_timestamp = call.data.get("new_timestamp")

    if coordinator.update_record(
        type_id,
        timestamp,
        value=value,
        note=note,
        new_timestamp=new_timestamp,
        record_id=record_id,
    ):
        return {"success": True}

    raise ServiceValidationError(
        f"Record not found for member '{member_id}', type '{type_id}', "
        f"timestamp '{timestamp}'"
        + (f", record_id '{record_id}'" if record_id else ""),
        translation_domain=DOMAIN,
        translation_key="health.record_not_found",
        translation_placeholders={
            "member_id": member_id,
            "type_id": type_id,
            "timestamp": timestamp,
        },
    )


async def handle_delete_record(call: ServiceCall) -> ServiceResponse:
    """Delete a single health record."""
    hass = call.hass
    member_id = call.data["member_id"]
    type_id = call.data["type_id"]
    timestamp = call.data["timestamp"]
    record_id = call.data.get("record_id")

    coordinator = _get_coordinator(hass, member_id)

    if coordinator.delete_record(type_id, timestamp, record_id=record_id):
        return {"success": True}

    raise ServiceValidationError(
        f"Record not found for member '{member_id}', type '{type_id}', "
        f"timestamp '{timestamp}'"
        + (f", record_id '{record_id}'" if record_id else ""),
        translation_domain=DOMAIN,
        translation_key="health.record_not_found",
        translation_placeholders={
            "member_id": member_id,
            "type_id": type_id,
            "timestamp": timestamp,
        },
    )


# ---------------------------------------------------------------------------
# Record type management — SupportsResponse.OPTIONAL
# ---------------------------------------------------------------------------


async def handle_add_record_type(call: ServiceCall) -> ServiceResponse:
    """Define a new record type for a member."""
    hass = call.hass
    member_id = call.data["member_id"]
    name = call.data["name"]
    unit = call.data.get("unit", "")
    default_value = call.data.get("default_value", 0)
    default_value_mode = call.data.get("default_value_mode", "fixed")

    coordinator = _get_coordinator(hass, member_id)

    type_id = name.lower().replace(" ", "_").replace("-", "_")
    type_id = "".join(c for c in type_id if c.isalnum() or c == "_")

    if not type_id:
        raise ServiceValidationError(
            "Name must contain at least one alphanumeric character",
            translation_domain=DOMAIN,
            translation_key="health.invalid_type_id",
        )

    if type_id in coordinator.record_sets:
        raise ServiceValidationError(
            f"Record type '{type_id}' already exists",
            translation_domain=DOMAIN,
            translation_key="health.type_exists",
            translation_placeholders={"type_id": type_id},
        )

    coordinator.add_record_type(type_id, name, unit, default_value, default_value_mode)
    return {"success": True, "type_id": type_id}


async def handle_update_record_type(call: ServiceCall) -> ServiceResponse:
    """Change a record type's name, unit, or defaults."""
    hass = call.hass
    member_id = call.data["member_id"]
    type_id = call.data["type_id"]

    coordinator = _get_coordinator(hass, member_id)

    if not coordinator.update_record_type(
        type_id,
        name=call.data.get("name"),
        unit=call.data.get("unit"),
        default_value=call.data.get("default_value"),
        default_value_mode=call.data.get("default_value_mode"),
    ):
        raise ServiceValidationError(
            f"Record type '{type_id}' not found",
            translation_domain=DOMAIN,
            translation_key="health.type_not_found",
            translation_placeholders={"type_id": type_id},
        )

    return {"success": True}


async def handle_delete_record_type(call: ServiceCall) -> ServiceResponse:
    """Remove a record type and every record logged against it."""
    hass = call.hass
    member_id = call.data["member_id"]
    type_id = call.data["type_id"]

    coordinator = _get_coordinator(hass, member_id)

    if not coordinator.delete_record_type(type_id):
        raise ServiceValidationError(
            f"Record type '{type_id}' not found",
            translation_domain=DOMAIN,
            translation_key="health.type_not_found",
            translation_placeholders={"type_id": type_id},
        )

    return {"success": True}


async def handle_add_member(call: ServiceCall) -> ServiceResponse:
    """Add a member to track.

    Creating a Member used to mean starting a config flow and waiting for the
    entry to finish setting up, which callers routinely raced. It is an
    ordinary store write now.
    """
    hass = call.hass
    name = call.data["name"]
    member_id = call.data.get("member_id")
    note = call.data.get("note", "")

    if not member_id:
        member_id = name.lower().replace(" ", "_").replace("-", "_")
        member_id = "".join(c for c in member_id if c.isalnum() or c == "_")

    if not member_id:
        raise ServiceValidationError(
            "Member ID is empty after sanitization",
            translation_domain=DOMAIN,
            translation_key="health.invalid_member_id",
        )

    area = _area(hass)
    if area.get(member_id) is not None:
        raise ServiceValidationError(
            f"Member '{member_id}' already exists",
            translation_domain=DOMAIN,
            translation_key="health.member_exists",
            translation_placeholders={"member_id": member_id},
        )

    area.add_member(member_id, name, note)
    return {"success": True, "member_id": member_id}


async def handle_update_member(call: ServiceCall) -> ServiceResponse:
    """Rename a member."""
    hass = call.hass
    member_id = call.data["member_id"]

    coordinator = _get_coordinator(hass, member_id)
    coordinator.member_name = call.data["name"]
    coordinator.note = call.data.get("note", "")
    _area(hass).async_schedule_save()

    return {"success": True}


async def handle_delete_member(call: ServiceCall) -> ServiceResponse:
    """Delete a member and everything recorded against them."""
    hass = call.hass
    member_id = call.data["member_id"]

    _get_coordinator(hass, member_id)
    _area(hass).remove_member(member_id)

    return {"success": True}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

# Field names, requiredness and types mirror this Area's WebSocket commands;
# ``services.yaml`` is the reference where no command covers the operation.
# ``_valid_float`` is the same NaN/Infinity rejection ``valid_float`` makes
# over WebSocket. Not mirrored is ``vol.In`` on ``default_value_mode``:
# rejecting a *value* the service accepts today is a different change from
# rejecting a *field* it should never have accepted, which is all issue #44
# asked for.
#
# No optional field carries a ``default=`` either. Handlers read absence with
# ``call.data.get(...) is None`` and treat it as "leave unchanged", so a
# default would turn every omitted field into an explicit overwrite — on the
# update verbs that silently rewrites data the caller never mentioned.
SERVICE_HANDLERS = {
    # Query — ONLY
    "get_members": (
        handle_get_members,
        SupportsResponse.ONLY,
        vol.Schema({}),
    ),
    "get_records": (
        handle_get_records,
        SupportsResponse.ONLY,
        vol.Schema(
            {
                vol.Required("start_time"): cv.string,
                vol.Required("end_time"): cv.string,
            }
        ),
    ),
    "export_csv": (
        handle_export_csv,
        SupportsResponse.ONLY,
        vol.Schema({vol.Required("member_id"): cv.string}),
    ),
    # Record CRUD — OPTIONAL
    "log_record": (
        handle_log_record,
        SupportsResponse.OPTIONAL,
        vol.Schema(
            {
                vol.Required("member_id"): cv.string,
                vol.Required("record_type"): cv.string,
                vol.Required("value"): _valid_float,
                vol.Optional("note"): cv.string,
                vol.Optional("timestamp"): cv.string,
            }
        ),
    ),
    "update_record": (
        handle_update_record,
        SupportsResponse.OPTIONAL,
        vol.Schema(
            {
                vol.Required("member_id"): cv.string,
                vol.Required("type_id"): cv.string,
                vol.Required("timestamp"): cv.string,
                vol.Optional("record_id"): cv.string,
                vol.Optional("value"): _valid_float,
                vol.Optional("note"): cv.string,
                vol.Optional("new_timestamp"): cv.string,
            }
        ),
    ),
    "delete_record": (
        handle_delete_record,
        SupportsResponse.OPTIONAL,
        vol.Schema(
            {
                vol.Required("member_id"): cv.string,
                vol.Required("type_id"): cv.string,
                vol.Required("timestamp"): cv.string,
                vol.Optional("record_id"): cv.string,
            }
        ),
    ),
    # Record type — OPTIONAL
    "add_record_type": (
        handle_add_record_type,
        SupportsResponse.OPTIONAL,
        vol.Schema(
            {
                vol.Required("member_id"): cv.string,
                vol.Required("name"): cv.string,
                vol.Required("unit"): cv.string,
                vol.Optional("default_value"): _valid_float,
                vol.Optional("default_value_mode"): cv.string,
            }
        ),
    ),
    "update_record_type": (
        handle_update_record_type,
        SupportsResponse.OPTIONAL,
        vol.Schema(
            {
                vol.Required("member_id"): cv.string,
                vol.Required("type_id"): cv.string,
                vol.Optional("name"): cv.string,
                vol.Optional("unit"): cv.string,
                vol.Optional("default_value"): _valid_float,
                vol.Optional("default_value_mode"): cv.string,
            }
        ),
    ),
    "delete_record_type": (
        handle_delete_record_type,
        SupportsResponse.OPTIONAL,
        vol.Schema(
            {
                vol.Required("member_id"): cv.string,
                vol.Required("type_id"): cv.string,
            }
        ),
    ),
    # Member — OPTIONAL
    "add_member": (
        handle_add_member,
        SupportsResponse.OPTIONAL,
        vol.Schema(
            {
                vol.Required("name"): cv.string,
                vol.Optional("member_id"): cv.string,
                vol.Optional("note"): cv.string,
            }
        ),
    ),
    "update_member": (
        handle_update_member,
        SupportsResponse.OPTIONAL,
        vol.Schema(
            {
                vol.Required("member_id"): cv.string,
                vol.Required("name"): cv.string,
                vol.Optional("note"): cv.string,
            }
        ),
    ),
    "delete_member": (
        handle_delete_member,
        SupportsResponse.OPTIONAL,
        vol.Schema({vol.Required("member_id"): cv.string}),
    ),
}
