"""Config flow for Ha Note Record integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    ACTION_CREATE_CATEGORY,
    ACTION_CREATE_NOTE,
    ACTION_DELETE_CATEGORY,
    ACTION_DELETE_NOTE,
    DEFAULT_CONTENT,
    DEFAULT_PINNED,
    DOMAIN,
)
from .store import HaNoteRecordStore

_LOGGER = logging.getLogger(__name__)

# Translation keys for action labels
ACTION_LABELS = {
    ACTION_CREATE_CATEGORY: "create_category",
    ACTION_CREATE_NOTE: "create_note",
    ACTION_DELETE_NOTE: "delete_note",
    ACTION_DELETE_CATEGORY: "delete_category",
}


class HaNoteRecordConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Ha Note Record."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        # Only allow one instance
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            return self.async_create_entry(title="Ha Note Record", data={})

        return self.async_show_form(
            step_id="user",
            description_placeholders={},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Get the options flow for this handler."""
        return HaNoteRecordOptionsFlow(config_entry)


class HaNoteRecordOptionsFlow(OptionsFlow):
    """Handle options flow for Ha Note Record."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    @property
    def _store(self) -> HaNoteRecordStore:
        """Get the store from runtime data."""
        return self._config_entry.runtime_data

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial options step - action selection."""
        if user_input is not None:
            action = user_input.get("action")
            if action == ACTION_CREATE_CATEGORY:
                return await self.async_step_create_category()
            if action == ACTION_CREATE_NOTE:
                return await self.async_step_create_note()
            if action == ACTION_DELETE_NOTE:
                return await self.async_step_delete_note()
            if action == ACTION_DELETE_CATEGORY:
                return await self.async_step_delete_category()

        # Build action options using translation keys
        actions = [
            selector.SelectOptionDict(
                value=ACTION_CREATE_CATEGORY,
                label=ACTION_LABELS[ACTION_CREATE_CATEGORY],
            ),
        ]

        # Only show note-related options if categories exist
        if self._store.categories:
            actions.append(
                selector.SelectOptionDict(
                    value=ACTION_CREATE_NOTE,
                    label=ACTION_LABELS[ACTION_CREATE_NOTE],
                )
            )

        # Only show delete note if notes exist
        if self._store.notes:
            actions.append(
                selector.SelectOptionDict(
                    value=ACTION_DELETE_NOTE,
                    label=ACTION_LABELS[ACTION_DELETE_NOTE],
                )
            )

        # Only show delete category if categories exist
        if self._store.categories:
            actions.append(
                selector.SelectOptionDict(
                    value=ACTION_DELETE_CATEGORY,
                    label=ACTION_LABELS[ACTION_DELETE_CATEGORY],
                )
            )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required("action"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=actions,
                            mode=selector.SelectSelectorMode.LIST,
                            translation_key="action",
                        )
                    ),
                }
            ),
        )

    async def async_step_create_category(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle create category step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            name = user_input.get("name", "").strip()
            if not name:
                errors["name"] = "name_required"
            else:
                # Check for duplicate name
                for category in self._store.categories:
                    if category.name.lower() == name.lower():
                        errors["name"] = "name_exists"
                        break

            if not errors:
                await self._store.async_create_category(name)
                return self.async_create_entry(data={})

        return self.async_show_form(
            step_id="create_category",
            data_schema=vol.Schema(
                {
                    vol.Required("name"): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_create_note(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle create note step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            category_id = user_input.get("category")
            title = user_input.get("title", "").strip()
            content = user_input.get("content", DEFAULT_CONTENT)
            pinned = user_input.get("pinned", DEFAULT_PINNED)

            if not title:
                errors["title"] = "title_required"
            elif category_id:
                # Check for duplicate title within the same category
                for note in self._store.get_notes_by_category(category_id):
                    if note.title.lower() == title.lower():
                        errors["title"] = "title_exists"
                        break

            if not category_id:
                errors["category"] = "category_required"

            if not errors:
                await self._store.async_create_note(
                    category_id=category_id,
                    title=title,
                    content=content,
                    pinned=pinned,
                )
                return self.async_create_entry(data={})

        # Build category options
        category_options = [
            selector.SelectOptionDict(value=c.id, label=c.name)
            for c in self._store.categories
        ]

        return self.async_show_form(
            step_id="create_note",
            data_schema=vol.Schema(
                {
                    vol.Required("category"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=category_options,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Required("title"): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
                    ),
                    vol.Optional("content", default=DEFAULT_CONTENT): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT,
                            multiline=True,
                        )
                    ),
                    vol.Optional("pinned", default=DEFAULT_PINNED): selector.BooleanSelector(),
                }
            ),
            errors=errors,
        )

    async def async_step_delete_note(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle delete note step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            note_id = user_input.get("note")
            if note_id:
                await self._store.async_delete_note(note_id)
                return self.async_create_entry(data={})
            errors["note"] = "note_required"

        # Build note options with category prefix
        note_options = []
        for note in self._store.notes:
            category = self._store.get_category(note.category_id)
            category_name = category.name if category else "Unknown"
            note_options.append(
                selector.SelectOptionDict(
                    value=note.id,
                    label=f"{category_name} / {note.title}",
                )
            )

        if not note_options:
            return self.async_abort(reason="no_notes")

        return self.async_show_form(
            step_id="delete_note",
            data_schema=vol.Schema(
                {
                    vol.Required("note"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=note_options,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_delete_category(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle delete category step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            category_id = user_input.get("category")
            if category_id:
                # Check if category has notes
                notes = self._store.get_notes_by_category(category_id)
                if notes:
                    errors["category"] = "category_not_empty"
                else:
                    await self._store.async_delete_category(category_id)
                    return self.async_create_entry(data={})
            else:
                errors["category"] = "category_required"

        # Build category options with note count
        category_options = []
        for category in self._store.categories:
            note_count = len(self._store.get_notes_by_category(category.id))
            label = f"{category.name} ({note_count} notes)"
            category_options.append(
                selector.SelectOptionDict(value=category.id, label=label)
            )

        if not category_options:
            return self.async_abort(reason="no_categories")

        return self.async_show_form(
            step_id="delete_category",
            data_schema=vol.Schema(
                {
                    vol.Required("category"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=category_options,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
            errors=errors,
        )
