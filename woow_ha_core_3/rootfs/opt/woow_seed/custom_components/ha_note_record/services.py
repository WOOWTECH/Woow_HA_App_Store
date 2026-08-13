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

from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .const import (
    DOMAIN,
    MAX_CATEGORY_NAME_LENGTH,
    MAX_NOTE_CONTENT_LENGTH,
    MAX_NOTE_TITLE_LENGTH,
)
from .store import HaNoteRecordStore

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_store(hass: HomeAssistant) -> HaNoteRecordStore:
    """Retrieve the HaNoteRecordStore from hass.data."""
    store = None
    if DOMAIN in hass.data:
        store = hass.data[DOMAIN].get("store")
    if store is None:
        raise ServiceValidationError(
            "Note Record integration is not configured",
            translation_domain=DOMAIN,
            translation_key="not_configured",
        )
    return store


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
            translation_key="note_not_found",
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

    # Build category name lookup
    cat_map = {c.id: c.name for c in store.categories}

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
            translation_key="category_name_required",
        )

    if len(name) > MAX_CATEGORY_NAME_LENGTH:
        raise ServiceValidationError(
            f"Category name exceeds maximum length of {MAX_CATEGORY_NAME_LENGTH} characters",
            translation_domain=DOMAIN,
            translation_key="category_name_too_long",
            translation_placeholders={"max_length": str(MAX_CATEGORY_NAME_LENGTH)},
        )

    # Case-insensitive duplicate check
    for category in store.categories:
        if category.name.lower() == name.lower():
            raise ServiceValidationError(
                "Category already exists",
                translation_domain=DOMAIN,
                translation_key="category_duplicate",
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
            translation_key="title_required",
        )

    if len(title) > MAX_NOTE_TITLE_LENGTH:
        raise ServiceValidationError(
            f"Note title exceeds maximum length of {MAX_NOTE_TITLE_LENGTH} characters",
            translation_domain=DOMAIN,
            translation_key="title_too_long",
            translation_placeholders={"max_length": str(MAX_NOTE_TITLE_LENGTH)},
        )

    if len(content) > MAX_NOTE_CONTENT_LENGTH:
        raise ServiceValidationError(
            f"Note content exceeds maximum length of {MAX_NOTE_CONTENT_LENGTH} characters",
            translation_domain=DOMAIN,
            translation_key="content_too_long",
            translation_placeholders={"max_length": str(MAX_NOTE_CONTENT_LENGTH)},
        )

    if not store.get_category(category_id):
        raise ServiceValidationError(
            f"Category '{category_id}' not found",
            translation_domain=DOMAIN,
            translation_key="category_not_found",
            translation_placeholders={"category_id": category_id},
        )

    # Case-insensitive duplicate title check within category
    for note in store.get_notes_by_category(category_id):
        if note.title.lower() == title.lower():
            raise ServiceValidationError(
                "Note title already exists in this category",
                translation_domain=DOMAIN,
                translation_key="title_duplicate",
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
            translation_key="create_failed",
        )

    return {"success": True, "note": note.to_dict()}


async def handle_update_note(call: ServiceCall) -> ServiceResponse:
    """Update one or more fields on an existing note."""
    store = _get_store(call.hass)
    note_id = call.data["note_id"]
    note = store.get_note(note_id)

    if note is None:
        raise ServiceValidationError(
            f"Note '{note_id}' not found",
            translation_domain=DOMAIN,
            translation_key="note_not_found",
            translation_placeholders={"note_id": note_id},
        )

    # Validate title if provided
    title = None
    if "title" in call.data:
        title = call.data["title"].strip()
        if not title:
            raise ServiceValidationError(
                "Note title is required",
                translation_domain=DOMAIN,
                translation_key="title_required",
            )

        if len(title) > MAX_NOTE_TITLE_LENGTH:
            raise ServiceValidationError(
                f"Note title exceeds maximum length of {MAX_NOTE_TITLE_LENGTH} characters",
                translation_domain=DOMAIN,
                translation_key="title_too_long",
                translation_placeholders={"max_length": str(MAX_NOTE_TITLE_LENGTH)},
            )

        # Case-insensitive duplicate title check (excluding current note)
        for other_note in store.get_notes_by_category(note.category_id):
            if other_note.id != note_id and other_note.title.lower() == title.lower():
                raise ServiceValidationError(
                    "Note title already exists in this category",
                    translation_domain=DOMAIN,
                    translation_key="title_duplicate",
                )

    # Validate content if provided
    content = None
    if "content" in call.data:
        content = call.data["content"]
        if len(content) > MAX_NOTE_CONTENT_LENGTH:
            raise ServiceValidationError(
                f"Note content exceeds maximum length of {MAX_NOTE_CONTENT_LENGTH} characters",
                translation_domain=DOMAIN,
                translation_key="content_too_long",
                translation_placeholders={"max_length": str(MAX_NOTE_CONTENT_LENGTH)},
            )

    # Get pinned if provided
    pinned = call.data.get("pinned") if "pinned" in call.data else None

    # Apply all updates atomically
    await store.async_update_note(
        note_id, title=title, content=content, pinned=pinned
    )

    updated_note = store.get_note(note_id)
    if updated_note is None:
        raise ServiceValidationError(
            "Failed to update note",
            translation_domain=DOMAIN,
            translation_key="update_failed",
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
            translation_key="note_not_found",
            translation_placeholders={"note_id": note_id},
        )

    category_id = note.category_id

    success = await store.async_delete_note(note_id)
    if not success:
        raise ServiceValidationError(
            f"Failed to delete note '{note_id}'",
            translation_domain=DOMAIN,
            translation_key="delete_failed",
        )

    # Clean up entity registry entries
    ent_reg = er.async_get(call.hass)
    for platform, suffix in [("text", "_content"), ("switch", "_pinned")]:
        unique_id = f"{DOMAIN}_{category_id}_{note_id}{suffix}"
        entity_id = ent_reg.async_get_entity_id(platform, DOMAIN, unique_id)
        if entity_id:
            ent_reg.async_remove(entity_id)

    return {"success": True}


async def handle_delete_category(call: ServiceCall) -> ServiceResponse:
    """Delete a category and cascade-delete all notes in it."""
    store = _get_store(call.hass)
    category_id = call.data["category_id"]

    if store.get_category(category_id) is None:
        raise ServiceValidationError(
            f"Category '{category_id}' not found",
            translation_domain=DOMAIN,
            translation_key="category_not_found",
            translation_placeholders={"category_id": category_id},
        )

    # Cascade-delete all notes in this category first
    notes = store.get_notes_by_category(category_id)
    ent_reg = er.async_get(call.hass)
    for note in notes:
        await store.async_delete_note(note.id)
        # Clean up entity registry entries for each deleted note
        for platform, suffix in [("text", "_content"), ("switch", "_pinned")]:
            unique_id = f"{DOMAIN}_{category_id}_{note.id}{suffix}"
            entity_id = ent_reg.async_get_entity_id(platform, DOMAIN, unique_id)
            if entity_id:
                ent_reg.async_remove(entity_id)

    success = await store.async_delete_category(category_id)
    if not success:
        raise ServiceValidationError(
            f"Failed to delete category '{category_id}'",
            translation_domain=DOMAIN,
            translation_key="delete_category_failed",
        )

    # Clean up device registry entry
    dev_reg = dr.async_get(call.hass)
    device = dev_reg.async_get_device(identifiers={(DOMAIN, category_id)})
    if device:
        dev_reg.async_remove_device(device.id)

    return {"success": True}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

_SERVICE_HANDLERS = {
    # Query — ONLY
    "list_notes": (handle_list_notes, SupportsResponse.ONLY),
    "get_note": (handle_get_note, SupportsResponse.ONLY),
    "list_categories": (handle_list_categories, SupportsResponse.ONLY),
    "export_markdown": (handle_export_markdown, SupportsResponse.ONLY),
    # Note CRUD — OPTIONAL
    "create_note": (handle_create_note, SupportsResponse.OPTIONAL),
    "update_note": (handle_update_note, SupportsResponse.OPTIONAL),
    "delete_note": (handle_delete_note, SupportsResponse.OPTIONAL),
    # Category CRUD — OPTIONAL
    "create_category": (handle_create_category, SupportsResponse.OPTIONAL),
    "delete_category": (handle_delete_category, SupportsResponse.OPTIONAL),
}


def async_register_services(hass: HomeAssistant) -> None:
    """Register all ha_note_record services."""
    for name, (handler, response_type) in _SERVICE_HANDLERS.items():
        hass.services.async_register(
            DOMAIN,
            name,
            handler,
            supports_response=response_type,
        )
    _LOGGER.debug("Registered %d services for %s", len(_SERVICE_HANDLERS), DOMAIN)


def async_unregister_services(hass: HomeAssistant) -> None:
    """Remove all ha_note_record services."""
    for name in _SERVICE_HANDLERS:
        hass.services.async_remove(DOMAIN, name)
    _LOGGER.debug("Unregistered services for %s", DOMAIN)
