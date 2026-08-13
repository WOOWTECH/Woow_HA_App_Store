// Home Assistant Unified Control Panel
// Combines Area Control and Label Control into a single tabbed interface
// Matches HA Home Dashboard design with tall tiles and embedded controls

// Local Lit bundle (no CDN dependency for offline/intranet environments)
const { LitElement, html, css } = await import(
  "/local/lit.js"
);

// ============================================================================
// DESIGN TOKENS - HA Native Style (Theme-Aware)
// ============================================================================

// Functional colors that remain fixed (safety/status indicators)
const FUNCTIONAL_COLORS = {
  climate_cool: "#2196F3",
  climate_heat: "#FF9800",
  lock: "#4CAF50",
  lock_unlocked: "#F44336",
};

/**
 * Read the HA theme's --primary-color at runtime.
 * Returns { hex, rgb } where rgb is "r, g, b" string for rgba() usage.
 */
function getThemePrimaryColor() {
  try {
    const root = document.documentElement;
    const raw = getComputedStyle(root).getPropertyValue("--primary-color").trim();
    if (raw) {
      const match = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(raw);
      if (match) {
        return {
          hex: raw,
          rgb: `${parseInt(match[1], 16)}, ${parseInt(match[2], 16)}, ${parseInt(match[3], 16)}`,
        };
      }
      const rgbMatch = raw.match(/(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/);
      if (rgbMatch) {
        return { hex: raw, rgb: `${rgbMatch[1]}, ${rgbMatch[2]}, ${rgbMatch[3]}` };
      }
    }
  } catch (e) { /* fallback */ }
  return { hex: "#03a9f4", rgb: "3, 169, 244" };
}

const DOMAIN_ICONS = {
  light: "mdi:lightbulb",
  switch: "mdi:toggle-switch",
  input_boolean: "mdi:toggle-switch-outline",
  fan: "mdi:fan",
  climate: "mdi:thermostat",
  cover: "mdi:window-shutter",
  lock: "mdi:lock",
  vacuum: "mdi:robot-vacuum",
  media_player: "mdi:cast",
  humidifier: "mdi:air-humidifier",
  automation: "mdi:robot",
  script: "mdi:script-text",
  scene: "mdi:palette",
  sensor: "mdi:eye",
  binary_sensor: "mdi:checkbox-marked-circle",
  button: "mdi:gesture-tap-button",
  person: "mdi:account",
  camera: "mdi:cctv",
  alarm_control_panel: "mdi:shield-home",
  update: "mdi:package-up",
  weather: "mdi:weather-partly-cloudy",
  input_number: "mdi:ray-vertex",
  input_select: "mdi:form-dropdown",
  input_text: "mdi:form-textbox",
  number: "mdi:ray-vertex",
  select: "mdi:form-dropdown",
  text: "mdi:form-textbox",
  device_tracker: "mdi:crosshairs-gps",
  calendar: "mdi:calendar",
  todo: "mdi:clipboard-list",
  remote: "mdi:remote",
};

// Fixed 9 domains that always show in summary section
const SUMMARY_DOMAINS = [
  "light",
  "climate",
  "cover",
  "fan",
  "media_player",
  "lock",
  "vacuum",
  "switch",
  "input_boolean",
];

// Domains that can be toggled
const TOGGLEABLE_DOMAINS = [
  "light",
  "switch",
  "input_boolean",
  "fan",
  "climate",
  "humidifier",
  "automation",
  "lock",
  "vacuum",
  "media_player",
];

// Domain display order
const DOMAIN_ORDER = [
  "light", "switch", "climate", "cover", "fan", "media_player",
  "automation", "script", "scene", "button",
  "sensor", "binary_sensor",
  "vacuum", "lock", "camera",
  "input_boolean", "input_number", "input_select", "input_text",
  "number", "select", "text",
  "person", "device_tracker",
  "calendar", "todo",
  "alarm_control_panel", "update",
];

// States considered "active" for counting purposes
const ACTIVE_STATES = ["on", "playing", "open", "unlocked", "heat", "cool", "heat_cool", "auto", "cleaning", "home"];

// Translations
const TRANSLATIONS = {
  en: {
    title: "Control Panel",
    areasTab: "Areas",
    labelsTab: "Labels",
    summary: "Summary",
    areas: "Areas",
    labels: "Labels",
    noAreas: "No areas available",
    noLabels: "No labels available",
    noEntities: "No entities in this section",
    entities: "entities",
    loading: "Loading...",
    on: "on",
    off: "off",
    allOff: "All off",
    searchPlaceholder: "Search devices...",
    all: "All",
    retry: "Retry",
    light: "Lights", switch: "Switches", climate: "Climate", cover: "Covers",
    fan: "Fans", media_player: "Media", vacuum: "Vacuums", lock: "Locks",
    humidifier: "Humidifiers", automation: "Automations", script: "Scripts",
    scene: "Scenes", button: "Buttons", sensor: "Sensors",
    binary_sensor: "Binary Sensors", input_boolean: "Input Boolean",
    input_number: "Input Number", input_select: "Input Select",
    input_text: "Input Text", alarm_control_panel: "Security",
    camera: "Cameras", person: "Persons", device_tracker: "Trackers",
  },
  "zh-Hant": {
    title: "控制面板",
    areasTab: "分區",
    labelsTab: "標籤",
    summary: "摘要",
    areas: "分區",
    labels: "標籤",
    noAreas: "沒有可用的分區",
    noLabels: "沒有可用的標籤",
    noEntities: "此區域沒有實體",
    entities: "個實體",
    loading: "載入中...",
    on: "開啟",
    off: "關閉",
    allOff: "全部關閉",
    searchPlaceholder: "搜尋裝置...",
    all: "全部",
    retry: "重試",
    light: "燈光", switch: "開關", climate: "溫控", cover: "窗簾",
    fan: "風扇", media_player: "媒體播放器", vacuum: "掃地機", lock: "門鎖",
    humidifier: "加濕器", automation: "自動化", script: "腳本",
    scene: "場景", button: "按鈕", sensor: "感測器",
    binary_sensor: "二元感測器", input_boolean: "輔助開關",
    input_number: "輸入數字", input_select: "輸入選擇",
    input_text: "輸入文字", alarm_control_panel: "保全",
    camera: "攝影機", person: "人員", device_tracker: "追蹤器",
  },
  "zh-Hans": {
    title: "控制面板",
    areasTab: "分区",
    labelsTab: "标签",
    summary: "摘要",
    areas: "分区",
    labels: "标签",
    noAreas: "没有可用的分区",
    noLabels: "没有可用的标签",
    noEntities: "此区域没有实体",
    entities: "个实体",
    loading: "加载中...",
    on: "开启",
    off: "关闭",
    allOff: "全部关闭",
    searchPlaceholder: "搜索设备...",
    all: "全部",
    retry: "重试",
    light: "灯光", switch: "开关", climate: "温控", cover: "窗帘",
    fan: "风扇", media_player: "媒体播放器", vacuum: "扫地机", lock: "门锁",
    humidifier: "加湿器", automation: "自动化", script: "脚本",
    scene: "场景", button: "按钮", sensor: "传感器",
    binary_sensor: "二元传感器", input_boolean: "辅助开关",
    input_number: "输入数字", input_select: "输入选择",
    input_text: "输入文字", alarm_control_panel: "安防",
    camera: "摄像机", person: "人员", device_tracker: "追踪器",
  },
};

// Label color mapping
const LABEL_COLORS = {
  red: "#f44336", pink: "#e91e63", purple: "#9c27b0", deep_purple: "#673ab7",
  indigo: "#3f51b5", blue: "#2196f3", light_blue: "#03a9f4", cyan: "#00bcd4",
  teal: "#009688", green: "#4caf50", light_green: "#8bc34a", lime: "#cddc39",
  yellow: "#ffeb3b", amber: "#ffc107", orange: "#ff9800", deep_orange: "#ff5722",
  brown: "#795548", grey: "#9e9e9e", blue_grey: "#607d8b",
};

// ============================================================================
// UTILITY FUNCTIONS
// ============================================================================

function hexToRgb(hex) {
  if (!hex) return "3, 169, 244";
  if (hex.startsWith("rgb")) {
    const match = hex.match(/\d+/g);
    return match ? match.slice(0, 3).join(", ") : "3, 169, 244";
  }
  const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
  return result
    ? `${parseInt(result[1], 16)}, ${parseInt(result[2], 16)}, ${parseInt(result[3], 16)}`
    : "3, 169, 244";
}

function getLabelColor(color) {
  if (!color) return "#2196f3";
  return LABEL_COLORS[color] || color;
}

// ============================================================================
// BASE TILE COMPONENT
// ============================================================================

class CpBaseTile extends LitElement {
  static get properties() {
    return {
      hass: { type: Object },
      entityId: { type: String, attribute: "entity-id" },
    };
  }

  static get styles() {
    return css`
      :host {
        display: block;
      }

      .tile {
        background: var(--tile-bg, rgba(255, 255, 255, 0.05));
        border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
        border-radius: 12px;
        padding: 12px 16px;
        min-height: 56px;
        height: auto;
        width: 100%;
        box-sizing: border-box;
        display: flex;
        flex-direction: row;
        align-items: center;
        gap: 12px;
        cursor: pointer;
        transition: background-color 0.2s ease, transform 0.1s ease;
        position: relative;
        overflow: hidden;
      }

      .tile:hover {
        background: var(--tile-bg-hover, rgba(255, 255, 255, 0.08));
      }

      .tile:active {
        transform: scale(0.98);
      }

      .tile.on {
        background: var(--tile-color-bg, rgba(3, 169, 244, 0.2));
      }

      .tile.unavailable {
        opacity: 0.5;
      }

      .tile-icon {
        width: 40px;
        height: 40px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        background: var(--icon-bg, rgba(255, 255, 255, 0.1));
        color: var(--icon-color, #9e9e9e);
        flex-shrink: 0;
      }

      .tile.on .tile-icon {
        background: var(--tile-color-bg, rgba(3, 169, 244, 0.3));
        color: var(--tile-color, var(--primary-color, #03a9f4));
      }

      .tile-icon ha-icon {
        --mdc-icon-size: 20px;
      }

      .tile-info {
        flex: 1;
        min-width: 0;
        overflow: hidden;
        display: flex;
        flex-direction: column;
        justify-content: center;
      }

      .tile-name {
        font-size: 14px;
        font-weight: 500;
        color: var(--primary-text-color, #fff);
        white-space: normal;
        display: -webkit-box;
        -webkit-line-clamp: 2;
        -webkit-box-orient: vertical;
        overflow: hidden;
        line-height: 1.3;
        max-width: 100%;
      }

      .tile-state {
        font-size: 12px;
        color: var(--secondary-text-color, rgba(255, 255, 255, 0.7));
        margin-top: 2px;
      }
    `;
  }

  get entity() {
    return this.hass?.states?.[this.entityId];
  }

  get isOn() {
    const state = this.entity?.state;
    return ["on", "playing", "open", "unlocked", "heat", "cool", "heat_cool", "auto", "cleaning", "returning", "home"].includes(state);
  }

  get isUnavailable() {
    return this.entity?.state === "unavailable" || !this.entity;
  }

  get stateDisplay() {
    if (this.isUnavailable) return "Unavailable";
    try {
      return this.hass.formatEntityState(this.entity);
    } catch {
      return this.entity?.state || "Unknown";
    }
  }

  get icon() {
    const domain = this.entityId?.split(".")[0];
    return this.entity?.attributes?.icon || DOMAIN_ICONS[domain] || "mdi:help-circle";
  }

  get tileColor() {
    const domain = this.entityId?.split(".")[0];

    // For RGB lights, use actual color
    if (domain === "light" && this.isOn) {
      const rgb = this.entity?.attributes?.rgb_color;
      if (rgb) {
        return `rgb(${rgb[0]}, ${rgb[1]}, ${rgb[2]})`;
      }
    }

    // Climate: functional safety colors
    if (domain === "climate" && this.isOn) {
      const hvacAction = this.entity?.attributes?.hvac_action;
      if (hvacAction === "cooling") return FUNCTIONAL_COLORS.climate_cool;
      if (hvacAction === "heating") return FUNCTIONAL_COLORS.climate_heat;
    }

    // Lock: functional safety colors
    if (domain === "lock") {
      return this.entity?.state === "locked"
        ? FUNCTIONAL_COLORS.lock
        : FUNCTIONAL_COLORS.lock_unlocked;
    }

    // All other domains: use theme primary color
    const theme = getThemePrimaryColor();
    return theme.hex;
  }

  toggle() {
    if (this.isUnavailable || !this.hass) return;
    const domain = this.entityId?.split(".")[0];

    if (domain === "scene" || domain === "script") {
      this.hass.callService(domain, "turn_on", { entity_id: this.entityId });
    } else if (domain === "button") {
      this.hass.callService("button", "press", { entity_id: this.entityId });
    } else if (domain === "lock") {
      const service = this.entity?.state === "locked" ? "unlock" : "lock";
      this.hass.callService("lock", service, { entity_id: this.entityId });
    } else if (TOGGLEABLE_DOMAINS.includes(domain)) {
      this.hass.callService("homeassistant", "toggle", { entity_id: this.entityId });
    }
  }

  openMoreInfo() {
    const event = new CustomEvent("hass-more-info", {
      bubbles: true,
      composed: true,
      detail: { entityId: this.entityId },
    });
    this.dispatchEvent(event);
  }

  handleClick(e) {
    e.stopPropagation();
    this.openMoreInfo();
  }

  handleLongPress(e) {
    e.preventDefault();
    this.openMoreInfo();
  }

  connectedCallback() {
    super.connectedCallback();
    this._longPressTimer = null;

    this._boundHandleTouchStart = this._handleTouchStart.bind(this);
    this._boundHandleTouchEnd = this._handleTouchEnd.bind(this);

    this.addEventListener("touchstart", this._boundHandleTouchStart);
    this.addEventListener("touchend", this._boundHandleTouchEnd);
    this.addEventListener("touchcancel", this._boundHandleTouchEnd);
  }

  disconnectedCallback() {
    super.disconnectedCallback();

    if (this._boundHandleTouchStart) {
      this.removeEventListener("touchstart", this._boundHandleTouchStart);
    }
    if (this._boundHandleTouchEnd) {
      this.removeEventListener("touchend", this._boundHandleTouchEnd);
      this.removeEventListener("touchcancel", this._boundHandleTouchEnd);
    }

    if (this._longPressTimer) {
      clearTimeout(this._longPressTimer);
      this._longPressTimer = null;
    }
  }

  _handleTouchStart(e) {
    this._longPressTimer = setTimeout(() => {
      this.openMoreInfo();
      this._longPressTimer = null;
    }, 500);
  }

  _handleTouchEnd(e) {
    if (this._longPressTimer) {
      clearTimeout(this._longPressTimer);
      this._longPressTimer = null;
    }
  }

  render() {
    const entity = this.entity;
    if (!entity && !this.entityId) return html``;

    const color = this.tileColor;
    const colorRgb = hexToRgb(color);

    return html`
      <div
        class="tile ${this.isOn ? "on" : ""} ${this.isUnavailable ? "unavailable" : ""}"
        style="--tile-color: ${color}; --tile-color-bg: rgba(${colorRgb}, 0.2); --icon-bg: rgba(${colorRgb}, 0.1);"
        @click=${this.handleClick}
        @contextmenu=${this.handleLongPress}
      >
        <div class="tile-icon">
          <ha-icon icon=${this.icon}></ha-icon>
        </div>
        <div class="tile-info">
          <div class="tile-name">${entity?.attributes?.friendly_name || this.entityId}</div>
          <div class="tile-state">${this.stateDisplay}</div>
        </div>
      </div>
    `;
  }
}

customElements.define("cp-base-tile", CpBaseTile);

// ============================================================================
// SPECIALIZED TILE COMPONENTS
// ============================================================================

class CpLightTile extends CpBaseTile {
  get stateDisplay() {
    if (this.isUnavailable) return "Unavailable";
    if (!this.isOn) return "Off";
    const brightness = this.entity?.attributes?.brightness;
    if (brightness) {
      return `${Math.round((brightness / 255) * 100)}%`;
    }
    return "On";
  }
}
customElements.define("cp-light-tile", CpLightTile);

class CpClimateTile extends CpBaseTile {
  get stateDisplay() {
    if (this.isUnavailable) return "Unavailable";
    const state = this.entity?.state;
    if (state === "off") return "Off";
    const currentTemp = this.entity?.attributes?.current_temperature;
    const targetTemp = this.entity?.attributes?.temperature;
    if (currentTemp && targetTemp) return `${currentTemp}°C → ${targetTemp}°C`;
    if (currentTemp) return `${currentTemp}°C`;
    return state;
  }
}
customElements.define("cp-climate-tile", CpClimateTile);

class CpCoverTile extends CpBaseTile {
  get stateDisplay() {
    if (this.isUnavailable) return "Unavailable";
    const state = this.entity?.state;
    const position = this.entity?.attributes?.current_position;
    if (position !== undefined) {
      if (position === 0) return "Closed";
      if (position === 100) return "Open";
      return `${position}%`;
    }
    if (state === "open") return "Open";
    if (state === "closed") return "Closed";
    if (state === "opening") return "Opening";
    if (state === "closing") return "Closing";
    return state;
  }
}
customElements.define("cp-cover-tile", CpCoverTile);

class CpFanTile extends CpBaseTile {
  static get styles() {
    return [
      super.styles,
      css`
        .tile-icon.spinning ha-icon {
          animation: spin 1s linear infinite;
        }
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `,
    ];
  }

  get stateDisplay() {
    if (this.isUnavailable) return "Unavailable";
    if (!this.isOn) return "Off";
    const percentage = this.entity?.attributes?.percentage;
    if (percentage) return `${percentage}%`;
    return "On";
  }

  render() {
    const entity = this.entity;
    if (!entity && !this.entityId) return html``;

    const color = this.tileColor;
    const colorRgb = hexToRgb(color);

    return html`
      <div
        class="tile ${this.isOn ? "on" : ""} ${this.isUnavailable ? "unavailable" : ""}"
        style="--tile-color: ${color}; --tile-color-bg: rgba(${colorRgb}, 0.2); --icon-bg: rgba(${colorRgb}, 0.1);"
        @click=${this.handleClick}
        @contextmenu=${this.handleLongPress}
      >
        <div class="tile-icon ${this.isOn ? "spinning" : ""}">
          <ha-icon icon=${this.icon}></ha-icon>
        </div>
        <div class="tile-info">
          <div class="tile-name">${entity?.attributes?.friendly_name || this.entityId}</div>
          <div class="tile-state">${this.stateDisplay}</div>
        </div>
      </div>
    `;
  }
}
customElements.define("cp-fan-tile", CpFanTile);

class CpMediaPlayerTile extends CpBaseTile {
  get stateDisplay() {
    if (this.isUnavailable) return "Unavailable";
    const state = this.entity?.state;
    const mediaTitle = this.entity?.attributes?.media_title;
    if (state === "playing" && mediaTitle) return mediaTitle;
    if (state === "playing") return "Playing";
    if (state === "paused") return "Paused";
    if (state === "idle") return "Idle";
    if (state === "off") return "Off";
    return state;
  }
}
customElements.define("cp-media-player-tile", CpMediaPlayerTile);

class CpLockTile extends CpBaseTile {
  get stateDisplay() {
    if (this.isUnavailable) return "Unavailable";
    const state = this.entity?.state;
    if (state === "locked") return "Locked";
    if (state === "unlocked") return "Unlocked";
    if (state === "locking") return "Locking";
    if (state === "unlocking") return "Unlocking";
    return state;
  }
}
customElements.define("cp-lock-tile", CpLockTile);

class CpVacuumTile extends CpBaseTile {
  get stateDisplay() {
    if (this.isUnavailable) return "Unavailable";
    const state = this.entity?.state;
    if (state === "cleaning") return "Cleaning";
    if (state === "docked") return "Docked";
    if (state === "returning") return "Returning";
    if (state === "paused") return "Paused";
    if (state === "idle") return "Idle";
    if (state === "error") return "Error";
    return state;
  }
}
customElements.define("cp-vacuum-tile", CpVacuumTile);

class CpSceneTile extends CpBaseTile {
  get stateDisplay() {
    const lastChanged = this.entity?.last_changed;
    if (!lastChanged) return "";

    const date = new Date(lastChanged);
    const now = new Date();
    const diff = now - date;

    const minutes = Math.floor(diff / 60000);
    const hours = Math.floor(diff / 3600000);
    const days = Math.floor(diff / 86400000);

    if (minutes < 1) return "Just now";
    if (minutes < 60) return `${minutes}m ago`;
    if (hours < 24) return `${hours}h ago`;
    return `${days}d ago`;
  }

  toggle() {
    if (!this.hass) return;
    this.hass.callService("scene", "turn_on", { entity_id: this.entityId });
  }
}
customElements.define("cp-scene-tile", CpSceneTile);

class CpSwitchTile extends CpBaseTile {}
customElements.define("cp-switch-tile", CpSwitchTile);

class CpSensorTile extends CpBaseTile {
  get stateDisplay() {
    if (this.isUnavailable) return "Unavailable";
    const state = this.entity?.state;
    const unit = this.entity?.attributes?.unit_of_measurement;
    return unit ? `${state} ${unit}` : state;
  }

  toggle() {
    this.openMoreInfo();
  }
}
customElements.define("cp-sensor-tile", CpSensorTile);

class CpBinarySensorTile extends CpBaseTile {
  get stateDisplay() {
    if (this.isUnavailable) return "Unavailable";
    const state = this.entity?.state;
    const deviceClass = this.entity?.attributes?.device_class;

    if (deviceClass === "door") return state === "on" ? "Open" : "Closed";
    if (deviceClass === "window") return state === "on" ? "Open" : "Closed";
    if (deviceClass === "motion") return state === "on" ? "Detected" : "Clear";
    if (deviceClass === "occupancy") return state === "on" ? "Occupied" : "Clear";

    return state === "on" ? "On" : "Off";
  }

  toggle() {
    this.openMoreInfo();
  }
}
customElements.define("cp-binary-sensor-tile", CpBinarySensorTile);

class CpButtonTile extends CpBaseTile {
  get stateDisplay() {
    return "";
  }

  toggle() {
    if (!this.hass) return;
    this.hass.callService("button", "press", { entity_id: this.entityId });
  }
}
customElements.define("cp-button-tile", CpButtonTile);

class CpScriptTile extends CpSceneTile {
  toggle() {
    if (!this.hass) return;
    this.hass.callService("script", "turn_on", { entity_id: this.entityId });
  }
}
customElements.define("cp-script-tile", CpScriptTile);

class CpAutomationTile extends CpSceneTile {
  get stateDisplay() {
    if (this.isUnavailable) return "Unavailable";
    return this.entity?.state === "on" ? "Enabled" : "Disabled";
  }
}
customElements.define("cp-automation-tile", CpAutomationTile);

class CpHumidifierTile extends CpBaseTile {
  get stateDisplay() {
    if (this.isUnavailable) return "Unavailable";
    if (!this.isOn) return "Off";
    const humidity = this.entity?.attributes?.humidity;
    if (humidity) return `${humidity}%`;
    return "On";
  }
}
customElements.define("cp-humidifier-tile", CpHumidifierTile);

// ============================================================================
// DOMAIN SECTION COMPONENT
// ============================================================================

class CpDomainSection extends LitElement {
  static get properties() {
    return {
      hass: { type: Object },
      domain: { type: String },
      entities: { type: Array },
      expanded: { type: Boolean },
    };
  }

  constructor() {
    super();
    this.expanded = true;
  }

  static get styles() {
    return css`
      :host {
        display: block;
        margin-bottom: 16px;
      }

      .section-header {
        display: flex;
        align-items: center;
        padding: 8px 4px;
        cursor: pointer;
        user-select: none;
      }

      .section-header:hover {
        background: rgba(255, 255, 255, 0.05);
        border-radius: 8px;
      }

      .section-icon {
        width: 24px;
        height: 24px;
        margin-right: 8px;
        color: var(--secondary-text-color);
      }

      .section-icon ha-icon {
        --mdc-icon-size: 20px;
      }

      .section-title {
        flex: 1;
        font-size: 14px;
        font-weight: 500;
        color: var(--primary-text-color);
      }

      .section-arrow {
        color: var(--secondary-text-color, rgba(255, 255, 255, 0.7));
        transition: transform 0.2s ease;
      }

      .section-arrow.collapsed {
        transform: rotate(-90deg);
      }

      .section-arrow ha-icon {
        --mdc-icon-size: 20px;
      }

      .tiles-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 8px;
        padding-top: 8px;
      }

      @media (min-width: 600px) {
        .tiles-grid {
          grid-template-columns: repeat(3, minmax(0, 1fr));
        }
      }

      @media (min-width: 1024px) {
        .tiles-grid {
          grid-template-columns: repeat(4, minmax(0, 1fr));
        }
      }

      .tiles-grid.collapsed {
        display: none;
      }
    `;
  }

  _getDomainLabel(domain) {
    const lang = this.hass?.language || "en";
    const t = TRANSLATIONS[lang] || TRANSLATIONS.en;
    return t[domain] || domain;
  }

  toggleExpanded() {
    this.expanded = !this.expanded;
  }

  renderTile(entityId) {
    const domain = entityId.split(".")[0];

    switch (domain) {
      case "light":
        return html`<cp-light-tile .hass=${this.hass} entity-id=${entityId}></cp-light-tile>`;
      case "climate":
        return html`<cp-climate-tile .hass=${this.hass} entity-id=${entityId}></cp-climate-tile>`;
      case "cover":
        return html`<cp-cover-tile .hass=${this.hass} entity-id=${entityId}></cp-cover-tile>`;
      case "fan":
        return html`<cp-fan-tile .hass=${this.hass} entity-id=${entityId}></cp-fan-tile>`;
      case "media_player":
        return html`<cp-media-player-tile .hass=${this.hass} entity-id=${entityId}></cp-media-player-tile>`;
      case "lock":
        return html`<cp-lock-tile .hass=${this.hass} entity-id=${entityId}></cp-lock-tile>`;
      case "vacuum":
        return html`<cp-vacuum-tile .hass=${this.hass} entity-id=${entityId}></cp-vacuum-tile>`;
      case "scene":
        return html`<cp-scene-tile .hass=${this.hass} entity-id=${entityId}></cp-scene-tile>`;
      case "script":
        return html`<cp-script-tile .hass=${this.hass} entity-id=${entityId}></cp-script-tile>`;
      case "automation":
        return html`<cp-automation-tile .hass=${this.hass} entity-id=${entityId}></cp-automation-tile>`;
      case "switch":
      case "input_boolean":
        return html`<cp-switch-tile .hass=${this.hass} entity-id=${entityId}></cp-switch-tile>`;
      case "sensor":
        return html`<cp-sensor-tile .hass=${this.hass} entity-id=${entityId}></cp-sensor-tile>`;
      case "binary_sensor":
        return html`<cp-binary-sensor-tile .hass=${this.hass} entity-id=${entityId}></cp-binary-sensor-tile>`;
      case "button":
        return html`<cp-button-tile .hass=${this.hass} entity-id=${entityId}></cp-button-tile>`;
      case "humidifier":
        return html`<cp-humidifier-tile .hass=${this.hass} entity-id=${entityId}></cp-humidifier-tile>`;
      default:
        return html`<cp-base-tile .hass=${this.hass} entity-id=${entityId}></cp-base-tile>`;
    }
  }

  render() {
    const icon = DOMAIN_ICONS[this.domain] || "mdi:help-circle";
    const label = this._getDomainLabel(this.domain);

    return html`
      <div class="section-header" @click=${this.toggleExpanded}>
        <div class="section-icon">
          <ha-icon icon=${icon}></ha-icon>
        </div>
        <div class="section-title">${label}</div>
        <div class="section-arrow ${this.expanded ? "" : "collapsed"}">
          <ha-icon icon="mdi:chevron-down"></ha-icon>
        </div>
      </div>
      <div class="tiles-grid ${this.expanded ? "" : "collapsed"}">
        ${this.entities?.map((entityId) => this.renderTile(entityId))}
      </div>
    `;
  }
}

customElements.define("cp-domain-section", CpDomainSection);

// ============================================================================
// DOMAIN TABS COMPONENT
// ============================================================================

class CpDomainTabs extends LitElement {
  static get properties() {
    return {
      hass: { type: Object },
      domains: { type: Array },
      selectedDomain: { type: String },
    };
  }

  static get styles() {
    return css`
      :host { display: block; }

      .tabs-container {
        display: flex;
        gap: 8px;
        overflow-x: auto;
        padding: 8px 0;
        scrollbar-width: none;
      }
      .tabs-container::-webkit-scrollbar { display: none; }

      .domain-tab {
        display: flex;
        align-items: center;
        gap: 6px;
        padding: 8px 16px;
        background: rgba(255, 255, 255, 0.05);
        border-radius: 20px;
        cursor: pointer;
        white-space: nowrap;
        transition: all 0.2s;
        border: none;
        color: var(--primary-text-color);
        font-size: 13px;
      }

      .domain-tab:hover {
        background: rgba(255, 255, 255, 0.1);
      }

      .domain-tab.active {
        background: var(--primary-color);
        color: var(--text-primary-color-on-primary, #fff);
      }

      .tab-icon { --mdc-icon-size: 18px; }
      .tab-count {
        font-size: 11px;
        background: rgba(0,0,0,0.2);
        padding: 2px 6px;
        border-radius: 10px;
      }
    `;
  }

  _t(key) {
    const lang = this.hass?.language || "en";
    const t = TRANSLATIONS[lang] || TRANSLATIONS.en;
    return t[key] || key;
  }

  _handleTabClick(domain) {
    this.dispatchEvent(new CustomEvent('domain-tab-selected', {
      bubbles: true, composed: true,
      detail: { domain }
    }));
  }

  _getIcon(domain) {
    if (domain === 'all') return 'mdi:view-grid';
    return DOMAIN_ICONS[domain] || 'mdi:help';
  }

  _getLabel(domain) {
    if (domain === 'all') return this._t('all');
    return this._t(domain) || domain;
  }

  render() {
    return html`
      <div class="tabs-container">
        ${this.domains?.map(d => html`
          <button class="domain-tab ${d.domain === this.selectedDomain ? 'active' : ''}"
                  @click=${() => this._handleTabClick(d.domain)}>
            <ha-icon class="tab-icon" icon=${this._getIcon(d.domain)}></ha-icon>
            <span>${this._getLabel(d.domain)}</span>
            <span class="tab-count">${d.count}</span>
          </button>
        `)}
      </div>
    `;
  }
}

customElements.define("cp-domain-tabs", CpDomainTabs);

// ============================================================================
// SEARCH BAR COMPONENT
// ============================================================================

class CpSearchBar extends LitElement {
  static get properties() {
    return {
      value: { type: String },
      placeholder: { type: String },
    };
  }

  static get styles() {
    return css`
      :host { display: block; margin-bottom: 16px; }

      .search-container {
        display: flex;
        align-items: center;
        background: var(--card-background-color, rgba(255,255,255,0.05));
        border-radius: 28px;
        padding: 0 16px;
        height: 48px;
        border: 1px solid var(--divider-color, rgba(255,255,255,0.1));
      }

      .search-container:focus-within {
        border-color: var(--primary-color);
      }

      .search-icon {
        color: var(--secondary-text-color);
        --mdc-icon-size: 20px;
        margin-right: 12px;
      }

      input {
        flex: 1;
        border: none;
        background: transparent;
        font-size: 14px;
        color: var(--primary-text-color);
        outline: none;
      }

      input::placeholder {
        color: var(--secondary-text-color);
      }

      .clear-btn {
        background: none;
        border: none;
        color: var(--secondary-text-color);
        cursor: pointer;
        padding: 4px;
        display: flex;
        --mdc-icon-size: 18px;
      }

      .clear-btn:hover {
        color: var(--primary-text-color);
      }
    `;
  }

  _handleInput(e) {
    this.dispatchEvent(new CustomEvent('search-changed', {
      bubbles: true, composed: true,
      detail: { value: e.target.value }
    }));
  }

  _handleClear() {
    this.dispatchEvent(new CustomEvent('search-changed', {
      bubbles: true, composed: true,
      detail: { value: '' }
    }));
  }

  render() {
    return html`
      <div class="search-container">
        <ha-icon class="search-icon" icon="mdi:magnify"></ha-icon>
        <input type="text"
               .value=${this.value || ''}
               placeholder=${this.placeholder || 'Search...'}
               @input=${this._handleInput}>
        ${this.value ? html`
          <button class="clear-btn" @click=${this._handleClear}>
            <ha-icon icon="mdi:close"></ha-icon>
          </button>
        ` : ''}
      </div>
    `;
  }
}

customElements.define("cp-search-bar", CpSearchBar);

// ============================================================================
// SUMMARY CARD COMPONENT
// ============================================================================

class CpSummaryCard extends LitElement {
  static get properties() {
    return {
      hass: { type: Object },
      domain: { type: String },
      entities: { type: Array },
    };
  }

  static get styles() {
    return css`
      :host {
        display: block;
      }

      .summary-card {
        background: var(--card-background-color, rgba(255, 255, 255, 0.05));
        border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
        border-radius: 12px;
        padding: 16px;
        cursor: pointer;
        transition: background 0.2s ease, transform 0.1s ease;
        display: flex;
        flex-direction: column;
        align-items: center;
        text-align: center;
        min-height: 100px;
        justify-content: center;
      }

      .summary-card:hover {
        filter: brightness(1.1);
      }

      .summary-card:active {
        transform: scale(0.98);
      }

      .summary-card.active {
        background: var(--tile-color-bg, rgba(3, 169, 244, 0.15));
      }

      .summary-icon {
        width: 48px;
        height: 48px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        background: rgba(255, 255, 255, 0.1);
        color: var(--secondary-text-color);
        margin-bottom: 12px;
      }

      .summary-card.active .summary-icon {
        background: var(--tile-color-bg, rgba(3, 169, 244, 0.3));
        color: var(--tile-color, var(--primary-color, #03a9f4));
      }

      .summary-icon ha-icon {
        --mdc-icon-size: 24px;
      }

      .summary-label {
        font-size: 14px;
        font-weight: 500;
        color: var(--primary-text-color);
        margin-bottom: 4px;
      }

      .summary-state {
        font-size: 12px;
        color: var(--secondary-text-color);
      }

      .summary-card.active .summary-state {
        color: var(--primary-text-color);
        opacity: 0.8;
      }
    `;
  }

  _t(key) {
    const lang = this.hass?.language || "en";
    const t = TRANSLATIONS[lang] || TRANSLATIONS.en;
    return t[key] || key;
  }

  get totalCount() {
    return (this.entities || []).length;
  }

  get activeCount() {
    if (!this.entities || !this.hass) return 0;
    return this.entities.filter((entityId) => {
      const state = this.hass.states[entityId]?.state;
      return ACTIVE_STATES.includes(state);
    }).length;
  }

  get isActive() {
    return this.activeCount > 0;
  }

  get stateText() {
    return `${this.totalCount} ${this._t('entities')} · ${this.activeCount} ${this._t('on')}`;
  }

  get domainLabel() {
    return this._t(this.domain) || this.domain;
  }

  _handleClick() {
    this.dispatchEvent(
      new CustomEvent("domain-selected", {
        bubbles: true,
        composed: true,
        detail: { domain: this.domain },
      })
    );
  }

  render() {
    const icon = DOMAIN_ICONS[this.domain] || "mdi:help-circle";
    const theme = getThemePrimaryColor();

    return html`
      <div
        class="summary-card ${this.isActive ? "active" : ""}"
        style="--tile-color: ${theme.hex}; --tile-color-bg: rgba(${theme.rgb}, 0.2);"
        @click=${this._handleClick}
      >
        <div class="summary-icon">
          <ha-icon icon=${icon}></ha-icon>
        </div>
        <div class="summary-label">${this.domainLabel}</div>
        <div class="summary-state">${this.stateText}</div>
      </div>
    `;
  }
}

customElements.define("cp-summary-card", CpSummaryCard);

// ============================================================================
// AREA CARD COMPONENT
// ============================================================================

class CpAreaCard extends LitElement {
  static get properties() {
    return {
      hass: { type: Object },
      area: { type: Object },
      areaEntities: { type: Object },
    };
  }

  static get styles() {
    return css`
      :host {
        display: block;
      }

      .area-card {
        background: var(--card-background-color, rgba(255, 255, 255, 0.05));
        border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
        border-radius: 12px;
        padding: 16px;
        cursor: pointer;
        transition: background 0.2s ease, transform 0.1s ease;
        text-align: center;
        display: flex;
        flex-direction: column;
        align-items: center;
      }

      .area-card:hover {
        filter: brightness(1.05);
      }

      .area-card:active {
        transform: scale(0.98);
      }

      .area-icon {
        width: 48px;
        height: 48px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        background: var(--area-icon-bg, rgba(3, 169, 244, 0.2));
        color: var(--area-icon-color, var(--primary-color, #03a9f4));
        margin-bottom: 12px;
      }

      .area-icon ha-icon {
        --mdc-icon-size: 24px;
      }

      .area-name {
        font-size: 14px;
        font-weight: 500;
        color: var(--primary-text-color, #fff);
        margin-bottom: 4px;
      }

      .area-count {
        font-size: 12px;
        color: var(--secondary-text-color, rgba(255, 255, 255, 0.7));
      }
    `;
  }

  _t(key) {
    const lang = this.hass?.language || "en";
    const t = TRANSLATIONS[lang] || TRANSLATIONS.en;
    return t[key] || key;
  }

  _getAllEntityIds() {
    if (!this.areaEntities) return [];
    const ids = [];
    for (const entityIds of Object.values(this.areaEntities)) {
      ids.push(...entityIds);
    }
    return ids;
  }

  _getActiveCount() {
    if (!this.hass) return 0;
    return this._getAllEntityIds().filter((entityId) => {
      const state = this.hass.states[entityId]?.state;
      return ACTIVE_STATES.includes(state);
    }).length;
  }

  handleClick() {
    this.dispatchEvent(
      new CustomEvent("area-selected", {
        bubbles: true,
        composed: true,
        detail: { areaId: this.area.id },
      })
    );
  }

  render() {
    const icon = this.area.icon || "mdi:home";
    const name = this.area.name || this.area.id;
    const total = this.area.entity_count || 0;
    const activeCount = this._getActiveCount();
    const theme = getThemePrimaryColor();

    return html`
      <div class="area-card" @click=${this.handleClick}
           style="--area-icon-bg: rgba(${theme.rgb}, 0.2); --area-icon-color: ${theme.hex};">
        <div class="area-icon">
          <ha-icon icon=${icon}></ha-icon>
        </div>
        <div class="area-name">${name}</div>
        <div class="area-count">${total} ${this._t('entities')} · ${activeCount} ${this._t('on')}</div>
      </div>
    `;
  }
}

customElements.define("cp-area-card", CpAreaCard);

// ============================================================================
// LABEL CARD COMPONENT
// ============================================================================

class CpLabelCard extends LitElement {
  static get properties() {
    return {
      hass: { type: Object },
      label: { type: Object },
      labelEntities: { type: Object },
    };
  }

  static get styles() {
    return css`
      :host {
        display: block;
      }

      .label-card {
        background: var(--card-background-color, rgba(255, 255, 255, 0.05));
        border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
        border-radius: 12px;
        padding: 16px;
        cursor: pointer;
        transition: background 0.2s ease, transform 0.1s ease;
        display: flex;
        flex-direction: column;
        align-items: center;
        text-align: center;
        min-height: 100px;
      }

      .label-card:hover {
        filter: brightness(1.1);
      }

      .label-card:active {
        transform: scale(0.98);
      }

      .label-icon {
        width: 48px;
        height: 48px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        background: var(--label-color-bg, rgba(33, 150, 243, 0.2));
        color: var(--label-color, #2196f3);
        margin-bottom: 12px;
      }

      .label-icon ha-icon {
        --mdc-icon-size: 24px;
      }

      .label-name {
        font-size: 14px;
        font-weight: 500;
        color: var(--primary-text-color);
        margin-bottom: 4px;
        word-break: break-word;
      }

      .label-count {
        font-size: 12px;
        color: var(--secondary-text-color);
      }
    `;
  }

  _t(key) {
    const lang = this.hass?.language || "en";
    const t = TRANSLATIONS[lang] || TRANSLATIONS.en;
    return t[key] || key;
  }

  _getAllEntityIds() {
    if (!this.labelEntities) return [];
    const ids = [];
    for (const entityIds of Object.values(this.labelEntities)) {
      ids.push(...entityIds);
    }
    return ids;
  }

  _getActiveCount() {
    if (!this.hass) return 0;
    return this._getAllEntityIds().filter((entityId) => {
      const state = this.hass.states[entityId]?.state;
      return ACTIVE_STATES.includes(state);
    }).length;
  }

  _handleClick() {
    this.dispatchEvent(
      new CustomEvent("label-selected", {
        bubbles: true,
        composed: true,
        detail: { label: this.label },
      })
    );
  }

  render() {
    const icon = this.label.icon || "mdi:label";
    const color = getLabelColor(this.label.color);
    const colorRgb = hexToRgb(color);
    const total = this.label.entity_count || 0;
    const activeCount = this._getActiveCount();

    return html`
      <div
        class="label-card"
        style="--label-color: ${color}; --label-color-bg: rgba(${colorRgb}, 0.2);"
        @click=${this._handleClick}
      >
        <div class="label-icon">
          <ha-icon icon=${icon}></ha-icon>
        </div>
        <div class="label-name">${this.label.name}</div>
        <div class="label-count">${total} ${this._t('entities')} · ${activeCount} ${this._t('on')}</div>
      </div>
    `;
  }
}

customElements.define("cp-label-card", CpLabelCard);

// ============================================================================
// MAIN PANEL COMPONENT
// ============================================================================

class HaControlPanel extends LitElement {
  static get properties() {
    return {
      hass: { type: Object },
      narrow: { type: Boolean },
      panel: { type: Object },
      // Tab state
      activeTab: { type: String },
      // View state
      _view: { type: String },
      // Areas state
      _areas: { type: Array },
      _areaEntities: { type: Object },
      _selectedAreaId: { type: String },
      _selectedAreaDomain: { type: String },
      // Labels state
      _labels: { type: Array },
      _labelEntities: { type: Object },
      _selectedLabel: { type: Object },
      _selectedLabelDomain: { type: String },
      // Summary domain view
      _selectedDomain: { type: String },
      // Loading state
      _loading: { type: Boolean },
      _loadError: { type: String },
      // Search
      _searchQuery: { type: String },
    };
  }

  constructor() {
    super();
    this.activeTab = "areas";
    this._view = "home";
    this._areas = [];
    this._areaEntities = {};
    this._selectedAreaId = null;
    this._selectedAreaDomain = null;
    this._labels = [];
    this._labelEntities = {};
    this._selectedLabel = null;
    this._selectedLabelDomain = null;
    this._selectedDomain = null;
    this._loading = true;
    this._loadError = null;
    this._searchQuery = "";
    this._areasLoading = false;
    this._labelsLoading = false;
    // Memoization cache
    this._cachedDomainCounts = null;
    this._lastHassStatesRef = null;
  }

  static get styles() {
    return css`
      :host {
        display: block;
        height: 100%;
        background: var(--primary-background-color);
      }

      .panel-container {
        height: 100%;
        display: flex;
        flex-direction: column;
      }

      /* App Header */
      .app-header {
        background-color: var(--app-header-background-color);
        color: var(--app-header-text-color, var(--text-primary-color));
        border-bottom: 1px solid var(--divider-color);
        position: sticky;
        top: 0;
        z-index: 4;
        display: flex;
        align-items: center;
        height: 56px;
        padding: 0 4px;
        box-sizing: border-box;
        flex-shrink: 0;
      }

      .toolbar-icon {
        position: relative;
        width: 48px;
        height: 48px;
        display: flex;
        align-items: center;
        justify-content: center;
        border: none;
        background: transparent;
        color: inherit;
        cursor: pointer;
        border-radius: 50%;
        --mdc-icon-size: 24px;
      }

      .toolbar-icon:hover {
        background: var(--secondary-background-color);
      }

      .toolbar-icon:active {
        background: var(--divider-color);
      }

      .header-title {
        font-size: 20px;
        font-weight: 400;
        flex: 1;
        margin-left: 4px;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }

      :host([narrow]) .menu-btn {
        display: flex;
      }

      .menu-btn {
        display: none;
      }

      @media (max-width: 870px) {
        .menu-btn {
          display: flex;
        }
      }

      /* Tab Bar */
      .tab-bar {
        display: flex;
        background: var(--app-header-background-color);
        border-bottom: 1px solid var(--divider-color);
        flex-shrink: 0;
      }

      .tab {
        flex: 1;
        padding: 12px 16px;
        text-align: center;
        cursor: pointer;
        font-size: 14px;
        font-weight: 500;
        color: var(--app-header-text-color, #fff);
        opacity: 0.7;
        border: none;
        background: transparent;
        border-bottom: 3px solid transparent;
        transition: all 0.2s ease;
      }

      .tab:hover {
        opacity: 0.85;
        background: rgba(255, 255, 255, 0.05);
      }

      .tab.active {
        color: var(--app-header-text-color, #fff);
        opacity: 1;
        border-bottom: 3px solid var(--app-header-text-color, #fff);
      }

      .tab-content {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 8px;
      }

      .tab ha-icon {
        --mdc-icon-size: 20px;
      }

      /* Content */
      .content {
        flex: 1;
        overflow-y: auto;
        padding: 16px;
      }

      /* Section styling */
      .section {
        margin-bottom: 24px;
      }

      .section-label {
        font-size: 12px;
        font-weight: 500;
        color: var(--secondary-text-color);
        text-transform: uppercase;
        letter-spacing: 0.5px;
        margin-bottom: 12px;
      }

      /* Summary grid */
      .summary-grid {
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 8px;
      }

      @media (max-width: 599px) {
        .summary-grid {
          grid-template-columns: repeat(3, 1fr);
        }
      }

      /* Areas/Labels grid */
      .items-grid {
        display: grid;
        grid-template-columns: repeat(2, 1fr);
        gap: 8px;
      }

      @media (min-width: 600px) {
        .items-grid {
          grid-template-columns: repeat(3, 1fr);
        }
      }

      @media (min-width: 1024px) {
        .items-grid {
          grid-template-columns: repeat(4, 1fr);
        }
      }

      /* Loading */
      .loading {
        display: flex;
        align-items: center;
        justify-content: center;
        flex-direction: column;
        gap: 16px;
        height: 200px;
        color: var(--secondary-text-color);
      }

      .empty {
        display: flex;
        align-items: center;
        justify-content: center;
        height: 100px;
        color: var(--secondary-text-color);
        font-size: 14px;
      }

      /* Error State */
      .error-container {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        height: 200px;
        color: var(--error-color, #f44336);
        text-align: center;
        padding: 16px;
      }

      .error-icon {
        margin-bottom: 12px;
        --mdc-icon-size: 48px;
      }

      .error-message {
        font-size: 14px;
        margin-bottom: 16px;
      }

      .retry-button {
        background: var(--primary-color);
        color: var(--text-primary-color);
        border: none;
        border-radius: 8px;
        padding: 8px 24px;
        font-size: 14px;
        cursor: pointer;
        transition: opacity 0.2s;
      }

      .retry-button:hover {
        opacity: 0.9;
      }
    `;
  }

  _t(key) {
    const lang = this.hass?.language || "en";
    const t = TRANSLATIONS[lang] || TRANSLATIONS.en;
    return t[key] || key;
  }

  connectedCallback() {
    super.connectedCallback();
  }

  updated(changedProperties) {
    super.updated(changedProperties);
    if (changedProperties.has("hass") && this.hass) {
      if (this._areas.length === 0 && !this._areasLoading) {
        this._areasLoading = true;
        this._loadAreas();
      }
      if (this._labels.length === 0 && !this._labelsLoading) {
        this._labelsLoading = true;
        this._loadLabels();
      }
    }
  }

  async _loadAreas() {
    if (!this.hass) {
      this._areasLoading = false;
      return;
    }
    try {
      const result = await this.hass.callWS({
        type: "area_control/get_permitted_areas",
      });

      if (!result || !Array.isArray(result.areas)) {
        throw new Error("Invalid response format from server");
      }

      this._areas = result.areas;

      // Load all area entities in parallel
      const loadPromises = this._areas.map((area) =>
        this._loadAreaEntitiesQuiet(area.id)
      );
      await Promise.all(loadPromises);

      this.requestUpdate();
    } catch (err) {
      console.error("Failed to load areas:", err);
      this._loadError = err.message || "Failed to load areas";
      this._areas = [];
    }
    this._areasLoading = false;
    this._updateLoadingState();
  }

  async _loadLabels() {
    if (!this.hass) {
      this._labelsLoading = false;
      return;
    }
    try {
      const result = await this.hass.callWS({
        type: "label_control/get_permitted_labels",
      });

      if (!result || !Array.isArray(result.labels)) {
        throw new Error("Invalid response format from server");
      }

      this._labels = result.labels;

      // Load all label entities in parallel
      const loadPromises = this._labels.map((label) =>
        this._loadLabelEntitiesQuiet(label.id)
      );
      await Promise.all(loadPromises);

      this.requestUpdate();
    } catch (err) {
      console.error("Failed to load labels:", err);
      if (!this._loadError) {
        this._loadError = err.message || "Failed to load labels";
      }
      this._labels = [];
    }
    this._labelsLoading = false;
    this._updateLoadingState();
  }

  _updateLoadingState() {
    this._loading = this._areasLoading || this._labelsLoading;
  }

  async _loadAreaEntitiesQuiet(areaId) {
    if (this._areaEntities[areaId]) return;
    try {
      const result = await this.hass.callWS({
        type: "area_control/get_area_entities",
        area_id: areaId,
      });
      this._areaEntities = {
        ...this._areaEntities,
        [areaId]: result.entities || {},
      };
    } catch (err) {
      console.error("Failed to load area entities:", err);
    }
  }

  async _loadLabelEntitiesQuiet(labelId) {
    if (this._labelEntities[labelId]) return;
    try {
      const result = await this.hass.callWS({
        type: "label_control/get_label_entities",
        label_id: labelId,
      });
      this._labelEntities = {
        ...this._labelEntities,
        [labelId]: result.entities || {},
      };
    } catch (err) {
      console.error("Failed to load label entities:", err);
    }
  }

  async _loadAreaEntities(areaId) {
    if (this._areaEntities[areaId]) return;
    try {
      const result = await this.hass.callWS({
        type: "area_control/get_area_entities",
        area_id: areaId,
      });
      this._areaEntities = {
        ...this._areaEntities,
        [areaId]: result.entities || {},
      };
      this.requestUpdate();
    } catch (err) {
      console.error("Failed to load area entities:", err);
    }
  }

  async _loadLabelEntities(labelId) {
    if (this._labelEntities[labelId]) return;
    try {
      const result = await this.hass.callWS({
        type: "label_control/get_label_entities",
        label_id: labelId,
      });
      this._labelEntities = {
        ...this._labelEntities,
        [labelId]: result.entities || {},
      };
      this.requestUpdate();
    } catch (err) {
      console.error("Failed to load label entities:", err);
    }
  }

  _getAllEntitiesByDomain() {
    // Memoization
    if (this._cachedDomainCounts && this._lastHassStatesRef === this.hass?.states) {
      return this._cachedDomainCounts;
    }
    this._lastHassStatesRef = this.hass?.states;

    const domainEntities = {};
    const entitiesSource = this.activeTab === "areas" ? this._areaEntities : this._labelEntities;

    for (const id of Object.keys(entitiesSource)) {
      const entities = entitiesSource[id];
      for (const [domain, entityIds] of Object.entries(entities)) {
        if (!domainEntities[domain]) {
          domainEntities[domain] = new Set();
        }
        entityIds.forEach((entityId) => domainEntities[domain].add(entityId));
      }
    }

    const result = {};
    for (const [domain, entitySet] of Object.entries(domainEntities)) {
      result[domain] = Array.from(entitySet);
    }
    this._cachedDomainCounts = result;
    return result;
  }

  _filterEntities(entities, query) {
    if (!query) return entities;
    const q = query.toLowerCase();
    return entities.filter(entityId => {
      const entity = this.hass?.states?.[entityId];
      const name = entity?.attributes?.friendly_name || entityId;
      return name.toLowerCase().includes(q) || entityId.toLowerCase().includes(q);
    });
  }

  _handleRetry() {
    this._areasLoading = false;
    this._labelsLoading = false;
    this._areas = [];
    this._labels = [];
    this._areaEntities = {};
    this._labelEntities = {};
    this._loadError = null;
    this._loading = true;
    this._areasLoading = true;
    this._labelsLoading = true;
    this._loadAreas();
    this._loadLabels();
  }

  _handleTabChange(tab) {
    this.activeTab = tab;
    this._view = "home";
    this._selectedAreaId = null;
    this._selectedAreaDomain = null;
    this._selectedLabel = null;
    this._selectedLabelDomain = null;
    this._selectedDomain = null;
    this._searchQuery = "";
    // Clear memoization cache when switching tabs
    this._cachedDomainCounts = null;
  }

  _handleAreaSelected(e) {
    const areaId = e.detail.areaId;
    this._selectedAreaId = areaId;
    this._view = "area";
    this._searchQuery = "";
    this._selectedAreaDomain = null;
    this._loadAreaEntities(areaId);
  }

  _handleLabelSelected(e) {
    const label = e.detail.label;
    this._selectedLabel = label;
    this._view = "label";
    this._searchQuery = "";
    this._selectedLabelDomain = null;
    this._loadLabelEntities(label.id);
  }

  _handleDomainSelected(e) {
    const domain = e.detail.domain;
    this._selectedDomain = domain;
    this._view = "domain";
  }

  _handleBack() {
    this._view = "home";
    this._selectedAreaId = null;
    this._selectedAreaDomain = null;
    this._selectedLabel = null;
    this._selectedLabelDomain = null;
    this._selectedDomain = null;
    this._searchQuery = "";
  }

  _handleDomainTabSelected(e) {
    if (this.activeTab === "areas") {
      this._selectedAreaDomain = e.detail.domain;
    } else {
      this._selectedLabelDomain = e.detail.domain;
    }
  }

  _handleSearchChanged(e) {
    this._searchQuery = e.detail.value;
  }

  _toggleSidebar() {
    this.dispatchEvent(
      new CustomEvent("hass-toggle-menu", {
        bubbles: true,
        composed: true,
      })
    );
  }

  _getSelectedArea() {
    return this._areas.find((a) => a.id === this._selectedAreaId);
  }

  render() {
    return html`
      <div class="panel-container">
        ${this._renderHeader()}
        ${this._view === "home" ? this._renderTabBar() : ""}
        <div class="content">
          ${this._loading
            ? html`<div class="loading">${this._t("loading")}</div>`
            : this._loadError
              ? this._renderError()
              : this._renderView()}
        </div>
      </div>
    `;
  }

  _renderHeader() {
    let title = this._t("title");
    let showBack = false;

    if (this._view === "area") {
      const area = this._getSelectedArea();
      title = area?.name || "Area";
      showBack = true;
    } else if (this._view === "label" && this._selectedLabel) {
      title = this._selectedLabel.name;
      showBack = true;
    } else if (this._view === "domain" && this._selectedDomain) {
      title = this._t(this._selectedDomain) || this._selectedDomain;
      showBack = true;
    }

    return html`
      <div class="app-header">
        ${showBack
          ? html`
              <button class="toolbar-icon" @click=${this._handleBack}>
                <ha-icon icon="mdi:arrow-left"></ha-icon>
              </button>
            `
          : html`
              <button class="toolbar-icon menu-btn" @click=${this._toggleSidebar}>
                <ha-icon icon="mdi:menu"></ha-icon>
              </button>
            `}
        <div class="header-title">${title}</div>
      </div>
    `;
  }

  _renderTabBar() {
    return html`
      <div class="tab-bar">
        <button
          class="tab ${this.activeTab === "areas" ? "active" : ""}"
          @click=${() => this._handleTabChange("areas")}
        >
          <div class="tab-content">
            <ha-icon icon="mdi:floor-plan"></ha-icon>
            <span>${this._t("areasTab")}</span>
          </div>
        </button>
        <button
          class="tab ${this.activeTab === "labels" ? "active" : ""}"
          @click=${() => this._handleTabChange("labels")}
        >
          <div class="tab-content">
            <ha-icon icon="mdi:label"></ha-icon>
            <span>${this._t("labelsTab")}</span>
          </div>
        </button>
      </div>
    `;
  }

  _renderError() {
    return html`
      <div class="error-container">
        <ha-icon class="error-icon" icon="mdi:alert-circle"></ha-icon>
        <div class="error-message">${this._loadError}</div>
        <button class="retry-button" @click=${this._handleRetry}>
          ${this._t("retry")}
        </button>
      </div>
    `;
  }

  _renderView() {
    switch (this._view) {
      case "home":
        return this.activeTab === "areas" ? this._renderAreasHome() : this._renderLabelsHome();
      case "area":
        return this._renderAreaView();
      case "label":
        return this._renderLabelView();
      case "domain":
        return this._renderDomainView();
      default:
        return this._renderAreasHome();
    }
  }

  _renderAreasHome() {
    const allEntitiesByDomain = this._getAllEntitiesByDomain();

    return html`
      <!-- Summary Section -->
      <div class="section">
        <div class="section-label">${this._t("summary")}</div>
        <div class="summary-grid">
          ${SUMMARY_DOMAINS.map(
            (domain) => html`
              <cp-summary-card
                .hass=${this.hass}
                .domain=${domain}
                .entities=${allEntitiesByDomain[domain] || []}
                @domain-selected=${this._handleDomainSelected}
              ></cp-summary-card>
            `
          )}
        </div>
      </div>

      <!-- Areas Section -->
      <div class="section">
        <div class="section-label">${this._t("areas")}</div>
        ${this._areas.length === 0
          ? html`<div class="empty">${this._t("noAreas")}</div>`
          : html`
              <div class="items-grid">
                ${this._areas.map(
                  (area) => html`
                    <cp-area-card
                      .hass=${this.hass}
                      .area=${area}
                      .areaEntities=${this._areaEntities[area.id] || {}}
                      @area-selected=${this._handleAreaSelected}
                    ></cp-area-card>
                  `
                )}
              </div>
            `}
      </div>
    `;
  }

  _renderLabelsHome() {
    const allEntitiesByDomain = this._getAllEntitiesByDomain();

    return html`
      <!-- Summary Section -->
      <div class="section">
        <div class="section-label">${this._t("summary")}</div>
        <div class="summary-grid">
          ${SUMMARY_DOMAINS.map(
            (domain) => html`
              <cp-summary-card
                .hass=${this.hass}
                .domain=${domain}
                .entities=${allEntitiesByDomain[domain] || []}
                @domain-selected=${this._handleDomainSelected}
              ></cp-summary-card>
            `
          )}
        </div>
      </div>

      <!-- Labels Section -->
      <div class="section">
        <div class="section-label">${this._t("labels")}</div>
        ${this._labels.length === 0
          ? html`<div class="empty">${this._t("noLabels")}</div>`
          : html`
              <div class="items-grid">
                ${this._labels.map(
                  (label) => html`
                    <cp-label-card
                      .hass=${this.hass}
                      .label=${label}
                      .labelEntities=${this._labelEntities[label.id] || {}}
                      @label-selected=${this._handleLabelSelected}
                    ></cp-label-card>
                  `
                )}
              </div>
            `}
      </div>
    `;
  }

  _renderAreaView() {
    const entities = this._areaEntities[this._selectedAreaId] || {};

    // Sort domains by entity count
    const domains = Object.keys(entities).sort((a, b) => {
      const countA = entities[a]?.length || 0;
      const countB = entities[b]?.length || 0;
      return countB - countA;
    });

    // Build domain data with counts (filtered if search is active)
    const domainData = domains.map(d => {
      const filtered = this._filterEntities(entities[d] || [], this._searchQuery);
      return {
        domain: d,
        entities: filtered,
        count: filtered.length
      };
    }).filter(d => d.count > 0 || !this._searchQuery);

    // Calculate total entities for "All" tab
    const allEntities = [];
    for (const d of domainData) {
      allEntities.push(...d.entities);
    }

    // Add "all" as first entry
    const domainDataWithAll = [
      { domain: 'all', entities: allEntities, count: allEntities.length },
      ...domainData
    ];

    // Use selected domain or default to "all"
    const selectedDomain = this._selectedAreaDomain && domainDataWithAll.find(d => d.domain === this._selectedAreaDomain)
      ? this._selectedAreaDomain
      : 'all';

    // Render grouped view for "all", single domain view for specific domain
    if (selectedDomain === 'all') {
      return html`
        <cp-search-bar
          .value=${this._searchQuery}
          placeholder=${this._t("searchPlaceholder")}
          @search-changed=${this._handleSearchChanged}
        ></cp-search-bar>
        <cp-domain-tabs
          .hass=${this.hass}
          .domains=${domainDataWithAll}
          .selectedDomain=${selectedDomain}
          @domain-tab-selected=${this._handleDomainTabSelected}
        ></cp-domain-tabs>
        ${domainData.length === 0
          ? html`<div class="empty">${this._t("noEntities")}</div>`
          : domainData.map(d => html`
              <cp-domain-section
                .hass=${this.hass}
                .domain=${d.domain}
                .entities=${d.entities}
              ></cp-domain-section>
            `)}
      `;
    }

    // Single domain view
    const selectedEntities = this._filterEntities(entities[selectedDomain] || [], this._searchQuery);

    return html`
      <cp-search-bar
        .value=${this._searchQuery}
        placeholder=${this._t("searchPlaceholder")}
        @search-changed=${this._handleSearchChanged}
      ></cp-search-bar>
      <cp-domain-tabs
        .hass=${this.hass}
        .domains=${domainDataWithAll}
        .selectedDomain=${selectedDomain}
        @domain-tab-selected=${this._handleDomainTabSelected}
      ></cp-domain-tabs>
      ${selectedEntities.length === 0
        ? html`<div class="empty">${this._t("noEntities")}</div>`
        : html`
            <cp-domain-section
              .hass=${this.hass}
              .domain=${selectedDomain}
              .entities=${selectedEntities}
            ></cp-domain-section>
          `}
    `;
  }

  _renderLabelView() {
    const entities = this._labelEntities[this._selectedLabel?.id] || {};

    // Sort domains by DOMAIN_ORDER
    const domains = Object.keys(entities).sort((a, b) => {
      const indexA = DOMAIN_ORDER.indexOf(a);
      const indexB = DOMAIN_ORDER.indexOf(b);
      if (indexA === -1 && indexB === -1) return a.localeCompare(b);
      if (indexA === -1) return 1;
      if (indexB === -1) return -1;
      return indexA - indexB;
    });

    // Build domain data with counts (filtered if search is active)
    const domainData = domains.map(d => {
      const filtered = this._filterEntities(entities[d] || [], this._searchQuery);
      return {
        domain: d,
        entities: filtered,
        count: filtered.length
      };
    }).filter(d => d.count > 0 || !this._searchQuery);

    // Calculate total entities for "All" tab
    const allEntities = [];
    for (const d of domainData) {
      allEntities.push(...d.entities);
    }

    // Add "all" as first entry
    const domainDataWithAll = [
      { domain: 'all', entities: allEntities, count: allEntities.length },
      ...domainData
    ];

    // Use selected domain or default to "all"
    const selectedDomain = this._selectedLabelDomain && domainDataWithAll.find(d => d.domain === this._selectedLabelDomain)
      ? this._selectedLabelDomain
      : 'all';

    // Check if original entities object is empty
    const hasNoEntities = Object.keys(entities).length === 0;
    if (hasNoEntities) {
      return html`<div class="empty">${this._t("noEntities")}</div>`;
    }

    // Render grouped view for "all", single domain view for specific domain
    if (selectedDomain === 'all') {
      return html`
        <cp-search-bar
          .value=${this._searchQuery}
          placeholder=${this._t("searchPlaceholder")}
          @search-changed=${this._handleSearchChanged}
        ></cp-search-bar>
        <cp-domain-tabs
          .hass=${this.hass}
          .domains=${domainDataWithAll}
          .selectedDomain=${selectedDomain}
          @domain-tab-selected=${this._handleDomainTabSelected}
        ></cp-domain-tabs>
        ${domainData.length === 0
          ? html`<div class="empty">${this._t("noEntities")}</div>`
          : domainData.map(d => html`
              <cp-domain-section
                .hass=${this.hass}
                .domain=${d.domain}
                .entities=${d.entities}
              ></cp-domain-section>
            `)}
      `;
    }

    // Single domain view
    const selectedEntities = this._filterEntities(entities[selectedDomain] || [], this._searchQuery);

    return html`
      <cp-search-bar
        .value=${this._searchQuery}
        placeholder=${this._t("searchPlaceholder")}
        @search-changed=${this._handleSearchChanged}
      ></cp-search-bar>
      <cp-domain-tabs
        .hass=${this.hass}
        .domains=${domainDataWithAll}
        .selectedDomain=${selectedDomain}
        @domain-tab-selected=${this._handleDomainTabSelected}
      ></cp-domain-tabs>
      ${selectedEntities.length === 0
        ? html`<div class="empty">${this._t("noEntities")}</div>`
        : html`
            <cp-domain-section
              .hass=${this.hass}
              .domain=${selectedDomain}
              .entities=${selectedEntities}
            ></cp-domain-section>
          `}
    `;
  }

  _renderDomainView() {
    // Collect all entities of selected domain across all areas or labels
    const allEntities = [];
    const entitiesSource = this.activeTab === "areas" ? this._areaEntities : this._labelEntities;

    for (const id of Object.keys(entitiesSource)) {
      const entities = entitiesSource[id];
      if (entities[this._selectedDomain]) {
        allEntities.push(...entities[this._selectedDomain]);
      }
    }

    // Remove duplicates
    const uniqueEntities = [...new Set(allEntities)];

    if (uniqueEntities.length === 0) {
      return html`<div class="empty">${this._t("noEntities")}</div>`;
    }

    return html`
      <cp-domain-section
        .hass=${this.hass}
        .domain=${this._selectedDomain}
        .entities=${uniqueEntities}
      ></cp-domain-section>
    `;
  }
}

customElements.define("ha-control-panel", HaControlPanel);
