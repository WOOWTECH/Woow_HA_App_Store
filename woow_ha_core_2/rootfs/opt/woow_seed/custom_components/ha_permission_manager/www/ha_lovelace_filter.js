/**
 * HA Permission Manager - Lovelace Filter
 * Hides dashboard content for users with restricted permissions
 *
 * v2.7.10 - Security hardening: removed debug objects and verbose logging
 */
(function() {
  "use strict";

  // Loading overlay is owned by ha_sidebar_filter.js — do not create here.
  // This prevents the race condition where duplicate overlays cause permanent UI blocking.

  const PERM_DENY = 0;

  // State
  let permissions = null;
  let isAdmin = false;
  let initialized = false;
  let contentHidden = false;
  let hideAttempts = 0;

  /**
   * Wait for Home Assistant frontend to be ready
   */
  function waitForHass(maxWait = 15000) {
    return new Promise((resolve) => {
      const start = Date.now();

      function check() {
        const haMain = document.querySelector("home-assistant");
        if (haMain && haMain.hass && haMain.hass.user) {
          resolve(haMain.hass);
          return;
        }

        if (Date.now() - start > maxWait) {
          console.warn("[LovelaceFilter] Timeout waiting for hass");
          resolve(null);
          return;
        }

        setTimeout(check, 100);
      }

      check();
    });
  }

  /**
   * Fetch all permissions from WebSocket API
   */
  async function fetchAllPermissions() {
    try {
      const hass = await waitForHass();
      if (!hass) return null;

      const result = await hass.callWS({
        type: "permission_manager/get_all_permissions",
      });

      isAdmin = result.is_admin || false;
      permissions = result;

      return result;
    } catch (err) {
      console.error("[LovelaceFilter] Failed to fetch permissions:", err);
      return null;
    }
  }

  /**
   * Check if user should see lovelace content
   * Returns TRUE if content should be VISIBLE
   */
  function shouldShowContent() {
    // Admin always sees everything
    if (isAdmin) {
      return true;
    }

    // No permissions loaded yet - fail-secure: hide content
    if (!permissions) {
      return false;
    }

    // Check lovelace panel permission specifically
    // The panel key could be "lovelace" or other variants
    const panelKeys = Object.keys(permissions.panels || {});

    // Find lovelace permission
    let lovelaceLevel = null;
    for (const key of panelKeys) {
      if (key === "lovelace" || key.includes("lovelace")) {
        lovelaceLevel = permissions.panels[key];
        break;
      }
    }

    // If lovelace permission is 0 (DENY), hide content
    if (lovelaceLevel !== null && lovelaceLevel === PERM_DENY) {
      return false;
    }

    // If we have lovelace permission > 0, show content
    // Panel permission alone controls dashboard visibility
    if (lovelaceLevel !== null && lovelaceLevel > PERM_DENY) {
      return true;
    }

    // Default: fail-secure - hide content if no explicit lovelace permission found
    return false;
  }

  /**
   * Find and hide lovelace content by traversing Shadow DOM
   */
  function hideLovelaceContent() {
    const show = shouldShowContent();

    if (show) {
      removeContentHiding();
      return;
    }

    hideAttempts++;

    // Traverse Shadow DOM to find hui-root
    const haMain = document.querySelector("home-assistant");
    if (!haMain || !haMain.shadowRoot) {
      return;
    }

    const homeAssistantMain = haMain.shadowRoot.querySelector("home-assistant-main");
    if (!homeAssistantMain || !homeAssistantMain.shadowRoot) {
      return;
    }

    const haDrawer = homeAssistantMain.shadowRoot.querySelector("ha-drawer");
    if (!haDrawer) {
      return;
    }

    const partialPanelResolver = haDrawer.querySelector("partial-panel-resolver");
    if (!partialPanelResolver || !partialPanelResolver.shadowRoot) {
      return;
    }

    const haPanelLovelace = partialPanelResolver.shadowRoot.querySelector("ha-panel-lovelace");
    if (!haPanelLovelace || !haPanelLovelace.shadowRoot) {
      return;
    }

    const huiRoot = haPanelLovelace.shadowRoot.querySelector("hui-root");
    if (!huiRoot || !huiRoot.shadowRoot) {
      return;
    }

    // Hide the view content
    const viewContainer = huiRoot.shadowRoot.querySelector("#view");
    if (viewContainer) {
      viewContainer.style.display = "none";
    }

    // Hide the toolbar action items (right side buttons including ... menu)
    const toolbar = huiRoot.shadowRoot.querySelector(".toolbar");
    if (toolbar) {
      // Hide all action items in the toolbar
      const actionItems = toolbar.querySelectorAll("ha-icon-button, ha-button-menu, mwc-icon-button");
      actionItems.forEach(item => {
        item.style.display = "none";
      });
    }

    // Also check for app-toolbar and its action items
    const appToolbar = huiRoot.shadowRoot.querySelector("app-toolbar");
    if (appToolbar) {
      const toolbarActions = appToolbar.querySelectorAll('[slot="actionItems"], ha-icon-button, ha-button-menu');
      toolbarActions.forEach(item => {
        item.style.display = "none";
      });
    }

    // Add "no access" message if not already there
    let messageContainer = document.getElementById("perm-manager-no-access-msg");
    if (!messageContainer) {
      messageContainer = document.createElement("div");
      messageContainer.id = "perm-manager-no-access-msg";
      messageContainer.style.cssText = `
        position: fixed;
        top: 50%;
        left: 50%;
        transform: translate(-50%, -50%);
        text-align: center;
        font-size: 18px;
        color: var(--secondary-text-color, #666);
        z-index: 1000;
        padding: 20px;
      `;

      // Build DOM structure safely without innerHTML (security fix)
      const iconWrapper = document.createElement("div");
      iconWrapper.style.marginBottom = "10px";
      const icon = document.createElement("ha-icon");
      icon.setAttribute("icon", "mdi:shield-lock");
      icon.style.cssText = "--mdc-icon-size: 48px;";
      iconWrapper.appendChild(icon);

      const titleDiv = document.createElement("div");
      titleDiv.textContent = "\u7121\u53EF\u7528\u5167\u5BB9"; // "無可用內容"

      const subtitleDiv = document.createElement("div");
      subtitleDiv.style.cssText = "font-size: 14px; margin-top: 8px;";
      subtitleDiv.textContent = "\u8ACB\u806F\u7E6B\u7BA1\u7406\u54E1\u7372\u53D6\u8A2A\u554F\u6B0A\u9650"; // "請聯繫管理員獲取訪問權限"

      messageContainer.appendChild(iconWrapper);
      messageContainer.appendChild(titleDiv);
      messageContainer.appendChild(subtitleDiv);

      document.body.appendChild(messageContainer);
    }

    contentHidden = true;
  }

  /**
   * Remove content hiding
   */
  function removeContentHiding() {
    if (!contentHidden) return;

    // Remove message
    const msg = document.getElementById("perm-manager-no-access-msg");
    if (msg) msg.remove();

    // Try to restore view
    const haMain = document.querySelector("home-assistant");
    if (!haMain || !haMain.shadowRoot) return;

    const homeAssistantMain = haMain.shadowRoot.querySelector("home-assistant-main");
    if (!homeAssistantMain || !homeAssistantMain.shadowRoot) return;

    const haDrawer = homeAssistantMain.shadowRoot.querySelector("ha-drawer");
    if (!haDrawer) return;

    const partialPanelResolver = haDrawer.querySelector("partial-panel-resolver");
    if (!partialPanelResolver || !partialPanelResolver.shadowRoot) return;

    const haPanelLovelace = partialPanelResolver.shadowRoot.querySelector("ha-panel-lovelace");
    if (!haPanelLovelace || !haPanelLovelace.shadowRoot) return;

    const huiRoot = haPanelLovelace.shadowRoot.querySelector("hui-root");
    if (!huiRoot || !huiRoot.shadowRoot) return;

    const viewContainer = huiRoot.shadowRoot.querySelector("#view");
    if (viewContainer) {
      viewContainer.style.display = "";
    }

    const toolbar = huiRoot.shadowRoot.querySelector(".toolbar");
    if (toolbar) {
      const actionItems = toolbar.querySelectorAll("ha-icon-button, ha-button-menu, mwc-icon-button");
      actionItems.forEach(item => {
        item.style.display = "";
      });
    }

    const appToolbar = huiRoot.shadowRoot.querySelector("app-toolbar");
    if (appToolbar) {
      const toolbarActions = appToolbar.querySelectorAll('[slot="actionItems"], ha-icon-button, ha-button-menu');
      toolbarActions.forEach(item => {
        item.style.display = "";
      });
    }

    contentHidden = false;
  }

  /**
   * Check if on lovelace page and apply filter
   */
  function checkAndApplyFilter() {
    const path = window.location.pathname;
    const isLovelacePage = path === "/" || path === "" || path.startsWith("/lovelace");

    if (isLovelacePage) {
      hideLovelaceContent();
    } else {
      removeContentHiding();
    }
  }

  /**
   * Subscribe to permission changes via event bus (replaces 5-second polling)
   */
  let lastPermHash = null;

  async function subscribeToPermissionChanges() {
    const hass = await waitForHass();
    if (!hass || !hass.connection) return;

    hass.connection.subscribeEvents(async () => {
      const result = await fetchAllPermissions();
      if (!result) return;
      const newHash = JSON.stringify(result);
      if (newHash !== lastPermHash) {
        lastPermHash = newHash;
        checkAndApplyFilter();
      }
    }, "permission_manager_updated");
  }

  /**
   * Initialize
   */
  async function init() {
    if (initialized) return;
    initialized = true;

    await fetchAllPermissions();
    lastPermHash = JSON.stringify(permissions);
    checkAndApplyFilter();
    await subscribeToPermissionChanges();

    // Watch for navigation
    window.addEventListener("popstate", () => {
      setTimeout(checkAndApplyFilter, 500);
    });

    // Observe DOM changes to catch when lovelace loads (replaces 1-second polling)
    const observer = new MutationObserver(() => {
      if (window.location.pathname === "/" || window.location.pathname.startsWith("/lovelace")) {
        checkAndApplyFilter();
      }
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }

  // Start when DOM is ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  // Debug object removed for security - do not expose internal state in production
})();
