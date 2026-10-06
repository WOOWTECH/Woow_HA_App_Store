/**
 * Sidebar title localization for ha_note_record.
 *
 * Strategy (Plan B): Mutate hass.panels[key].title and trigger a reactive
 * update via Object.assign.  ha-sidebar's shouldUpdate() detects the change
 * and re-renders with the translated title — no Shadow DOM traversal needed.
 *
 * Loaded on every page via frontend.add_extra_js_url() so that the sidebar
 * displays the correct language even before the user visits the panel.
 */
(function () {
  'use strict';

  var PANEL_KEY = 'ha-note-record';

  var TITLES = {
    'en': 'Note Record',
    'zh-Hant': '\u7b46\u8a18\u672c',
    'zh-Hans': '\u7b14\u8bb0\u672c'
  };

  function getLanguage(hass) {
    var locale = (hass && hass.language)
              || (hass && hass.locale && hass.locale.language)
              || navigator.language || 'en';
    if (TITLES[locale]) return locale;
    if (locale.indexOf('zh-TW') === 0 || locale.indexOf('zh-HK') === 0) return 'zh-Hant';
    if (locale.indexOf('zh-CN') === 0 || locale.indexOf('zh-SG') === 0) return 'zh-Hans';
    if (locale.indexOf('zh') === 0) return 'zh-Hans';
    return 'en';
  }

  function getTitle(lang) {
    return TITLES[lang] || TITLES['en'];
  }

  function getHassObject() {
    try {
      var ha = document.querySelector('home-assistant');
      if (!ha || !ha.shadowRoot) return null;
      var main = ha.shadowRoot.querySelector('home-assistant-main');
      return (main && main.hass) ? main.hass : null;
    } catch (e) {
      return null;
    }
  }

  function updateTitle(hass, title) {
    try {
      if (!hass || !hass.panels || !hass.panels[PANEL_KEY]) return false;
      if (hass.panels[PANEL_KEY].title === title) return true;

      var ha = document.querySelector('home-assistant');
      if (!ha || !ha.shadowRoot) return false;
      var main = ha.shadowRoot.querySelector('home-assistant-main');
      if (!main || !main.hass) return false;

      main.hass.panels[PANEL_KEY].title = title;
      main.hass = Object.assign({}, main.hass, {
        panels: Object.assign({}, main.hass.panels)
      });
      return true;
    } catch (e) {
      return false;
    }
  }

  function init() {
    var lastLang = null;
    var attempts = 0;
    var maxAttempts = 30;

    var retryInterval = setInterval(function () {
      attempts++;
      var hass = getHassObject();
      if (!hass || !hass.panels || !hass.panels[PANEL_KEY]) {
        if (attempts >= maxAttempts) clearInterval(retryInterval);
        return;
      }

      var lang = getLanguage(hass);
      var title = getTitle(lang);
      lastLang = lang;

      if (updateTitle(hass, title)) {
        clearInterval(retryInterval);
      } else if (attempts >= maxAttempts) {
        clearInterval(retryInterval);
      }
    }, 2000);

    var subscribed = false;
    var subInterval = setInterval(function () {
      if (subscribed) { clearInterval(subInterval); return; }
      var hass = getHassObject();
      if (!hass || !hass.connection) return;
      subscribed = true;
      clearInterval(subInterval);
      try {
        hass.connection.subscribeEvents(function () {
          setTimeout(function () {
            var h = getHassObject();
            if (!h) return;
            var lang = getLanguage(h);
            var title = getTitle(lang);
            updateTitle(h, title);
            lastLang = lang;
          }, 500);
        }, 'core_config_updated');
      } catch (e) { /* ignore */ }
    }, 1000);

    setInterval(function () {
      var hass = getHassObject();
      if (!hass) return;
      var lang = getLanguage(hass);
      if (lang !== lastLang) {
        lastLang = lang;
        var title = getTitle(lang);
        updateTitle(hass, title);
      }
    }, 5000);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
