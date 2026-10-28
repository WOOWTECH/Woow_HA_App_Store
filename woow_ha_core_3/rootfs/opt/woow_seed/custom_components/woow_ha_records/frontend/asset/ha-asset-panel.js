/**
 * ha-asset-panel.js - Asset Record panel for Home Assistant
 *
 * CDN dependency: lit-element v2.4.0 from unpkg.com
 * This import loads LitElement, html, css, and unsafeCSS from the CDN.
 * For future vendoring consideration, this could be replaced with a local
 * bundled copy of lit-element to eliminate the external network dependency.
 * Version pinned to 2.4.0 for stability.
 */
import {
  LitElement,
  html,
  css,
  unsafeCSS,
} from "https://unpkg.com/lit-element@2.4.0/lit-element.js?module";

// Translations are loaded from a local JSON file at init time — the same
// pattern the note panel uses (frontend/note/ha-note-record-panel.js). The
// _translations module-level variable holds the parsed data.
let _translations = null;

async function loadTranslations() {
  if (_translations) return _translations;
  try {
    // Resolve the translations.json URL relative to this module's location.
    const base = new URL(".", import.meta.url).href;
    const resp = await fetch(base + "translations.json?v=" + Date.now());
    _translations = await resp.json();
  } catch (e) {
    console.warn("ha-asset-panel: failed to load translations.json, using built-in English fallback", e);
    _translations = {
      en: {
        title: "Asset Record",
        add_asset: "Add Asset",
        edit_asset: "Edit Asset",
        name: "Name",
        brand: "Brand",
        category: "Category",
        value: "Value",
        warranty: "Warranty",
        purchase_at: "Purchase Date",
        warranty_until: "Warranty Until",
        manual: "Manual",
        maintenance: "Maintenance",
        save: "Save",
        cancel: "Cancel",
        delete: "Delete",
        delete_confirm: "Are you sure you want to delete this asset?",
        total_assets: "Total Assets",
        total_value: "Total Value",
        no_assets: "No assets yet",
        no_assets_hint: "Click the button above to add your first asset",
        expired: "Expired",
        name_required: "Name is required",
        no_search_results: "No assets match your search",
        all_categories: "All",
        uncategorized: "Uncategorized",
        add_category: "Add Category",
        category_name: "Category Name",
        category_name_placeholder: "Enter category name",
        rename_category: "Rename Category",
        delete_category: "Delete Category",
        delete_category_confirm: "This will also delete {count} asset(s) in this category. Are you sure?",
        category_empty_error: "Category name cannot be empty",
        category_duplicate_error: "A category with this name already exists",
        sort_by: "Sort by",
        sort_name: "Name",
        sort_created: "Created",
        sort_updated: "Updated",
        sort_asc: "Ascending",
        sort_desc: "Descending",
        load_error: "Failed to load assets",
        save_error: "Failed to save asset",
        delete_error: "Failed to delete asset",
        deleting: "Deleting...",
        invalid_date: "Invalid date",
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
  /* TOP BAR - matches HA standard header */
  .top-bar {
    display: flex;
    align-items: center;
    height: 56px;
    padding: 0 16px;
    background: var(--app-header-background-color, var(--primary-background-color));
    color: var(--app-header-text-color, var(--primary-text-color));
    position: sticky;
    top: 0;
    z-index: 100;
    gap: 12px;
    margin: -16px -16px 16px -16px;
    border-bottom: 1px solid var(--divider-color);
  }
  .top-bar-title {
    flex: 1;
    font-size: 20px;
    font-weight: 500;
    margin: 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
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
  .top-bar-actions { display: flex; align-items: center; gap: 4px; flex-shrink: 0; }
  .top-bar-action-btn {
    width: 40px;
    height: 40px;
    border: none;
    background: transparent;
    color: var(--app-header-text-color, var(--primary-text-color));
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 50%;
    transition: background 0.2s;
  }
  .top-bar-action-btn:hover { background: rgba(127, 127, 127, 0.2); }
  .top-bar-action-btn svg { width: 24px; height: 24px; }

  /* SEARCH ROW */
  .search-row {
    display: flex;
    align-items: center;
    height: 48px;
    padding: 0 16px;
    background: var(--primary-background-color);
    border-bottom: 1px solid var(--divider-color);
    margin: 0 -16px 0 -16px;
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

  /* ACTION ROW (add button + sort, below search) */
  .action-row {
    display: flex;
    align-items: center;
    padding: 8px 16px;
    margin: 0 -16px;
    gap: 8px;
  }
`;

// Translation helper
const commonTranslations = {
  en: { search: 'Search...', add: 'Add', more_actions: 'More actions' },
  'zh-Hant': { search: '搜尋...', add: '新增', more_actions: '更多操作' },
  'zh-Hans': { search: '搜索...', add: '添加', more_actions: '更多操作' },
};
function getCommonTranslation(key, lang = 'en') {
  const langKey = lang?.startsWith('zh-TW') || lang?.startsWith('zh-HK') ? 'zh-Hant' :
                  lang?.startsWith('zh') ? 'zh-Hans' : 'en';
  return commonTranslations[langKey]?.[key] || commonTranslations['en'][key] || key;
}

/**
 * Helper: fire a hass-notification event to show a toast via HA's
 * built-in notification manager. This follows the same pattern used
 * by HA core panels (e.g. zwave_js-node-config.ts).
 */
function fireHassNotification(element, message) {
  element.dispatchEvent(
    new CustomEvent("hass-notification", {
      detail: { message },
      bubbles: true,
      composed: true,
    })
  );
}

/**
 * Helper: safely parse a date string with cross-browser validation.
 * Returns a valid Date object or null if parsing fails.
 * Addresses cross-browser inconsistencies with new Date(isoString).
 */
function safeParseDateStr(dateStr) {
  if (!dateStr || typeof dateStr !== "string") return null;
  // Normalize date-only strings (YYYY-MM-DD) to avoid UTC/local timezone ambiguity
  // by appending T00:00:00 so all browsers treat it consistently as local time
  let normalized = dateStr.trim();
  if (/^\d{4}-\d{2}-\d{2}$/.test(normalized)) {
    normalized = normalized + "T00:00:00";
  }
  const date = new Date(normalized);
  if (isNaN(date.getTime())) return null;
  return date;
}

class HaAssetPanel extends LitElement {
  static get properties() {
    return {
      hass: { type: Object },
      narrow: { type: Boolean },
      panel: { type: Object },
      _assets: { type: Array },
      _categories: { type: Array },
      _loading: { type: Boolean },
      _dialogOpen: { type: Boolean },
      _editingAsset: { type: Object },
      _deleteConfirmOpen: { type: Boolean },
      _saving: { type: Boolean },
      _deleting: { type: Boolean },
      _nameError: { type: Boolean },
      _searchQuery: { type: String },
      _errorMessage: { type: String },
      _activeTab: { type: String },
      _sortField: { type: String },
      _sortDirection: { type: String },
      _categoryDialogOpen: { type: Boolean },
      _categoryDialogName: { type: String },
      _categoryDialogId: { type: String },
      _categoryDeleteConfirmOpen: { type: Boolean },
      _categoryDeleteTarget: { type: Object },
    };
  }

  static get styles() {
    return css`
      ${unsafeCSS(sharedStylesLit)}

      :host {
        display: block;
        height: 100%;
        background: var(--primary-background-color);
      }
      *, *::before, *::after {
        box-sizing: border-box;
      }

      .container {
        padding: 16px;
      }

      .header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 16px;
      }

      .header h1 {
        margin: 0;
        font-size: 24px;
        font-weight: 400;
        color: var(--primary-text-color);
      }

      .add-button {
        background: var(--primary-color);
        color: var(--text-primary-color);
        border: none;
        border-radius: 4px;
        padding: 8px 16px;
        cursor: pointer;
        font-size: 14px;
        display: flex;
        align-items: center;
        gap: 8px;
      }

      .add-button:hover {
        opacity: 0.9;
      }

      /* Error banner for visible error feedback (M-19) */
      .error-banner {
        background: var(--error-color, #f44336);
        color: white;
        padding: 12px 16px;
        border-radius: 4px;
        margin-bottom: 16px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
      }

      .error-banner-message {
        flex: 1;
        font-size: 14px;
      }

      .error-banner-close {
        background: none;
        border: none;
        color: white;
        cursor: pointer;
        padding: 4px;
        font-size: 18px;
        line-height: 1;
        flex-shrink: 0;
      }

      /* Category Tab Bar */
      .tab-bar {
        display: flex;
        align-items: center;
        padding: 0 16px;
        background: var(--primary-background-color);
        border-bottom: 1px solid var(--divider-color);
        margin: 0 -16px 0 -16px;
        overflow-x: auto;
        -webkit-overflow-scrolling: touch;
        gap: 0;
        min-height: 44px;
      }
      .tab-bar::-webkit-scrollbar { display: none; }
      .tab-item {
        padding: 10px 16px;
        border: none;
        background: transparent;
        color: var(--secondary-text-color);
        font-size: 14px;
        cursor: pointer;
        white-space: nowrap;
        border-bottom: 2px solid transparent;
        transition: color 0.2s, border-color 0.2s;
        flex-shrink: 0;
        position: relative;
      }
      .tab-item:hover {
        color: var(--primary-text-color);
      }
      .tab-item.active {
        color: var(--primary-color);
        border-bottom-color: var(--primary-color);
        font-weight: 500;
      }
      .tab-item-count {
        font-size: 12px;
        color: var(--secondary-text-color);
        margin-left: 4px;
      }
      .tab-add-btn {
        width: 32px;
        height: 32px;
        border: 1px dashed var(--divider-color);
        background: transparent;
        color: var(--secondary-text-color);
        cursor: pointer;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
        margin-left: 8px;
        transition: color 0.2s, border-color 0.2s;
        font-size: 18px;
      }
      .tab-add-btn:hover {
        color: var(--primary-color);
        border-color: var(--primary-color);
      }
      .tab-actions {
        display: flex;
        gap: 4px;
        margin-left: 8px;
        flex-shrink: 0;
      }
      .tab-action-btn {
        padding: 4px 8px;
        cursor: pointer;
        border: none;
        background: none;
        color: var(--secondary-text-color);
        border-radius: 4px;
        display: flex;
        align-items: center;
        justify-content: center;
      }
      .tab-action-btn:hover {
        background: var(--secondary-background-color);
        color: var(--primary-text-color);
      }
      .tab-action-btn.danger:hover {
        color: var(--error-color);
      }

      /* Sort controls */
      .sort-btn {
        display: flex;
        align-items: center;
        gap: 4px;
        padding: 6px 12px;
        border: 1px solid var(--divider-color);
        border-radius: 8px;
        background: var(--card-background-color);
        color: var(--primary-text-color);
        font-size: 13px;
        cursor: pointer;
        white-space: nowrap;
        flex-shrink: 0;
        height: 36px;
        box-sizing: border-box;
      }
      .sort-btn:hover {
        border-color: var(--primary-color);
      }
      .sort-btn svg {
        width: 16px;
        height: 16px;
      }
      .sort-dropdown {
        position: absolute;
        top: 100%;
        right: 0;
        background: var(--card-background-color);
        border: 1px solid var(--divider-color);
        border-radius: 8px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        z-index: 200;
        min-width: 160px;
        overflow: hidden;
        margin-top: 4px;
      }
      .sort-dropdown-item {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 10px 16px;
        border: none;
        background: transparent;
        color: var(--primary-text-color);
        font-size: 14px;
        cursor: pointer;
        width: 100%;
        text-align: left;
      }
      .sort-dropdown-item:hover {
        background: var(--secondary-background-color);
      }
      .sort-dropdown-item.active {
        color: var(--primary-color);
        font-weight: 500;
      }
      .sort-dropdown-item svg {
        width: 16px;
        height: 16px;
        margin-left: 8px;
      }
      .sort-wrapper {
        position: relative;
      }

      /* Tab context menu */
      .tab-context-menu {
        position: fixed;
        background: var(--card-background-color);
        border: 1px solid var(--divider-color);
        border-radius: 8px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        z-index: 300;
        min-width: 140px;
        overflow: hidden;
      }
      .tab-context-menu-item {
        display: block;
        width: 100%;
        padding: 10px 16px;
        border: none;
        background: transparent;
        color: var(--primary-text-color);
        font-size: 14px;
        cursor: pointer;
        text-align: left;
      }
      .tab-context-menu-item:hover {
        background: var(--secondary-background-color);
      }
      .tab-context-menu-item.danger {
        color: var(--error-color, #f44336);
      }

      .table-container {
        background: var(--card-background-color);
        border-radius: 8px;
        overflow-x: auto;
        box-shadow: var(--ha-card-box-shadow, 0 2px 2px rgba(0,0,0,0.1));
        -webkit-overflow-scrolling: touch;
      }

      table {
        width: 100%;
        border-collapse: collapse;
        min-width: 500px;
      }

      th, td {
        padding: 12px 16px;
        text-align: left;
        border-bottom: 1px solid var(--divider-color);
        white-space: nowrap;
      }

      /* Name column can wrap */
      th:first-child, td:first-child {
        white-space: normal;
        min-width: 120px;
        max-width: 200px;
      }

      th {
        background: var(--table-header-background-color, var(--secondary-background-color));
        font-weight: 500;
        color: var(--primary-text-color);
        position: sticky;
        top: 0;
      }

      /* Keyboard-navigable table rows (M-22) */
      tbody tr {
        cursor: pointer;
      }

      tbody tr:hover,
      tbody tr:focus {
        background: var(--table-row-background-color, rgba(0,0,0,0.04));
        outline: none;
      }

      tbody tr:focus-visible {
        box-shadow: inset 0 0 0 2px var(--primary-color);
      }

      tr:last-child td {
        border-bottom: none;
      }

      /* Mobile responsive */
      @media (max-width: 600px) {
        /* Top bar touch targets */
        .top-bar-sidebar-btn {
          width: 44px;
          height: 44px;
        }
        .top-bar-action-btn {
          width: 44px;
          height: 44px;
        }
        .top-bar {
          margin: -16px -16px 12px -16px;
        }

        /* Search row wrapping */
        .search-row {
          flex-wrap: wrap;
          height: auto;
          padding: 8px 16px;
        }
        .search-row-input-wrapper {
          height: 44px;
          min-width: 0;
          flex: 1 1 100%;
        }
        .search-row-input {
          font-size: 16px;
        }

        /* Sort controls */
        .sort-btn {
          min-height: 44px;
          height: 44px;
        }
        .sort-dropdown-item {
          padding: 12px 16px;
          min-height: 44px;
        }

        /* Tab bar with scroll indicator */
        .tab-bar {
          -webkit-mask-image: linear-gradient(90deg, transparent 0, #000 20px, #000 calc(100% - 20px), transparent 100%);
          mask-image: linear-gradient(90deg, transparent 0, #000 20px, #000 calc(100% - 20px), transparent 100%);
          padding: 0 20px;
          scrollbar-width: none;
          -webkit-overflow-scrolling: touch;
        }
        .tab-bar::-webkit-scrollbar {
          display: none;
        }
        .tab-item {
          min-height: 44px;
          padding: 12px 14px;
          display: flex;
          align-items: center;
        }
        .tab-add-btn {
          min-width: 44px;
          min-height: 44px;
          width: 44px;
          height: 44px;
        }
        .tab-action-btn {
          min-width: 44px;
          min-height: 44px;
        }

        /* Tab context menu */
        .tab-context-menu-item {
          min-height: 44px;
          padding: 12px 16px;
          display: flex;
          align-items: center;
        }

        /* Error banner close */
        .error-banner-close {
          min-width: 44px;
          min-height: 44px;
          padding: 10px;
          display: flex;
          align-items: center;
          justify-content: center;
        }

        /* Table to card layout */
        table {
          min-width: unset;
        }
        thead {
          display: none;
        }
        .table-container {
          box-shadow: none;
          background: transparent;
          border-radius: 0;
        }
        tbody tr {
          display: block;
          padding: 12px 16px;
          margin-bottom: 8px;
          background: var(--card-background-color);
          border-radius: 8px;
          box-shadow: 0 1px 3px rgba(0,0,0,0.08);
          border-bottom: none;
        }
        tbody tr:last-child {
          border-bottom: none;
        }
        tbody td {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 4px 0;
          border-bottom: none;
          white-space: normal;
        }
        tbody td::before {
          content: attr(data-label);
          font-weight: 500;
          color: var(--secondary-text-color);
          font-size: 12px;
          min-width: 80px;
          margin-right: 8px;
        }
        tbody td:first-child {
          font-weight: 500;
          font-size: 16px;
          padding-bottom: 8px;
          border-bottom: 1px solid var(--divider-color);
          margin-bottom: 8px;
          max-width: unset;
          min-width: unset;
        }
        tbody td:first-child::before {
          display: none;
        }
        th:first-child, td:first-child {
          max-width: unset;
          min-width: unset;
        }

        /* Dialog full-screen on mobile */
        .dialog {
          width: 100%;
          max-width: 100%;
          height: 100vh;
          max-height: 100vh;
          border-radius: 0;
          display: flex;
          flex-direction: column;
        }
        .dialog-content {
          flex: 1;
          overflow-y: auto;
          -webkit-overflow-scrolling: touch;
        }
        .dialog-close {
          padding: 10px;
          min-width: 44px;
          min-height: 44px;
          display: flex;
          align-items: center;
          justify-content: center;
        }
        .dialog-footer {
          flex-wrap: wrap;
          gap: 12px;
          padding: 12px 16px;
        }
        .dialog-footer-left {
          flex: 1 1 auto;
        }
        .dialog-footer-right {
          flex: 1 1 auto;
          justify-content: flex-end;
        }

        /* Form inputs - 44px touch targets + iOS zoom prevention */
        .form-group label {
          margin-bottom: 8px;
        }
        .form-group input,
        .form-group textarea,
        .form-group select {
          min-height: 44px;
          font-size: 16px;
          padding: 10px 12px;
        }
        .form-group textarea {
          min-height: 100px;
        }

        /* All buttons - 44px min-height */
        .btn {
          min-height: 44px;
          font-size: 15px;
          padding: 10px 16px;
        }

        /* Summary */
        .summary {
          gap: 16px;
          flex-wrap: wrap;
          padding: 12px 16px;
        }
        .summary-item {
          min-width: 0;
          flex: 1 1 auto;
        }
        .summary-value {
          font-size: 18px;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
      }

      .warranty-ok {
        color: var(--success-color, #4caf50);
      }

      .warranty-warning {
        color: var(--warning-color, #ff9800);
      }

      .warranty-expired {
        color: var(--error-color, #f44336);
      }

      .summary {
        margin-top: 16px;
        padding: 16px;
        background: var(--card-background-color);
        border-radius: 8px;
        display: flex;
        gap: 32px;
        box-shadow: var(--ha-card-box-shadow, 0 2px 2px rgba(0,0,0,0.1));
      }

      .summary-item {
        display: flex;
        flex-direction: column;
      }

      .summary-label {
        font-size: 12px;
        color: var(--secondary-text-color);
      }

      .summary-value {
        font-size: 20px;
        font-weight: 500;
        color: var(--primary-text-color);
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }

      .empty-state {
        text-align: center;
        padding: 48px 16px;
        color: var(--secondary-text-color);
      }

      .empty-state ha-icon {
        --mdc-icon-size: 64px;
        margin-bottom: 16px;
        opacity: 0.5;
      }

      /* Dialog styles */
      .dialog-backdrop {
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: rgba(0, 0, 0, 0.5);
        z-index: 100;
        display: flex;
        align-items: center;
        justify-content: center;
      }

      .dialog {
        background: var(--card-background-color);
        border-radius: 8px;
        width: 90%;
        max-width: 500px;
        max-height: 90vh;
        overflow-y: auto;
        box-shadow: 0 4px 20px rgba(0,0,0,0.3);
      }

      .dialog-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 16px;
        border-bottom: 1px solid var(--divider-color);
      }

      .dialog-header h2 {
        margin: 0;
        font-size: 18px;
        font-weight: 500;
      }

      .dialog-close {
        background: none;
        border: none;
        cursor: pointer;
        padding: 4px;
        color: var(--secondary-text-color);
      }

      .dialog-content {
        padding: 16px;
      }

      .form-group {
        margin-bottom: 16px;
      }

      .form-group label {
        display: block;
        margin-bottom: 4px;
        font-size: 14px;
        color: var(--primary-text-color);
      }

      .form-group input,
      .form-group textarea,
      .form-group select {
        width: 100%;
        padding: 8px 12px;
        border: 1px solid var(--divider-color);
        border-radius: 4px;
        font-size: 14px;
        background: var(--card-background-color);
        color: var(--primary-text-color);
        box-sizing: border-box;
      }

      .form-group textarea {
        min-height: 80px;
        resize: vertical;
      }

      .form-group input:focus,
      .form-group textarea:focus,
      .form-group select:focus {
        outline: none;
        border-color: var(--primary-color);
      }

      .dialog-footer {
        display: flex;
        justify-content: space-between;
        padding: 16px;
        border-top: 1px solid var(--divider-color);
      }

      .dialog-footer-left {
        display: flex;
      }

      .dialog-footer-right {
        display: flex;
        gap: 8px;
      }

      .btn {
        padding: 8px 16px;
        border-radius: 4px;
        font-size: 14px;
        cursor: pointer;
        border: none;
      }

      .btn-primary {
        background: var(--primary-color);
        color: var(--text-primary-color);
      }

      .btn-secondary {
        background: var(--secondary-background-color);
        color: var(--primary-text-color);
      }

      .btn-danger {
        background: var(--error-color, #f44336);
        color: white;
      }

      .btn:hover {
        opacity: 0.9;
      }

      .loading {
        display: flex;
        justify-content: center;
        padding: 48px;
      }

      .form-group.error input {
        border-color: var(--error-color, #f44336);
      }

      .form-group .error-message {
        color: var(--error-color, #f44336);
        font-size: 12px;
        margin-top: 4px;
      }

      .btn:disabled {
        opacity: 0.5;
        cursor: not-allowed;
      }

      .content-area {
        margin-top: 16px;
      }
    `;
  }

  constructor() {
    super();
    this._assets = [];
    this._categories = [];
    this._loading = true;
    this._dialogOpen = false;
    this._editingAsset = null;
    this._deleteConfirmOpen = false;
    this._saving = false;
    this._deleting = false;
    this._nameError = false;
    this._searchQuery = "";
    this._errorMessage = "";
    this._activeTab = "all";
    this._sortField = "updated_at";
    this._sortDirection = "desc";
    this._sortDropdownOpen = false;
    this._categoryDialogOpen = false;
    this._categoryDialogName = "";
    this._categoryDialogId = null;
    this._categoryDeleteConfirmOpen = false;
    this._categoryDeleteTarget = null;
    this._tabContextMenu = null;
    this._boundHandleKeydown = this._handleKeydown.bind(this);
    this._boundCloseMenus = this._closeAllMenus.bind(this);
    this._prevLanguage = null;
  }

  _onSearchInput(e) {
    this._searchQuery = e.target.value;
  }

  _getCategoryName(categoryId) {
    if (!categoryId) return this._localize("uncategorized");
    const cat = this._categories.find(c => c.id === categoryId);
    return cat ? cat.name : this._localize("uncategorized");
  }

  _getFilteredAssets() {
    let assets = this._assets;

    // 1. Category filter
    if (this._activeTab && this._activeTab !== "all") {
      if (this._activeTab === "__uncategorized__") {
        assets = assets.filter(a => !a.category_id);
      } else {
        assets = assets.filter(a => a.category_id === this._activeTab);
      }
    }

    // 2. Search filter
    if (this._searchQuery?.trim()) {
      const query = this._searchQuery.toLowerCase().trim();
      assets = assets.filter((asset) => {
        const name = (asset.name || "").toLowerCase();
        const brand = (asset.brand || "").toLowerCase();
        const catName = this._getCategoryName(asset.category_id).toLowerCase();
        return name.includes(query) || brand.includes(query) || catName.includes(query);
      });
    }

    // 3. Sort
    assets = this._sortAssets(assets);
    return assets;
  }

  _sortAssets(assets) {
    const sorted = [...assets];
    const dir = this._sortDirection === "asc" ? 1 : -1;
    sorted.sort((a, b) => {
      let va, vb;
      switch (this._sortField) {
        case "name":
          va = (a.name || "").toLowerCase();
          vb = (b.name || "").toLowerCase();
          return va < vb ? -dir : va > vb ? dir : 0;
        case "created_at":
          va = a.created_at || "";
          vb = b.created_at || "";
          return va < vb ? -dir : va > vb ? dir : 0;
        case "updated_at":
        default:
          va = a.updated_at || "";
          vb = b.updated_at || "";
          return va < vb ? -dir : va > vb ? dir : 0;
      }
    });
    return sorted;
  }

  connectedCallback() {
    super.connectedCallback();
    // Ensure translations are loaded before the data load's re-render.
    loadTranslations().then(() => {
      this._loadAssets();
    });
    document.addEventListener("keydown", this._boundHandleKeydown);
    document.addEventListener("click", this._boundCloseMenus);
    if (this.hass) {
      const lang = this.hass.language || "en";
      this._prevLanguage = lang;
      HaAssetPanel._startSidebarPatcher(lang);
    }
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    document.removeEventListener("keydown", this._boundHandleKeydown);
    document.removeEventListener("click", this._boundCloseMenus);
  }

  updated(changedProperties) {
    super.updated(changedProperties);
    if (changedProperties.has("hass") && this.hass) {
      const newLang = this.hass.language || "en";
      if (this._prevLanguage !== newLang) {
        this._prevLanguage = newLang;
        HaAssetPanel._startSidebarPatcher(newLang);
      }
    }
  }

  _handleKeydown(e) {
    if (e.key === "Escape") {
      if (this._categoryDialogOpen) {
        this._closeCategoryDialog();
      } else if (this._dialogOpen) {
        this._closeDialog();
      }
      this._closeAllMenus();
    }
  }

  _closeAllMenus() {
    if (this._sortDropdownOpen) {
      this._sortDropdownOpen = false;
      this.requestUpdate();
    }
    if (this._tabContextMenu) {
      this._tabContextMenu = null;
      this.requestUpdate();
    }
  }

  /**
   * Show an error message both in console and as a visible notification.
   * Uses HA's hass-notification event pattern for toast display, with
   * a fallback error banner rendered in the panel itself.
   */
  _showError(message, error) {
    console.error(message, error);
    // Fire HA toast notification (bubbles up to notification-manager)
    fireHassNotification(this, message);
    // Also set an inline error banner as fallback
    this._errorMessage = message;
  }

  _dismissError() {
    this._errorMessage = "";
  }

  async _loadAssets() {
    this._loading = true;
    try {
      const result = await this.hass.callWS({ type: "woow_ha_records/asset/list" });
      this._assets = result.assets || [];
      this._categories = result.categories || [];
    } catch (e) {
      this._showError(this._localize("load_error"), e);
      this._assets = [];
      this._categories = [];
    }
    this._loading = false;
  }

  _toggleSidebar() {
    this.dispatchEvent(new CustomEvent("hass-toggle-menu", { bubbles: true, composed: true }));
  }

  _localize(key) {
    return _getTranslation(key, this.hass?.language);
  }

  /**
   * Format a date string for display. Uses safeParseDateStr to validate
   * the date and handle cross-browser parsing inconsistencies (M-20).
   */
  _formatDate(dateStr) {
    if (!dateStr) return "-";
    const date = safeParseDateStr(dateStr);
    if (!date) return this._localize("invalid_date");
    try {
      return date.toLocaleDateString(this.hass?.language || "en");
    } catch (_e) {
      // Fallback if locale is not supported by browser
      return date.toLocaleDateString("en");
    }
  }

  /**
   * Format a numeric value for display. Explicitly checks for null,
   * undefined, and empty string so that 0 displays as "0" (L-16).
   */
  _formatValue(value) {
    if (value === null || value === undefined || value === "") return "-";
    return Number(value).toLocaleString(this.hass?.language || "en");
  }

  /**
   * Determine warranty status. Uses safeParseDateStr for robust
   * cross-browser date handling (M-20).
   */
  _getWarrantyStatus(warrantyUntil) {
    if (!warrantyUntil) return { class: "", text: "-" };

    const now = new Date();
    const warranty = safeParseDateStr(warrantyUntil);
    if (!warranty) return { class: "", text: this._localize("invalid_date") };

    const daysLeft = Math.ceil((warranty - now) / (1000 * 60 * 60 * 24));

    if (daysLeft < 0) {
      return { class: "warranty-expired", text: this._localize("expired") };
    } else if (daysLeft <= 30) {
      return { class: "warranty-warning", text: this._formatDate(warrantyUntil) };
    }
    return { class: "warranty-ok", text: this._formatDate(warrantyUntil) };
  }

  // ---- Asset dialog ----

  _openAddDialog() {
    this._editingAsset = {
      name: "",
      brand: "",
      category_id: this._activeTab !== "all" && this._activeTab !== "__uncategorized__" ? this._activeTab : "",
      value: 0,
      purchase_at: "",
      warranty_until: "",
      manual_md: "",
      maintenance_md: "",
    };
    this._dialogOpen = true;
    this._errorMessage = "";
    this.updateComplete.then(() => this._focusFirstDialogInput());
  }

  _openEditDialog(asset) {
    this._editingAsset = { ...asset };
    this._dialogOpen = true;
    this._errorMessage = "";
    this.updateComplete.then(() => this._focusFirstDialogInput());
  }

  _focusFirstDialogInput() {
    const dialog = this.shadowRoot?.querySelector(".dialog");
    if (!dialog) return;
    const firstInput = dialog.querySelector("input, textarea, button, select");
    if (firstInput) firstInput.focus();
  }

  _handleDialogKeydown(e) {
    if (e.key !== "Tab") return;

    const dialog = this.shadowRoot?.querySelector(".dialog");
    if (!dialog) return;

    const focusableSelector = 'input, textarea, button:not([disabled]), select, [tabindex]:not([tabindex="-1"])';
    const focusableElements = [...dialog.querySelectorAll(focusableSelector)];
    if (focusableElements.length === 0) return;

    const firstFocusable = focusableElements[0];
    const lastFocusable = focusableElements[focusableElements.length - 1];

    if (e.shiftKey) {
      if (document.activeElement === firstFocusable ||
          this.shadowRoot.activeElement === firstFocusable) {
        e.preventDefault();
        lastFocusable.focus();
      }
    } else {
      if (document.activeElement === lastFocusable ||
          this.shadowRoot.activeElement === lastFocusable) {
        e.preventDefault();
        firstFocusable.focus();
      }
    }
  }

  _closeDialog() {
    this._dialogOpen = false;
    this._editingAsset = null;
    this._deleteConfirmOpen = false;
    this._nameError = false;
  }

  async _saveAsset() {
    const name = (this._editingAsset?.name || "").trim();
    if (!name) {
      this._nameError = true;
      return;
    }
    this._nameError = false;

    if (this._saving) return;
    this._saving = true;

    try {
      if (this._editingAsset.id) {
        await this.hass.callWS({
          type: "woow_ha_records/asset/update",
          asset_id: this._editingAsset.id,
          name: name,
          brand: (this._editingAsset.brand || "").trim(),
          category_id: this._editingAsset.category_id || "",
          value: parseFloat(this._editingAsset.value) || 0,
          purchase_at: this._editingAsset.purchase_at || null,
          warranty_until: this._editingAsset.warranty_until || null,
          manual_md: this._editingAsset.manual_md || "",
          maintenance_md: this._editingAsset.maintenance_md || "",
        });
      } else {
        await this.hass.callWS({
          type: "woow_ha_records/asset/create",
          name: name,
          brand: (this._editingAsset.brand || "").trim(),
          category_id: this._editingAsset.category_id || "",
          value: parseFloat(this._editingAsset.value) || 0,
          purchase_at: this._editingAsset.purchase_at || null,
          warranty_until: this._editingAsset.warranty_until || null,
          manual_md: this._editingAsset.manual_md || "",
          maintenance_md: this._editingAsset.maintenance_md || "",
        });
      }
      this._closeDialog();
      await this._loadAssets();
    } catch (e) {
      this._showError(this._localize("save_error"), e);
    } finally {
      this._saving = false;
    }
  }

  async _deleteAsset() {
    if (!this._editingAsset?.id) return;

    if (this._deleting) return;
    this._deleting = true;

    try {
      await this.hass.callWS({
        type: "woow_ha_records/asset/delete",
        asset_id: this._editingAsset.id,
      });
      this._closeDialog();
      await this._loadAssets();
    } catch (e) {
      this._showError(this._localize("delete_error"), e);
    } finally {
      this._deleting = false;
    }
  }

  _handleInput(e, field) {
    this._editingAsset = {
      ...this._editingAsset,
      [field]: e.target.value,
    };
  }

  _handleRowKeydown(e, asset) {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      this._openEditDialog(asset);
    }
  }

  // ---- Category CRUD ----

  _openAddCategoryDialog() {
    this._categoryDialogName = "";
    this._categoryDialogId = null;
    this._categoryDialogOpen = true;
    this._closeAllMenus();
    this.updateComplete.then(() => {
      const input = this.shadowRoot?.querySelector(".category-dialog-input");
      if (input) input.focus();
    });
  }

  _openRenameCategoryDialog(cat) {
    this._categoryDialogName = cat.name;
    this._categoryDialogId = cat.id;
    this._categoryDialogOpen = true;
    this._closeAllMenus();
    this.updateComplete.then(() => {
      const input = this.shadowRoot?.querySelector(".category-dialog-input");
      if (input) input.focus();
    });
  }

  _closeCategoryDialog() {
    this._categoryDialogOpen = false;
    this._categoryDialogName = "";
    this._categoryDialogId = null;
  }

  async _saveCategoryDialog() {
    const name = this._categoryDialogName.trim();
    if (!name) {
      this._showError(this._localize("category_empty_error"));
      return;
    }

    try {
      if (this._categoryDialogId) {
        await this.hass.callWS({
          type: "woow_ha_records/asset/update_category",
          category_id: this._categoryDialogId,
          name: name,
        });
      } else {
        await this.hass.callWS({
          type: "woow_ha_records/asset/create_category",
          name: name,
        });
      }
      this._closeCategoryDialog();
      await this._loadAssets();
    } catch (e) {
      const errMsg = e?.message || "";
      if (errMsg.toLowerCase().includes("duplicate") || errMsg.toLowerCase().includes("already exists")) {
        this._showError(this._localize("category_duplicate_error"), e);
      } else {
        this._showError(errMsg || this._localize("save_error"), e);
      }
    }
  }

  _openDeleteCategoryConfirm(cat) {
    const count = this._assets.filter(a => a.category_id === cat.id).length;
    this._categoryDeleteTarget = { ...cat, assetCount: count };
    this._categoryDeleteConfirmOpen = true;
    this._closeAllMenus();
  }

  _closeDeleteCategoryConfirm() {
    this._categoryDeleteConfirmOpen = false;
    this._categoryDeleteTarget = null;
  }

  async _confirmDeleteCategory() {
    if (!this._categoryDeleteTarget) return;
    try {
      await this.hass.callWS({
        type: "woow_ha_records/asset/delete_category",
        // The cascade is opt-in on the API (#49). This dialog is that opt-in:
        // it names the category and counts the assets that go with it.
        //
        // It is a weaker gate than the note panel's, which makes the user type
        // the category name back. Accepted here because an asset has an escape
        // route a note does not — reassign it with update and it survives the
        // cascade — and because #49 asked to guard the API, not to tighten a
        // panel that already confirmed. Tighten this before assuming the two
        // panels gate alike.
        category_id: this._categoryDeleteTarget.id,
        force: true,
      });
      if (this._activeTab === this._categoryDeleteTarget.id) {
        this._activeTab = "all";
      }
      this._closeDeleteCategoryConfirm();
      await this._loadAssets();
    } catch (e) {
      this._showError(this._localize("delete_error"), e);
    }
  }

  // ---- Sort ----

  _toggleSortDropdown(e) {
    e.stopPropagation();
    this._sortDropdownOpen = !this._sortDropdownOpen;
    this._tabContextMenu = null;
    this.requestUpdate();
  }

  _setSortField(field) {
    if (this._sortField === field) {
      this._sortDirection = this._sortDirection === "asc" ? "desc" : "asc";
    } else {
      this._sortField = field;
      this._sortDirection = field === "name" ? "asc" : "desc";
    }
    this._sortDropdownOpen = false;
  }

  _getSortLabel() {
    const labels = {
      name: this._localize("sort_name"),
      created_at: this._localize("sort_created"),
      updated_at: this._localize("sort_updated"),
    };
    return labels[this._sortField] || this._sortField;
  }

  // ---- Tab context menu ----

  _onTabContextMenu(e, cat) {
    e.preventDefault();
    e.stopPropagation();
    this._tabContextMenu = { cat, x: e.clientX, y: e.clientY };
    this._sortDropdownOpen = false;
    this.requestUpdate();
  }

  // ---- Render helpers ----

  _renderTabBar() {
    const allCount = this._assets.length;
    const activeCategory = this._categories.find(cat => cat.id === this._activeTab);

    return html`
      <div class="tab-bar">
        <button
          class="tab-item ${this._activeTab === "all" ? "active" : ""}"
          @click=${() => { this._activeTab = "all"; }}
        >
          ${this._localize("all_categories")}
          <span class="tab-item-count">${allCount}</span>
        </button>
        ${this._categories.map(cat => {
          const count = this._assets.filter(a => a.category_id === cat.id).length;
          return html`
            <button
              class="tab-item ${this._activeTab === cat.id ? "active" : ""}"
              @click=${() => { this._activeTab = cat.id; }}
              @contextmenu=${(e) => this._onTabContextMenu(e, cat)}
            >
              ${cat.name}
              <span class="tab-item-count">${count}</span>
            </button>
          `;
        })}
        <button
          class="tab-add-btn"
          @click=${() => this._openAddCategoryDialog()}
          title="${this._localize("add_category")}"
        >+</button>
        ${activeCategory
          ? html`
              <div class="tab-actions">
                <button
                  class="tab-action-btn"
                  @click=${() => this._openRenameCategoryDialog(activeCategory)}
                  title="${this._localize("rename_category")}"
                >
                  <svg viewBox="0 0 24 24" style="width:16px;height:16px"><path fill="currentColor" d="M20.71,7.04C21.1,6.65 21.1,6 20.71,5.63L18.37,3.29C18,2.9 17.35,2.9 16.96,3.29L15.12,5.12L18.87,8.87M3,17.25V21H6.75L17.81,9.93L14.06,6.18L3,17.25Z"/></svg>
                </button>
                <button
                  class="tab-action-btn danger"
                  @click=${() => this._openDeleteCategoryConfirm(activeCategory)}
                  title="${this._localize("delete_category")}"
                >
                  <svg viewBox="0 0 24 24" style="width:16px;height:16px"><path fill="currentColor" d="M19,4H15.5L14.5,3H9.5L8.5,4H5V6H19M6,19A2,2 0 0,0 8,21H16A2,2 0 0,0 18,19V7H6V19Z"/></svg>
                </button>
              </div>
            `
          : ""}
      </div>
    `;
  }

  _renderTabContextMenu() {
    if (!this._tabContextMenu) return "";
    const { cat, x, y } = this._tabContextMenu;
    return html`
      <div
        class="tab-context-menu"
        style="left: ${x}px; top: ${y}px;"
        @click=${(e) => e.stopPropagation()}
      >
        <button class="tab-context-menu-item" @click=${() => this._openRenameCategoryDialog(cat)}>
          ${this._localize("rename_category")}
        </button>
        <button class="tab-context-menu-item danger" @click=${() => this._openDeleteCategoryConfirm(cat)}>
          ${this._localize("delete_category")}
        </button>
      </div>
    `;
  }

  _renderSortDropdown() {
    const arrowUp = html`<svg viewBox="0 0 24 24"><path fill="currentColor" d="M7,15L12,10L17,15H7Z"/></svg>`;
    const arrowDown = html`<svg viewBox="0 0 24 24"><path fill="currentColor" d="M7,10L12,15L17,10H7Z"/></svg>`;
    const currentArrow = this._sortDirection === "asc" ? arrowUp : arrowDown;

    return html`
      <div class="sort-wrapper">
        <button class="sort-btn" @click=${(e) => this._toggleSortDropdown(e)}>
          ${currentArrow}
          ${this._getSortLabel()}
        </button>
        ${this._sortDropdownOpen ? html`
          <div class="sort-dropdown" @click=${(e) => e.stopPropagation()}>
            ${["name", "created_at", "updated_at"].map(field => html`
              <button
                class="sort-dropdown-item ${this._sortField === field ? "active" : ""}"
                @click=${() => this._setSortField(field)}
              >
                ${{
                  name: this._localize("sort_name"),
                  created_at: this._localize("sort_created"),
                  updated_at: this._localize("sort_updated"),
                }[field]}
                ${this._sortField === field
                  ? (this._sortDirection === "asc" ? arrowUp : arrowDown)
                  : ""}
              </button>
            `)}
          </div>
        ` : ""}
      </div>
    `;
  }

  _renderTable() {
    const filteredAssets = this._getFilteredAssets();

    if (this._assets.length === 0) {
      return html`
        <div class="table-container">
          <div class="empty-state">
            <ha-icon icon="mdi:package-variant-closed"></ha-icon>
            <div>${this._localize("no_assets")}</div>
            <div style="font-size: 14px; margin-top: 8px;">${this._localize("no_assets_hint")}</div>
          </div>
        </div>
      `;
    }

    if (filteredAssets.length === 0) {
      return html`
        <div class="table-container">
          <div class="empty-state">
            <ha-icon icon="mdi:magnify"></ha-icon>
            <div>${this._localize("no_search_results")}</div>
          </div>
        </div>
      `;
    }

    return html`
      <div class="table-container">
        <table>
          <thead>
            <tr>
              <th>${this._localize("name")}</th>
              <th>${this._localize("brand")}</th>
              <th>${this._localize("category")}</th>
              <th>${this._localize("value")}</th>
              <th>${this._localize("warranty")}</th>
            </tr>
          </thead>
          <tbody>
            ${filteredAssets.map(asset => {
              const warranty = this._getWarrantyStatus(asset.warranty_until);
              const catName = this._getCategoryName(asset.category_id);
              return html`
                <tr
                  tabindex="0"
                  role="row"
                  aria-label="${asset.name}"
                  @click=${() => this._openEditDialog(asset)}
                  @keydown=${(e) => this._handleRowKeydown(e, asset)}
                >
                  <td data-label="${this._localize("name")}">${asset.name}</td>
                  <td data-label="${this._localize("brand")}">${asset.brand || "-"}</td>
                  <td data-label="${this._localize("category")}">${catName}</td>
                  <td data-label="${this._localize("value")}">${this._formatValue(asset.value)}</td>
                  <td data-label="${this._localize("warranty")}" class=${warranty.class}>${warranty.text}</td>
                </tr>
              `;
            })}
          </tbody>
        </table>
      </div>
    `;
  }

  _renderSummary() {
    const filteredAssets = this._getFilteredAssets();
    const totalAssets = filteredAssets.length;
    const totalValue = filteredAssets.reduce((sum, a) => sum + (a.value || 0), 0);

    return html`
      <div class="summary">
        <div class="summary-item">
          <span class="summary-label">${this._localize("total_assets")}</span>
          <span class="summary-value">${totalAssets}</span>
        </div>
        <div class="summary-item">
          <span class="summary-label">${this._localize("total_value")}</span>
          <span class="summary-value">${this._formatValue(totalValue)}</span>
        </div>
      </div>
    `;
  }

  _renderDialog() {
    const isEditing = !!this._editingAsset?.id;
    const title = isEditing ? this._localize("edit_asset") : this._localize("add_asset");

    return html`
      <div
        class="dialog-backdrop"
        @click=${this._closeDialog}
      >
        <div
          class="dialog"
          role="dialog"
          aria-modal="true"
          aria-labelledby="asset-dialog-title"
          @click=${e => e.stopPropagation()}
          @keydown=${(e) => this._handleDialogKeydown(e)}
        >
          <div class="dialog-header">
            <h2 id="asset-dialog-title">${title}</h2>
            <button
              class="dialog-close"
              @click=${this._closeDialog}
              aria-label="${this._localize("cancel")}"
            >&#x2715;</button>
          </div>

          <div class="dialog-content">
            <div class="form-group ${this._nameError ? "error" : ""}">
              <label>${this._localize("name")} *</label>
              <input
                type="text"
                .value=${this._editingAsset?.name || ""}
                aria-required="true"
                aria-invalid="${this._nameError}"
                @input=${e => {
                  this._handleInput(e, "name");
                  this._nameError = false;
                }}
              />
              ${this._nameError ? html`<div class="error-message" role="alert">${this._localize("name_required")}</div>` : ""}
            </div>

            <div class="form-group">
              <label>${this._localize("brand")}</label>
              <input
                type="text"
                .value=${this._editingAsset?.brand || ""}
                @input=${e => this._handleInput(e, "brand")}
              />
            </div>

            <div class="form-group">
              <label>${this._localize("category")}</label>
              <select
                .value=${this._editingAsset?.category_id || ""}
                @change=${e => this._handleInput(e, "category_id")}
              >
                <option value="">${this._localize("uncategorized")}</option>
                ${this._categories.map(cat => html`
                  <option value="${cat.id}" ?selected=${this._editingAsset?.category_id === cat.id}>${cat.name}</option>
                `)}
              </select>
            </div>

            <div class="form-group">
              <label>${this._localize("value")}</label>
              <input
                type="number"
                .value=${this._editingAsset?.value ?? 0}
                @input=${e => this._handleInput(e, "value")}
              />
            </div>

            <div class="form-group">
              <label>${this._localize("purchase_at")}</label>
              <input
                type="date"
                .value=${this._editingAsset?.purchase_at?.split("T")[0] || ""}
                @input=${e => this._handleInput(e, "purchase_at")}
              />
            </div>

            <div class="form-group">
              <label>${this._localize("warranty_until")}</label>
              <input
                type="date"
                .value=${this._editingAsset?.warranty_until?.split("T")[0] || ""}
                @input=${e => this._handleInput(e, "warranty_until")}
              />
            </div>

            <div class="form-group">
              <label>${this._localize("manual")}</label>
              <textarea
                .value=${this._editingAsset?.manual_md || ""}
                @input=${e => this._handleInput(e, "manual_md")}
              ></textarea>
            </div>

            <div class="form-group">
              <label>${this._localize("maintenance")}</label>
              <textarea
                .value=${this._editingAsset?.maintenance_md || ""}
                @input=${e => this._handleInput(e, "maintenance_md")}
              ></textarea>
            </div>
          </div>

          ${this._deleteConfirmOpen
            ? html`
                <div class="dialog-footer" style="background: var(--error-color); color: white;">
                  <div>${this._localize("delete_confirm")}</div>
                  <div class="dialog-footer-right">
                    <button
                      class="btn btn-secondary"
                      @click=${() => (this._deleteConfirmOpen = false)}
                      ?disabled=${this._deleting}
                    >
                      ${this._localize("cancel")}
                    </button>
                    <button
                      class="btn btn-danger"
                      @click=${this._deleteAsset}
                      ?disabled=${this._deleting}
                      aria-label="${this._localize("delete")}"
                    >
                      ${this._deleting ? this._localize("deleting") : this._localize("delete")}
                    </button>
                  </div>
                </div>
              `
            : html`
                <div class="dialog-footer">
                  <div class="dialog-footer-left">
                    ${isEditing
                      ? html`
                          <button
                            class="btn btn-danger"
                            @click=${() => (this._deleteConfirmOpen = true)}
                            ?disabled=${this._saving || this._deleting}
                            aria-label="${this._localize("delete")}"
                          >
                            ${this._localize("delete")}
                          </button>
                        `
                      : ""}
                  </div>
                  <div class="dialog-footer-right">
                    <button class="btn btn-secondary" @click=${this._closeDialog} ?disabled=${this._saving}>
                      ${this._localize("cancel")}
                    </button>
                    <button class="btn btn-primary" @click=${this._saveAsset} ?disabled=${this._saving}>
                      ${this._saving ? "..." : this._localize("save")}
                    </button>
                  </div>
                </div>
              `}
        </div>
      </div>
    `;
  }

  _renderCategoryDialog() {
    if (!this._categoryDialogOpen) return "";
    const isRename = !!this._categoryDialogId;
    const title = isRename ? this._localize("rename_category") : this._localize("add_category");

    return html`
      <div class="dialog-backdrop" @click=${this._closeCategoryDialog}>
        <div
          class="dialog"
          role="dialog"
          aria-modal="true"
          @click=${e => e.stopPropagation()}
          @keydown=${(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              this._saveCategoryDialog();
            }
          }}
        >
          <div class="dialog-header">
            <h2>${title}</h2>
            <button class="dialog-close" @click=${this._closeCategoryDialog}>&#x2715;</button>
          </div>
          <div class="dialog-content">
            <div class="form-group">
              <label>${this._localize("category_name")}</label>
              <input
                class="category-dialog-input"
                type="text"
                .value=${this._categoryDialogName}
                placeholder="${this._localize("category_name_placeholder")}"
                @input=${(e) => { this._categoryDialogName = e.target.value; }}
              />
            </div>
          </div>
          <div class="dialog-footer">
            <div></div>
            <div class="dialog-footer-right">
              <button class="btn btn-secondary" @click=${this._closeCategoryDialog}>
                ${this._localize("cancel")}
              </button>
              <button class="btn btn-primary" @click=${() => this._saveCategoryDialog()}>
                ${this._localize("save")}
              </button>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  _renderDeleteCategoryConfirm() {
    if (!this._categoryDeleteConfirmOpen || !this._categoryDeleteTarget) return "";
    const { name, assetCount } = this._categoryDeleteTarget;

    return html`
      <div class="dialog-backdrop" @click=${this._closeDeleteCategoryConfirm}>
        <div class="dialog" @click=${e => e.stopPropagation()}>
          <div class="dialog-header">
            <h2>${this._localize("delete_category")}</h2>
            <button class="dialog-close" @click=${this._closeDeleteCategoryConfirm}>&#x2715;</button>
          </div>
          <div class="dialog-content">
            <p>${this._localize("delete_category_confirm").replace("{count}", assetCount)}</p>
            <p style="font-weight: 500; margin-top: 8px;">${name} (${assetCount})</p>
          </div>
          <div class="dialog-footer">
            <div></div>
            <div class="dialog-footer-right">
              <button class="btn btn-secondary" @click=${this._closeDeleteCategoryConfirm}>
                ${this._localize("cancel")}
              </button>
              <button class="btn btn-danger" @click=${() => this._confirmDeleteCategory()}>
                ${this._localize("delete")}
              </button>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  render() {
    return html`
      <div class="container">
        <!-- Top Bar -->
        <div class="top-bar">
          <button class="top-bar-sidebar-btn" @click=${this._toggleSidebar}>
            <svg viewBox="0 0 24 24"><path fill="currentColor" d="M3,6H21V8H3V6M3,11H21V13H3V11M3,16H21V18H3V16Z"/></svg>
          </button>
          <h1 class="top-bar-title">${this._localize("title")}</h1>
        </div>

        <!-- Search Row (full width) -->
        <div class="search-row">
          <div class="search-row-input-wrapper">
            <svg class="search-row-icon" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M9.5,3A6.5,6.5 0 0,1 16,9.5C16,11.11 15.41,12.59 14.44,13.73L14.71,14H15.5L20.5,19L19,20.5L14,15.5V14.71L13.73,14.44C12.59,15.41 11.11,16 9.5,16A6.5,6.5 0 0,1 3,9.5A6.5,6.5 0 0,1 9.5,3M9.5,5C7,5 5,7 5,9.5C5,12 7,14 9.5,14C12,14 14,12 14,9.5C14,7 12,5 9.5,5Z"/></svg>
            <input
              class="search-row-input"
              type="text"
              placeholder="${getCommonTranslation('search', this.hass?.language)}"
              aria-label="${getCommonTranslation('search', this.hass?.language)}"
              .value=${this._searchQuery}
              @input=${this._onSearchInput}
            />
          </div>
        </div>

        <!-- Action Row: Add button + Sort -->
        <div class="action-row">
          <button
            class="btn btn-primary"
            @click=${this._openAddDialog}
            title="${this._localize("add_asset")}"
            aria-label="${this._localize("add_asset")}"
          >
            + ${this._localize("add_asset")}
          </button>
          ${this._renderSortDropdown()}
        </div>

        <!-- Category Tabs -->
        ${this._renderTabBar()}

        <!-- Error banner (M-19: visible error feedback) -->
        ${this._errorMessage
          ? html`
              <div class="error-banner" role="alert">
                <span class="error-banner-message">${this._errorMessage}</span>
                <button
                  class="error-banner-close"
                  @click=${this._dismissError}
                  aria-label="${this._localize("cancel")}"
                >&#x2715;</button>
              </div>
            `
          : ""}

        <div class="content-area">
          ${this._loading
            ? html`<div class="loading"><ha-circular-progress active></ha-circular-progress></div>`
            : html`
                ${this._renderTable()}
                ${this._renderSummary()}
              `}
        </div>

        ${this._dialogOpen ? this._renderDialog() : ""}
        ${this._renderCategoryDialog()}
        ${this._renderDeleteCategoryConfirm()}
        ${this._renderTabContextMenu()}
      </div>
    `;
  }

  static _patchSidebarTitle(lang) {
    const title = lang && (lang.startsWith("zh-TW") || lang.startsWith("zh-HK") || lang === "zh-Hant")
      ? "\u8CC7\u7522\u7D00\u9304"
      : lang && lang.startsWith("zh")
        ? "\u8D44\u4EA7\u7EAA\u5F55"
        : "Asset Record";
    window.__haAssetRecordLang = lang;
    try {
      const ha = document.querySelector("home-assistant");
      if (!ha || !ha.shadowRoot) return;
      const main = ha.shadowRoot.querySelector("home-assistant-main");
      if (!main || !main.shadowRoot) return;
      const sidebar = main.shadowRoot.querySelector("ha-sidebar");
      if (!sidebar || !sidebar.shadowRoot) return;
      const items = sidebar.shadowRoot.querySelectorAll("ha-md-list-item");
      for (const item of items) {
        const anchor = item.shadowRoot && item.shadowRoot.querySelector('a[href="/ha-asset-record"]');
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
    if (window.__haAssetRecordSidebarInterval) {
      HaAssetPanel._patchSidebarTitle(lang);
      return;
    }
    window.__haAssetRecordLang = lang;
    window.__haAssetRecordSidebarInterval = setInterval(() => {
      try {
        const haEl = document.querySelector("home-assistant");
        if (haEl && haEl.hass && haEl.hass.language) {
          window.__haAssetRecordLang = haEl.hass.language;
        }
      } catch (e) { /* ignore */ }
      const currentLang = window.__haAssetRecordLang || "en";
      HaAssetPanel._patchSidebarTitle(currentLang);
    }, 2000);
    setTimeout(() => HaAssetPanel._patchSidebarTitle(lang), 200);
  }
}

customElements.define("ha-asset-panel", HaAssetPanel);
