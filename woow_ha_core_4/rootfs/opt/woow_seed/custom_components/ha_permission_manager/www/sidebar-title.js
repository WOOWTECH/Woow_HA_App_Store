/**
 * sidebar-title.js — Permission Manager
 * Dynamically updates sidebar panel titles based on HA language setting.
 * Handles two panels: ha_permission_manager and ha-control-panel.
 * Loaded via frontend.add_extra_js_url() so it runs on every page.
 */
(function () {
  "use strict";

  const PANELS = {
    ha_permission_manager: {
      en: "Permission Manager",
      "zh-Hant": "\u6b0a\u9650\u7ba1\u7406\u5668",
      "zh-Hans": "\u6743\u9650\u7ba1\u7406\u5668",
    },
    "ha-control-panel": {
      en: "Control Panel",
      "zh-Hant": "\u63a7\u5236\u9762\u677f",
      "zh-Hans": "\u63a7\u5236\u9762\u677f",
    },
  };

  function getLanguage(hass) {
    if (!hass) return "en";
    // User-level language takes priority
    if (hass.language) return hass.language;
    // Fall back to system config language
    if (hass.config && hass.config.language) return hass.config.language;
    return "en";
  }

  function getTitleForLanguage(titles, lang) {
    if (!lang) return titles.en;
    // Exact match first
    if (titles[lang]) return titles[lang];
    // zh-Hant, zh-TW → zh-Hant
    if (lang.startsWith("zh") && (lang.includes("Hant") || lang.includes("TW") || lang.includes("HK"))) {
      return titles["zh-Hant"];
    }
    // zh-Hans, zh-CN → zh-Hans
    if (lang.startsWith("zh")) {
      return titles["zh-Hans"];
    }
    // Language prefix fallback (e.g. "en-US" → "en")
    var prefix = lang.split("-")[0];
    if (titles[prefix]) return titles[prefix];
    return titles.en;
  }

  function getHassMainElement() {
    var main = document.querySelector("home-assistant");
    if (main && main.shadowRoot) {
      main = main.shadowRoot.querySelector("home-assistant-main");
    }
    return main;
  }

  function getHassObject() {
    var el = document.querySelector("home-assistant");
    if (el && el.hass) return el.hass;
    var main = getHassMainElement();
    if (main && main.hass) return main.hass;
    return null;
  }

  function updateTitles() {
    var hass = getHassObject();
    if (!hass || !hass.panels) return false;

    var lang = getLanguage(hass);
    var changed = false;
    var anyPanelFound = false;

    for (var panelKey in PANELS) {
      if (!hass.panels[panelKey]) continue;
      anyPanelFound = true;

      var title = getTitleForLanguage(PANELS[panelKey], lang);
      if (hass.panels[panelKey].title !== title) {
        hass.panels[panelKey].title = title;
        changed = true;
      }
    }

    if (!anyPanelFound) return false;

    // Force ha-sidebar to re-render by creating new panels reference
    if (changed) {
      var main = getHassMainElement();
      if (main && main.hass) {
        main.hass = Object.assign({}, main.hass, {
          panels: Object.assign({}, main.hass.panels),
        });
      }
    }

    return true;
  }

  // Phase 1: setInterval retry until hass and panels are ready
  var retryCount = 0;
  var maxRetries = 30;
  var initInterval = setInterval(function () {
    retryCount++;
    if (updateTitles() || retryCount >= maxRetries) {
      clearInterval(initInterval);
      // Phase 2: Subscribe to core_config_updated for system language changes
      startEventListener();
      // Phase 3: Polling fallback for user-level language changes
      startPolling();
    }
  }, 2000);

  function startEventListener() {
    var hass = getHassObject();
    if (!hass || !hass.connection) return;
    try {
      hass.connection.subscribeEvents(function () {
        setTimeout(updateTitles, 500);
      }, "core_config_updated");
    } catch (e) {
      // Silently ignore subscription errors
    }
  }

  var lastLang = null;
  function startPolling() {
    setInterval(function () {
      var hass = getHassObject();
      if (!hass) return;
      var lang = getLanguage(hass);
      if (lang !== lastLang) {
        lastLang = lang;
        updateTitles();
      }
    }, 5000);
  }
})();
