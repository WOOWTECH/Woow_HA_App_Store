// Local vendor bundles (lit-element 2.4.0, marked 9.1.6, dompurify 3.0.6)
// These are self-contained ESM builds so the panel works without external network access.
import {
  LitElement,
  html,
  css,
  unsafeCSS,
} from "./vendor/lit-element.esm.js";

import { marked } from "./vendor/marked.esm.js";
import DOMPurify from "./vendor/dompurify.esm.js";

// Translations are loaded from a local JSON file at init time.
// The _translations module-level variable holds the parsed data.
let _translations = null;

async function loadTranslations() {
  if (_translations) return _translations;
  try {
    // Resolve the translations.json URL relative to this module's location.
    const base = new URL(".", import.meta.url).href;
    const resp = await fetch(base + "translations.json?v=" + Date.now());
    _translations = await resp.json();
  } catch (e) {
    console.warn("ha-note-record: failed to load translations.json, using built-in English fallback", e);
    _translations = {
      en: {
        title: "Note Record", add_note: "Add Note", edit_note: "Edit Note",
        create_note: "Create Note", note_title: "Title", content: "Content (Markdown)",
        save: "Save", cancel: "Cancel", delete: "Delete", create: "Create",
        updated: "Updated", preview: "Preview", pin_note: "Pin this note",
        note_title_placeholder: "Note title",
        note_content_placeholder: "Write your note in Markdown...",
        add_category: "Add Category", create_category: "Create Category",
        delete_category: "Delete Category", category_name: "Category Name",
        category_placeholder: "e.g., Passwords, Notes, Todo",
        no_categories: "No categories yet. Create one to get started!",
        no_notes: "No notes in this category yet.", error: "Error",
        delete_category_confirm: "Delete category",
        delete_category_warning: 'This will permanently delete the category "{name}" and all {count} note(s) in it. This action cannot be undone.',
        delete_category_empty_warning: 'This will permanently delete the empty category "{name}". This action cannot be undone.',
        delete_category_confirm_label: 'Type "{name}" to confirm',
        menu: "Menu", search: "Search...", add: "Add", more_actions: "More actions",
        add_note_to_category: "Add Note to this Category",
      },
    };
  }
  return _translations;
}

/**
 * Resolve the language key for the translations object.
 * zh-TW / zh-HK map to zh-Hant; other zh-* to zh-Hans; everything else to en.
 */
function _resolveLangKey(lang) {
  if (!lang) return "en";
  if (lang.startsWith("zh-TW") || lang.startsWith("zh-HK") || lang === "zh-Hant") return "zh-Hant";
  if (lang.startsWith("zh")) return "zh-Hans";
  return "en";
}

/**
 * Look up a single translation key using the loaded translations data.
 */
function _getTranslation(key, lang) {
  if (!_translations) return key;
  const langKey = _resolveLangKey(lang);
  return _translations[langKey]?.[key] || _translations["en"]?.[key] || key;
}

// Inlined shared styles for HA panel compatibility
const sharedStylesLit = `
  /* TOP BAR - follows HA dark/light mode */
  .top-bar {
    display: flex;
    align-items: center;
    height: 56px;
    padding: 0 16px;
    background: var(--app-header-background-color, var(--primary-background-color));
    color: var(--app-header-text-color, var(--primary-text-color));
    border-bottom: 1px solid var(--divider-color);
    position: sticky;
    top: 0;
    z-index: 100;
    gap: 12px;
    margin: -16px -16px 16px -16px;
  }
  .top-bar-sidebar-btn {
    width: 40px;
    height: 40px;
    border: none;
    background: transparent;
    color: inherit;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 50%;
    transition: background 0.2s;
    flex-shrink: 0;
  }
  .top-bar-sidebar-btn:hover { background: var(--secondary-background-color, rgba(0,0,0,0.1)); }
  .top-bar-sidebar-btn svg { width: 24px; height: 24px; }
  .top-bar-title {
    flex: 1;
    font-size: 20px;
    font-weight: 500;
    margin: 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .add-note-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    width: 100%;
    padding: 24px;
    margin-top: 16px;
    border: 2px dashed var(--divider-color);
    border-radius: 8px;
    background: transparent;
    color: var(--secondary-text-color);
    cursor: pointer;
    font-size: 14px;
    transition: all 0.2s ease;
  }
  .add-note-btn:hover {
    border-color: var(--primary-color);
    color: var(--primary-color);
    background: var(--secondary-background-color);
  }
  .add-note-btn svg { width: 20px; height: 20px; }

  /* SEARCH ROW */
  .search-row {
    display: flex;
    align-items: center;
    height: 48px;
    padding: 0 16px;
    background: var(--primary-background-color);
    border-bottom: 1px solid var(--divider-color);
    margin: 0 -16px 16px -16px;
    gap: 8px;
  }
  .search-row-input-wrapper {
    flex: 1;
    display: flex;
    align-items: center;
    background: var(--card-background-color);
    border: 1px solid var(--divider-color);
    border-radius: 8px;
    padding: 0 12px;
    height: 36px;
    transition: border-color 0.2s, box-shadow 0.2s;
  }
  .search-row-input-wrapper:focus-within {
    border-color: var(--primary-color);
    box-shadow: 0 0 0 2px rgba(var(--rgb-primary-color, 3, 169, 244), 0.2);
  }
  .search-row-icon {
    width: 20px;
    height: 20px;
    color: var(--secondary-text-color);
    flex-shrink: 0;
    margin-right: 8px;
  }
  .search-row-input {
    flex: 1;
    border: none;
    background: transparent;
    font-size: 14px;
    color: var(--primary-text-color);
    outline: none;
    height: 100%;
  }
  .search-row-input::placeholder { color: var(--secondary-text-color); }
`;

class HaNoteRecordPanel extends LitElement {
  static get properties() {
    return {
      hass: { type: Object },
      narrow: { type: Boolean },
      panel: { type: Object },
      _categories: { type: Array },
      _notes: { type: Array },
      _activeTab: { type: String },
      _loading: { type: Boolean },
      _dialogOpen: { type: Boolean },
      _dialogMode: { type: String },
      _editingNote: { type: Object },
      _categoryDialogOpen: { type: Boolean },
      _categoryDialogMode: { type: String },
      _editingCategory: { type: Object },
      _searchQuery: { type: String },
      _deleteCategoryDialogOpen: { type: Boolean },
      _deleteCategoryTarget: { type: Object },
      _deleteCategoryInput: { type: String },
    };
  }

  static get styles() {
    return css`
      ${unsafeCSS(sharedStylesLit)}

      :host {
        display: block;
        padding: 16px;
        background: var(--primary-background-color);
        min-height: 100vh;
        box-sizing: border-box;
      }

      .header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 16px;
      }

      .header h1 {
        margin: 0;
        font-size: 24px;
        font-weight: 400;
        color: var(--primary-text-color);
      }

      .tabs-container {
        display: flex;
        align-items: center;
        border-bottom: 1px solid var(--divider-color);
        margin-bottom: 16px;
        overflow-x: auto;
      }

      .category-tabs {
        display: flex;
        gap: 4px;
        flex: 1;
      }

      .category-tab {
        padding: 12px 16px;
        cursor: pointer;
        border: none;
        background: none;
        color: var(--secondary-text-color);
        font-size: 14px;
        font-weight: 500;
        border-bottom: 2px solid transparent;
        transition: all 0.2s ease;
        white-space: nowrap;
      }

      .category-tab:hover {
        color: var(--primary-text-color);
        background: var(--secondary-background-color);
      }

      .category-tab.active {
        color: var(--primary-color);
        border-bottom-color: var(--primary-color);
      }

      .add-tab-btn {
        padding: 8px 12px;
        cursor: pointer;
        border: none;
        background: none;
        color: var(--primary-color);
        font-size: 20px;
        display: flex;
        align-items: center;
        justify-content: center;
        border-radius: 4px;
        margin-left: 8px;
      }

      .add-tab-btn:hover {
        background: var(--secondary-background-color);
      }

      .tab-actions {
        display: flex;
        gap: 4px;
        margin-left: 8px;
      }

      .tab-action-btn {
        padding: 4px 8px;
        cursor: pointer;
        border: none;
        background: none;
        color: var(--secondary-text-color);
        font-size: 12px;
        border-radius: 4px;
      }

      .tab-action-btn:hover {
        background: var(--secondary-background-color);
        color: var(--error-color);
      }

      .content {
        padding: 16px 0;
      }

      .notes-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
        gap: 16px;
      }

      .note-card {
        background: var(--card-background-color);
        border-radius: 8px;
        padding: 16px;
        cursor: pointer;
        box-shadow: var(--ha-card-box-shadow, 0 2px 4px rgba(0,0,0,0.1));
        transition: all 0.2s ease;
        position: relative;
        border-left: 4px solid transparent;
        overflow: hidden;
      }

      @media (hover: hover) {
        .note-card:hover {
          box-shadow: 0 4px 8px rgba(0,0,0,0.15);
          transform: translateY(-2px);
        }
      }

      .note-card.pinned {
        border-left-color: var(--primary-color);
      }

      .note-card-header {
        display: flex;
        align-items: center;
        gap: 8px;
        margin-bottom: 8px;
      }

      .note-card-title {
        font-size: 16px;
        font-weight: 500;
        color: var(--primary-text-color);
        flex: 1;
        margin: 0;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }

      .pin-icon {
        color: var(--primary-color);
        font-size: 16px;
      }

      .note-card-content {
        color: var(--secondary-text-color);
        font-size: 14px;
        line-height: 1.5;
        max-height: 100px;
        overflow: hidden;
        position: relative;
        overflow-wrap: break-word;
        word-break: break-word;
      }

      .note-card-content::after {
        content: "";
        position: absolute;
        bottom: 0;
        left: 0;
        right: 0;
        height: 40px;
        background: linear-gradient(transparent, var(--card-background-color));
      }

      .note-card-content :first-child {
        margin-top: 0;
      }

      .note-card-footer {
        margin-top: 12px;
        font-size: 12px;
        color: var(--secondary-text-color);
      }

      .empty-state {
        text-align: center;
        padding: 48px 16px;
        color: var(--secondary-text-color);
      }

      .empty-state ha-icon {
        font-size: 48px;
        margin-bottom: 16px;
        opacity: 0.5;
      }

      .loading {
        display: flex;
        justify-content: center;
        padding: 48px;
      }

      /* Dialog styles */
      .dialog-overlay {
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: rgba(0, 0, 0, 0.5);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 1000;
      }

      .dialog {
        background: var(--card-background-color);
        border-radius: 12px;
        width: 90%;
        max-width: 600px;
        max-height: 90vh;
        overflow: auto;
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
      }

      .dialog-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 16px 20px;
        border-bottom: 1px solid var(--divider-color);
      }

      .dialog-header h2 {
        margin: 0;
        font-size: 18px;
        font-weight: 500;
        color: var(--primary-text-color);
      }

      .dialog-close {
        cursor: pointer;
        border: none;
        background: none;
        color: var(--secondary-text-color);
        font-size: 24px;
        padding: 4px;
        line-height: 1;
      }

      .dialog-close:hover {
        color: var(--primary-text-color);
      }

      .dialog-content {
        padding: 20px;
      }

      .form-group {
        margin-bottom: 16px;
      }

      .form-group label {
        display: block;
        margin-bottom: 8px;
        font-size: 14px;
        font-weight: 500;
        color: var(--primary-text-color);
      }

      .form-group input,
      .form-group textarea {
        width: 100%;
        padding: 12px;
        border: 1px solid var(--divider-color);
        border-radius: 8px;
        font-size: 14px;
        background: var(--primary-background-color);
        color: var(--primary-text-color);
        box-sizing: border-box;
      }

      .form-group input:focus,
      .form-group textarea:focus {
        outline: none;
        border-color: var(--primary-color);
      }

      .form-group textarea {
        min-height: 150px;
        resize: vertical;
        font-family: "Noto Sans Mono", "Noto Sans SC", "Microsoft YaHei", "PingFang SC", monospace;
      }

      .form-group-checkbox {
        display: flex;
        align-items: center;
        gap: 8px;
      }

      .form-group-checkbox input {
        width: auto;
      }

      .preview-section {
        margin-top: 16px;
        padding: 16px;
        background: var(--secondary-background-color);
        border-radius: 8px;
      }

      .preview-section h3 {
        margin: 0 0 12px 0;
        font-size: 14px;
        font-weight: 500;
        color: var(--secondary-text-color);
      }

      .preview-content {
        color: var(--primary-text-color);
        font-size: 14px;
        line-height: 1.6;
        overflow-wrap: break-word;
        word-break: break-word;
      }

      .preview-content h1,
      .preview-content h2,
      .preview-content h3 {
        margin-top: 16px;
        margin-bottom: 8px;
      }

      .preview-content h1:first-child,
      .preview-content h2:first-child,
      .preview-content h3:first-child {
        margin-top: 0;
      }

      .preview-content ul,
      .preview-content ol {
        padding-left: 20px;
      }

      .preview-content code {
        background: var(--primary-background-color);
        padding: 2px 6px;
        border-radius: 4px;
        font-family: "Noto Sans Mono", "Noto Sans SC", "Microsoft YaHei", "PingFang SC", Consolas, monospace;
      }

      .preview-content pre {
        background: var(--primary-background-color);
        padding: 12px;
        border-radius: 8px;
        overflow-x: auto;
      }

      .preview-content pre code {
        background: none;
        padding: 0;
      }

      .dialog-footer {
        display: flex;
        justify-content: space-between;
        padding: 16px 20px;
        border-top: 1px solid var(--divider-color);
      }

      .dialog-footer-left {
        display: flex;
        gap: 8px;
      }

      .dialog-footer-right {
        display: flex;
        gap: 8px;
      }

      .btn {
        padding: 10px 20px;
        border: none;
        border-radius: 8px;
        font-size: 14px;
        font-weight: 500;
        cursor: pointer;
        transition: all 0.2s ease;
      }

      .btn-primary {
        background: var(--primary-color);
        color: white;
      }

      .btn-primary:hover {
        opacity: 0.9;
      }

      .btn-secondary {
        background: var(--secondary-background-color);
        color: var(--primary-text-color);
      }

      .btn-secondary:hover {
        background: var(--divider-color);
      }

      .btn-danger {
        background: var(--error-color);
        color: white;
      }

      .btn-danger:hover {
        opacity: 0.9;
      }

      .btn-danger:disabled {
        opacity: 0.5;
        cursor: not-allowed;
      }

      .delete-warning-text {
        color: var(--error-color, #db4437);
        font-size: 14px;
        line-height: 1.5;
        margin-bottom: 16px;
      }

      @media (max-width: 600px) {
        :host {
          padding: 8px;
          padding-bottom: max(8px, env(safe-area-inset-bottom));
        }

        /* Fix negative margin overflow: host is 8px, not 16px */
        .top-bar {
          margin: -8px -8px 16px -8px;
          padding: 0 8px;
        }
        .search-row {
          margin: 0 -8px 16px -8px;
          padding: 0 8px;
        }

        /* Sidebar button 44px touch target */
        .top-bar-sidebar-btn {
          width: 44px;
          height: 44px;
        }

        /* Search input iOS auto-zoom prevention + 44px height */
        .search-row-input {
          font-size: 16px;
        }
        .search-row-input-wrapper {
          height: 44px;
        }

        /* Tab scrollbar hiding + momentum scroll */
        .tabs-container {
          -webkit-overflow-scrolling: touch;
          scrollbar-width: none;
          -ms-overflow-style: none;
        }
        .tabs-container::-webkit-scrollbar {
          display: none;
        }

        /* Category tab 44px touch target */
        .category-tab {
          min-height: 44px;
          display: inline-flex;
          align-items: center;
        }

        /* Add-tab button 44px */
        .add-tab-btn {
          min-width: 44px;
          min-height: 44px;
        }

        /* Delete-category button 44px */
        .tab-action-btn {
          min-width: 44px;
          min-height: 44px;
          display: flex;
          align-items: center;
          justify-content: center;
          padding: 10px;
        }

        .notes-grid {
          grid-template-columns: 1fr;
        }

        /* Empty state less padding on mobile */
        .empty-state {
          padding: 24px 16px;
        }

        /* Dialog full-screen on mobile */
        .dialog {
          width: 100%;
          max-width: 100%;
          height: 100%;
          max-height: 100%;
          border-radius: 0;
        }
        .dialog-overlay {
          align-items: stretch;
        }

        /* Dialog close button 44px */
        .dialog-close {
          padding: 10px;
          min-width: 44px;
          min-height: 44px;
          display: flex;
          align-items: center;
          justify-content: center;
        }

        /* Form inputs: 16px to prevent iOS auto-zoom */
        .form-group input,
        .form-group textarea {
          font-size: 16px;
        }

        /* Checkbox touch target */
        .form-group-checkbox {
          min-height: 44px;
        }

        /* Dialog footer wrapping */
        .dialog-footer {
          flex-wrap: wrap;
          gap: 8px;
          padding-bottom: max(16px, env(safe-area-inset-bottom));
        }
        .dialog-footer-left,
        .dialog-footer-right {
          flex-wrap: wrap;
          gap: 8px;
        }

        /* All buttons 44px min-height */
        .btn {
          min-height: 44px;
          box-sizing: border-box;
        }
      }
    `;
  }

  constructor() {
    super();
    this._categories = [];
    this._notes = [];
    this._activeTab = null;
    this._loading = true;
    this._dialogOpen = false;
    this._dialogMode = "create";
    this._editingNote = null;
    this._categoryDialogOpen = false;
    this._categoryDialogMode = "create";
    this._editingCategory = null;
    this._searchQuery = "";
    this._deleteCategoryDialogOpen = false;
    this._deleteCategoryTarget = null;
    this._deleteCategoryInput = "";
    this._prevLanguage = null;
  }

  connectedCallback() {
    super.connectedCallback();
    if (this.hass) {
      const lang = this.hass.language || "en";
      this._prevLanguage = lang;
      HaNoteRecordPanel._startSidebarPatcher(lang);
    }
  }

  _onSearchInput(e) {
    this._searchQuery = e.target.value;
  }

  firstUpdated() {
    // Ensure translations are loaded before rendering content.
    loadTranslations().then(() => {
      this._loadData();
    });
  }

  async _loadData() {
    this._loading = true;
    try {
      const result = await this.hass.callWS({
        type: "ha_note_record/get_data",
      });
      this._categories = result.categories || [];
      this._notes = result.notes || [];

      if (!this._activeTab && this._categories.length > 0) {
        this._activeTab = this._categories[0].id;
      }
    } catch (error) {
      console.error("Failed to load data:", error);
    }
    this._loading = false;
  }

  _getNotesForCategory(categoryId) {
    let notes = this._notes.filter((n) => n.category_id === categoryId);

    // Apply search filter
    if (this._searchQuery && this._searchQuery.trim()) {
      const query = this._searchQuery.toLowerCase().trim();
      notes = notes.filter((n) => {
        const title = (n.title || "").toLowerCase();
        const content = (n.content || "").toLowerCase();
        return title.includes(query) || content.includes(query);
      });
    }

    // Sort: pinned first, then by updated_at desc
    return notes.sort((a, b) => {
      if (a.pinned && !b.pinned) return -1;
      if (!a.pinned && b.pinned) return 1;
      return new Date(b.updated_at) - new Date(a.updated_at);
    });
  }

  _renderMarkdown(content) {
    if (!content) return "";
    try {
      const rawHtml = marked.parse(content);
      return DOMPurify.sanitize(rawHtml);
    } catch (e) {
      // If markdown parsing fails, escape the content as plain text
      // instead of passing raw content through DOMPurify (which could
      // still render unexpected HTML present in the original input).
      const escaped = content
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
      return escaped;
    }
  }

  _formatDate(dateStr) {
    try {
      const date = new Date(dateStr);
      return date.toLocaleDateString() + " " + date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch (e) {
      return dateStr;
    }
  }

  _toggleSidebar() {
    this.dispatchEvent(new CustomEvent("hass-toggle-menu", { bubbles: true, composed: true }));
  }

  _localize(key) {
    // Try to get translation from HA's built-in localization first
    const translation = this.hass?.localize?.(`component.ha_note_record.panel.${key}`);
    if (translation) return translation;

    // Fall back to locally loaded translations.json
    return _getTranslation(key, this.hass?.language);
  }

  _showNotification(message, type = "info") {
    // Use Home Assistant's notification system
    this.hass.callService("persistent_notification", "create", {
      message: message,
      title: type === "error" ? this._localize("error") : this._localize("title"),
      notification_id: `ha_note_record_${Date.now()}`,
    });
  }

  _showError(message) {
    this._showNotification(message, "error");
  }

  _truncateContent(content, maxLength = 150) {
    if (!content) return "";
    if (content.length <= maxLength) return content;
    return content.substring(0, maxLength) + "...";
  }

  // Tab actions
  _selectTab(categoryId) {
    this._activeTab = categoryId;
  }

  _openCategoryDialog(mode = "create", category = null) {
    this._categoryDialogMode = mode;
    this._editingCategory = category;
    this._categoryDialogOpen = true;
  }

  _closeCategoryDialog() {
    this._categoryDialogOpen = false;
    this._editingCategory = null;
  }

  async _saveCategory(e) {
    e.preventDefault();
    const form = e.target;
    const name = form.querySelector("#category-name").value.trim();

    if (!name) return;

    try {
      const result = await this.hass.callWS({
        type: "ha_note_record/create_category",
        name: name,
      });
      this._categories = [...this._categories, result];
      this._activeTab = result.id;
      this._closeCategoryDialog();
    } catch (error) {
      console.error("Failed to create category:", error);
      this._showError(error.message || "Failed to create category");
    }
  }

  async _deleteCategory(categoryId) {
    const category = this._categories.find((c) => c.id === categoryId);
    if (!category) return;
    this._deleteCategoryTarget = {
      id: categoryId,
      name: category.name,
      noteCount: this._notes.filter((n) => n.category_id === categoryId).length,
    };
    this._deleteCategoryInput = "";
    this._deleteCategoryDialogOpen = true;
  }

  _closeDeleteCategoryDialog() {
    this._deleteCategoryDialogOpen = false;
    this._deleteCategoryTarget = null;
    this._deleteCategoryInput = "";
  }

  async _confirmDeleteCategory() {
    const target = this._deleteCategoryTarget;
    if (!target) return;
    if (this._deleteCategoryInput !== target.name) return;

    try {
      await this.hass.callWS({
        type: "ha_note_record/delete_category",
        category_id: target.id,
      });
      this._notes = this._notes.filter((n) => n.category_id !== target.id);
      this._categories = this._categories.filter((c) => c.id !== target.id);
      if (this._activeTab === target.id) {
        this._activeTab = this._categories.length > 0 ? this._categories[0].id : null;
      }
      this._closeDeleteCategoryDialog();
    } catch (error) {
      console.error("Failed to delete category:", error);
      this._showError(error.message || "Failed to delete category");
    }
  }

  // Note actions
  _openNoteDialog(mode = "create", note = null) {
    this._dialogMode = mode;
    this._editingNote = note
      ? { ...note }
      : { title: "", content: "", pinned: false, category_id: this._activeTab };
    this._dialogOpen = true;
  }

  _closeNoteDialog() {
    this._dialogOpen = false;
    this._editingNote = null;
  }

  _updateNoteField(field, value) {
    this._editingNote = { ...this._editingNote, [field]: value };
  }

  async _saveNote(e) {
    e.preventDefault();

    if (!this._editingNote.title.trim()) {
      this._showError("Title is required");
      return;
    }

    try {
      if (this._dialogMode === "create") {
        const result = await this.hass.callWS({
          type: "ha_note_record/create_note",
          category_id: this._editingNote.category_id,
          title: this._editingNote.title,
          content: this._editingNote.content,
          pinned: this._editingNote.pinned,
        });
        this._notes = [...this._notes, result];
      } else {
        const result = await this.hass.callWS({
          type: "ha_note_record/update_note",
          note_id: this._editingNote.id,
          title: this._editingNote.title,
          content: this._editingNote.content,
          pinned: this._editingNote.pinned,
        });
        this._notes = this._notes.map((n) =>
          n.id === result.id ? result : n
        );
      }
      this._closeNoteDialog();
    } catch (error) {
      console.error("Failed to save note:", error);
      this._showError(error.message || "Failed to save note");
    }
  }

  async _deleteNote() {
    if (!this._editingNote || !this._editingNote.id) return;
    if (!confirm(`Delete note "${this._editingNote.title}"?`)) return;

    try {
      await this.hass.callWS({
        type: "ha_note_record/delete_note",
        note_id: this._editingNote.id,
      });
      this._notes = this._notes.filter((n) => n.id !== this._editingNote.id);
      this._closeNoteDialog();
    } catch (error) {
      console.error("Failed to delete note:", error);
      this._showError(error.message || "Failed to delete note");
    }
  }

  render() {
    if (this._loading) {
      return html`
        <div class="loading">
          <ha-circular-progress active></ha-circular-progress>
        </div>
      `;
    }

    const activeCategory = this._categories.find((c) => c.id === this._activeTab);
    const notes = this._activeTab ? this._getNotesForCategory(this._activeTab) : [];

    return html`
      <!-- Top Bar -->
      <div class="top-bar">
        <button class="top-bar-sidebar-btn" @click=${this._toggleSidebar}>
          <svg viewBox="0 0 24 24"><path fill="currentColor" d="M3,6H21V8H3V6M3,11H21V13H3V11M3,16H21V18H3V16Z"/></svg>
        </button>
        <h1 class="top-bar-title">${this._localize("title")}</h1>
      </div>

      <!-- Search Row -->
      <div class="search-row">
        <div class="search-row-input-wrapper">
          <svg class="search-row-icon" viewBox="0 0 24 24"><path fill="currentColor" d="M9.5,3A6.5,6.5 0 0,1 16,9.5C16,11.11 15.41,12.59 14.44,13.73L14.71,14H15.5L20.5,19L19,20.5L14,15.5V14.71L13.73,14.44C12.59,15.41 11.11,16 9.5,16A6.5,6.5 0 0,1 3,9.5A6.5,6.5 0 0,1 9.5,3M9.5,5C7,5 5,7 5,9.5C5,12 7,14 9.5,14C12,14 14,12 14,9.5C14,7 12,5 9.5,5Z"/></svg>
          <input
            class="search-row-input"
            type="text"
            placeholder="${this._localize('search')}"
            .value=${this._searchQuery}
            @input=${this._onSearchInput}
          />
        </div>
      </div>

      <div class="tabs-container">
        <div class="category-tabs">
          ${this._categories.map(
            (category) => html`
              <button
                class="category-tab ${category.id === this._activeTab ? "active" : ""}"
                @click=${() => this._selectTab(category.id)}
              >
                ${category.name}
              </button>
            `
          )}
        </div>
        <button
          class="add-tab-btn"
          @click=${() => this._openCategoryDialog("create")}
          title="${this._localize("add_category")}"
        >
          +
        </button>
        ${activeCategory
          ? html`
              <div class="tab-actions">
                <button
                  class="tab-action-btn"
                  @click=${() => this._deleteCategory(this._activeTab)}
                  title="${this._localize("delete_category")}"
                >
                  <svg viewBox="0 0 24 24" style="width:16px;height:16px"><path fill="currentColor" d="M19,4H15.5L14.5,3H9.5L8.5,4H5V6H19M6,19A2,2 0 0,0 8,21H16A2,2 0 0,0 18,19V7H6V19Z"/></svg>
                </button>
              </div>
            `
          : ""}
      </div>

      <div class="content">
        ${this._categories.length === 0
          ? html`
              <div class="empty-state">
                <ha-icon icon="mdi:folder-plus-outline"></ha-icon>
                <p>${this._localize("no_categories")}</p>
                <button
                  class="btn btn-primary"
                  @click=${() => this._openCategoryDialog("create")}
                >
                  ${this._localize("create_category")}
                </button>
              </div>
            `
          : this._activeTab
          ? html`
              ${notes.length === 0
                ? html`
                    <div class="empty-state">
                      <ha-icon icon="mdi:note-plus-outline"></ha-icon>
                      <p>${this._localize("no_notes")}</p>
                      <button class="btn btn-primary" @click=${() => this._openNoteDialog("create")}>
                        ${this._localize("add_note_to_category")}
                      </button>
                    </div>
                  `
                : html`
                    <div class="notes-grid">
                      ${notes.map(
                        (note) => html`
                          <div
                            class="note-card ${note.pinned ? "pinned" : ""}"
                            @click=${() => this._openNoteDialog("edit", note)}
                          >
                            <div class="note-card-header">
                              <h3 class="note-card-title">${note.title}</h3>
                              ${note.pinned
                                ? html`<span class="pin-icon">📌</span>`
                                : ""}
                            </div>
                            <div
                              class="note-card-content"
                              .innerHTML=${this._renderMarkdown(
                                this._truncateContent(note.content)
                              )}
                            ></div>
                            <div class="note-card-footer">
                              ${this._localize("updated")}: ${this._formatDate(note.updated_at)}
                            </div>
                          </div>
                        `
                      )}
                    </div>
                    <button class="add-note-btn" @click=${() => this._openNoteDialog("create")}>
                      <svg viewBox="0 0 24 24"><path fill="currentColor" d="M19,13H13V19H11V13H5V11H11V5H13V11H19V13Z"/></svg>
                      ${this._localize("add_note_to_category")}
                    </button>
                  `}
            `
          : ""}
      </div>

      ${this._dialogOpen ? this._renderNoteDialog() : ""}
      ${this._categoryDialogOpen ? this._renderCategoryDialog() : ""}
      ${this._deleteCategoryDialogOpen ? this._renderDeleteCategoryDialog() : ""}
    `;
  }

  _renderNoteDialog() {
    const isEdit = this._dialogMode === "edit";
    return html`
      <div class="dialog-overlay" @click=${this._closeNoteDialog}>
        <div class="dialog" @click=${(e) => e.stopPropagation()}>
          <div class="dialog-header">
            <h2>${isEdit ? this._localize("edit_note") : this._localize("create_note")}</h2>
            <button class="dialog-close" @click=${this._closeNoteDialog}>
              ×
            </button>
          </div>
          <form @submit=${this._saveNote}>
            <div class="dialog-content">
              <div class="form-group">
                <label for="note-title">${this._localize("note_title")}</label>
                <input
                  type="text"
                  id="note-title"
                  .value=${this._editingNote?.title || ""}
                  @input=${(e) => this._updateNoteField("title", e.target.value)}
                  placeholder="${this._localize("note_title_placeholder")}"
                  required
                />
              </div>
              <div class="form-group">
                <label for="note-content">${this._localize("content")}</label>
                <textarea
                  id="note-content"
                  .value=${this._editingNote?.content || ""}
                  @input=${(e) =>
                    this._updateNoteField("content", e.target.value)}
                  placeholder="${this._localize("note_content_placeholder")}"
                ></textarea>
              </div>
              <div class="form-group form-group-checkbox">
                <input
                  type="checkbox"
                  id="note-pinned"
                  .checked=${this._editingNote?.pinned || false}
                  @change=${(e) =>
                    this._updateNoteField("pinned", e.target.checked)}
                />
                <label for="note-pinned">${this._localize("pin_note")}</label>
              </div>
              ${this._editingNote?.content
                ? html`
                    <div class="preview-section">
                      <h3>${this._localize("preview")}</h3>
                      <div
                        class="preview-content"
                        .innerHTML=${this._renderMarkdown(
                          this._editingNote.content
                        )}
                      ></div>
                    </div>
                  `
                : ""}
            </div>
            <div class="dialog-footer">
              <div class="dialog-footer-left">
                ${isEdit
                  ? html`
                      <button
                        type="button"
                        class="btn btn-danger"
                        @click=${this._deleteNote}
                      >
                        ${this._localize("delete")}
                      </button>
                    `
                  : ""}
              </div>
              <div class="dialog-footer-right">
                <button
                  type="button"
                  class="btn btn-secondary"
                  @click=${this._closeNoteDialog}
                >
                  ${this._localize("cancel")}
                </button>
                <button type="submit" class="btn btn-primary">${this._localize("save")}</button>
              </div>
            </div>
          </form>
        </div>
      </div>
    `;
  }

  _renderCategoryDialog() {
    return html`
      <div class="dialog-overlay" @click=${this._closeCategoryDialog}>
        <div class="dialog" @click=${(e) => e.stopPropagation()}>
          <div class="dialog-header">
            <h2>${this._localize("create_category")}</h2>
            <button class="dialog-close" @click=${this._closeCategoryDialog}>
              ×
            </button>
          </div>
          <form @submit=${this._saveCategory}>
            <div class="dialog-content">
              <div class="form-group">
                <label for="category-name">${this._localize("category_name")}</label>
                <input
                  type="text"
                  id="category-name"
                  placeholder="${this._localize("category_placeholder")}"
                  required
                />
              </div>
            </div>
            <div class="dialog-footer">
              <div class="dialog-footer-left"></div>
              <div class="dialog-footer-right">
                <button
                  type="button"
                  class="btn btn-secondary"
                  @click=${this._closeCategoryDialog}
                >
                  ${this._localize("cancel")}
                </button>
                <button type="submit" class="btn btn-primary">${this._localize("create")}</button>
              </div>
            </div>
          </form>
        </div>
      </div>
    `;
  }

  _renderDeleteCategoryDialog() {
    const target = this._deleteCategoryTarget;
    if (!target) return html``;

    const warningKey = target.noteCount > 0
      ? "delete_category_warning"
      : "delete_category_empty_warning";
    const warningTemplate = this._localize(warningKey);
    const warningText = warningTemplate
      .replace("{name}", target.name)
      .replace("{count}", String(target.noteCount));
    const confirmLabel = this._localize("delete_category_confirm_label")
      .replace("{name}", target.name);
    const canConfirm = this._deleteCategoryInput === target.name;

    return html`
      <div class="dialog-overlay" @click=${this._closeDeleteCategoryDialog}>
        <div class="dialog" @click=${(e) => e.stopPropagation()} style="max-width:480px">
          <div class="dialog-header">
            <h2>${this._localize("delete_category")}</h2>
            <button class="dialog-close" @click=${this._closeDeleteCategoryDialog}>
              &times;
            </button>
          </div>
          <div class="dialog-content">
            <p class="delete-warning-text"></p>
            <div class="form-group">
              <label>${confirmLabel}</label>
              <input
                type="text"
                .value=${this._deleteCategoryInput}
                @input=${(e) => { this._deleteCategoryInput = e.target.value; }}
                autocomplete="off"
              />
            </div>
          </div>
          <div class="dialog-footer">
            <div class="dialog-footer-left"></div>
            <div class="dialog-footer-right">
              <button
                type="button"
                class="btn btn-secondary"
                @click=${this._closeDeleteCategoryDialog}
              >
                ${this._localize("cancel")}
              </button>
              <button
                type="button"
                class="btn btn-danger"
                ?disabled=${!canConfirm}
                @click=${this._confirmDeleteCategory}
              >
                ${this._localize("delete")}
              </button>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  updated(changedProperties) {
    super.updated(changedProperties);
    if (changedProperties.has("hass") && this.hass) {
      const newLang = this.hass.language || "en";
      if (this._prevLanguage !== newLang) {
        this._prevLanguage = newLang;
        HaNoteRecordPanel._startSidebarPatcher(newLang);
      }
    }
    // Safely set warning text via textContent to avoid XSS from category names
    if (this._deleteCategoryDialogOpen && this._deleteCategoryTarget) {
      const warningEl = this.shadowRoot?.querySelector(".delete-warning-text");
      if (warningEl) {
        const target = this._deleteCategoryTarget;
        const warningKey = target.noteCount > 0
          ? "delete_category_warning"
          : "delete_category_empty_warning";
        const warningTemplate = this._localize(warningKey);
        const warningText = warningTemplate
          .replace("{name}", target.name)
          .replace("{count}", String(target.noteCount));
        warningEl.textContent = warningText;
      }
    }
  }

  static _patchSidebarTitle(lang) {
    const title = lang && (lang.startsWith("zh-TW") || lang.startsWith("zh-HK") || lang === "zh-Hant")
      ? "\u8A18\u4E8B\u672C"
      : lang && lang.startsWith("zh")
        ? "\u8BB0\u4E8B\u672C"
        : "Note Record";
    window.__haNoteRecordLang = lang;
    try {
      const ha = document.querySelector("home-assistant");
      if (!ha || !ha.shadowRoot) return;
      const main = ha.shadowRoot.querySelector("home-assistant-main");
      if (!main || !main.shadowRoot) return;
      const sidebar = main.shadowRoot.querySelector("ha-sidebar");
      if (!sidebar || !sidebar.shadowRoot) return;
      const items = sidebar.shadowRoot.querySelectorAll("ha-md-list-item");
      for (const item of items) {
        const anchor = item.shadowRoot && item.shadowRoot.querySelector('a[href="/ha-note-record"]');
        if (anchor) {
          const span = item.querySelector(".item-text");
          if (span) {
            for (let i = 0; i < span.childNodes.length; i++) {
              if (span.childNodes[i].nodeType === 3) {
                if (span.childNodes[i].data !== title) {
                  span.childNodes[i].data = title;
                }
                break;
              }
            }
          }
          break;
        }
      }
    } catch (e) {
      // Silently fail if sidebar not rendered yet
    }
  }

  static _startSidebarPatcher(lang) {
    if (window.__haNoteRecordSidebarInterval) {
      HaNoteRecordPanel._patchSidebarTitle(lang);
      return;
    }
    window.__haNoteRecordLang = lang;
    window.__haNoteRecordSidebarInterval = setInterval(() => {
      try {
        const haEl = document.querySelector("home-assistant");
        if (haEl && haEl.hass && haEl.hass.language) {
          window.__haNoteRecordLang = haEl.hass.language;
        }
      } catch (e) { /* ignore */ }
      const currentLang = window.__haNoteRecordLang || "en";
      HaNoteRecordPanel._patchSidebarTitle(currentLang);
    }, 2000);
    setTimeout(() => HaNoteRecordPanel._patchSidebarTitle(lang), 200);
  }
}

customElements.define("ha-note-record-panel", HaNoteRecordPanel);
