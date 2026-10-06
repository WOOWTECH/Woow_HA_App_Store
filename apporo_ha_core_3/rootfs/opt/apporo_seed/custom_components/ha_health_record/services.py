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
from datetime import datetime
import io
import logging
import math
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_MEMBER_ID,
    CONF_RECORD_NAME,
    CONF_RECORD_SETS,
    CONF_RECORD_TYPE,
    CONF_RECORD_UNIT,
    DOMAIN,
    EVENT_RECORD_LOGGED,
)
from .coordinator import HealthRecordCoordinator

from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

KEY_COORDINATOR_MAP = f"{DOMAIN}_coordinator_map"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_all_coordinators(hass: HomeAssistant) -> list[HealthRecordCoordinator]:
    """Return every loaded coordinator."""
    coordinators: list[HealthRecordCoordinator] = []
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED:
            coordinators.append(entry.runtime_data)
    return coordinators


def _get_coordinator(
    hass: HomeAssistant, member_id: str
) -> HealthRecordCoordinator:
    """Find a coordinator by *member_id*, raise on miss."""
    coord_map = hass.data.get(KEY_COORDINATOR_MAP, {})
    coord = coord_map.get(member_id)
    if coord is not None:
        return coord
    # Fallback: linear scan
    for c in _get_all_coordinators(hass):
        if c.member_id == member_id:
            return c
    raise ServiceValidationError(
        f"Member '{member_id}' not found",
        translation_domain=DOMAIN,
        translation_key="member_not_found",
        translation_placeholders={"member_id": member_id},
    )


def _find_entry(hass: HomeAssistant, member_id: str):
    """Find the config entry for *member_id*, raise on miss."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.data.get(CONF_MEMBER_ID) == member_id:
            return entry
    raise ServiceValidationError(
        f"Member '{member_id}' not found",
        translation_domain=DOMAIN,
        translation_key="member_not_found",
        translation_placeholders={"member_id": member_id},
    )


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
            translation_key="invalid_datetime",
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
            "note": coordinator.entry.data.get("note", ""),
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
            translation_key="record_type_not_found",
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
            translation_key="log_failed",
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
        f"timestamp '{timestamp}'" + (f", record_id '{record_id}'" if record_id else ""),
        translation_domain=DOMAIN,
        translation_key="record_not_found",
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
        f"timestamp '{timestamp}'" + (f", record_id '{record_id}'" if record_id else ""),
        translation_domain=DOMAIN,
        translation_key="record_not_found",
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
    """Add a new record type to a member."""
    hass = call.hass
    member_id = call.data["member_id"]
    name = call.data["name"]
    unit = call.data["unit"]
    default_value = call.data.get("default_value", 0)
    default_value_mode = call.data.get("default_value_mode", "fixed")

    entry = _find_entry(hass, member_id)

    # Generate type_id from name
    type_id = name.lower().replace(" ", "_").replace("-", "_")
    type_id = "".join(c for c in type_id if c.isalnum() or c == "_")

    if not type_id:
        raise ServiceValidationError(
            "Name must contain at least one alphanumeric character",
            translation_domain=DOMAIN,
            translation_key="invalid_type_id",
        )

    current_options = dict(entry.options)
    record_sets = list(current_options.get(CONF_RECORD_SETS, []))

    for s in record_sets:
        if s.get(CONF_RECORD_TYPE) == type_id:
            raise ServiceValidationError(
                f"Record type '{type_id}' already exists",
                translation_domain=DOMAIN,
                translation_key="type_exists",
                translation_placeholders={"type_id": type_id},
            )

    record_sets.append(
        {
            CONF_RECORD_TYPE: type_id,
            CONF_RECORD_NAME: name,
            CONF_RECORD_UNIT: unit,
            "default_value": default_value,
            "default_value_mode": default_value_mode,
        }
    )

    current_options[CONF_RECORD_SETS] = record_sets
    hass.config_entries.async_update_entry(entry, options=current_options)
    await hass.config_entries.async_reload(entry.entry_id)

    return {"success": True, "type_id": type_id}


async def handle_update_record_type(call: ServiceCall) -> ServiceResponse:
    """Update the metadata of an existing record type."""
    hass = call.hass
    member_id = call.data["member_id"]
    type_id = call.data["type_id"]
    name = call.data["name"]
    unit = call.data["unit"]
    default_value = call.data.get("default_value")
    default_value_mode = call.data.get("default_value_mode")

    entry = _find_entry(hass, member_id)

    current_options = dict(entry.options)
    record_sets = list(current_options.get(CONF_RECORD_SETS, []))

    found = False
    for i, s in enumerate(record_sets):
        if s.get(CONF_RECORD_TYPE) == type_id:
            updated = dict(s)
            updated[CONF_RECORD_NAME] = name
            updated[CONF_RECORD_UNIT] = unit
            if default_value is not None:
                updated["default_value"] = default_value
            if default_value_mode is not None:
                updated["default_value_mode"] = default_value_mode
            record_sets[i] = updated
            found = True
            break

    if not found:
        raise ServiceValidationError(
            f"Record type '{type_id}' not found",
            translation_domain=DOMAIN,
            translation_key="type_not_found",
            translation_placeholders={"type_id": type_id},
        )

    current_options[CONF_RECORD_SETS] = record_sets
    hass.config_entries.async_update_entry(entry, options=current_options)
    await hass.config_entries.async_reload(entry.entry_id)

    return {"success": True}


async def handle_delete_record_type(call: ServiceCall) -> ServiceResponse:
    """Delete a record type and its associated entities."""
    hass = call.hass
    member_id = call.data["member_id"]
    type_id = call.data["type_id"]

    entry = _find_entry(hass, member_id)

    current_options = dict(entry.options)
    record_sets = list(current_options.get(CONF_RECORD_SETS, []))

    new_sets = [s for s in record_sets if s.get(CONF_RECORD_TYPE) != type_id]
    if len(new_sets) == len(record_sets):
        raise ServiceValidationError(
            f"Record type '{type_id}' not found",
            translation_domain=DOMAIN,
            translation_key="type_not_found",
            translation_placeholders={"type_id": type_id},
        )

    # Remove entities
    entity_reg = er.async_get(hass)
    for platform, suffix in [
        ("sensor", "_record"),
        ("button", "_log"),
        ("number", "_value"),
        ("text", "_note"),
    ]:
        unique_id = f"{member_id}_{type_id}{suffix}"
        entity_id = entity_reg.async_get_entity_id(platform, DOMAIN, unique_id)
        if entity_id:
            entity_reg.async_remove(entity_id)

    current_options[CONF_RECORD_SETS] = new_sets
    hass.config_entries.async_update_entry(entry, options=current_options)
    await hass.config_entries.async_reload(entry.entry_id)

    return {"success": True}


# ---------------------------------------------------------------------------
# Member management — SupportsResponse.OPTIONAL
# ---------------------------------------------------------------------------


async def handle_add_member(call: ServiceCall) -> ServiceResponse:
    """Add a new member (person) to be tracked."""
    hass = call.hass
    name = call.data["name"]
    member_id = call.data.get("member_id")
    note = call.data.get("note", "")

    # Generate member_id from name if not provided
    if not member_id:
        member_id = name.lower().replace(" ", "_").replace("-", "_")
        member_id = "".join(c for c in member_id if c.isalnum() or c == "_")

    if not member_id:
        raise ServiceValidationError(
            "Member ID is empty after sanitization",
            translation_domain=DOMAIN,
            translation_key="invalid_member_id",
        )

    # Check duplicate
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.data.get(CONF_MEMBER_ID) == member_id:
            raise ServiceValidationError(
                f"Member '{member_id}' already exists",
                translation_domain=DOMAIN,
                translation_key="member_exists",
                translation_placeholders={"member_id": member_id},
            )

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "user"},
        data={"member_name": name, "member_id": member_id, "note": note},
    )

    if result.get("type") == "create_entry":
        return {
            "success": True,
            "member_id": member_id,
            "entry_id": (
                result.get("result").entry_id if result.get("result") else None
            ),
        }

    raise ServiceValidationError(
        "Failed to create member",
        translation_domain=DOMAIN,
        translation_key="create_failed",
    )


async def handle_update_member(call: ServiceCall) -> ServiceResponse:
    """Update a member's display name and note."""
    hass = call.hass
    member_id = call.data["member_id"]
    name = call.data["name"]
    note = call.data.get("note", "")

    entry = _find_entry(hass, member_id)

    new_data = dict(entry.data)
    new_data["member_name"] = name
    new_data["note"] = note

    hass.config_entries.async_update_entry(entry, data=new_data, title=name)
    await hass.config_entries.async_reload(entry.entry_id)

    return {"success": True}


async def handle_delete_member(call: ServiceCall) -> ServiceResponse:
    """Delete a member and all associated data."""
    hass = call.hass
    member_id = call.data["member_id"]

    entry = _find_entry(hass, member_id)
    await hass.config_entries.async_remove(entry.entry_id)

    return {"success": True}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

_SERVICE_HANDLERS = {
    # Query — ONLY
    "get_members": (handle_get_members, SupportsResponse.ONLY),
    "get_records": (handle_get_records, SupportsResponse.ONLY),
    "export_csv": (handle_export_csv, SupportsResponse.ONLY),
    # Record CRUD — OPTIONAL
    "log_record": (handle_log_record, SupportsResponse.OPTIONAL),
    "update_record": (handle_update_record, SupportsResponse.OPTIONAL),
    "delete_record": (handle_delete_record, SupportsResponse.OPTIONAL),
    # Record type — OPTIONAL
    "add_record_type": (handle_add_record_type, SupportsResponse.OPTIONAL),
    "update_record_type": (handle_update_record_type, SupportsResponse.OPTIONAL),
    "delete_record_type": (handle_delete_record_type, SupportsResponse.OPTIONAL),
    # Member — OPTIONAL
    "add_member": (handle_add_member, SupportsResponse.OPTIONAL),
    "update_member": (handle_update_member, SupportsResponse.OPTIONAL),
    "delete_member": (handle_delete_member, SupportsResponse.OPTIONAL),
}


def async_register_services(hass: HomeAssistant) -> None:
    """Register all ha_health_record services."""
    for name, (handler, response_type) in _SERVICE_HANDLERS.items():
        hass.services.async_register(
            DOMAIN,
            name,
            handler,
            supports_response=response_type,
        )
    _LOGGER.debug("Registered %d services for %s", len(_SERVICE_HANDLERS), DOMAIN)


def async_unregister_services(hass: HomeAssistant) -> None:
    """Remove all ha_health_record services."""
    for name in _SERVICE_HANDLERS:
        hass.services.async_remove(DOMAIN, name)
    _LOGGER.debug("Unregistered services for %s", DOMAIN)
