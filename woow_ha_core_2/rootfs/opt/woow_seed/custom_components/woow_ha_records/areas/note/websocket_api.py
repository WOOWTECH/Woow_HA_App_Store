"""WebSocket API for Ha Note Record integration.

Provides note management with categories through Home Assistant's
WebSocket interface. All commands use the ``ha_note_record/`` prefix.

Commands
--------
ha_note_record/get_data
    Retrieve all categories and notes. No parameters required.
    Permission: public (no admin required).

ha_note_record/create_category
    Create a new category.
    Parameters: name (str, required).
    Permission: admin required.

ha_note_record/create_note
    Create a new note within a category.
    Parameters: category_id (str, required), title (str, required),
    content (str, optional), pinned (bool, optional).
    Permission: admin required.

ha_note_record/update_note
    Update an existing note, including moving it to another category.
    Parameters: note_id (str, required), category_id (str, optional),
    title (str, optional), content (str, optional), pinned (bool, optional).
    Permission: admin required.

ha_note_record/delete_note
    Delete a note and its associated entities.
    Parameters: note_id (str, required).
    Permission: admin required.

ha_note_record/delete_category
    Delete a category, with cascade deletion of all its notes.
    Parameters: category_id (str, required), force (bool, optional).
    Permission: admin required.

Permission model
----------------
``get_data`` is public and available to all authenticated users.
All write operations (create, update, delete) require admin privileges
enforced via the ``@websocket_api.require_admin`` decorator.

Validation constants
--------------------
- ``MAX_CATEGORY_NAME_LENGTH`` = 100
- ``MAX_NOTE_TITLE_LENGTH`` = 200
- ``MAX_NOTE_CONTENT_LENGTH`` = 100000

Duplicate name checks
---------------------
Category names and note titles (within the same category) are checked
for uniqueness using case-insensitive comparison (``str.lower()``).

Cascade delete behavior
-----------------------
Deleting a category triggers a cascade that removes all notes belonging
to that category, cleans up their text and switch entities from the
entity registry, and removes the category's device from the device
registry. It is opt-in: a category that still holds notes is refused
unless the caller passes ``force``. A caller who wants to keep those
notes can now move them out first with ``update_note``, which is what
ADR-0003 made possible.

Error codes
-----------
- ``not_found``      -- Store not initialized, category not found, or note not found.
- ``invalid_input``  -- Empty name/title after trimming, or value exceeds max length.
- ``duplicate``      -- Case-insensitive duplicate category name or note title.
- ``not_empty``      -- Category still holds notes and ``force`` was not set.
- ``error``          -- Generic failure during create, update, or delete operations.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
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


def async_register_websocket_api(hass: HomeAssistant) -> None:
    """Register WebSocket API handlers."""
    websocket_api.async_register_command(hass, websocket_get_data)
    websocket_api.async_register_command(hass, websocket_create_category)
    websocket_api.async_register_command(hass, websocket_create_note)
    websocket_api.async_register_command(hass, websocket_update_note)
    websocket_api.async_register_command(hass, websocket_delete_note)
    websocket_api.async_register_command(hass, websocket_delete_category)


def _get_store(hass: HomeAssistant) -> HaNoteRecordStore:
    """Return the note Area's store."""
    return get_data(hass).note


@websocket_api.websocket_command(
    {
        vol.Required("type"): "woow_ha_records/note/get_data",
    }
)
@callback
def websocket_get_data(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Handle ``ha_note_record/get_data`` WebSocket command.

    Retrieve all categories and notes from the store.

    Parameters
    ----------
    No additional parameters beyond the required ``type``.

    Permission
    ----------
    Public -- no admin privileges required.

    Returns
    -------
    dict
        ``categories`` : list of category dicts, each containing
        ``{id, name, created_at, updated_at}``.
        ``notes`` : list of note dicts, each containing
        ``{id, category_id, title, content, pinned, created_at, updated_at}``.

    Errors
    ------
    not_found
        Store is not initialized (integration not loaded).
    """
    store = _get_store(hass)
    if store is None:
        connection.send_error(msg["id"], "not_found", "Store not initialized")
        return

    connection.send_result(
        msg["id"],
        {
            "categories": [c.to_dict() for c in store.categories],
            "notes": [n.to_dict() for n in store.notes],
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "woow_ha_records/note/create_category",
        vol.Required("name"): str,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_create_category(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Handle ``ha_note_record/create_category`` WebSocket command.

    Create a new category for organizing notes.

    Parameters
    ----------
    name : str, required
        Category name. Whitespace is trimmed from both ends. Cannot be
        empty after trimming. Maximum length is ``MAX_CATEGORY_NAME_LENGTH``
        (100 characters).

    Permission
    ----------
    Admin required.

    Returns
    -------
    dict
        The created category: ``{id, name, created_at, updated_at}``.

    Errors
    ------
    not_found
        Store is not initialized.
    invalid_input
        Name is empty after trimming, or exceeds the maximum length
        of 100 characters.
    duplicate
        A category with the same name already exists
        (case-insensitive comparison).
    """
    store = _get_store(hass)
    if store is None:
        connection.send_error(msg["id"], "not_found", "Store not initialized")
        return

    name = msg["name"].strip()
    if not name:
        connection.send_error(msg["id"], "invalid_input", "Category name is required")
        return

    if len(name) > MAX_CATEGORY_NAME_LENGTH:
        connection.send_error(
            msg["id"],
            "invalid_input",
            f"Category name exceeds maximum length of "
            f"{MAX_CATEGORY_NAME_LENGTH} characters",
        )
        return

    # Check for duplicate name
    for category in store.categories:
        if category.name.lower() == name.lower():
            connection.send_error(msg["id"], "duplicate", "Category already exists")
            return

    category = await store.async_create_category(name)
    connection.send_result(msg["id"], category.to_dict())


@websocket_api.websocket_command(
    {
        vol.Required("type"): "woow_ha_records/note/create_note",
        vol.Required("category_id"): str,
        vol.Required("title"): str,
        vol.Optional("content", default=""): str,
        vol.Optional("pinned", default=False): bool,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_create_note(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Handle ``ha_note_record/create_note`` WebSocket command.

    Create a new note within the specified category.

    Parameters
    ----------
    category_id : str, required
        The ID of the category to create the note in.
    title : str, required
        Note title. Whitespace is trimmed from both ends. Cannot be
        empty after trimming. Maximum length is ``MAX_NOTE_TITLE_LENGTH``
        (200 characters).
    content : str, optional
        Note body text. Defaults to ``""``. Maximum length is
        ``MAX_NOTE_CONTENT_LENGTH`` (100000 characters).
    pinned : bool, optional
        Whether the note is pinned. Defaults to ``False``.

    Permission
    ----------
    Admin required.

    Returns
    -------
    dict
        The created note:
        ``{id, category_id, title, content, pinned, created_at, updated_at}``.

    Errors
    ------
    not_found
        Store is not initialized, or the specified category does not exist.
    invalid_input
        Title is empty after trimming, title exceeds 200 characters,
        or content exceeds 100000 characters.
    duplicate
        A note with the same title already exists in the category
        (case-insensitive comparison).
    error
        Note creation failed in the store.

    Side effects
    ------------
    Creates a text entity for the note content and a switch entity for
    the pinned status.
    """
    store = _get_store(hass)
    if store is None:
        connection.send_error(msg["id"], "not_found", "Store not initialized")
        return

    category_id = msg["category_id"]
    title = msg["title"].strip()
    content = msg["content"]

    if not title:
        connection.send_error(msg["id"], "invalid_input", "Note title is required")
        return

    if len(title) > MAX_NOTE_TITLE_LENGTH:
        connection.send_error(
            msg["id"],
            "invalid_input",
            f"Note title exceeds maximum length of {MAX_NOTE_TITLE_LENGTH} characters",
        )
        return

    if len(content) > MAX_NOTE_CONTENT_LENGTH:
        connection.send_error(
            msg["id"],
            "invalid_input",
            f"Note content exceeds maximum length of "
            f"{MAX_NOTE_CONTENT_LENGTH} characters",
        )
        return

    if not store.get_category(category_id):
        connection.send_error(msg["id"], "not_found", "Category not found")
        return

    # Check for duplicate title in category
    for note in store.get_notes_by_category(category_id):
        if note.title.lower() == title.lower():
            connection.send_error(
                msg["id"],
                "duplicate",
                "Note title already exists in this category",
            )
            return

    note = await store.async_create_note(
        category_id=category_id,
        title=title,
        content=msg["content"],
        pinned=msg["pinned"],
    )

    if note is None:
        connection.send_error(msg["id"], "error", "Failed to create note")
        return

    connection.send_result(msg["id"], note.to_dict())


@websocket_api.websocket_command(
    {
        vol.Required("type"): "woow_ha_records/note/update_note",
        vol.Required("note_id"): str,
        vol.Optional("category_id"): str,
        vol.Optional("title"): str,
        vol.Optional("content"): str,
        vol.Optional("pinned"): bool,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_update_note(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Handle ``ha_note_record/update_note`` WebSocket command.

    Update an existing note. Only the fields provided in the message
    are modified; omitted fields remain unchanged.

    Parameters
    ----------
    note_id : str, required
        The ID of the note to update.
    category_id : str, optional
        Move the note to this category. The note keeps its title, content,
        pinned state and creation time; its entities are re-pointed at the
        destination category's device. Omit to leave the category unchanged.
        See ADR-0003.
    title : str, optional
        New title. Whitespace is trimmed from both ends. Cannot be
        empty after trimming. Maximum length is ``MAX_NOTE_TITLE_LENGTH``
        (200 characters).
    content : str, optional
        New body text. Maximum length is ``MAX_NOTE_CONTENT_LENGTH``
        (100000 characters).
    pinned : bool, optional
        New pinned status.

    Permission
    ----------
    Admin required.

    Returns
    -------
    dict
        The updated note:
        ``{id, category_id, title, content, pinned, created_at, updated_at}``.

    Errors
    ------
    not_found
        Store is not initialized, the note does not exist, or the
        destination category does not exist.
    invalid_input
        Title is empty after trimming, title exceeds 200 characters,
        or content exceeds 100000 characters.
    duplicate
        The title already exists for another note in the category the
        note will be in (case-insensitive comparison). A move is refused
        on this too, since it carries the note's title into a category
        that may already hold it.
    error
        Failed to retrieve the note after update.

    Side effects
    ------------
    On a move, re-points the note's text and switch entities at the
    destination category's device in the entity registry, creating that
    device if the category held no notes yet.
    """
    store = _get_store(hass)
    if store is None:
        connection.send_error(msg["id"], "not_found", "Store not initialized")
        return

    note_id = msg["note_id"]
    note = store.get_note(note_id)

    if note is None:
        connection.send_error(msg["id"], "not_found", "Note not found")
        return

    # Validate the destination category if a move was asked for. Nothing is
    # written until every check below passes, so a bad destination leaves the
    # note exactly as it was.
    destination = None
    category_id = note.category_id
    if "category_id" in msg:
        category_id = msg["category_id"]
        destination = store.get_category(category_id)
        if destination is None:
            connection.send_error(msg["id"], "not_found", "Category not found")
            return

    # Validate title if provided
    title = None
    if "title" in msg:
        title = msg["title"].strip()
        if not title:
            connection.send_error(msg["id"], "invalid_input", "Note title is required")
            return

        if len(title) > MAX_NOTE_TITLE_LENGTH:
            connection.send_error(
                msg["id"],
                "invalid_input",
                f"Note title exceeds maximum length of "
                f"{MAX_NOTE_TITLE_LENGTH} characters",
            )
            return

    # Case-insensitive duplicate title check, against the category the note
    # will be in and under the title it will have. A move carries the note's
    # existing title into a category that may already hold it, so the check
    # has to run for a move that renames nothing. It is skipped when neither
    # is changing, so an edit to content alone cannot be refused by a
    # duplicate that predates it. ``handle_update_note`` in services.py
    # applies the same rule; the two surfaces must not drift.
    moving = category_id != note.category_id
    renaming = title is not None and title.lower() != note.title.lower()
    if moving or renaming:
        new_title = title if title is not None else note.title
        for other_note in store.get_notes_by_category(category_id):
            if (
                other_note.id != note_id
                and other_note.title.lower() == new_title.lower()
            ):
                connection.send_error(
                    msg["id"],
                    "duplicate",
                    "Note title already exists in this category",
                )
                return

    # Validate content if provided
    content = None
    if "content" in msg:
        content = msg["content"]
        if len(content) > MAX_NOTE_CONTENT_LENGTH:
            connection.send_error(
                msg["id"],
                "invalid_input",
                f"Note content exceeds maximum length of "
                f"{MAX_NOTE_CONTENT_LENGTH} characters",
            )
            return

    # Get pinned if provided
    pinned = msg.get("pinned")

    # Apply all updates atomically (single save)
    await store.async_update_note(
        note_id,
        title=title,
        content=content,
        pinned=pinned,
        category_id=category_id if moving else None,
    )

    # Refresh note data
    updated_note = store.get_note(note_id)
    if updated_note is None:
        connection.send_error(msg["id"], "error", "Failed to update note")
        return

    # The store holds no registry, so the entities follow separately.
    if moving and destination is not None:
        async_move_note_entities(hass, store.entry.entry_id, note_id, destination)

    connection.send_result(msg["id"], updated_note.to_dict())


@websocket_api.websocket_command(
    {
        vol.Required("type"): "woow_ha_records/note/delete_note",
        vol.Required("note_id"): str,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_delete_note(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Handle ``ha_note_record/delete_note`` WebSocket command.

    Delete a single note and clean up its associated entities.

    Parameters
    ----------
    note_id : str, required
        The ID of the note to delete.

    Permission
    ----------
    Admin required.

    Returns
    -------
    dict
        ``{deleted: True}`` on success.

    Errors
    ------
    not_found
        Store is not initialized, or the note does not exist.
    error
        Deletion failed in the store.

    Side effects
    ------------
    Removes the text entity (``_content`` suffix) and switch entity
    (``_pinned`` suffix) from the entity registry.
    """
    store = _get_store(hass)
    if store is None:
        connection.send_error(msg["id"], "not_found", "Store not initialized")
        return

    note_id = msg["note_id"]

    note = store.get_note(note_id)
    if note is None:
        connection.send_error(msg["id"], "not_found", "Note not found")
        return

    success = await store.async_delete_note(note_id)
    if success:
        async_remove_note_entities(hass, note_id)
        connection.send_result(msg["id"], {"deleted": True})
    else:
        connection.send_error(msg["id"], "error", "Failed to delete note")


@websocket_api.websocket_command(
    {
        vol.Required("type"): "woow_ha_records/note/delete_category",
        vol.Required("category_id"): str,
        vol.Optional("force"): bool,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_delete_category(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Handle ``ha_note_record/delete_category`` WebSocket command.

    Delete a category, cascade-deleting its notes only if asked to.

    Parameters
    ----------
    category_id : str, required
        The ID of the category to delete.
    force : bool, optional
        Confirm that the notes in the category may be destroyed with it.
        Defaults to ``False``, which refuses a category that still holds
        notes and deletes nothing.

    Permission
    ----------
    Admin required.

    Returns
    -------
    dict
        ``{deleted: True}`` on success.

    Errors
    ------
    not_found
        Store is not initialized, or the category does not exist.
    not_empty
        The category still holds notes and ``force`` was not set. Nothing
        was deleted.
    error
        Category deletion failed in the store.

    Side effects
    ------------
    With ``force``, CASCADE deletes all notes belonging to the category.
    For each deleted note, removes its text entity (``_content`` suffix)
    and switch entity (``_pinned`` suffix) from the entity registry.
    After all notes are removed, deletes the category's device from
    the device registry.
    """
    store = _get_store(hass)
    if store is None:
        connection.send_error(msg["id"], "not_found", "Store not initialized")
        return

    category_id = msg["category_id"]

    category = store.get_category(category_id)
    if category is None:
        connection.send_error(msg["id"], "not_found", "Category not found")
        return

    # The cascade destroys an arbitrary number of notes, so it is opt-in. Since
    # ADR-0003 a caller who wants to keep them can move them out first, which
    # makes the refusal an instruction rather than a dead end. The panel
    # type-gates the deletion behind the category's name and passes ``force``.
    # Issue #45.
    #
    # ``handle_delete_category`` in services.py guards identically and words it
    # the same way; the two surfaces duplicate the cascade itself already, and
    # the wording is the part that must not drift.
    notes = store.get_notes_by_category(category_id)
    if notes and not msg.get("force", False):
        connection.send_error(
            msg["id"],
            "not_empty",
            f"Category '{category.name}' still holds {len(notes)} note(s), "
            f"and deleting it deletes them too. Pass force: true to confirm.",
        )
        return

    # Cascade-delete all notes in this category first
    for note in notes:
        await store.async_delete_note(note.id)
        async_remove_note_entities(hass, note.id)

    success = await store.async_delete_category(category_id)
    if success:
        # Clean up device registry entry
        dev_reg = dr.async_get(hass)
        device = dev_reg.async_get_device(
            identifiers={(DOMAIN, device_id(AREA, category_id))}
        )
        if device:
            dev_reg.async_remove_device(device.id)
        connection.send_result(msg["id"], {"deleted": True})
    else:
        connection.send_error(msg["id"], "error", "Failed to delete category")
