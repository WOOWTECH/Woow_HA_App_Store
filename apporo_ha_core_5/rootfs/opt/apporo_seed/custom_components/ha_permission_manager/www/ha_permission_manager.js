/**
 * HA Permission Manager - Frontend Panel
 * Uses Lit Element for reactive UI components
 */

// Local Lit bundle (no CDN dependency for offline/intranet environments)
import {
  LitElement,
  html,
  css,
  unsafeCSS,
} from "/local/lit.js";

// Inlined shared styles for HA panel compatibility
const sharedStylesLit = `
  /* TOP BAR - follows HA native theme */
  .top-bar {
    display: flex;
    align-items: center;
    height: 56px;
    padding: 0 16px;
    background: var(--app-header-background-color, var(--primary-color));
    color: var(--app-header-text-color, var(--text-primary-color, white));
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
  .top-bar-sidebar-btn:hover { background: rgba(255, 255, 255, 0.1); }
  .top-bar-sidebar-btn svg { width: 24px; height: 24px; }
  .top-bar-title {
    flex: 1;
    font-size: 20px;
    font-weight: 500;
    margin: 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    color: inherit;
  }
  .top-bar-actions { display: flex; align-items: center; gap: 4px; flex-shrink: 0; }
  .top-bar-action-btn {
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
  }
  .top-bar-action-btn:hover { background: rgba(255, 255, 255, 0.1); }
  .top-bar-action-btn svg { width: 24px; height: 24px; }

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

// Translation helper
const commonTranslations = {
  en: { menu: 'Menu', search: 'Search...', add: 'Add', more_actions: 'More actions' },
  'zh-Hant': { menu: '選單', search: '搜尋...', add: '新增', more_actions: '更多操作' },
  'zh-Hans': { menu: '菜单', search: '搜索...', add: '添加', more_actions: '更多操作' },
};
function getCommonTranslation(key, lang = 'en') {
  const langKey = lang?.startsWith('zh-TW') || lang?.startsWith('zh-HK') ? 'zh-Hant' :
                  lang?.startsWith('zh') ? 'zh-Hans' : 'en';
  return commonTranslations[langKey]?.[key] || commonTranslations['en'][key] || key;
}

// Internationalization strings
const I18N = {
  en: {
    title: "Permission Manager",
    users: "Users",
    resources: "Resources",
    user: "User",
    searchPlaceholder: "Search resources...",
    loading: "Loading permission matrix...",
    noEntities: "No permission entities found",
    addResources: "Add some areas, labels, or other resources to get started",
    noMatch: "No resources match your search",
    items: "items",
    admin: "Admin",
    protected: "Protected",
    permissionLevels: {
      "0": "Closed",
      "1": "View",
    },
    resourceTypes: {
      areas: "Areas",
      labels: "Labels",
      panels: "Panels",
    },
    resourceDescriptions: {
      areas: "Controls which areas appear in the Control Panel. The Control Panel is automatically created by Permission Manager and cannot be customized by users.",
      labels: "Controls which labels appear in the Control Panel. The Control Panel is automatically created by Permission Manager and cannot be customized by users.",
    },
    accessDenied: "Access Denied",
    accessDeniedMessage: "You don't have permission to view this panel.",
    returnHome: "Return to Home",
    readOnlyMode: "Read-only mode",
  },
  "zh-Hans": {
    title: "权限管理器",
    users: "用户",
    resources: "资源",
    user: "用户",
    searchPlaceholder: "搜索资源...",
    loading: "正在加载权限矩阵...",
    noEntities: "未找到权限实体",
    addResources: "添加一些区域、标签或其他资源以开始使用",
    noMatch: "没有匹配搜索的资源",
    items: "项",
    admin: "管理员",
    protected: "受保护",
    permissionLevels: {
      "0": "关闭",
      "1": "查看",
    },
    resourceTypes: {
      areas: "区域",
      labels: "标签",
      panels: "面板",
    },
    resourceDescriptions: {
      areas: "控制哪些区域会显示在控制面板中。控制面板由权限管理器自动创建，用户无法自定义。",
      labels: "控制哪些标签会显示在控制面板中。控制面板由权限管理器自动创建，用户无法自定义。",
    },
    accessDenied: "访问被拒绝",
    accessDeniedMessage: "您没有权限查看此面板。",
    returnHome: "返回首页",
    readOnlyMode: "只读模式",
  },
  "zh-Hant": {
    title: "權限管理器",
    users: "用戶",
    resources: "資源",
    user: "用戶",
    searchPlaceholder: "搜尋資源...",
    loading: "正在載入權限矩陣...",
    noEntities: "未找到權限實體",
    addResources: "添加一些區域、標籤或其他資源以開始使用",
    noMatch: "沒有匹配搜尋的資源",
    items: "項",
    admin: "管理員",
    protected: "受保護",
    permissionLevels: {
      "0": "關閉",
      "1": "檢視",
    },
    resourceTypes: {
      areas: "區域",
      labels: "標籤",
      panels: "面板",
    },
    resourceDescriptions: {
      areas: "控制哪些區域會顯示在控制面板中。控制面板由權限管理器自動建立，用戶無法自訂。",
      labels: "控制哪些標籤會顯示在控制面板中。控制面板由權限管理器自動建立，用戶無法自訂。",
    },
    accessDenied: "存取被拒絕",
    accessDeniedMessage: "您沒有權限檢視此面板。",
    returnHome: "返回首頁",
    readOnlyMode: "唯讀模式",
  },
};

// Get translations for a language (falls back to English)
const getI18n = (lang) => {
  // Check for exact match first
  if (I18N[lang]) return I18N[lang];
  // Check for language family (e.g., "zh" matches "zh-Hant" - Traditional Chinese as default)
  if (lang && lang.startsWith("zh")) return I18N["zh-Hant"];
  // Default to English
  return I18N.en;
};

// Permission levels configuration (matches backend const.py PERMISSION_LABELS)
const PERMISSION_LEVELS = [
  { value: "0", color: "#db4437" },  // Red - Closed
  { value: "1", color: "#43a047" },  // Green - View (full access)
];

// Resource type configuration (keys match backend resource types with 's' suffix)
// Order: Panels first (most commonly restricted), then Areas, then Labels
const RESOURCE_TYPE_KEYS = ["panels", "areas", "labels"];
const RESOURCE_TYPE_ICONS = {
  areas: "mdi:floor-plan",
  labels: "mdi:tag",
  panels: "mdi:view-dashboard",
};

// Map resource type to grouping key
const getResourceTypeKey = (type) => type + "s";

// Permission level constants
const PERM_DENY = 0;
const PERM_VIEW = 1;

/**
 * Fetch panel permissions for current user via WebSocket
 * @param {Object} hass - Home Assistant object
 * @returns {Promise<Object>} Map of panel_id -> permission_level, empty object on error (fail-secure)
 */
async function fetchPanelPermissions(hass) {
  try {
    const result = await hass.callWS({
      type: "permission_manager/get_panel_permissions",
    });
    return result.permissions || {};
  } catch (err) {
    console.warn("[PermissionManager] Failed to fetch panel permissions, defaulting to CLOSED (fail-secure):", err.message || err);
    return {}; // Empty object = fail-secure (no access granted)
  }
}

/**
 * Check if user can access a panel
 * @param {Object} permissions - Map of panel_id -> level
 * @param {string} panelId - Panel ID to check
 * @returns {boolean} True if access allowed (level >= 1)
 */
function canAccessPanel(permissions, panelId) {
  // Fail-secure: if permissions is null/undefined or empty, deny access
  if (!permissions || Object.keys(permissions).length === 0) {
    console.warn("[PermissionManager] No permissions available, denying access (fail-secure)");
    return false;
  }
  const level = permissions[panelId];
  // Fail-secure: if permission level not set for this panel, deny access
  if (level === undefined) {
    return false;
  }
  return level >= PERM_VIEW;
}

/**
 * Check if panel is read-only for user
 * @param {Object} permissions - Map of panel_id -> level
 * @param {string} panelId - Panel ID to check
 * @returns {boolean} True if read-only (level === 1)
 */
function isPanelReadOnly(permissions, panelId) {
  if (!permissions) return false;
  const level = permissions[panelId];
  return level === PERM_VIEW;
}

class HaPermissionManager extends LitElement {
  static get properties() {
    return {
      hass: { type: Object },
      narrow: { type: Boolean },
      panel: { type: Object },
      _users: { type: Array, state: true },
      _permissions: { type: Object, state: true },
      _resourcesByType: { type: Object, state: true },
      _activeTabIndex: { type: Number, state: true },
      _searchQuery: { type: String, state: true },
      _saving: { type: Object, state: true },
      _loading: { type: Boolean, state: true },
    };
  }

  constructor() {
    super();
    this._users = [];
    this._permissions = {};  // user_id -> {resource_id: level}
    this._resourcesByType = {};
    this._activeTabIndex = 0;
    this._searchQuery = "";
    this._saving = {};
    this._loading = true;
    this._dataLoaded = false;
    this._loadingData = false;
  }

  // Get current language translations
  get _i18n() {
    const lang = this.hass?.language || "en";
    return getI18n(lang);
  }

  updated(changedProperties) {
    super.updated(changedProperties);
    if (changedProperties.has("hass") && this.hass && !this._dataLoaded) {
      this._loadAdminData();
    }
  }

  async _loadAdminData() {
    // Prevent multiple concurrent loads
    if (this._loadingData) return;
    this._loadingData = true;

    try {
      // Fetch all data from websocket API
      const result = await this.hass.callWS({
        type: "permission_manager/get_admin_data",
      });

      this._users = result.users || [];
      this._permissions = result.permissions || {};
      this._resourcesByType = result.resources || {};
      this._dataLoaded = true;
      this._loading = false;
    } catch (err) {
      console.error("[PermissionManager] Failed to load admin data:", err);
      this._users = [];
      this._permissions = {};
      this._resourcesByType = {};
      this._loading = false;
    } finally {
      this._loadingData = false;
    }
  }

  _getAvailableTabs() {
    return RESOURCE_TYPE_KEYS
      .filter((key) => {
        const resources = this._resourcesByType[key] || [];
        return resources.length > 0;
      })
      .map((key) => ({
        key,
        icon: RESOURCE_TYPE_ICONS[key],
        label: this._i18n.resourceTypes[key],
      }));
  }

  _getCurrentResources() {
    const tabs = this._getAvailableTabs();
    if (tabs.length === 0) return [];

    const currentTab = tabs[this._activeTabIndex] || tabs[0];
    let resources = this._resourcesByType[currentTab.key] || [];

    // Apply search filter
    if (this._searchQuery) {
      const query = this._searchQuery.toLowerCase();
      resources = resources.filter((r) =>
        r.name.toLowerCase().includes(query)
      );
    }

    return resources;
  }

  _getPermission(userId, resourceId, resourceType) {
    // Build the full resource ID with prefix
    const prefixMap = {
      panel: "panel_",
      area: "area_",
      label: "label_",
    };
    const prefix = prefixMap[resourceType] || "";
    const fullResourceId = prefix + resourceId;

    const userPerms = this._permissions[userId];
    if (!userPerms) return "0";
    const level = userPerms[fullResourceId];
    return level !== undefined ? String(level) : "0";
  }

  _isUserAdmin(userId) {
    const user = this._users.find((u) => u.id === userId);
    return user ? user.is_admin : false;
  }

  async _changePermission(userId, resourceId, resourceType, newValue) {
    // Build the full resource ID with prefix
    const prefixMap = {
      panel: "panel_",
      area: "area_",
      label: "label_",
    };
    const prefix = prefixMap[resourceType] || "";
    const fullResourceId = prefix + resourceId;
    const savingKey = `${userId}_${fullResourceId}`;

    if (this._saving[savingKey]) return;

    this._saving = { ...this._saving, [savingKey]: true };

    try {
      await this.hass.callWS({
        type: "permission_manager/set_permission",
        user_id: userId,
        resource_id: fullResourceId,
        level: parseInt(newValue, 10),
      });

      // Update local state
      if (!this._permissions[userId]) {
        this._permissions[userId] = {};
      }
      this._permissions[userId][fullResourceId] = parseInt(newValue, 10);
      this._permissions = { ...this._permissions };
    } catch (err) {
      console.error("Failed to save permission:", err);
    } finally {
      const newSaving = { ...this._saving };
      delete newSaving[savingKey];
      this._saving = newSaving;
    }
  }

  _handleTabClick(index) {
    this._activeTabIndex = index;
  }

  _handleSearchInput(e) {
    this._searchQuery = e.target.value;
  }

  _toggleSidebar() {
    this.dispatchEvent(new CustomEvent("hass-toggle-menu", { bubbles: true, composed: true }));
  }

  _getPermissionColor(value) {
    const level = PERMISSION_LEVELS.find((l) => l.value === value);
    return level ? level.color : "#999";
  }

  _getPermissionLabel(value) {
    return this._i18n.permissionLevels[value] || "Unknown";
  }

  static get styles() {
    return css`
      ${unsafeCSS(sharedStylesLit)}

      :host {
        display: block;
        padding: 16px;
        background: var(--primary-background-color, #fafafa);
        min-height: 100vh;
        font-family: var(--paper-font-body1_-_font-family, "Roboto", sans-serif);
        color: var(--primary-text-color, #212121);
      }

      .header-stats {
        display: flex;
        gap: 8px;
        margin-left: auto;
      }

      .stat-chip {
        display: flex;
        align-items: center;
        gap: 6px;
        background: rgba(255, 255, 255, 0.2);
        padding: 4px 10px;
        border-radius: 12px;
        font-size: 12px;
        font-weight: 500;
        color: white;
      }

      .stat-chip ha-icon {
        --mdc-icon-size: 16px;
      }

      .content {
        max-width: 1400px;
        margin: 0 auto;
      }

      .tabs-container {
        display: flex;
        gap: 8px;
        margin-bottom: 16px;
        flex-wrap: wrap;
      }

      .tab {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 10px 16px;
        background: var(--card-background-color, white);
        border: 1px solid var(--divider-color, #e0e0e0);
        border-radius: 8px;
        cursor: pointer;
        font-size: 14px;
        font-weight: 500;
        color: var(--secondary-text-color, #757575);
        transition: all 0.2s;
      }

      .tab:hover {
        background: var(--secondary-background-color, #f5f5f5);
      }

      .tab.active {
        background: var(--primary-color, #03a9f4);
        color: white;
        border-color: var(--primary-color, #03a9f4);
      }

      .tab.active ha-icon {
        color: white;
      }

      .card {
        background: var(--card-background-color, white);
        border-radius: 12px;
        box-shadow: var(--ha-card-box-shadow, 0 2px 4px rgba(0,0,0,0.1));
        overflow: hidden;
        margin-bottom: 16px;
      }

      .card-header {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 16px;
        border-bottom: 1px solid var(--divider-color, #e0e0e0);
      }

      .card-header ha-icon {
        color: var(--primary-color, #03a9f4);
      }

      .card-header span {
        font-size: 16px;
        font-weight: 500;
      }

      .card-header .count {
        margin-left: auto;
        font-size: 13px;
        color: var(--secondary-text-color, #757575);
        background: var(--secondary-background-color, #f5f5f5);
        padding: 4px 10px;
        border-radius: 12px;
      }

      .card-description {
        padding: 12px 16px;
        background: rgba(3, 155, 229, 0.08);
        border-left: 3px solid var(--info-color, #039be5);
        color: var(--secondary-text-color, #757575);
        font-size: 13px;
        line-height: 1.5;
        display: flex;
        align-items: flex-start;
        gap: 8px;
      }

      .card-description ha-icon {
        --mdc-icon-size: 18px;
        flex-shrink: 0;
        color: var(--info-color, #039be5);
        margin-top: 1px;
      }

      .table-container {
        overflow-x: auto;
      }

      table {
        width: 100%;
        border-collapse: collapse;
        min-width: 600px;
      }

      th, td {
        padding: 12px 16px;
        text-align: left;
        border-bottom: 1px solid var(--divider-color, #e0e0e0);
      }

      th {
        background: var(--secondary-background-color, #f5f5f5);
        font-weight: 500;
        font-size: 13px;
        color: var(--secondary-text-color, #757575);
        position: sticky;
        top: 0;
        z-index: 1;
      }

      th:first-child {
        position: sticky;
        left: 0;
        z-index: 2;
        min-width: 160px;
        background: var(--secondary-background-color, #f5f5f5);
      }

      td:first-child {
        position: sticky;
        left: 0;
        background: var(--card-background-color, white);
        z-index: 1;
      }

      tbody tr:hover td {
        background: var(--secondary-background-color, #f5f5f5);
      }

      tbody tr:last-child td {
        border-bottom: none;
      }

      .user-cell {
        display: flex;
        align-items: center;
        gap: 12px;
      }

      .user-avatar {
        width: 36px;
        height: 36px;
        border-radius: 50%;
        background: var(--primary-color, #03a9f4);
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 14px;
        font-weight: 600;
        color: white;
        text-transform: uppercase;
        flex-shrink: 0;
      }

      .user-info {
        display: flex;
        flex-direction: column;
        gap: 2px;
      }

      .user-name {
        font-weight: 500;
        font-size: 14px;
      }

      .admin-badge {
        display: inline-flex;
        align-items: center;
        font-size: 10px;
        font-weight: 600;
        color: #43a047;
        background: rgba(67, 160, 71, 0.1);
        padding: 2px 8px;
        border-radius: 4px;
        text-transform: uppercase;
        width: fit-content;
      }

      .permission-cell {
        min-width: 120px;
      }

      .permission-select {
        position: relative;
        display: inline-block;
      }

      .permission-select select {
        appearance: none;
        padding: 8px 32px 8px 12px;
        border: 1px solid var(--divider-color, #e0e0e0);
        border-radius: 8px;
        font-size: 13px;
        font-weight: 500;
        background: var(--card-background-color, white);
        cursor: pointer;
        min-width: 100px;
        color: var(--primary-text-color, #212121);
      }

      .permission-select select:focus {
        outline: none;
        border-color: var(--primary-color, #03a9f4);
      }

      .permission-select select:disabled {
        opacity: 0.6;
        cursor: not-allowed;
      }

      .permission-select::after {
        content: "";
        position: absolute;
        right: 12px;
        top: 50%;
        transform: translateY(-50%);
        width: 0;
        height: 0;
        border-left: 5px solid transparent;
        border-right: 5px solid transparent;
        border-top: 5px solid var(--secondary-text-color, #666);
        pointer-events: none;
      }

      .permission-indicator {
        display: inline-block;
        width: 10px;
        height: 10px;
        border-radius: 50%;
        margin-right: 8px;
        vertical-align: middle;
      }

      .protected-indicator {
        margin-left: 8px;
        font-size: 12px;
      }

      .legend {
        display: flex;
        justify-content: center;
        gap: 24px;
        padding: 16px;
        background: var(--secondary-background-color, #f5f5f5);
        border-top: 1px solid var(--divider-color, #e0e0e0);
        flex-wrap: wrap;
      }

      .legend-item {
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 13px;
        color: var(--secondary-text-color, #757575);
      }

      .legend-dot {
        width: 12px;
        height: 12px;
        border-radius: 50%;
      }

      .loading {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        height: 300px;
        gap: 16px;
      }

      .spinner {
        width: 40px;
        height: 40px;
        border: 3px solid var(--divider-color, #e0e0e0);
        border-top-color: var(--primary-color, #03a9f4);
        border-radius: 50%;
        animation: spin 1s linear infinite;
      }

      @keyframes spin {
        to { transform: rotate(360deg); }
      }

      .loading-text {
        color: var(--secondary-text-color, #757575);
        font-size: 14px;
      }

      .empty-state {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        padding: 48px 24px;
        color: var(--secondary-text-color, #757575);
        text-align: center;
      }

      .empty-state ha-icon {
        --mdc-icon-size: 48px;
        margin-bottom: 16px;
        opacity: 0.5;
      }

      .empty-state p {
        margin: 4px 0;
        font-size: 14px;
      }

      @media (max-width: 768px) {
        .header {
          padding: 12px 16px;
        }

        .header-title h1 {
          font-size: 18px;
        }

        .header-stats {
          display: none;
        }

        .content {
          padding: 12px;
        }

        th, td {
          padding: 10px 12px;
        }
      }

      /* Mobile responsive styles */
      @media (max-width: 600px) {
        .top-bar {
          height: 48px;
          padding: 0 8px;
        }
        .top-bar-title {
          font-size: 16px;
        }
        .top-bar-sidebar-btn,
        .top-bar-action-btn {
          width: 36px;
          height: 36px;
        }
        .permission-select select {
          min-width: 70px;
          padding: 6px 24px 6px 8px;
          font-size: 12px;
        }
        .permission-select::after {
          right: 8px;
          border-left: 4px solid transparent;
          border-right: 4px solid transparent;
          border-top: 4px solid var(--secondary-text-color, #666);
        }
        .permission-table-wrapper {
          overflow-x: auto;
          -webkit-overflow-scrolling: touch;
        }
        .tab {
          padding: 8px 12px;
          font-size: 12px;
        }
        .tabs {
          gap: 4px;
        }
        .legend {
          gap: 12px;
          padding: 12px;
        }
        .legend-item {
          font-size: 11px;
        }
        .search-row {
          padding: 0 8px;
        }
        .card {
          border-radius: 8px;
        }
      }

      /* Small phone responsive styles */
      @media (max-width: 400px) {
        .user-cell {
          flex-direction: column;
          align-items: flex-start;
          gap: 4px;
        }
        .user-avatar {
          width: 28px;
          height: 28px;
          font-size: 12px;
        }
        .user-info {
          font-size: 13px;
        }
        .permission-select select {
          min-width: 60px;
          font-size: 11px;
        }
        .legend {
          flex-direction: column;
          gap: 8px;
          align-items: flex-start;
        }
      }
    `;
  }

  render() {
    const i18n = this._i18n;

    // Loading state
    if (this._loading) {
      return html`
        <div class="loading">
          <div class="spinner"></div>
          <span class="loading-text">${i18n.loading}</span>
        </div>
      `;
    }

    const availableTabs = this._getAvailableTabs();
    const resources = this._getCurrentResources();
    const totalResources = Object.values(this._resourcesByType).flat().length;
    const currentTab = availableTabs[this._activeTabIndex] || availableTabs[0];

    return html`
      <!-- Top Bar -->
      <div class="top-bar">
        <button class="top-bar-sidebar-btn" @click=${this._toggleSidebar} title="${getCommonTranslation('menu', this.hass?.language)}">
          <svg viewBox="0 0 24 24"><path fill="currentColor" d="M3,6H21V8H3V6M3,11H21V13H3V11M3,16H21V18H3V16Z"/></svg>
        </button>
        <h1 class="top-bar-title">${i18n.title}</h1>
        <div class="header-stats">
          <div class="stat-chip">
            <ha-icon icon="mdi:account-group"></ha-icon>
            ${this._users.length} ${i18n.users}
          </div>
          <div class="stat-chip">
            <ha-icon icon="mdi:cube-outline"></ha-icon>
            ${totalResources} ${i18n.resources}
          </div>
        </div>
      </div>

      <!-- Search Row -->
      <div class="search-row">
        <div class="search-row-input-wrapper">
          <svg class="search-row-icon" viewBox="0 0 24 24"><path fill="currentColor" d="M9.5,3A6.5,6.5 0 0,1 16,9.5C16,11.11 15.41,12.59 14.44,13.73L14.71,14H15.5L20.5,19L19,20.5L14,15.5V14.71L13.73,14.44C12.59,15.41 11.11,16 9.5,16A6.5,6.5 0 0,1 3,9.5A6.5,6.5 0 0,1 9.5,3M9.5,5C7,5 5,7 5,9.5C5,12 7,14 9.5,14C12,14 14,12 14,9.5C14,7 12,5 9.5,5Z"/></svg>
          <input
            class="search-row-input"
            type="text"
            placeholder="${i18n.searchPlaceholder}"
            .value=${this._searchQuery}
            @input=${this._handleSearchInput}
          />
        </div>
      </div>

      <div class="content">

        ${availableTabs.length > 0
          ? html`
              <div class="tabs-container">
                ${availableTabs.map(
                  (tab, index) => html`
                    <div
                      class="tab ${index === this._activeTabIndex ? "active" : ""}"
                      @click=${() => this._handleTabClick(index)}
                    >
                      <ha-icon icon=${tab.icon}></ha-icon>
                      ${tab.label}
                    </div>
                  `
                )}
              </div>

              <div class="card">
                <div class="card-header">
                  <ha-icon icon=${currentTab?.icon || "mdi:help"}></ha-icon>
                  <span>${currentTab?.label || i18n.resources}</span>
                  <span class="count">${resources.length} ${i18n.items}</span>
                </div>

                ${(currentTab?.key === 'areas' || currentTab?.key === 'labels') && i18n.resourceDescriptions?.[currentTab.key]
                  ? html`
                      <div class="card-description">
                        <ha-icon icon="mdi:information-outline"></ha-icon>
                        <span>${i18n.resourceDescriptions[currentTab.key]}</span>
                      </div>
                    `
                  : ''}

                ${resources.length > 0
                  ? html`
                      <div class="table-container">
                        <table>
                          <thead>
                            <tr>
                              <th>${i18n.user}</th>
                              ${resources.map(
                                (r) => html`<th title=${r.id}>${r.name}</th>`
                              )}
                            </tr>
                          </thead>
                          <tbody>
                            ${this._users.map((user) =>
                              this._renderUserRow(user, resources)
                            )}
                          </tbody>
                        </table>
                      </div>
                      ${this._renderLegend()}
                    `
                  : html`
                      <div class="empty-state">
                        <ha-icon icon="mdi:magnify-close"></ha-icon>
                        <p>${i18n.noMatch}</p>
                      </div>
                    `}
              </div>
            `
          : html`
              <div class="card">
                <div class="empty-state">
                  <ha-icon icon="mdi:alert-circle-outline"></ha-icon>
                  <p>${i18n.noEntities}</p>
                  <p>${i18n.addResources}</p>
                </div>
              </div>
            `}
      </div>
    `;
  }

  _renderUserRow(user, resources) {
    const i18n = this._i18n;
    return html`
      <tr>
        <td>
          <div class="user-cell">
            <div class="user-avatar">${user.name ? user.name.charAt(0) : "?"}</div>
            <div class="user-info">
              <span class="user-name">${user.name || "Unknown"}</span>
              ${user.is_admin
                ? html`<span class="admin-badge">${i18n.admin}</span>`
                : ""}
            </div>
          </div>
        </td>
        ${resources.map((resource) =>
          this._renderPermissionCell(user, resource)
        )}
      </tr>
    `;
  }

  _renderPermissionCell(user, resource) {
    const currentLevel = this._getPermission(user.id, resource.id, resource.type);
    const prefixMap = { panel: "panel_", area: "area_", label: "label_" };
    const prefix = prefixMap[resource.type] || "";
    const savingKey = `${user.id}_${prefix}${resource.id}`;
    const isSaving = this._saving[savingKey];
    const i18n = this._i18n;

    return html`
      <td class="permission-cell">
        <div class="permission-select">
          <select
            .value=${currentLevel}
            ?disabled=${isSaving}
            @change=${(e) => this._changePermission(user.id, resource.id, resource.type, e.target.value)}
            style="border-left: 3px solid ${this._getPermissionColor(currentLevel)}"
          >
            ${PERMISSION_LEVELS.map(
              (level) => html`
                <option value=${level.value} ?selected=${currentLevel === level.value}>
                  ${i18n.permissionLevels[level.value]}
                </option>
              `
            )}
          </select>
        </div>
      </td>
    `;
  }

  _renderLegend() {
    const i18n = this._i18n;
    return html`
      <div class="legend">
        ${PERMISSION_LEVELS.map(
          (level) => html`
            <div class="legend-item">
              <span class="legend-dot" style="background: ${level.color}"></span>
              ${i18n.permissionLevels[level.value]}
            </div>
          `
        )}
      </div>
    `;
  }
}

customElements.define("ha-permission-manager", HaPermissionManager);
