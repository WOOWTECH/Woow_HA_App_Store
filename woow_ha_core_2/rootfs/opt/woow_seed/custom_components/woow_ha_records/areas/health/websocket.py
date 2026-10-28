"""WebSocket commands for the health Area.

Panel registration and WebSocket API for Ha Health Record.

This module registers a custom panel in the Home Assistant sidebar and
exposes 12 WebSocket commands that the frontend uses to manage health
records.  All commands live under the ``ha_health_record/`` namespace.

WebSocket Command Reference
============================

Query APIs (no admin required)
------------------------------
- **ha_health_record/get_members**
    Params: (none)
    Returns: ``{members: [{id, name, note, record_sets: [{type, name,
    unit, default_value, default_value_mode, current_value,
    last_record}]}]}``

- **ha_health_record/get_records**
    Params: ``start_time`` (str, ISO 8601), ``end_time`` (str, ISO 8601)
    Returns: ``{records: [...]}`` sorted by timestamp descending.
    Errors: ``invalid_date``

- **ha_health_record/export_csv**
    Params: ``member_id`` (str)
    Returns: ``{csv_content, member_name, record_count}``
    Errors: ``member_not_found``

Record Logging (admin required)
-------------------------------
- **ha_health_record/log_record**
    Params: ``member_id`` (str), ``record_type`` (str),
    ``value`` (float, NaN/Inf rejected), ``note`` (str, optional),
    ``timestamp`` (str, optional, ISO 8601)
    Returns: ``{success: true}``
    Errors: ``member_not_found``, ``record_type_not_found``,
    ``invalid_timestamp``, ``log_failed``
    Side effects: fires ``ha_health_record_record_logged`` event.

Record Management (admin required)
-----------------------------------
- **ha_health_record/update_record**
    Params: ``member_id`` (str), ``type_id`` (str),
    ``timestamp`` (str, ISO 8601), ``record_id`` (str, optional),
    ``value`` (float, optional), ``note`` (str, optional),
    ``new_timestamp`` (str, optional)
    Returns: ``{success: true}``
    Errors: ``member_not_found``, ``record_not_found``

- **ha_health_record/delete_record**
    Params: ``member_id`` (str), ``type_id`` (str),
    ``timestamp`` (str), ``record_id`` (str, optional)
    Returns: ``{success: true}``
    Errors: ``member_not_found``, ``record_not_found``

Record Type Management (admin required)
----------------------------------------
- **ha_health_record/add_record_type**
    Params: ``member_id`` (str), ``name`` (str), ``unit`` (str),
    ``default_value`` (float, optional, default 0),
    ``default_value_mode`` (str, optional, "fixed"|"last_value",
    default "fixed")
    Returns: ``{success: true, type_id: str}``
    Errors: ``member_not_found``, ``type_exists``, ``invalid_type_id``
    Side effects: updates config entry, triggers config reload creating
    new entities.

- **ha_health_record/update_record_type**
    Params: ``member_id`` (str), ``type_id`` (str), ``name`` (str),
    ``unit`` (str), ``default_value`` (float, optional),
    ``default_value_mode`` (str, optional)
    Returns: ``{success: true}``
    Errors: ``member_not_found``, ``type_not_found``
    Side effects: updates config entry, triggers config reload.

- **ha_health_record/delete_record_type**
    Params: ``member_id`` (str), ``type_id`` (str)
    Returns: ``{success: true}``
    Errors: ``member_not_found``, ``type_not_found``
    Side effects: removes entities from entity registry (sensor, button,
    number, text), updates config entry, triggers config reload.

Member Management (admin required)
-----------------------------------
- **ha_health_record/add_member**
    Params: ``name`` (str), ``member_id`` (str, optional,
    auto-generated from name), ``note`` (str, optional, default "")
    Returns: ``{success: true, member_id: str, entry_id: str}``
    Errors: ``invalid_member_id``, ``member_exists``
    Side effects: creates a new config entry via the config flow.

- **ha_health_record/update_member**
    Params: ``member_id`` (str), ``name`` (str),
    ``note`` (str, optional, default "")
    Returns: ``{success: true}``
    Errors: ``member_not_found``
    Side effects: updates config entry data and title, triggers reload.

- **ha_health_record/delete_member**
    Params: ``member_id`` (str)
    Returns: ``{success: true}``
    Errors: ``member_not_found``
    Side effects: removes the config entry and all associated data.

Error Codes
-----------
``member_not_found``   -- No config entry matches the given member_id.
``record_not_found``   -- No record matches the given timestamp/record_id.
``type_not_found``     -- No record type matches the given type_id.
``type_exists``        -- A record type with that generated id already exists.
``member_exists``      -- A member with that id already exists.
``invalid_date``       -- start_time / end_time could not be parsed as ISO 8601.
``invalid_timestamp``  -- The optional timestamp could not be parsed.
``invalid_type_id``    -- The generated type_id is empty after sanitization.
``invalid_member_id``  -- The generated member_id is empty after sanitization.
``log_failed``         -- The coordinator failed to persist the record.
"""
from __future__ import annotations

import csv
import io
import logging
import math
from datetime import datetime
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from ...runtime import get_data
from .area import HealthArea
from .const import (
    EVENT_RECORD_LOGGED,
)
from .coordinator import HealthRecordCoordinator

_LOGGER = logging.getLogger(__name__)

@callback
def register_websocket_commands(hass: HomeAssistant) -> None:
    """Register all WebSocket commands (call once, not per entry)."""
    websocket_api.async_register_command(hass, ws_get_members)
    websocket_api.async_register_command(hass, ws_get_records)
    websocket_api.async_register_command(hass, ws_log_record)
    websocket_api.async_register_command(hass, ws_update_record)
    websocket_api.async_register_command(hass, ws_delete_record)
    websocket_api.async_register_command(hass, ws_add_record_type)
    websocket_api.async_register_command(hass, ws_update_record_type)
    websocket_api.async_register_command(hass, ws_delete_record_type)
    websocket_api.async_register_command(hass, ws_add_member)
    websocket_api.async_register_command(hass, ws_update_member)
    websocket_api.async_register_command(hass, ws_delete_member)
    websocket_api.async_register_command(hass, ws_export_csv)


def valid_float(value: Any) -> float:
    """Validate float, rejecting NaN and Infinity."""
    result = vol.Coerce(float)(value)
    if math.isnan(result) or math.isinf(result):
        raise vol.Invalid("NaN and Infinity are not allowed")
    return result


def _area(hass: HomeAssistant) -> HealthArea:
    """Return the health Area."""
    return get_data(hass).health


def _get_coordinators(hass: HomeAssistant) -> list[HealthRecordCoordinator]:
    """Return every Member's coordinator."""
    return list(_area(hass).members.values())


def _find_coordinator(
    hass: HomeAssistant, member_id: str
) -> HealthRecordCoordinator | None:
    """Find a coordinator by member_id."""
    return _area(hass).get(member_id)


# ============================================================================
# Query APIs
# ============================================================================


@websocket_api.websocket_command(
    {
        vol.Required("type"): "woow_ha_records/health/get_members",
    }
)
@callback
def ws_get_members(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return every registered member with their record-set metadata.

    Command:
        ``ha_health_record/get_members``

    Parameters:
        None (only the required ``type`` field).

    Permission:
        No admin required -- any authenticated user may call this.

    Returns:
        ``{members: [{id, name, note, record_sets: [{type, name, unit,
        default_value, default_value_mode, current_value,
        last_record}]}]}``

    Error codes:
        None.
    """
    members = []

    for coordinator in _get_coordinators(hass):
        member = {
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
                    } if s.last_record else None,
                }
                for s in coordinator.record_sets.values()
            ],
        }
        members.append(member)

    connection.send_result(msg["id"], {"members": members})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "woow_ha_records/health/get_records",
        vol.Required("start_time"): str,
        vol.Required("end_time"): str,
    }
)
@callback
def ws_get_records(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return health records across all members within a time range.

    Command:
        ``ha_health_record/get_records``

    Parameters:
        start_time (str): Start of the range in ISO 8601 format.
        end_time (str): End of the range in ISO 8601 format.

    Permission:
        No admin required -- any authenticated user may call this.

    Returns:
        ``{records: [...]}`` -- records sorted by timestamp descending.

    Error codes:
        ``invalid_date`` -- ``start_time`` or ``end_time`` could not be
        parsed as ISO 8601.
    """
    try:
        start_time = datetime.fromisoformat(msg["start_time"].replace('Z', '+00:00'))
        end_time = datetime.fromisoformat(msg["end_time"].replace('Z', '+00:00'))
    except ValueError:
        connection.send_error(msg["id"], "invalid_date", "Invalid date format")
        return

    records = []

    # Get records from all coordinators
    for coordinator in _get_coordinators(hass):
        coordinator_records = coordinator.get_records_in_range(start_time, end_time)
        records.extend(coordinator_records)

    # Sort by timestamp descending
    records.sort(key=lambda x: x["timestamp"], reverse=True)

    connection.send_result(msg["id"], {"records": records})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "woow_ha_records/health/export_csv",
        vol.Required("member_id"): str,
    }
)
@callback
def ws_export_csv(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Export all records for a single member as CSV text.

    Command:
        ``ha_health_record/export_csv``

    Parameters:
        member_id (str): The unique identifier of the member to export.

    Permission:
        No admin required -- any authenticated user may call this.

    Returns:
        ``{csv_content: str, member_name: str, record_count: int}``

    Error codes:
        ``member_not_found`` -- no config entry matches *member_id*.
    """
    member_id = msg["member_id"]

    coordinator = _find_coordinator(hass, member_id)
    if coordinator is None:
        connection.send_error(msg["id"], "member_not_found", f"Member {member_id} not found")
        return

    records = list(coordinator.records)
    records.sort(key=lambda r: r.get("timestamp", ""))

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["timestamp", "record_type", "record_name", "value", "unit", "note"])

    for record in records:
        type_id = record.get("record_type", "")
        rs = coordinator.record_sets.get(type_id)
        writer.writerow([
            record.get("timestamp", ""),
            type_id,
            rs.name if rs else record.get("record_name", type_id),
            record.get("value", ""),
            rs.unit if rs else record.get("unit", ""),
            record.get("note", ""),
        ])

    connection.send_result(msg["id"], {
        "csv_content": output.getvalue(),
        "member_name": coordinator.member_name,
        "record_count": len(records),
    })


# ============================================================================
# Record Logging API (unified)
# ============================================================================


@websocket_api.websocket_command(
    {
        vol.Required("type"): "woow_ha_records/health/log_record",
        vol.Required("member_id"): str,
        vol.Required("record_type"): str,
        vol.Required("value"): valid_float,
        vol.Optional("note", default=""): str,
        vol.Optional("timestamp"): str,
    }
)
@websocket_api.require_admin
@callback
def ws_log_record(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Log a new health record for a member.

    Command:
        ``ha_health_record/log_record``

    Parameters:
        member_id (str): The member to log the record for.
        record_type (str): The record-type id (must already exist).
        value (float): The measured value.  NaN and Infinity are
            rejected by the schema validator.
        note (str, optional): Free-text note attached to the record.
            Defaults to ``""``.
        timestamp (str, optional): ISO 8601 timestamp.  When omitted
            the current time is used.

    Permission:
        Admin required.

    Returns:
        ``{success: true}``

    Error codes:
        ``member_not_found`` -- no config entry matches *member_id*.
        ``record_type_not_found`` -- *record_type* is not in the
            member's record sets.
        ``invalid_timestamp`` -- the supplied *timestamp* could not be
            parsed as ISO 8601.
        ``log_failed`` -- the coordinator failed to persist the record.

    Side effects:
        Fires a ``ha_health_record_record_logged`` event on the HA
        event bus containing member details, value, unit, note, and
        timestamp.
    """
    member_id = msg["member_id"]
    record_type = msg["record_type"]
    value = msg["value"]
    note = msg.get("note", "")
    timestamp_str = msg.get("timestamp")

    # Find the coordinator
    coordinator = _find_coordinator(hass, member_id)
    if coordinator is None:
        connection.send_error(msg["id"], "member_not_found", f"Member {member_id} not found")
        return

    if record_type not in coordinator.record_sets:
        connection.send_error(msg["id"], "record_type_not_found", f"Record type {record_type} not found")
        return

    # Parse optional timestamp
    custom_timestamp = None
    if timestamp_str:
        try:
            custom_timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        except ValueError:
            connection.send_error(msg["id"], "invalid_timestamp", "Invalid timestamp format")
            return

    # Set the values and log
    coordinator.set_record_value(record_type, value)
    coordinator.set_record_note(record_type, note)
    record = coordinator.log_record(record_type, timestamp=custom_timestamp)

    if record is None:
        connection.send_error(msg["id"], "log_failed", "Failed to log record")
        return

    # Fire event
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
            "timestamp": record.timestamp.isoformat() if record.timestamp else None,
        },
    )

    connection.send_result(msg["id"], {"success": True})


# ============================================================================
# Record Management APIs
# ============================================================================


@websocket_api.websocket_command(
    {
        vol.Required("type"): "woow_ha_records/health/update_record",
        vol.Required("member_id"): str,
        vol.Required("type_id"): str,
        vol.Required("timestamp"): str,  # ISO format to identify the record
        vol.Optional("record_id"): str,  # UUID -- preferred over timestamp
        vol.Optional("value"): valid_float,
        vol.Optional("note"): str,
        vol.Optional("new_timestamp"): str,  # New timestamp if editing time
    }
)
@websocket_api.require_admin
@callback
def ws_update_record(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Update an existing health record's value, note, or timestamp.

    Command:
        ``ha_health_record/update_record``

    Parameters:
        member_id (str): The owning member's identifier.
        type_id (str): The record-type id the record belongs to.
        timestamp (str): ISO 8601 timestamp used to locate the record.
        record_id (str, optional): UUID of the record.  When provided
            this is preferred over *timestamp* for lookup.
        value (float, optional): New value for the record.
        note (str, optional): New note for the record.
        new_timestamp (str, optional): Replacement timestamp (ISO 8601).

    Permission:
        Admin required.

    Returns:
        ``{success: true}``

    Error codes:
        ``member_not_found`` -- no config entry matches *member_id*.
        ``record_not_found`` -- no record matches the given
            *timestamp* / *record_id*.
    """
    member_id = msg["member_id"]
    type_id = msg["type_id"]
    timestamp = msg["timestamp"]
    record_id = msg.get("record_id")

    # Find the coordinator
    coordinator = _find_coordinator(hass, member_id)
    if coordinator is None:
        connection.send_error(msg["id"], "member_not_found", f"Member {member_id} not found")
        return

    # Get the update values
    value = msg.get("value")
    note = msg.get("note")
    new_timestamp = msg.get("new_timestamp")

    if coordinator.update_record(
        type_id, timestamp,
        value=value, note=note, new_timestamp=new_timestamp,
        record_id=record_id,
    ):
        connection.send_result(msg["id"], {"success": True})
    else:
        connection.send_error(msg["id"], "record_not_found", "Record not found")


@websocket_api.websocket_command(
    {
        vol.Required("type"): "woow_ha_records/health/delete_record",
        vol.Required("member_id"): str,
        vol.Required("type_id"): str,
        vol.Required("timestamp"): str,
        vol.Optional("record_id"): str,  # UUID -- preferred over timestamp
    }
)
@websocket_api.require_admin
@callback
def ws_delete_record(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Delete a single health record.

    Command:
        ``ha_health_record/delete_record``

    Parameters:
        member_id (str): The owning member's identifier.
        type_id (str): The record-type id the record belongs to.
        timestamp (str): ISO 8601 timestamp used to locate the record.
        record_id (str, optional): UUID of the record.  When provided
            this is preferred over *timestamp* for lookup.

    Permission:
        Admin required.

    Returns:
        ``{success: true}``

    Error codes:
        ``member_not_found`` -- no config entry matches *member_id*.
        ``record_not_found`` -- no record matches the given
            *timestamp* / *record_id*.
    """
    member_id = msg["member_id"]
    type_id = msg["type_id"]
    timestamp = msg["timestamp"]
    record_id = msg.get("record_id")

    # Find the coordinator
    coordinator = _find_coordinator(hass, member_id)
    if coordinator is None:
        connection.send_error(msg["id"], "member_not_found", f"Member {member_id} not found")
        return

    if coordinator.delete_record(type_id, timestamp, record_id=record_id):
        connection.send_result(msg["id"], {"success": True})
    else:
        connection.send_error(msg["id"], "record_not_found", "Record not found")


# ============================================================================
# Record Type Management APIs (unified)
# ============================================================================
#
# These used to rewrite the member's config entry and reload it. A Member is a
# store record now (ADR-0001), so they are plain writes and the platforms
# reconcile their entities off the Area's dispatcher signal.


@websocket_api.websocket_command(
    {
        vol.Required("type"): "woow_ha_records/health/add_record_type",
        vol.Required("member_id"): str,
        vol.Required("name"): str,
        vol.Required("unit"): str,
        vol.Optional("default_value", default=0): valid_float,
        vol.Optional("default_value_mode", default="fixed"): vol.In(
            ["fixed", "last_value"]
        ),
    }
)
@websocket_api.require_admin
@callback
def ws_add_record_type(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Define a new record type for a member."""
    coordinator = _find_coordinator(hass, msg["member_id"])
    if coordinator is None:
        connection.send_error(msg["id"], "member_not_found", "Member not found")
        return

    type_id = msg["name"].lower().replace(" ", "_").replace("-", "_")
    type_id = "".join(c for c in type_id if c.isalnum() or c == "_")
    if not type_id:
        connection.send_error(msg["id"], "invalid_type_id", "Type id is empty")
        return

    if type_id in coordinator.record_sets:
        connection.send_error(
            msg["id"], "type_exists", f"Record type '{type_id}' already exists"
        )
        return

    coordinator.add_record_type(
        type_id,
        msg["name"],
        msg["unit"],
        msg["default_value"],
        msg["default_value_mode"],
    )
    connection.send_result(msg["id"], {"success": True, "type_id": type_id})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "woow_ha_records/health/update_record_type",
        vol.Required("member_id"): str,
        vol.Required("type_id"): str,
        vol.Optional("name"): str,
        vol.Optional("unit"): str,
        vol.Optional("default_value"): valid_float,
        vol.Optional("default_value_mode"): vol.In(["fixed", "last_value"]),
    }
)
@websocket_api.require_admin
@callback
def ws_update_record_type(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Change a record type's name, unit, or defaults."""
    coordinator = _find_coordinator(hass, msg["member_id"])
    if coordinator is None:
        connection.send_error(msg["id"], "member_not_found", "Member not found")
        return

    if not coordinator.update_record_type(
        msg["type_id"],
        name=msg.get("name"),
        unit=msg.get("unit"),
        default_value=msg.get("default_value"),
        default_value_mode=msg.get("default_value_mode"),
    ):
        connection.send_error(msg["id"], "type_not_found", "Record type not found")
        return

    connection.send_result(msg["id"], {"success": True})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "woow_ha_records/health/delete_record_type",
        vol.Required("member_id"): str,
        vol.Required("type_id"): str,
    }
)
@websocket_api.require_admin
@callback
def ws_delete_record_type(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Remove a record type and every record logged against it."""
    coordinator = _find_coordinator(hass, msg["member_id"])
    if coordinator is None:
        connection.send_error(msg["id"], "member_not_found", "Member not found")
        return

    if not coordinator.delete_record_type(msg["type_id"]):
        connection.send_error(msg["id"], "type_not_found", "Record type not found")
        return

    connection.send_result(msg["id"], {"success": True})


# ============================================================================
# Member Management APIs
# ============================================================================


@websocket_api.websocket_command(
    {
        vol.Required("type"): "woow_ha_records/health/add_member",
        vol.Required("name"): str,
        vol.Optional("member_id"): str,
        vol.Optional("note", default=""): str,
    }
)
@websocket_api.require_admin
@callback
def ws_add_member(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Add a member to track."""
    name = msg["name"]
    member_id = msg.get("member_id")
    if not member_id:
        member_id = name.lower().replace(" ", "_").replace("-", "_")
        member_id = "".join(c for c in member_id if c.isalnum() or c == "_")
    if not member_id:
        connection.send_error(msg["id"], "invalid_member_id", "Member id is empty")
        return

    area = _area(hass)
    if area.get(member_id) is not None:
        connection.send_error(
            msg["id"], "member_exists", f"Member '{member_id}' already exists"
        )
        return

    area.add_member(member_id, name, msg["note"])
    connection.send_result(msg["id"], {"success": True, "member_id": member_id})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "woow_ha_records/health/update_member",
        vol.Required("member_id"): str,
        vol.Required("name"): str,
        vol.Optional("note", default=""): str,
    }
)
@websocket_api.require_admin
@callback
def ws_update_member(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Rename a member."""
    coordinator = _find_coordinator(hass, msg["member_id"])
    if coordinator is None:
        connection.send_error(msg["id"], "member_not_found", "Member not found")
        return

    coordinator.member_name = msg["name"]
    coordinator.note = msg["note"]
    _area(hass).async_schedule_save()
    connection.send_result(msg["id"], {"success": True})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "woow_ha_records/health/delete_member",
        vol.Required("member_id"): str,
    }
)
@websocket_api.require_admin
@callback
def ws_delete_member(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Delete a member and everything recorded against them."""
    if not _area(hass).remove_member(msg["member_id"]):
        connection.send_error(msg["id"], "member_not_found", "Member not found")
        return

    connection.send_result(msg["id"], {"success": True})
