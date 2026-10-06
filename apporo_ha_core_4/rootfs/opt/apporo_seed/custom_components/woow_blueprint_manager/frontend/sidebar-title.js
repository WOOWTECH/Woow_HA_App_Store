/**
 * Blueprint Manager — Sidebar Title i18n
 *
 * HA's async_register_built_in_panel() only accepts a static sidebar_title.
 * HA frontend getPanelTitle() returns: hass.localize("panel." + title) || title
 * Custom integrations cannot inject into HA's panel.* translation namespace,
 * so we mutate hass.panels[key].title as the fallback value.
 *
 * ha-sidebar is a LitElement; shouldUpdate() compares hass.panels by reference,
 * so we must create a NEW panels object reference to trigger re-render.
 *
 * Strategy: extra_js_url loads this script on EVERY page (not just panel page).
 * Three-phase initialization ensures language changes are always detected.
 */
(() => {
  const PANEL_KEY = "woow-blueprints";

  const TITLES = {
    en: "Blueprint Manager",
    "zh-Hant": "藍圖管理器",
    "zh-Hans": "蓝图管理器",
  };

  /**
   * Resolve HA language to a supported title key.
   *   zh-Hant, zh-TW, zh-HK → zh-Hant
   *   zh-Hans, zh-CN, zh-SG → zh-Hans
   *   everything else        → en
   */
  function resolveLanguage(hass) {
    const lang =
      (hass && hass.language) ||
      (hass && hass.locale && hass.locale.language) ||
      (typeof navigator !== "undefined" && navigator.language) ||
      "en";

    if (lang === "zh-Hant" || lang === "zh-TW" || lang === "zh-HK") {
      return "zh-Hant";
    }
    if (lang === "zh-Hans" || lang === "zh-CN" || lang === "zh-SG") {
      return "zh-Hans";
    }
    if (lang.startsWith("zh")) {
      return "zh-Hant"; // default Chinese variant
    }
    return "en";
  }

  /** Walk shadow DOM to reach home-assistant-main and its hass property. */
  function getHassMain() {
    const ha = document.querySelector("home-assistant");
    if (!ha || !ha.shadowRoot) return null;
    const main = ha.shadowRoot.querySelector("home-assistant-main");
    return main || null;
  }

  /** Get the hass object from home-assistant-main. */
  function getHass() {
    const main = getHassMain();
    return main && main.hass ? main.hass : null;
  }

  /**
   * Update the sidebar title by mutating hass.panels and
   * creating new object references to trigger LitElement re-render.
   * Returns true if update was applied, false if skipped or failed.
   */
  function updateTitle(targetTitle) {
    const main = getHassMain();
    if (!main || !main.hass) return false;
    const hass = main.hass;

    if (!hass.panels || !hass.panels[PANEL_KEY]) return false;

    // Skip if title already correct
    if (hass.panels[PANEL_KEY].title === targetTitle) return true;

    // Mutate the panel title
    hass.panels[PANEL_KEY].title = targetTitle;

    // Create NEW references for both panels and hass to trigger shouldUpdate()
    main.hass = Object.assign({}, hass, {
      panels: Object.assign({}, hass.panels),
    });

    return true;
  }

  /** Compute the correct title and apply it. */
  function applyTitle() {
    const hass = getHass();
    if (!hass) return false;
    const lang = resolveLanguage(hass);
    const title = TITLES[lang] || TITLES.en;
    return updateTitle(title);
  }

  // Track last known language for change detection
  let _lastLang = null;

  function checkAndApply() {
    const hass = getHass();
    if (!hass) return;
    const lang = resolveLanguage(hass);
    if (lang !== _lastLang) {
      _lastLang = lang;
      applyTitle();
    }
  }

  // === Phase 1: Initial setup with retry ===
  let retryCount = 0;
  const maxRetries = 30;
  const initInterval = setInterval(() => {
    retryCount++;
    const hass = getHass();
    if (hass && hass.panels && hass.panels[PANEL_KEY]) {
      clearInterval(initInterval);
      applyTitle();
      _lastLang = resolveLanguage(hass);
      startPhase2();
      startPhase3();
    } else if (retryCount >= maxRetries) {
      clearInterval(initInterval);
    }
  }, 2000);

  // === Phase 2: Subscribe to core_config_updated (system language change) ===
  function startPhase2() {
    try {
      const hass = getHass();
      if (hass && hass.connection) {
        hass.connection.subscribeEvents(() => {
          // Delay slightly to let HA update hass.language
          setTimeout(checkAndApply, 1000);
        }, "core_config_updated");
      }
    } catch (_e) {
      // Best effort — Phase 3 polling is the fallback
    }
  }

  // === Phase 3: Polling fallback for profile-level language changes ===
  function startPhase3() {
    setInterval(checkAndApply, 5000);
  }
})();
