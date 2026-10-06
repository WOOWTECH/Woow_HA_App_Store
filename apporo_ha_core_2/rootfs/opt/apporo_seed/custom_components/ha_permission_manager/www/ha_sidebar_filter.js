/**
 * HA Permission Manager - Sidebar Filter
 * Hides panels user doesn't have access to
 *
 * v2.9.32 - Security hardening: removed debug objects and verbose logging
 */
(function() {
  "use strict";

  // === IMMEDIATE LOADING OVERLAY ===
  // Blocks content visibility until permissions are checked.
  // Must execute synchronously before any async work.
  // Guard: only create if no overlay exists yet (prevents duplicate with lovelace filter)
  if (!document.getElementById("perm-loading-overlay")) {
    const _loadingOverlay = document.createElement("div");
    _loadingOverlay.id = "perm-loading-overlay";
    _loadingOverlay.style.cssText =
      "position:fixed;top:0;left:0;right:0;bottom:0;" +
      "z-index:9999;" +
      "background:var(--primary-background-color,#fafafa);" +
      "transition:opacity 0.3s ease;";
    if (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches) {
      _loadingOverlay.style.background = "var(--primary-background-color, #111111)";
    }
    if (document.body) {
      document.body.appendChild(_loadingOverlay);
    } else {
      document.addEventListener("DOMContentLoaded", () => {
        document.body.appendChild(_loadingOverlay);
      });
    }
  }

  const PERM_DENY = 0;

  // Sidebar title translations
  const SIDEBAR_TITLES = {
    "ha_permission_manager": {
      en: "Permission Manager",
      zh: "權限管理器"
    },
    "ha-control-panel": {
      en: "Control Panel",
      zh: "控制面板"
    }
  };

  // State
  let originalPanels = null;  // Stored once on first load
  let currentUserId = null;
  let isAdmin = false;
  let initialized = false;
  let lastLanguage = null;
  let lastPermissionHash = null;
  let hassObserverSetup = false;

  /**
   * Reset all state (called when user changes or hass is recreated)
   */
  function resetState() {
    originalPanels = null;
    currentUserId = null;
    isAdmin = false;
    initialized = false;
    lastLanguage = null;
    lastPermissionHash = null;
  }

  /**
   * Remove loading overlay with fade-out animation
   */
  function removeLoadingOverlay() {
    // Use querySelectorAll to remove ALL overlays (defense against duplicate IDs)
    const overlays = document.querySelectorAll("#perm-loading-overlay");
    if (overlays.length === 0) return;
    overlays.forEach(el => {
      el.style.opacity = "0";
      setTimeout(() => el.remove(), 300);
    });
  }

  /**
   * Wait for Home Assistant frontend to be ready
   */
  function waitForHass(maxWait = 15000) {
    return new Promise((resolve) => {
      const start = Date.now();

      function check() {
        const haMain = document.querySelector("home-assistant");
        if (haMain && haMain.hass && haMain.hass.user && haMain.hass.panels) {
          resolve(haMain.hass);
          return;
        }

        if (Date.now() - start > maxWait) {
          console.warn("[SidebarFilter] Timeout waiting for hass");
          resolve(null);
          return;
        }

        setTimeout(check, 100);
      }

      check();
    });
  }

  /**
   * Store original panels on first load (before any filtering)
   */
  async function storeOriginalPanels() {
    if (originalPanels) return originalPanels;

    const hass = await waitForHass();
    if (!hass || !hass.panels) return null;

    // Deep copy the original panels
    originalPanels = JSON.parse(JSON.stringify(hass.panels));
    return originalPanels;
  }

  /**
   * Fetch permissions from WebSocket API
   */
  async function fetchPermissions() {
    try {
      const hass = await waitForHass();
      if (!hass) return { permissions: {}, is_admin: false };

      const result = await hass.callWS({
        type: "permission_manager/get_panel_permissions",
      });

      isAdmin = result.is_admin || false;
      currentUserId = result.user_id || null;

      return {
        permissions: result.permissions || {},
        is_admin: isAdmin,
        user_id: currentUserId,
      };
    } catch (err) {
      console.error("[SidebarFilter] Failed to fetch permissions:", err);
      return { permissions: {}, is_admin: false, user_id: null };
    }
  }

  /**
   * Apply sidebar filtering
   */
  async function applySidebarFilter() {
    const haMain = document.querySelector("home-assistant");
    if (!haMain || !haMain.hass) {
      return;
    }

    // Store original panels on first run
    await storeOriginalPanels();
    if (!originalPanels) {
      console.error("[SidebarFilter] Failed to store original panels");
      return;
    }

    // Fetch permissions from backend
    const { permissions, is_admin } = await fetchPermissions();

    // Admin users see all panels
    if (is_admin) {
      haMain.hass = { ...haMain.hass, panels: { ...originalPanels } };
      return;
    }

    // Core panels that should NEVER be hidden
    // - profile: user needs access to logout
    const ALWAYS_VISIBLE_PANELS = ["profile"];

    // For non-admin users, filter panels
    // ONLY hide panels that are explicitly set to 0 (DENY)
    // All other panels (undefined, 1, 2, 3) are shown
    const filteredPanels = {};
    let hiddenCount = 0;
    const hiddenPanels = [];

    for (const [panelId, panel] of Object.entries(originalPanels)) {
      // Never hide core panels like profile
      if (ALWAYS_VISIBLE_PANELS.includes(panelId)) {
        filteredPanels[panelId] = panel;
        continue;
      }

      const level = permissions[panelId];

      // Fail-secure: only show panels with explicit permission > 0
      // Hide panels that are undefined or explicitly set to 0
      if (level !== undefined && level > PERM_DENY) {
        filteredPanels[panelId] = panel;
      } else {
        // undefined or 0 = hide
        hiddenPanels.push(panelId);
        hiddenCount++;
      }
    }

    // Apply filtered panels
    haMain.hass = { ...haMain.hass, panels: filteredPanels };
  }

  /**
   * Check current URL and block access if denied
   * v2.9.26: Added hideAccessDenied() call when panel is accessible
   */
  async function checkCurrentPanelAccess() {
    if (isAdmin) {
      hideAccessDenied(); // Admin 用戶，確保移除 Access Denied
      return;
    }

    const { permissions } = await fetchPermissions();

    const path = window.location.pathname;

    // Handle root path as lovelace - always allow access (content will be filtered)
    if (path === "/" || path === "") {
      hideAccessDenied();
      return;
    }

    const match = path.match(/^\/([^\/]+)/);
    if (!match) {
      hideAccessDenied();
      return;
    }

    const currentPanel = match[1];

    // Skip system paths and always-accessible panels
    if (["local", "api", "auth", "static", "frontend_latest", "frontend_es5", "_my_redirect", "profile"].includes(currentPanel)) {
      hideAccessDenied();
      return;
    }

    let panelToCheck = currentPanel;

    // Fail-secure: only allow if explicitly granted (matches sidebar filtering logic)
    const level = permissions[panelToCheck];
    if (level !== undefined && level > PERM_DENY) {
      hideAccessDenied();
    } else {
      // undefined or 0 = deny access
      showAccessDenied();
    }
  }

  /**
   * Show access denied page - use standalone mode with header
   * v2.9.27: Restored standalone mode with header and hamburger button
   */
  function showAccessDenied() {
    // 檢查是否已存在
    if (document.querySelector("ha-access-denied")) {
      return;
    }

    // 獲取 DOM 引用
    const haMain = document.querySelector("home-assistant");
    const homeAssistantMain = haMain?.shadowRoot?.querySelector("home-assistant-main");
    const haDrawer = homeAssistantMain?.shadowRoot?.querySelector("ha-drawer");
    const haSidebar = haDrawer?.querySelector("ha-sidebar");
    const partialPanelResolver = haDrawer?.querySelector("partial-panel-resolver");

    // 載入組件腳本
    if (!customElements.get("ha-access-denied")) {
      const script = document.createElement("script");
      script.type = "module";
      script.src = "/local/ha_access_denied.js?v=" + Date.now();
      document.head.appendChild(script);
    }

    // 計算側邊欄寬度
    const sidebarWidth = haSidebar?.offsetWidth || 0;

    // 創建組件 - 使用 standalone 模式（含 header 和漢堡按鈕）
    const accessDenied = document.createElement("ha-access-denied");
    accessDenied.setAttribute("standalone", "true");
    if (haMain?.hass) {
      accessDenied.hass = haMain.hass;
    }

    // 定位組件（從側邊欄右邊開始，覆蓋主內容區域）
    accessDenied.style.cssText = `
      position: fixed;
      top: 0;
      left: ${sidebarWidth}px;
      right: 0;
      bottom: 0;
      z-index: 1;
      background: var(--primary-background-color, #fafafa);
      overflow: auto;
    `;

    document.body.appendChild(accessDenied);

    // 隱藏原有面板內容
    if (partialPanelResolver) {
      partialPanelResolver.style.visibility = "hidden";
    }
  }

  /**
   * Hide access denied page and restore original panel content
   * v2.9.27: Fixed - use removeProperty for more reliable restoration
   */
  function hideAccessDenied() {
    // 獲取 DOM 引用
    const haMain = document.querySelector("home-assistant");
    const homeAssistantMain = haMain?.shadowRoot?.querySelector("home-assistant-main");
    const haDrawer = homeAssistantMain?.shadowRoot?.querySelector("ha-drawer");
    const partialPanelResolver = haDrawer?.querySelector("partial-panel-resolver");

    // 移除 partial-panel-resolver 中的 Access Denied
    const accessDeniedInResolver = partialPanelResolver?.querySelector("ha-access-denied");
    if (accessDeniedInResolver) {
      accessDeniedInResolver.remove();

      // 恢復原有內容的顯示 - 使用 removeProperty 更可靠
      if (partialPanelResolver) {
        Array.from(partialPanelResolver.children).forEach(child => {
          child.style.removeProperty("display");
          child.style.removeProperty("visibility");
        });
      }
    }

    // 移除 document.body 中的 Access Denied (standalone 模式)
    const accessDeniedInBody = document.querySelector("ha-access-denied");
    if (accessDeniedInBody) {
      accessDeniedInBody.remove();

      // 恢復 partial-panel-resolver 的可見性
      if (partialPanelResolver) {
        partialPanelResolver.style.removeProperty("visibility");
        partialPanelResolver.style.removeProperty("display");
        // 也恢復子元素的顯示
        Array.from(partialPanelResolver.children).forEach(child => {
          child.style.removeProperty("display");
          child.style.removeProperty("visibility");
        });
      }
    }
  }

  /**
   * Subscribe to permission changes
   */
  async function subscribeToChanges() {
    const hass = await waitForHass();
    if (!hass || !hass.connection) return;

    // Listen for user_updated events (when admin status changes in HA)
    hass.connection.subscribeEvents(async (event) => {
      // Check if current user's admin status changed
      const oldIsAdmin = isAdmin;
      const { is_admin } = await fetchPermissions();

      if (oldIsAdmin !== is_admin) {
        // Force reload to reset all state
        location.reload();
        return;
      }

      // Even if admin status didn't change, re-apply filter in case permissions changed
      await applySidebarFilter();
    }, "user_updated");

    // Listen for auth events (login/logout, permission changes)
    hass.connection.subscribeEvents(async (event) => {
      // Re-check admin status and permissions
      const oldIsAdmin = isAdmin;
      const { is_admin } = await fetchPermissions();

      if (oldIsAdmin !== is_admin) {
        location.reload();
        return;
      }

      await applySidebarFilter();
    }, "homeassistant_auth_updated");

    // Listen for lovelace dashboard changes (create/delete)
    hass.connection.subscribeEvents(async (event) => {
      const action = event.data?.action;

      if (action === "create" || action === "delete") {
        // Wait a bit for backend to update permissions
        await new Promise(r => setTimeout(r, 500));

        // Refresh originalPanels from current hass.panels
        const haMain = document.querySelector("home-assistant");
        if (haMain && haMain.hass && haMain.hass.panels) {
          originalPanels = JSON.parse(JSON.stringify(haMain.hass.panels));
        }

        // Re-apply filter with new permissions
        await applySidebarFilter();
      }
    }, "lovelace_updated");

    // Subscribe to permission_manager_updated event (replaces 5-second polling)
    hass.connection.subscribeEvents(async (event) => {
      const oldIsAdmin = isAdmin;
      const { permissions, is_admin } = await fetchPermissions();

      if (oldIsAdmin !== is_admin) {
        location.reload();
        return;
      }

      const newHash = JSON.stringify(permissions);
      if (newHash !== lastPermissionHash) {
        lastPermissionHash = newHash;
        await applySidebarFilter();
        await checkCurrentPanelAccess();
      }
    }, "permission_manager_updated");

    // Listen for language changes via core_config_updated event
    hass.connection.subscribeEvents(async (event) => {
      // Get current language from hass object (more reliable than event data)
      const haMain = document.querySelector("home-assistant");
      const newLanguage = haMain?.hass?.language || "en";

      // Skip if language hasn't changed
      if (newLanguage === lastLanguage) {
        return;
      }

      lastLanguage = newLanguage;

      // Update sidebar title via DOM manipulation (more reliable than hass.panels)
      updateSidebarTitle();
    }, "core_config_updated");
  }

  /**
   * Update sidebar title based on current language
   * Returns true if successfully updated, false otherwise
   */
  function updateSidebarTitle() {
    const hass = document.querySelector("home-assistant")?.hass;
    if (!hass) {
      return false;
    }

    const lang = hass.language || "en";
    const isZh = lang.startsWith("zh");

    // Traverse Shadow DOM to find sidebar items
    const haMain = document.querySelector("home-assistant");
    if (!haMain?.shadowRoot) return false;

    const homeAssistantMain = haMain.shadowRoot.querySelector("home-assistant-main");
    if (!homeAssistantMain?.shadowRoot) return false;

    const haDrawer = homeAssistantMain.shadowRoot.querySelector("ha-drawer");
    if (!haDrawer) return false;

    // Try shadowRoot first, then direct query (HA version differences)
    let haSidebar = haDrawer.shadowRoot?.querySelector("ha-sidebar");
    if (!haSidebar) {
      haSidebar = haDrawer.querySelector("ha-sidebar");
    }
    if (!haSidebar?.shadowRoot) return false;

    // Find sidebar navigation items - try multiple selectors for HA version compatibility
    let items = [];

    // Modern HA (2024+) uses different structure
    const sidebarRoot = haSidebar.shadowRoot;

    // Try paper-listbox first (older HA)
    const paperListbox = sidebarRoot.querySelector("paper-listbox");
    if (paperListbox) {
      items = paperListbox.querySelectorAll("a");
    }

    // Try ha-md-list (newer HA)
    if (items.length === 0) {
      const mdList = sidebarRoot.querySelector("ha-md-list");
      if (mdList) {
        items = mdList.querySelectorAll("a");
      }
    }

    // Fallback: query all anchor tags in sidebar
    if (items.length === 0) {
      items = sidebarRoot.querySelectorAll("a[href]");
    }

    if (items.length === 0) return false;

    let updated = false;

    // Panels to translate
    const panelsToTranslate = ["ha_permission_manager", "ha-control-panel"];

    items.forEach(item => {
      const href = item.getAttribute("href");
      if (!href) return;

      // Extract panel ID from href (e.g., "/ha_permission_manager" -> "ha_permission_manager")
      const panelId = href.replace(/^\//, "");

      if (panelsToTranslate.includes(panelId) && SIDEBAR_TITLES[panelId]) {
        const title = isZh ? SIDEBAR_TITLES[panelId].zh : SIDEBAR_TITLES[panelId].en;

        // Try multiple selectors for text element (HA version compatibility)
        let textEl = item.querySelector(".item-text");
        if (!textEl) textEl = item.querySelector("[slot='headline']");
        if (!textEl) textEl = item.querySelector("span");

        if (textEl && textEl.textContent !== title) {
          textEl.textContent = title;
          updated = true;
        } else if (textEl && textEl.textContent === title) {
          updated = true; // Already correct
        }
      }
    });

    return updated;
  }

  /**
   * Update sidebar title by modifying hass.panels data model
   * This triggers HA's reactive UI update automatically
   */
  function updateSidebarTitleViaHass(lang) {
    const haMain = document.querySelector("home-assistant");
    if (!haMain?.hass?.panels) {
      return false;
    }

    const isZh = lang && lang.startsWith("zh");
    const panelsToUpdate = ["ha_permission_manager", "ha-control-panel"];
    let anyUpdated = false;

    // Create a copy of panels to modify
    const updatedPanels = { ...haMain.hass.panels };

    for (const panelId of panelsToUpdate) {
      const panel = updatedPanels[panelId];
      if (!panel || !SIDEBAR_TITLES[panelId]) continue;

      const title = isZh ? SIDEBAR_TITLES[panelId].zh : SIDEBAR_TITLES[panelId].en;

      // Only update if title actually changed
      if (panel.title !== title) {
        updatedPanels[panelId] = { ...panel, title: title };
        anyUpdated = true;
      }
    }

    // Trigger reactive update by assigning new hass object if any panel was updated
    if (anyUpdated) {
      haMain.hass = { ...haMain.hass, panels: updatedPanels };
    }

    return true;
  }

  /**
   * Initialize sidebar title with retry mechanism
   * Uses DOM manipulation directly (updateSidebarTitleViaHass doesn't work for title updates)
   */
  function initSidebarTitle() {
    let attempts = 0;
    const maxAttempts = 30;

    // 嘗試立即更新（使用 DOM 操作）
    if (updateSidebarTitle()) {
      return;
    }

    // 重試機制
    const interval = setInterval(() => {
      attempts++;
      if (updateSidebarTitle()) {
        clearInterval(interval);
      } else if (attempts >= maxAttempts) {
        clearInterval(interval);
      }
    }, 2000);
  }

  /**
   * Watch for navigation
   */
  function watchNavigation() {
    window.addEventListener("popstate", () => checkCurrentPanelAccess());

    document.addEventListener("click", (e) => {
      const link = e.target.closest("a");
      if (link && link.href && link.href.startsWith(window.location.origin)) {
        setTimeout(() => checkCurrentPanelAccess(), 150);
      }
    });

    const originalPushState = history.pushState;
    history.pushState = function(...args) {
      originalPushState.apply(this, args);
      setTimeout(() => checkCurrentPanelAccess(), 150);
    };
  }

  /**
   * Setup observer to detect when home-assistant element is recreated (logout/login)
   */
  function setupHassObserver() {
    if (hassObserverSetup) return;
    hassObserverSetup = true;

    // Track the current home-assistant element
    let currentHaElement = document.querySelector("home-assistant");

    const observer = new MutationObserver((mutations) => {
      const newHaElement = document.querySelector("home-assistant");

      // Check if home-assistant element was recreated
      if (newHaElement && newHaElement !== currentHaElement) {
        currentHaElement = newHaElement;
        resetState();
        init();
      }
    });

    observer.observe(document.body, { childList: true, subtree: true });
  }

  /**
   * Initialize
   */
  async function init() {
    // Check if user changed (logout/re-login scenario)
    const haMain = document.querySelector("home-assistant");
    const newUserId = haMain?.hass?.user?.id;

    if (initialized && newUserId && currentUserId && newUserId !== currentUserId) {
      resetState();
    }

    if (initialized) return;
    initialized = true;

    // Initialize lastLanguage from current hass state
    const hass = await waitForHass();
    if (hass) {
      lastLanguage = hass.language || "en";
    }

    // Fetch permissions BEFORE filtering to enable restricted-panel redirect
    const { permissions: initPerms } = await fetchPermissions();
    lastPermissionHash = JSON.stringify(initPerms);

    // Redirect away from restricted panel BEFORE filtering hass.panels
    // This prevents partial-panel-resolver from getting stuck with _initialLoadDone=false
    if (!isAdmin) {
      const path = window.location.pathname;
      const match = path.match(/^\/([^\/]+)/);
      if (match) {
        const currentPanel = match[1];
        const skipPanels = ["local", "api", "auth", "static", "frontend_latest",
                            "frontend_es5", "_my_redirect", "profile"];
        if (!skipPanels.includes(currentPanel)) {
          const level = initPerms[currentPanel];
          if (level === undefined || level === PERM_DENY) {
            const defaultPanel = hass?.defaultPanel || "lovelace";
            window.location.replace("/" + defaultPanel);
            return; // Stop init — page will reload on allowed panel
          }
        }
      }
    }

    await applySidebarFilter();

    watchNavigation();
    await subscribeToChanges();
    await checkCurrentPanelAccess();

    // Permission check complete - remove loading overlay
    removeLoadingOverlay();

    // Initialize sidebar title - prefer hass.panels method, fallback to DOM
    if (!updateSidebarTitleViaHass(lastLanguage)) {
      initSidebarTitle(); // Fallback to DOM manipulation
    }
  }

  // Start when DOM is ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      setupHassObserver();
      init();
    });
  } else {
    setupHassObserver();
    init();
  }

  // Debug object removed for security - do not expose internal state in production
})();
