"""Base entity for Ha Note Record integration.

Provides the common base class for all note record entities (text and switch),
including shared device info, the no-poll update pattern, and the
length-bounded entity_id every note entity suggests to Home Assistant.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Final

from homeassistant.const import MAX_LENGTH_STATE_ENTITY_ID
from homeassistant.core import HomeAssistant, callback, valid_entity_id
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.util import slugify

from ...const import device_id, unique_id
from .const import AREA, DOMAIN
from .store import Category, HaNoteRecordStore, Note

_LOGGER = logging.getLogger(__name__)

# Hex characters of the note-id digest appended to a truncated object_id.
ENTITY_ID_HASH_LENGTH = 8

# Characters held back from the object_id budget, so an entity_id that is
# already taken can be suffixed with "_2", "_3" and so on without Home
# Assistant having to cut the string to make room.
ENTITY_ID_COLLISION_RESERVE = 10

# The device every note category presents in the device registry.
DEVICE_MANUFACTURER: Final = "Ha Note Record"
DEVICE_MODEL: Final = "Note Category"

# The two entities every note owns, as (platform, unique_id suffix). The move
# and delete paths both reach for a note's entities in the registry, and
# neither can keep its own copy of the shape without drifting from the entity
# classes that register it.
NOTE_ENTITIES: Final[tuple[tuple[str, str], ...]] = (
    ("text", "content"),
    ("switch", "pinned"),
)


def note_unique_id(note_id: str, suffix: str) -> str:
    """Return the unique_id of one of a note's entities.

    The category is absent by ADR-0003: it is an attribute of a note, not part
    of its identity, which is what lets a note move between categories without
    the move becoming an identity change.
    """
    return unique_id(AREA, note_id, suffix)


@callback
def async_move_note_entities(
    hass: HomeAssistant,
    entry_id: str,
    note_id: str,
    category: Category,
) -> None:
    """Re-point a moved note's entities at the destination category's device.

    Home Assistant reads ``device_info`` once, when an entity is added, and
    never again, so nothing about a move reaches the device registry on its
    own -- the note's entities would keep hanging off the category it left
    until the next restart rebuilt them. Updating the registry entry directly
    is what moves them now.

    The destination device is created if the category held no notes yet, since
    a category's device exists only once something has been added under it.
    The source category keeps its device even when this empties it: the
    category still exists, and only deleting one removes its device.
    """
    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_or_create(
        config_entry_id=entry_id,
        identifiers={(DOMAIN, device_id(AREA, category.id))},
        name=category.name,
        manufacturer=DEVICE_MANUFACTURER,
        model=DEVICE_MODEL,
    )

    ent_reg = er.async_get(hass)
    for platform, suffix in NOTE_ENTITIES:
        entity_id = ent_reg.async_get_entity_id(
            platform, DOMAIN, note_unique_id(note_id, suffix)
        )
        if entity_id:
            ent_reg.async_update_entity(entity_id, device_id=device.id)


@callback
def async_remove_note_entities(hass: HomeAssistant, note_id: str) -> None:
    """Remove a deleted note's entities from the entity registry."""
    ent_reg = er.async_get(hass)
    for platform, suffix in NOTE_ENTITIES:
        entity_id = ent_reg.async_get_entity_id(
            platform, DOMAIN, note_unique_id(note_id, suffix)
        )
        if entity_id:
            ent_reg.async_remove(entity_id)


def note_entity_id(
    entity_id_format: str,
    entity_name: str,
    note_id: str,
) -> str:
    """Return a length-bounded entity_id for a note entity.

    Home Assistant derives an object_id from the device name and the entity
    name, and a note title may be up to ``MAX_NOTE_TITLE_LENGTH`` (200)
    characters. Slugifying romanises each CJK character into several ASCII
    ones, so that object_id can run several times past the 255-character
    entity_id limit. Home Assistant truncates to 255, and that cut can land on
    an underscore -- an entity_id ``valid_entity_id`` rejects, which makes
    every state write for the note raise.

    So bound the object_id here instead. A name that fits keeps the slug Home
    Assistant would derive from the entity name, so short-titled notes read
    naturally. A longer one is cut to the budget and given a short digest of
    the note id, which keeps it unique between notes and stable across
    restarts.

    The category is deliberately absent. Home Assistant would compose from
    ``device.name_by_user or device.name`` -- the category's device -- and this
    once copied that by slugifying the category name alongside the entity name.
    A category name in the object_id is a snapshot, and ADR-0003 made a note
    movable between categories, so every such snapshot would go stale on the
    first move. Leaving it out is what stops an entity_id naming a category the
    note has left. Two notes with the same title in different categories now
    collide, and Home Assistant suffixes the second ``_2`` --
    ``ENTITY_ID_COLLISION_RESERVE`` holds back the room for it.
    """
    object_id = slugify(entity_name)
    budget = (
        MAX_LENGTH_STATE_ENTITY_ID
        - len(entity_id_format.format(""))
        - ENTITY_ID_COLLISION_RESERVE
    )
    if len(object_id) > budget:
        digest = hashlib.sha256(note_id.encode("utf-8")).hexdigest()[
            :ENTITY_ID_HASH_LENGTH
        ]
        head = object_id[: budget - len(digest) - 1].rstrip("_")
        object_id = f"{head}_{digest}"

    return entity_id_format.format(object_id)


class HaNoteRecordEntity(Entity):
    """Base class for Ha Note Record entities.

    Provides ``has_entity_name = True`` and ``should_poll = False`` for the
    text and switch entity platforms.

    Each note category creates a device with
    ``identifiers = {(DOMAIN, category_id)}``, so every note entity that
    belongs to the same category is grouped under one device.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        store: HaNoteRecordStore,
        note: Note,
        category: Category,
    ) -> None:
        """Initialize the entity."""
        self._store = store
        self._note = note
        self._category = category
        self._note_exists = True

    async def async_added_to_hass(self) -> None:
        """Follow the store for the life of the entity.

        Every write path edits the store and nothing else, so without this an
        edit made through a service or a WebSocket command sits in the store
        unread until something else happens to write state. A move is the case
        that made this necessary -- the entity registry moves the entity to the
        destination device immediately, and the ``category`` attribute would
        otherwise still name the source until the next restart.
        """
        await super().async_added_to_hass()
        self.async_on_remove(self._store.async_add_listener(self._handle_store_update))

    @callback
    def _handle_store_update(self) -> None:
        """Write state after any store change."""
        self._refresh_note()
        self.async_write_ha_state()

    def _apply_entity_id(self, entity_id_format: str) -> None:
        """Suggest a length-bounded entity_id to Home Assistant.

        Call after ``_attr_name`` is set: Home Assistant takes an entity_id set
        by the platform as its suggestion, so this is what bounds the object_id
        before it reaches ``async_generate_entity_id``. A note already in the
        entity registry keeps the entity_id it was given -- see
        ``async_repair_registry_entity_id`` for the ones that are unusable.
        """
        self.entity_id = note_entity_id(
            entity_id_format,
            self._attr_name or "",
            self._note.id,
        )

    @callback
    def async_repair_registry_entity_id(self, hass: HomeAssistant) -> None:
        """Rename a registry entry Home Assistant would refuse to serve.

        A note created before entity_ids were bounded left an over-long,
        invalid entity_id in the registry, and ``async_get_or_create`` hands
        that stored id straight back -- so bounding new ones is not enough on
        its own. Renaming the entry is what stops the note raising on every
        restart.
        """
        domain, object_id = self.entity_id.split(".", 1)
        ent_reg = er.async_get(hass)
        registered = ent_reg.async_get_entity_id(domain, DOMAIN, self.unique_id)
        if registered is None or valid_entity_id(registered):
            return

        repaired = ent_reg.async_generate_entity_id(domain, object_id)
        ent_reg.async_update_entity(registered, new_entity_id=repaired)
        _LOGGER.info(
            "Renamed unusable entity_id for note %s: %s", self._note.id, repaired
        )

    @property
    def note_id(self) -> str:
        """Return the note ID."""
        return self._note.id

    @property
    def available(self) -> bool:
        """Return True if the entity is available."""
        return self._note_exists and self._store.get_note(self._note.id) is not None

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, device_id(AREA, self._category.id))},
            name=self._category.name,
            manufacturer=DEVICE_MANUFACTURER,
            model=DEVICE_MODEL,
        )

    def _refresh_note(self) -> bool:
        """Refresh note data from store.

        Refreshes the category with it. A note can move between categories
        (ADR-0003), so the category held here is as mutable as the note is --
        leaving it behind would have the ``category`` attribute keep naming the
        one the note left.

        Returns True if note still exists, False otherwise.
        """
        note = self._store.get_note(self._note.id)
        if note:
            self._note = note
            category = self._store.get_category(note.category_id)
            if category:
                self._category = category
            self._note_exists = True
            return True
        self._note_exists = False
        return False
