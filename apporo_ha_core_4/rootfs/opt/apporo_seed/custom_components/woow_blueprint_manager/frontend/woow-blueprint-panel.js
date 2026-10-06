/**
 * Blueprint Manager - Custom Panel
 * A management panel for Home Assistant blueprints.
 * Uses vanilla Web Components + ha-card for native HA theme matching.
 * @version 1.0.0
 * Tested against HA 2026.4.x editor internals for blueprint pre-selection.
 */

const SCRIPT_BLUEPRINTS = new Set(["light_loop", "scene_loop"]);
var _escDiv = null;

const CATEGORIES = {
  lighting: {
    name_zh: "\u71c8\u5149\u63a7\u5236",
    name_en: "Lighting",
    icon: "mdi:lightbulb-group",
    blueprints: ["adalight", "switch_trigger_lights", "binary_sensor_trigger_light"],
  },
  scene: {
    name_zh: "\u5834\u666f\u5faa\u74b0",
    name_en: "Scene Loop",
    icon: "mdi:palette",
    blueprints: ["scenes_loop_detail", "scenes_loop_simple", "adascene_multi", "adascene_single"],
  },
  notify: {
    name_zh: "\u901a\u77e5\u63d0\u9192",
    name_en: "Notification",
    icon: "mdi:bell-ring",
    blueprints: ["entity_state_trigger_notify", "todo_trigger_notify"],
  },
  climate: {
    name_zh: "\u74b0\u5883\u63a7\u5236",
    name_en: "Climate",
    icon: "mdi:thermostat",
    blueprints: ["greenhouse", "sync_climate", "light_sync_cover_and_fan"],
  },
  device: {
    name_zh: "\u8a2d\u5099\u63a7\u5236",
    name_en: "Device Control",
    icon: "mdi:devices",
    blueprints: [
      "switch_trigger_things",
      "binary_sensor_trigger_things",
      "calendar_trigger_things",
      "time_pattern_trigger_things_simple",
      "time_pattern_trigger_things_complex",
      "voice_trigger_things",
    ],
  },
  script: {
    name_zh: "\u8173\u672c\u63a7\u5236",
    name_en: "Script Control",
    icon: "mdi:script-text",
    blueprints: [
      "light_loop",
      "scene_loop",
    ],
  },
};

const BLUEPRINT_META = {
  adalight: {
    name_zh: "\u81ea\u9069\u61c9\u71c8\u5149",
    name_en: "Adaptive Lighting",
    desc_zh: "\u6839\u64da\u4e00\u5929\u4e2d 6 \u500b\u6642\u6bb5\u81ea\u52d5\u8abf\u6574\u71c8\u5149\u4eae\u5ea6\u8207\u8272\u6eab",
    desc_en: "Auto-adjust brightness and color temperature across 6 daily time periods",
  },
  switch_trigger_lights: {
    name_zh: "\u958b\u95dc\u89f8\u767c\u71c8\u5149",
    name_en: "Switch Trigger Lights",
    desc_zh: "\u591a\u5207\u958b\u95dc\u63a7\u5236\u71c8\u5149\u5be6\u9ad4\uff0c\u652f\u63f4\u540c\u6b65\u5207\u63db",
    desc_en: "Multi-switch controls light entities with synchronized toggle",
  },
  binary_sensor_trigger_light: {
    name_zh: "\u611f\u6e2c\u5668\u89f8\u767c\u71c8\u5149",
    name_en: "Binary Sensor Trigger Light",
    desc_zh: "\u4e8c\u5143\u611f\u6e2c\u5668\u89f8\u767c\u71c8\u5149\u81ea\u52d5\u958b\u95dc",
    desc_en: "Binary sensor triggers automatic light on/off",
  },
  scenes_loop_detail: {
    name_zh: "\u5834\u666f\u5faa\u74b0\uff08\u9032\u968e\uff09",
    name_en: "Scene Loop (Detail)",
    desc_zh: "\u9032\u968e\u5834\u666f\u5faa\u74b0\u64ad\u653e\uff0c\u652f\u63f4\u81ea\u8a02\u6642\u9593\u8207\u8f49\u5834",
    desc_en: "Advanced scene loop with custom timing and transitions",
  },
  scenes_loop_simple: {
    name_zh: "\u5834\u666f\u5faa\u74b0\uff08\u7c21\u6613\uff09",
    name_en: "Scene Loop (Simple)",
    desc_zh: "\u7c21\u6613\u5834\u666f\u5faa\u74b0\u64ad\u653e",
    desc_en: "Simple scene loop playback",
  },
  adascene_multi: {
    name_zh: "\u81ea\u9069\u61c9\u5834\u666f\uff08\u591a\u5834\u666f\uff09",
    name_en: "Adaptive Scene (Multi)",
    desc_zh: "\u6839\u64da\u6642\u6bb5\u81ea\u52d5\u5207\u63db\u591a\u500b\u5834\u666f",
    desc_en: "Auto-switch multiple scenes based on time period",
  },
  adascene_single: {
    name_zh: "\u81ea\u9069\u61c9\u5834\u666f\uff08\u55ae\u5834\u666f\uff09",
    name_en: "Adaptive Scene (Single)",
    desc_zh: "\u6839\u64da\u6642\u6bb5\u81ea\u52d5\u5957\u7528\u55ae\u4e00\u5834\u666f",
    desc_en: "Auto-apply single scene based on time period",
  },
  entity_state_trigger_notify: {
    name_zh: "\u5be6\u9ad4\u72c0\u614b\u89f8\u767c\u901a\u77e5",
    name_en: "Entity State Trigger Notify",
    desc_zh: "\u5be6\u9ad4\u72c0\u614b\u8b8a\u5316\u6642\u767c\u9001\u901a\u77e5",
    desc_en: "Send notification when entity state changes",
  },
  todo_trigger_notify: {
    name_zh: "\u5f85\u8fa6\u4e8b\u9805\u89f8\u767c\u901a\u77e5",
    name_en: "Todo Trigger Notify",
    desc_zh: "\u5f85\u8fa6\u4e8b\u9805\u66f4\u65b0\u6642\u89f8\u767c\u901a\u77e5",
    desc_en: "Trigger notification when todo item updates",
  },
  greenhouse: {
    name_zh: "\u6eab\u5ba4\u81ea\u52d5\u63a7\u5236",
    name_en: "Greenhouse Control",
    desc_zh: "\u6eab\u5ba4\u74b0\u5883\u81ea\u52d5\u76e3\u63a7\u8207\u63a7\u5236",
    desc_en: "Automated greenhouse environment monitoring and control",
  },
  sync_climate: {
    name_zh: "\u540c\u6b65\u6eab\u63a7",
    name_en: "Sync Climate",
    desc_zh: "\u591a\u53f0\u51b7\u6c23\u540c\u6b65\u63a7\u5236\u6eab\u5ea6\u8207\u6a21\u5f0f",
    desc_en: "Synchronize temperature and mode across multiple climate devices",
  },
  light_sync_cover_and_fan: {
    name_zh: "\u71c8\u5149\u540c\u6b65\u7a97\u7c3e\u98ce\u6247",
    name_en: "Light Sync Cover & Fan",
    desc_zh: "\u71c8\u5149\u72c0\u614b\u540c\u6b65\u63a7\u5236\u7a97\u7c3e\u8207\u98a8\u6247",
    desc_en: "Sync cover and fan control based on light state",
  },
  switch_trigger_things: {
    name_zh: "\u958b\u95dc\u89f8\u767c\u52d5\u4f5c",
    name_en: "Switch Trigger Things",
    desc_zh: "\u591a\u5207\u958b\u95dc\u89f8\u767c\u5404\u7a2e\u5be6\u9ad4\u52d5\u4f5c",
    desc_en: "Multi-switch triggers various entity actions",
  },
  binary_sensor_trigger_things: {
    name_zh: "\u611f\u6e2c\u5668\u89f8\u767c\u52d5\u4f5c",
    name_en: "Binary Sensor Trigger Things",
    desc_zh: "\u4e8c\u5143\u611f\u6e2c\u5668\u89f8\u767c\u5404\u7a2e\u5be6\u9ad4\u52d5\u4f5c",
    desc_en: "Binary sensor triggers various entity actions",
  },
  calendar_trigger_things: {
    name_zh: "\u884c\u4e8b\u66c6\u89f8\u767c\u52d5\u4f5c",
    name_en: "Calendar Trigger Things",
    desc_zh: "\u884c\u4e8b\u66c6\u4e8b\u4ef6\u89f8\u767c\u5404\u7a2e\u5be6\u9ad4\u52d5\u4f5c",
    desc_en: "Calendar events trigger various entity actions",
  },
  time_pattern_trigger_things_simple: {
    name_zh: "\u6642\u9593\u6a21\u5f0f\u89f8\u767c\u52d5\u4f5c\uff08\u7c21\u6613\uff09",
    name_en: "Time Pattern Trigger (Simple)",
    desc_zh: "\u4f9d\u7167\u8a2d\u5b9a\u7684\u6642\u9593\u6a21\u5f0f\u89f8\u767c\u6307\u5b9a\u52d5\u4f5c",
    desc_en: "Trigger actions based on time patterns",
  },
  time_pattern_trigger_things_complex: {
    name_zh: "\u6642\u9593\u6a21\u5f0f\u89f8\u767c\u52d5\u4f5c\uff08\u9032\u968e\uff09",
    name_en: "Time Pattern Trigger (Complex)",
    desc_zh: "\u9032\u968e\u6642\u9593\u6a21\u5f0f\u89f8\u767c\uff0c\u652f\u63f4\u591a\u6642\u6bb5\u8207\u689d\u4ef6",
    desc_en: "Advanced time pattern trigger with multiple periods and conditions",
  },
  voice_trigger_things: {
    name_zh: "\u8a9e\u97f3\u89f8\u767c\u52d5\u4f5c",
    name_en: "Voice Trigger Things",
    desc_zh: "\u8a9e\u97f3\u52a9\u624b\u89f8\u767c\u5404\u7a2e\u5be6\u9ad4\u52d5\u4f5c",
    desc_en: "Voice assistant triggers various entity actions",
  },
  light_loop: {
    name_zh: "\u71c8\u5149\u5faa\u74b0\u63a7\u5236",
    name_en: "Light Loop Control",
    desc_zh: "\u4ee512\u7d44\u53ef\u81ea\u8a02\u6a21\u5f0f\u4f9d\u5e8f\u5faa\u74b0\u63a7\u5236\u591a\u76de\u71c8\uff0c\u652f\u63f4\u540c\u6b65/\u975e\u540c\u6b65\u3001RGB\u8207\u8272\u6eab",
    desc_en: "Cycles through up to 12 user-defined modes on multiple lights with sync/async, RGB and color-temp support",
  },
  scene_loop: {
    name_zh: "\u5834\u666f\u5faa\u74b0\u63a7\u5236",
    name_en: "Scene Loop Control",
    desc_zh: "\u4f9d\u5e8f\u6216\u540c\u6642\u57f7\u884c\u591a\u500b\u5834\u666f\uff0c\u652f\u63f4\u5faa\u74b0\u6b21\u6578\u8207\u904e\u6e21\u6642\u9593\u8a2d\u5b9a",
    desc_en: "Sequentially or simultaneously activates multiple scenes with configurable loops and transitions",
  },
};

const UI_STRINGS = {
  zh: {
    title: "\u85cd\u5716\u7ba1\u7406\u5668",
    deployed: "\u5df2\u90e8\u7f72",
    automations: "\u5df2\u5efa\u7acb\u7684\u81ea\u52d5\u5316",
    scripts: "\u5df2\u5efa\u7acb\u7684\u8173\u672c",
    no_automations: "\u5c1a\u7121\u81ea\u52d5\u5316",
    no_scripts: "\u5c1a\u7121\u8173\u672c",
    enabled: "\u555f\u7528\u4e2d",
    disabled: "\u5df2\u505c\u7528",
    idle: "\u9592\u7f6e",
    running: "\u57f7\u884c\u4e2d",
    edit: "\u7de8\u8f2f",
    run: "\u57f7\u884c",
    create: "+ \u5efa\u7acb\u81ea\u52d5\u5316",
    create_script: "+ \u5efa\u7acb\u8173\u672c",
    loading: "\u8f09\u5165\u4e2d\u2026",
  },
  en: {
    title: "Blueprint Manager",
    deployed: "Deployed",
    automations: "Automations",
    scripts: "Scripts",
    no_automations: "No automations yet",
    no_scripts: "No scripts yet",
    enabled: "Enabled",
    disabled: "Disabled",
    idle: "Idle",
    running: "Running",
    edit: "Edit",
    run: "Run",
    create: "+ Create Automation",
    create_script: "+ Create Script",
    loading: "Loading\u2026",
  },
};

/* ---------- Panel CSS ---------- */
const PANEL_CSS =
  // Host
  ":host { display: block; font-family: var(--paper-font-body1_-_font-family, Roboto, Noto, sans-serif); }"

  // Toolbar - matches HA standard app header
  + ".toolbar { display: flex; align-items: center; height: 56px; padding: 0 16px;"
  + " background-color: var(--app-header-background-color, var(--primary-color));"
  + " color: var(--app-header-text-color, var(--text-primary-color, #fff));"
  + " font-size: 20px; box-sizing: border-box; }"
  + ".toolbar h1 { font-size: 20px; font-weight: 400; margin: 0; flex: 1;"
  + " overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }"

  // Tabs - matches HA tab bar styling with conditional scroll fade
  + ".tabs-wrapper { position: relative; }"
  + ".tabs-wrapper.has-overflow::after { content: ''; position: absolute;"
  + " top: 0; right: 0; bottom: 0; width: 32px; pointer-events: none;"
  + " background: linear-gradient(to right, transparent,"
  + " var(--primary-background-color, #fff)); z-index: 1; }"
  + ".tabs { display: flex; overflow-x: auto; -webkit-overflow-scrolling: touch;"
  + " padding: 0 12px; background: var(--primary-background-color);"
  + " border-bottom: 1px solid var(--divider-color);"
  + " scrollbar-width: none; }"
  + ".tabs::-webkit-scrollbar { display: none; }"
  + ".tab { padding: 16px 16px; cursor: pointer; border-bottom: 3px solid transparent;"
  + " color: var(--secondary-text-color); font-size: 14px; font-weight: 500;"
  + " white-space: nowrap; transition: color 0.2s, border-color 0.2s;"
  + " display: flex; align-items: center; gap: 8px; flex-shrink: 0; }"
  + ".tab:hover { color: var(--primary-color); }"
  + ".tab.active { color: var(--primary-color); border-bottom-color: var(--primary-color); }"

  // Content area - matches HA overview padding
  + ".content { padding: 16px; max-width: 1024px; margin: 0 auto; }"

  // Blueprint card - uses ha-card for native theme
  + "ha-card { display: block; margin-bottom: 16px; overflow: hidden;"
  + " border-radius: var(--ha-card-border-radius, 12px); }"
  + ".card-content { padding: 16px; }"

  // Blueprint header row
  + ".blueprint-header { display: flex; justify-content: space-between;"
  + " align-items: flex-start; margin-bottom: 8px; gap: 8px; }"
  + ".blueprint-title-area { flex: 1; min-width: 0; }"
  + ".blueprint-name { font-size: 16px; font-weight: 500;"
  + " color: var(--primary-text-color); margin: 0; }"
  + ".blueprint-desc { font-size: 13px; color: var(--secondary-text-color);"
  + " margin-top: 4px; line-height: 1.5; }"
  + ".blueprint-status { font-size: 11px; color: var(--success-color, #43A047);"
  + " background: rgba(67, 160, 71, 0.1); padding: 4px 10px; border-radius: 12px;"
  + " white-space: nowrap; flex-shrink: 0; font-weight: 500; }"

  // Automations section - divider matches HA card sections
  + ".automations-section { border-top: 1px solid var(--divider-color);"
  + " margin-top: 12px; padding-top: 12px; }"
  + ".automations-header { display: flex; justify-content: space-between;"
  + " align-items: center; margin-bottom: 10px; gap: 8px; flex-wrap: wrap; }"
  + ".automations-title { font-size: 13px; font-weight: 500;"
  + " color: var(--secondary-text-color); }"

  // Create button - matches HA primary action button style
  + ".create-btn { cursor: pointer; background: var(--primary-color);"
  + " color: var(--text-primary-color, #fff); border: none; font-size: 13px;"
  + " font-weight: 500; padding: 8px 16px; border-radius: 18px;"
  + " transition: opacity 0.2s, box-shadow 0.2s; white-space: nowrap; flex-shrink: 0;"
  + " letter-spacing: 0.25px; min-height: 48px; box-sizing: border-box;"
  + " display: inline-flex; align-items: center; justify-content: center; }"
  + ".create-btn:hover { opacity: 0.85; box-shadow: 0 2px 8px rgba(0,0,0,0.2); }"
  + ".create-btn:active { opacity: 0.7; }"

  // Automation list items - fixed column layout for visual consistency
  + ".automation-item { display: flex; align-items: center;"
  + " padding: 10px 14px;"
  + " background: var(--secondary-background-color);"
  + " border-radius: 8px; margin-bottom: 8px;"
  + " gap: 8px; }"
  + ".automation-name { font-size: 14px; color: var(--primary-text-color);"
  + " overflow: hidden; text-overflow: ellipsis; white-space: nowrap;"
  + " flex: 1; min-width: 0; }"
  + ".automation-state { font-size: 11px; padding: 3px 8px; border-radius: 10px;"
  + " font-weight: 500; white-space: nowrap; flex-shrink: 0; }"
  + ".automation-state.on { color: var(--success-color, #43A047);"
  + " background: rgba(67, 160, 71, 0.15); }"
  + ".automation-state.off { color: var(--error-color, #DB4437);"
  + " background: rgba(219, 68, 55, 0.12); }"
  + ".automation-state.idle { color: var(--secondary-text-color);"
  + " background: rgba(128, 128, 128, 0.1); }"
  + ".automation-actions { display: flex; align-items: center; gap: 4px;"
  + " flex-shrink: 0; }"
  + ".action-btn { cursor: pointer; background: none; border: none;"
  + " color: var(--primary-color); font-size: 13px; padding: 8px;"
  + " border-radius: 8px; transition: background 0.2s; font-weight: 500;"
  + " min-height: 48px; min-width: 48px; box-sizing: border-box;"
  + " display: inline-flex; align-items: center; justify-content: center; }"
  + ".action-btn ha-icon { --mdc-icon-size: 20px; }"
  + ".action-btn:hover { background: var(--secondary-background-color); }"
  + ".action-btn:focus-visible { outline: 2px solid var(--primary-color);"
  + " outline-offset: -2px; }"
  + ".no-automations { font-size: 13px; color: var(--secondary-text-color);"
  + " padding: 4px 0; }";

class WoowBlueprintPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._activeTab = "lighting";
    this._automations = [];
    this._hass = null;
    this._loading = true;
    this._loadVersion = 0;
    this._renderScheduled = false;
    this._loadDebounceTimer = null;
    this._lastLoadTime = 0;
    this._initialLoadDone = false;
    this._retryTimer = null;
    this._retryCount = 0;
    this._maxRetries = 2;
    this._cancelCreate = null;
    this._tabsResizeObserver = null;
    this._tabsWrapper = null;
    this._tabsEl = null;
  }

  set hass(hass) {
    var oldHass = this._hass;
    this._hass = hass;

    if (this.shadowRoot) {
      var menuBtn = this.shadowRoot.getElementById("ha-menu-btn");
      if (menuBtn) { menuBtn.hass = hass; }
    }

    if (!oldHass || oldHass.language !== hass.language) {
      this._scheduleRender();
    }

    if (!oldHass) {
      this._loadAutomations();
      return;
    }

    if (oldHass.states !== hass.states) {
      // Only reload when an automation.* or script.* entity actually changed
      var dominated = false;
      var newStates = hass.states;
      var oldStates = oldHass.states;
      for (var key in newStates) {
        if ((key.startsWith("automation.") || key.startsWith("script."))
            && newStates[key] !== oldStates[key]) {
          dominated = true;
          break;
        }
      }
      if (!dominated) {
        // Check for removed entities
        for (var key in oldStates) {
          if ((key.startsWith("automation.") || key.startsWith("script."))
              && !(key in newStates)) {
            dominated = true;
            break;
          }
        }
      }
      if (dominated) {
        this._debouncedLoadAutomations();
      }
    }
  }

  get hass() { return this._hass; }

  set panel(panel) { this._panel = panel; }

  set narrow(narrow) {
    this._narrow = narrow;
    if (this.shadowRoot) {
      var menuBtn = this.shadowRoot.getElementById("ha-menu-btn");
      if (menuBtn) { menuBtn.narrow = narrow; }
    }
  }

  get _lang() {
    if (!this._hass) return "en";
    var lang = this._hass.language || "en";
    return lang.startsWith("zh") ? "zh" : "en";
  }

  get _ui() {
    return UI_STRINGS[this._lang] || UI_STRINGS.en;
  }

  _getName(meta) {
    return this._lang === "zh" ? meta.name_zh : meta.name_en;
  }

  _getDesc(meta) {
    return this._lang === "zh" ? meta.desc_zh : meta.desc_en;
  }

  disconnectedCallback() {
    if (this._loadDebounceTimer) {
      clearTimeout(this._loadDebounceTimer);
      this._loadDebounceTimer = null;
    }
    if (this._retryTimer) {
      clearTimeout(this._retryTimer);
      this._retryTimer = null;
    }
    if (this._tabsResizeObserver) {
      this._tabsResizeObserver.disconnect();
      this._tabsResizeObserver = null;
    }
    // Note: _navigateToCreate timers are intentionally NOT cancelled here.
    // The panel is unmounted during navigation to the editor page, but the
    // timers must continue running to inject the blueprint config.
  }

  connectedCallback() {
    if (!this.shadowRoot.querySelector("style")) {
      var style = document.createElement("style");
      style.textContent = PANEL_CSS;
      this.shadowRoot.appendChild(style);
    }
    this._render();
    if (this._hass) {
      this._loadAutomations();
    }
  }

  _debouncedLoadAutomations() {
    if (this._loadDebounceTimer) {
      clearTimeout(this._loadDebounceTimer);
    }
    this._loadDebounceTimer = setTimeout(() => {
      this._loadDebounceTimer = null;
      this._loadAutomations();
    }, 500);
  }

  _scheduleRender() {
    if (this._renderScheduled) return;
    this._renderScheduled = true;
    requestAnimationFrame(() => {
      this._renderScheduled = false;
      this._render();
    });
  }

  async _loadAutomations() {
    if (!this._hass) return;

    var version = ++this._loadVersion;
    this._lastLoadTime = Date.now();

    try {
      var allStates = this._hass.states || {};
      var self = this;

      // Discover automation.* entities via config API
      var autoStates = Object.values(allStates).filter(
        function(s) { return s.entity_id.startsWith("automation.") && s.attributes.id; }
      );

      var autoResults = await Promise.allSettled(
        autoStates.map(function(state) {
          var autoId = state.attributes.id;
          return self._hass.callApi(
            "GET",
            "config/automation/config/" + autoId
          ).then(function(resp) {
            if (
              resp &&
              resp.use_blueprint &&
              resp.use_blueprint.path &&
              resp.use_blueprint.path.includes("woowtech/")
            ) {
              return {
                entity_id: state.entity_id,
                name: state.attributes.friendly_name || state.entity_id,
                state: state.state,
                blueprint_path: resp.use_blueprint.path,
                config_id: autoId,
              };
            }
            return null;
          }).catch(function() {
            return null;
          });
        })
      );

      // Discover script.* entities via config API
      var scriptStates = Object.values(allStates).filter(
        function(s) { return s.entity_id.startsWith("script."); }
      );

      var scriptResults = await Promise.allSettled(
        scriptStates.map(function(state) {
          var scriptId = state.entity_id.replace("script.", "");
          return self._hass.callApi(
            "GET",
            "config/script/config/" + scriptId
          ).then(function(resp) {
            if (
              resp &&
              resp.use_blueprint &&
              resp.use_blueprint.path &&
              resp.use_blueprint.path.includes("woowtech/")
            ) {
              return {
                entity_id: state.entity_id,
                name: state.attributes.friendly_name || state.entity_id,
                state: state.state,
                blueprint_path: resp.use_blueprint.path,
                config_id: scriptId,
              };
            }
            return null;
          }).catch(function() {
            return null;
          });
        })
      );

      if (version !== self._loadVersion) return;

      var automations = [];
      var allResults = autoResults.concat(scriptResults);
      for (var i = 0; i < allResults.length; i++) {
        if (allResults[i].status === "fulfilled" && allResults[i].value) {
          automations.push(allResults[i].value);
        }
      }

      self._automations = automations;
      self._loading = false;
      self._initialLoadDone = true;
      self._render();

      if (automations.length > 0) {
        self._retryCount = 0;
      }

      // Bounded retry: only retry up to _maxRetries times when no automations found
      if (automations.length === 0 && !self._retryTimer && self._retryCount < self._maxRetries) {
        self._retryCount++;
        self._retryTimer = setTimeout(function() {
          self._retryTimer = null;
          self._loading = true;
          self._render();
          self._loadAutomations();
        }, 3000);
      }
    } catch (err) {
      console.warn("[woow-blueprint-panel] Error loading automations:", err);
      this._loading = false;
      this._render();
    }
  }

  _getBlueprintKey(path) {
    var parts = path.split("/");
    var filename = parts[parts.length - 1];
    return filename.replace(".yaml", "");
  }

  _getAutomationsForBlueprint(blueprintKey) {
    var self = this;
    return this._automations.filter(
      function(a) { return self._getBlueprintKey(a.blueprint_path) === blueprintKey; }
    );
  }

  async _toggleAutomation(entityId) {
    try {
      var domain = entityId.split(".")[0];
      var action = domain === "script" ? "turn_on" : "toggle";
      await this._hass.callService(domain, action, {
        entity_id: entityId,
      });
    } catch (err) {
      console.warn("[woow-blueprint-panel] Toggle failed for " + entityId + ":", err);
      if (this._hass && this._hass.callService) {
        this._hass.callService("persistent_notification", "create", {
          title: "Blueprint Manager",
          message: "Toggle failed for " + entityId + ". Please try again.",
          notification_id: "woow_toggle_fail",
        });
      }
    }
  }

  _navigate(path) {
    history.pushState(null, "", path);
    window.dispatchEvent(
      new CustomEvent("location-changed", { detail: { replace: false } })
    );
  }

  _navigateToEdit(entityId, configId) {
    var domain = entityId ? entityId.split(".")[0] : "automation";
    this._navigate("/config/" + domain + "/edit/" + configId);
  }

  _navigateToCreate(blueprintKey) {
    // Cancel any in-flight create flow before starting a new one
    if (this._cancelCreate) this._cancelCreate();

    var domain = SCRIPT_BLUEPRINTS.has(blueprintKey) ? "script" : "automation";
    var blueprintPath = "woowtech/" + blueprintKey + ".yaml";
    var editorTag =
      domain === "script" ? "ha-script-editor" : "ha-automation-editor";
    var hass = this._hass;

    this._navigate("/config/" + domain + "/edit/new");

    // Use a self-contained closure with its own DOM search.
    // The panel element is unmounted during navigation, so we cannot
    // rely on instance properties or _deepFind after _navigate().
    function deepFind(root, sel) {
      if (!root) return null;
      var found = root.querySelector(sel);
      if (found) return found;
      var children = root.querySelectorAll("*");
      for (var i = 0; i < children.length; i++) {
        if (children[i].shadowRoot) {
          var result = deepFind(children[i].shadowRoot, sel);
          if (result) return result;
        }
      }
      return null;
    }

    var cancelled = false;
    var trySetBlueprint = function (attempt) {
      if (cancelled) return;
      if (attempt > 50) {
        console.warn(
          "[woow-blueprint-panel] Could not find " +
            editorTag +
            " after 50 attempts"
        );
        if (hass && hass.callService) {
          hass.callService("persistent_notification", "create", {
            title: "Blueprint Manager",
            message:
              "Could not auto-select blueprint. Please select it manually.",
            notification_id: "woow_blueprint_nav_fail",
          });
        }
        return;
      }
      var el = deepFind(document, editorTag);
      if (el && el.config) {
        el.config = {
          description: "",
          use_blueprint: { path: blueprintPath, input: {} },
        };
        el.dirty = true;
        if (el.requestUpdate) el.requestUpdate();
        // Verify the config stuck after the editor completes its update cycle.
        // Checks both that use_blueprint exists and that the path matches.
        var verifyConfig = function (verifyAttempt) {
          if (cancelled) return;
          if (verifyAttempt > 10) {
            console.warn(
              "[woow-blueprint-panel] Blueprint config was overwritten " +
                "repeatedly; giving up verification"
            );
            if (hass && hass.callService) {
              hass.callService("persistent_notification", "create", {
                title: "Blueprint Manager",
                message:
                  "Blueprint may not have been selected correctly. " +
                  "Please verify or select it manually.",
                notification_id: "woow_blueprint_verify_fail",
              });
            }
            return;
          }
          var el2 = deepFind(document, editorTag);
          if (
            el2 &&
            el2.config &&
            (!el2.config.use_blueprint ||
              el2.config.use_blueprint.path !== blueprintPath)
          ) {
            el2.config = {
              description: "",
              use_blueprint: { path: blueprintPath, input: {} },
            };
            el2.dirty = true;
            if (el2.requestUpdate) el2.requestUpdate();
            setTimeout(function () {
              verifyConfig(verifyAttempt + 1);
            }, 300);
          }
        };
        setTimeout(function () {
          verifyConfig(0);
        }, 500);
      } else {
        setTimeout(function () {
          trySetBlueprint(attempt + 1);
        }, 150);
      }
    };
    setTimeout(function () {
      trySetBlueprint(0);
    }, 300);

    // Allow cancellation if the user navigates back before completion
    this._cancelCreate = function () {
      cancelled = true;
    };
  }

  _handleTabChange(tabId) {
    this._activeTab = tabId;
    this._render();
  }

  _render() {
    if (!this.shadowRoot) return;

    var ui = this._ui;
    var activeCategory = CATEGORIES[this._activeTab];

    // Build tabs
    var tabsHtml = "";
    var catKeys = Object.keys(CATEGORIES);
    for (var ci = 0; ci < catKeys.length; ci++) {
      var key = catKeys[ci];
      var cat = CATEGORIES[key];
      var isActive = this._activeTab === key ? " active" : "";
      tabsHtml += '<div class="tab' + isActive + '" data-tab="' + key + '">'
        + '<ha-icon icon="' + cat.icon + '" style="--mdc-icon-size: 20px;"></ha-icon>'
        + "<span>" + this._getName(cat) + "</span>"
        + "</div>";
    }

    // Build blueprint cards using <ha-card>
    var blueprintsHtml = "";
    var bps = activeCategory.blueprints;
    for (var bi = 0; bi < bps.length; bi++) {
      var bpKey = bps[bi];
      var meta = BLUEPRINT_META[bpKey];
      if (!meta) continue;

      var isScript = SCRIPT_BLUEPRINTS.has(bpKey);
      var automations = this._getAutomationsForBlueprint(bpKey);

      var automationsListHtml = "";
      var sectionLabel = isScript ? ui.scripts : ui.automations;
      var emptyLabel = isScript ? ui.no_scripts : ui.no_automations;
      if (this._loading) {
        automationsListHtml = '<div class="no-automations">' + ui.loading + "</div>";
      } else if (automations.length === 0) {
        automationsListHtml = '<div class="no-automations">' + emptyLabel + "</div>";
      } else {
        for (var ai = 0; ai < automations.length; ai++) {
          var auto = automations[ai];
          var stateLabel, toggleIcon, stateClass;
          if (isScript) {
            stateLabel = auto.state === "on" ? ui.running : ui.idle;
            stateClass = auto.state === "on" ? "on" : "idle";
            toggleIcon = "mdi:play";
          } else {
            stateLabel = auto.state === "on" ? ui.enabled : ui.disabled;
            stateClass = auto.state;
            toggleIcon = auto.state === "on" ? "mdi:pause" : "mdi:play";
          }
          automationsListHtml += '<div class="automation-item">'
            + '<span class="automation-name">' + this._escHtml(auto.name) + "</span>"
            + '<span class="automation-state ' + stateClass + '">'
            + stateLabel
            + "</span>"
            + '<div class="automation-actions">'
            + '<button class="action-btn toggle-btn" data-entity="' + auto.entity_id + '">'
            + '<ha-icon icon="' + toggleIcon + '"></ha-icon>'
            + "</button>"
            + '<button class="action-btn edit-btn" data-id="' + auto.config_id + '" data-entity="' + auto.entity_id + '">'
            + '<ha-icon icon="mdi:pencil"></ha-icon>'
            + "</button>"
            + "</div>"
            + "</div>";
        }
      }

      var createLabel = isScript ? ui.create_script : ui.create;

      blueprintsHtml += "<ha-card>"
        + '<div class="card-content">'
        + '<div class="blueprint-header">'
        + '<div class="blueprint-title-area">'
        + '<div class="blueprint-name">' + this._escHtml(this._getName(meta)) + "</div>"
        + '<div class="blueprint-desc">' + this._escHtml(this._getDesc(meta)) + "</div>"
        + "</div>"
        + '<span class="blueprint-status">\u2713 ' + ui.deployed + "</span>"
        + "</div>"
        + '<div class="automations-section">'
        + '<div class="automations-header">'
        + '<span class="automations-title">' + sectionLabel + " (" + automations.length + ")</span>"
        + '<button class="create-btn" data-key="' + bpKey + '">' + createLabel + "</button>"
        + "</div>"
        + automationsListHtml
        + "</div>"
        + "</div>"
        + "</ha-card>";
    }

    var contentHtml = '<div class="toolbar">'
      + '<ha-menu-button id="ha-menu-btn"></ha-menu-button>'
      + '<h1>' + ui.title + '</h1>'
      + '</div>'
      + '<div class="tabs-wrapper"><div class="tabs">' + tabsHtml + '</div></div>'
      + '<div class="content">' + blueprintsHtml + '</div>';

    var container = this.shadowRoot.getElementById("panel-root");
    if (!container) {
      container = document.createElement("div");
      container.id = "panel-root";
      this.shadowRoot.appendChild(container);

      // Event delegation: attach once, handle all clicks via data attributes
      var self = this;
      container.addEventListener("click", function(e) {
        var target = e.target.closest("[data-tab], .toggle-btn, .edit-btn, .create-btn");
        if (!target) return;

        if (target.dataset.tab) {
          self._handleTabChange(target.dataset.tab);
        } else if (target.classList.contains("toggle-btn") && target.dataset.entity) {
          self._toggleAutomation(target.dataset.entity);
        } else if (target.classList.contains("edit-btn") && target.dataset.id) {
          self._navigateToEdit(target.dataset.entity, target.dataset.id);
        } else if (target.classList.contains("create-btn") && target.dataset.key) {
          self._navigateToCreate(target.dataset.key);
        }
      });
    }
    container.innerHTML = contentHtml;

    // Toggle scroll fade based on actual tab overflow
    var tabsWrapper = this.shadowRoot.querySelector(".tabs-wrapper");
    var tabsEl = this.shadowRoot.querySelector(".tabs");
    if (tabsWrapper && tabsEl) {
      this._tabsWrapper = tabsWrapper;
      this._tabsEl = tabsEl;
      // Create the ResizeObserver once; reuse on subsequent renders
      if (!this._tabsResizeObserver) {
        var self = this;
        this._tabsResizeObserver = new ResizeObserver(function () {
          if (self._tabsEl && self._tabsWrapper) {
            if (self._tabsEl.scrollWidth > self._tabsEl.clientWidth) {
              self._tabsWrapper.classList.add("has-overflow");
            } else {
              self._tabsWrapper.classList.remove("has-overflow");
            }
          }
        });
      } else {
        this._tabsResizeObserver.disconnect();
      }
      this._tabsResizeObserver.observe(tabsEl);
      // Initial check
      if (tabsEl.scrollWidth > tabsEl.clientWidth) {
        tabsWrapper.classList.add("has-overflow");
      } else {
        tabsWrapper.classList.remove("has-overflow");
      }
    }

    var menuBtn = this.shadowRoot.getElementById("ha-menu-btn");
    if (menuBtn) {
      menuBtn.hass = this._hass;
      menuBtn.narrow = this._narrow;
    }
  }

  _escHtml(str) {
    if (!_escDiv) { _escDiv = document.createElement("div"); }
    _escDiv.textContent = str;
    return _escDiv.innerHTML;
  }
}

if (!customElements.get("woow-blueprint-panel")) {
  customElements.define("woow-blueprint-panel", WoowBlueprintPanel);
}
