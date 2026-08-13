/**
 * sidebar-title.js — Label Control
 * Dynamically updates the sidebar panel title based on HA language setting.
 * Loaded via frontend.add_extra_js_url() so it runs on every page.
 */
(function () {
  "use strict";

  const PANEL_KEY = "label-control";
  const TITLES = {
    en: "Label Control",
    "zh-Hant": "\u6a19\u7c64\u63a7\u5236",
    "zh-Hans": "\u6807\u7b7e\u63a7\u5236",
  };

  function getLanguage(hass) {
    if (!hass) return "en";
    // User-level language takes priority
    if (hass.language) return hass.language;
    // Fall back to system config language
    if (hass.config && hass.config.language) return hass.config.language;
    return "en";
  }

  function getTitleForLanguage(lang) {
    if (!lang) return TITLES.en;
    // Exact match first
    if (TITLES[lang]) return TITLES[lang];
    // zh-Hant, zh-TW → zh-Hant
    if (lang.startsWith("zh") && (lang.includes("Hant") || lang.includes("TW") || lang.includes("HK"))) {
      return TITLES["zh-Hant"];
    }
    // zh-Hans, zh-CN → zh-Hans
    if (lang.startsWith("zh")) {
      return TITLES["zh-Hans"];
    }
    // Language prefix fallback (e.g. "en-US" → "en")
    var prefix = lang.split("-")[0];
    if (TITLES[prefix]) return TITLES[prefix];
    return TITLES.en;
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

  function updateTitle() {
    var hass = getHassObject();
    if (!hass || !hass.panels || !hass.panels[PANEL_KEY]) return false;

    var lang = getLanguage(hass);
    var title = getTitleForLanguage(lang);

    // Only update if title actually changed
    if (hass.panels[PANEL_KEY].title === title) return true;

    // Mutate the title
    hass.panels[PANEL_KEY].title = title;

    // Force ha-sidebar to re-render by creating new panels reference
    var main = getHassMainElement();
    if (main && main.hass) {
      main.hass = Object.assign({}, main.hass, {
        panels: Object.assign({}, main.hass.panels),
      });
    }

    return true;
  }

  // Phase 1: setInterval retry until hass and panels are ready
  var retryCount = 0;
  var maxRetries = 30;
  var initInterval = setInterval(function () {
    retryCount++;
    if (updateTitle() || retryCount >= maxRetries) {
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
        setTimeout(updateTitle, 500);
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
        updateTitle();
      }
    }, 5000);
  }
})();
