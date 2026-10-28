"""Home Assistant service handlers for ha_note_record.

Exposes 9 services that mirror (and extend) the existing WebSocket API,
allowing automations, scripts, and AI agents to interact with note records
via ``hass.services.async_call()``.

Query services (list_notes, get_note, list_categories, export_markdown)
use ``SupportsResponse.ONLY`` — callers must request a response.

Write services use ``SupportsResponse.OPTIONAL`` — callers may
optionally receive a response dict.
"""

from __future__ import annotations

import logging

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
from .const import (
    AREA,
    DOMAIN,
    MAX_CATEGORY_NAME_LENGTH,
    MAX_NOTE_CONTENT_LENGTH,
    MAX_NOTE_TITLE_LENGTH,
)
from .entity import async_move_note_entities, async_remove_note_entities
from .store import HaNoteRecordStore

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_store(hass: HomeAssistant) -> HaNoteRecordStore:
    """Return the note Area's store."""
    return get_data(hass).note


# ---------------------------------------------------------------------------
# Query services — SupportsResponse.ONLY
# ---------------------------------------------------------------------------


async def handle_list_notes(call: ServiceCall) -> ServiceResponse:
    """List all categories and notes."""
    store = _get_store(call.hass)
    return {
        "categories": [c.to_dict() for c in store.categories],
        "notes": [n.to_dict() for n in store.notes],
    }


async def handle_get_note(call: ServiceCall) -> ServiceResponse:
    """Get a single note by ID."""
    store = _get_store(call.hass)
    note_id = call.data["note_id"]
    note = store.get_note(note_id)
    if note is None:
        raise ServiceValidationError(
            f"Note '{note_id}' not found",
            translation_domain=DOMAIN,
            translation_key="note.note_not_found",
            translation_placeholders={"note_id": note_id},
        )
    return {"note": note.to_dict()}


async def handle_list_categories(call: ServiceCall) -> ServiceResponse:
    """List all note categories."""
    store = _get_store(call.hass)
    return {"categories": [c.to_dict() for c in store.categories]}


async def handle_export_markdown(call: ServiceCall) -> ServiceResponse:
    """Export all notes as a single Markdown string."""
    store = _get_store(call.hass)

    # Group notes by category
    notes_by_cat: dict[str, list] = {}
    for note in store.notes:
        notes_by_cat.setdefault(note.category_id, []).append(note)

    parts: list[str] = []
    for category in store.categories:
        cat_notes = notes_by_cat.get(category.id, [])
        if not cat_notes:
            continue
        parts.append(f"# {category.name}\n")
        for note in cat_notes:
            parts.append(f"## {note.title}\n")
            if note.content:
                parts.append(f"{note.content}\n")
            parts.append("---\n")

    markdown_content = "\n".join(parts) if parts else ""

    return {
        "markdown_content": markdown_content,
        "note_count": len(store.notes),
        "category_count": len(store.categories),
    }


# ---------------------------------------------------------------------------
# Note CRUD — SupportsResponse.OPTIONAL
# ---------------------------------------------------------------------------


async def handle_create_category(call: ServiceCall) -> ServiceResponse:
    """Create a new note category."""
    store = _get_store(call.hass)
    name = call.data.get("name", "").strip()
    if not name:
        raise ServiceValidationError(
            "Category name is required",
            translation_domain=DOMAIN,
            translation_key="note.category_name_required",
        )

    if len(name) > MAX_CATEGORY_NAME_LENGTH:
        raise ServiceValidationError(
            f"Category name exceeds maximum length of "
            f"{MAX_CATEGORY_NAME_LENGTH} characters",
            translation_domain=DOMAIN,
            translation_key="note.category_name_too_long",
            translation_placeholders={"max_length": str(MAX_CATEGORY_NAME_LENGTH)},
        )

    # Case-insensitive duplicate check
    for category in store.categories:
        if category.name.lower() == name.lower():
            raise ServiceValidationError(
                "Category already exists",
                translation_domain=DOMAIN,
                translation_key="note.category_duplicate",
            )

    category = await store.async_create_category(name)
    return {"success": True, "category": category.to_dict()}


async def handle_create_note(call: ServiceCall) -> ServiceResponse:
    """Create a new note within a category."""
    store = _get_store(call.hass)
    category_id = call.data["category_id"]
    title = call.data.get("title", "").strip()
    content = call.data.get("content", "")
    pinned = call.data.get("pinned", False)

    if not title:
        raise ServiceValidationError(
            "Note title is required",
            translation_domain=DOMAIN,
            translation_key="note.title_required",
        )

    if len(title) > MAX_NOTE_TITLE_LENGTH:
        raise ServiceValidationError(
            f"Note title exceeds maximum length of {MAX_NOTE_TITLE_LENGTH} characters",
            translation_domain=DOMAIN,
            translation_key="note.title_too_long",
            translation_placeholders={"max_length": str(MAX_NOTE_TITLE_LENGTH)},
        )

    if len(content) > MAX_NOTE_CONTENT_LENGTH:
        raise ServiceValidationError(
            f"Note content exceeds maximum length of "
            f"{MAX_NOTE_CONTENT_LENGTH} characters",
            translation_domain=DOMAIN,
            translation_key="note.content_too_long",
            translation_placeholders={"max_length": str(MAX_NOTE_CONTENT_LENGTH)},
        )

    if not store.get_category(category_id):
        raise ServiceValidationError(
            f"Category '{category_id}' not found",
            translation_domain=DOMAIN,
            translation_key="note.category_not_found",
            translation_placeholders={"category_id": category_id},
        )

    # Case-insensitive duplicate title check within category
    for note in store.get_notes_by_category(category_id):
        if note.title.lower() == title.lower():
            raise ServiceValidationError(
                "Note title already exists in this category",
                translation_domain=DOMAIN,
                translation_key="note.title_duplicate",
            )

    note = await store.async_create_note(
        category_id=category_id,
        title=title,
        content=content,
        pinned=pinned,
    )

    if note is None:
        raise ServiceValidationError(
            "Failed to create note",
            translation_domain=DOMAIN,
            translation_key="note.create_failed",
        )

    return {"success": True, "note": note.to_dict()}


async def handle_update_note(call: ServiceCall) -> ServiceResponse:
    """Update one or more fields on an existing note.

    ``category_id`` moves the note to another category. It is one optional
    field among the others because ADR-0003 made the category an attribute of
    a note rather than part of its identity; the only thing a move needs
    beyond the store write is re-pointing the note's entities at the
    destination category's device.
    """
    store = _get_store(call.hass)
    note_id = call.data["note_id"]
    note = store.get_note(note_id)

    if note is None:
        raise ServiceValidationError(
            f"Note '{note_id}' not found",
            translation_domain=DOMAIN,
            translation_key="note.note_not_found",
            translation_placeholders={"note_id": note_id},
        )

    # Validate the destination category if a move was asked for. Nothing is
    # written until every check below passes, so a bad destination leaves the
    # note exactly as it was.
    destination = None
    category_id = note.category_id
    if "category_id" in call.data:
        category_id = call.data["category_id"]
        destination = store.get_category(category_id)
        if destination is None:
            raise ServiceValidationError(
                f"Category '{category_id}' not found",
                translation_domain=DOMAIN,
                translation_key="note.category_not_found",
                translation_placeholders={"category_id": category_id},
            )

    # Validate title if provided
    title = None
    if "title" in call.data:
        title = call.data["title"].strip()
        if not title:
            raise ServiceValidationError(
                "Note title is required",
                translation_domain=DOMAIN,
                translation_key="note.title_required",
            )

        if len(title) > MAX_NOTE_TITLE_LENGTH:
            raise ServiceValidationError(
                f"Note title exceeds maximum length of "
                f"{MAX_NOTE_TITLE_LENGTH} characters",
                translation_domain=DOMAIN,
                translation_key="note.title_too_long",
                translation_placeholders={"max_length": str(MAX_NOTE_TITLE_LENGTH)},
            )

    # Case-insensitive duplicate title check, against the category the note
    # will be in and under the title it will have. A move carries the note's
    # existing title into a category that may already hold it, so the check
    # has to run for a move that renames nothing. It is skipped when neither
    # is changing, so an edit to content alone cannot be refused by a
    # duplicate that predates it.
    moving = category_id != note.category_id
    renaming = title is not None and title.lower() != note.title.lower()
    if moving or renaming:
        new_title = title if title is not None else note.title
        for other_note in store.get_notes_by_category(category_id):
            if (
                other_note.id != note_id
                and other_note.title.lower() == new_title.lower()
            ):
                raise ServiceValidationError(
                    "Note title already exists in this category",
                    translation_domain=DOMAIN,
                    translation_key="note.title_duplicate",
                )

    # Validate content if provided
    content = None
    if "content" in call.data:
        content = call.data["content"]
        if len(content) > MAX_NOTE_CONTENT_LENGTH:
            raise ServiceValidationError(
                f"Note content exceeds maximum length of "
                f"{MAX_NOTE_CONTENT_LENGTH} characters",
                translation_domain=DOMAIN,
                translation_key="note.content_too_long",
                translation_placeholders={"max_length": str(MAX_NOTE_CONTENT_LENGTH)},
            )

    # Get pinned if provided
    pinned = call.data.get("pinned") if "pinned" in call.data else None

    # Apply all updates atomically
    await store.async_update_note(
        note_id,
        title=title,
        content=content,
        pinned=pinned,
        category_id=category_id if moving else None,
    )

    updated_note = store.get_note(note_id)
    if updated_note is None:
        raise ServiceValidationError(
            "Failed to update note",
            translation_domain=DOMAIN,
            translation_key="note.update_failed",
        )

    # The store holds no registry, so the entities follow separately.
    if moving and destination is not None:
        async_move_note_entities(
            call.hass, store.entry.entry_id, note_id, destination
        )

    return {"success": True, "note": updated_note.to_dict()}


async def handle_delete_note(call: ServiceCall) -> ServiceResponse:
    """Delete a note and its associated entities."""
    store = _get_store(call.hass)
    note_id = call.data["note_id"]
    note = store.get_note(note_id)

    if note is None:
        raise ServiceValidationError(
            f"Note '{note_id}' not found",
            translation_domain=DOMAIN,
            translation_key="note.note_not_found",
            translation_placeholders={"note_id": note_id},
        )

    success = await store.async_delete_note(note_id)
    if not success:
        raise ServiceValidationError(
            f"Failed to delete note '{note_id}'",
            translation_domain=DOMAIN,
            translation_key="note.delete_failed",
        )

    async_remove_note_entities(call.hass, note_id)

    return {"success": True}


async def handle_delete_category(call: ServiceCall) -> ServiceResponse:
    """Delete a category, cascade-deleting its notes only if asked to.

    The cascade destroys an arbitrary number of Notes, so ``force`` is the
    opt-in. Since ADR-0003 a caller who wants to keep them can move them out
    with ``note_update_note`` first, which turns the refusal into an
    instruction rather than a dead end. The panel already type-gates the
    deletion behind the Category's name, so it passes ``force: true`` and
    nothing changes there; what the flag guards is this surface, which
    ``services.yaml`` points AI assistants straight at. Issue #45.
    """
    store = _get_store(call.hass)
    category_id = call.data["category_id"]

    category = store.get_category(category_id)
    if category is None:
        raise ServiceValidationError(
            f"Category '{category_id}' not found",
            translation_domain=DOMAIN,
            translation_key="note.category_not_found",
            translation_placeholders={"category_id": category_id},
        )

    # ``websocket_delete_category`` guards identically and words it the same
    # way; the two surfaces duplicate the cascade itself already, and the
    # wording is the part that must not drift.
    notes = store.get_notes_by_category(category_id)
    if notes and not call.data.get("force", False):
        raise ServiceValidationError(
            f"Category '{category.name}' still holds {len(notes)} note(s), "
            f"and deleting it deletes them too. Pass force: true to confirm.",
            translation_domain=DOMAIN,
            translation_key="note.category_not_empty",
            translation_placeholders={
                "name": category.name,
                "note_count": str(len(notes)),
            },
        )

    # Cascade-delete all notes in this category first
    for note in notes:
        await store.async_delete_note(note.id)
        async_remove_note_entities(call.hass, note.id)

    success = await store.async_delete_category(category_id)
    if not success:
        raise ServiceValidationError(
            f"Failed to delete category '{category_id}'",
            translation_domain=DOMAIN,
            translation_key="note.delete_category_failed",
        )

    # Clean up device registry entry
    dev_reg = dr.async_get(call.hass)
    device = dev_reg.async_get_device(
        identifiers={(DOMAIN, device_id(AREA, category_id))}
    )
    if device:
        dev_reg.async_remove_device(device.id)

    return {"success": True}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

# Field names, requiredness and types mirror this Area's WebSocket commands;
# ``services.yaml`` is the reference where no command covers the operation.
# This Area's commands add no value-domain checks beyond that, so the two
# surfaces now agree field for field. The length limits stay where they were,
# in the handlers, which report them in the caller's language.
#
# No optional field carries a ``default=`` either. Handlers read absence with
# ``"field" in call.data`` and treat it as "leave unchanged", so a default
# would turn every omitted field into an explicit overwrite — on the update
# verbs that silently rewrites data the caller never mentioned.
SERVICE_HANDLERS = {
    # Query — ONLY
    "list_notes": (
        handle_list_notes,
        SupportsResponse.ONLY,
        vol.Schema({}),
    ),
    "get_note": (
        handle_get_note,
        SupportsResponse.ONLY,
        vol.Schema({vol.Required("note_id"): cv.string}),
    ),
    "list_categories": (
        handle_list_categories,
        SupportsResponse.ONLY,
        vol.Schema({}),
    ),
    "export_markdown": (
        handle_export_markdown,
        SupportsResponse.ONLY,
        vol.Schema({}),
    ),
    # Note CRUD — OPTIONAL
    "create_note": (
        handle_create_note,
        SupportsResponse.OPTIONAL,
        vol.Schema(
            {
                vol.Required("category_id"): cv.string,
                vol.Required("title"): cv.string,
                vol.Optional("content"): cv.string,
                vol.Optional("pinned"): cv.boolean,
            }
        ),
    ),
    "update_note": (
        handle_update_note,
        SupportsResponse.OPTIONAL,
        vol.Schema(
            {
                vol.Required("note_id"): cv.string,
                vol.Optional("category_id"): cv.string,
                vol.Optional("title"): cv.string,
                vol.Optional("content"): cv.string,
                vol.Optional("pinned"): cv.boolean,
            }
        ),
    ),
    "delete_note": (
        handle_delete_note,
        SupportsResponse.OPTIONAL,
        vol.Schema({vol.Required("note_id"): cv.string}),
    ),
    # Category CRUD — OPTIONAL
    "create_category": (
        handle_create_category,
        SupportsResponse.OPTIONAL,
        vol.Schema({vol.Required("name"): cv.string}),
    ),
    "delete_category": (
        handle_delete_category,
        SupportsResponse.OPTIONAL,
        vol.Schema(
            {
                vol.Required("category_id"): cv.string,
                vol.Optional("force"): cv.boolean,
            }
        ),
    ),
}
