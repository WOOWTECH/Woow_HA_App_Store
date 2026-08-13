// Home Assistant Native Style - Area Control Panel
// Matches HA Home Dashboard design with tall tiles and embedded controls

// Local Lit bundle (no CDN dependency for offline/intranet environments)
const { LitElement, html, css } = await import(
  "/ha_area_control/lit.js"
);

// ============================================================================
// I18N TRANSLATIONS
// ============================================================================

const TRANSLATIONS = {
  en: {
    title: "Area Control",
    summary: "Summary",
    areas: "Areas",
    loading: "Loading...",
    retry: "Retry",
    on: "on",
    off: "Off",
    unavailable: "Unavailable",
    opened: "Open",
    closed: "Closed",
    opening: "Opening",
    closing: "Closing",
    locked: "Locked",
    unlocked: "Unlocked",
    locking: "Locking",
    unlocking: "Unlocking",
    playing: "Playing",
    paused: "Paused",
    idle: "Idle",
    cleaning: "Cleaning",
    docked: "Charging",
    returning: "Returning",
    error: "Error",
    enabled: "Enabled",
    disabled: "Disabled",
    detected: "Detected",
    clear: "Clear",
    occupied: "Occupied",
    notOccupied: "Not occupied",
    justNow: "Just now",
    minutesAgo: "min ago",
    hoursAgo: "hr ago",
    daysAgo: "days ago",
    searchPlaceholder: "Search devices...",
    all: "All",
    back: "Back",
    openSidebar: "Open sidebar",
    entities: "entities",
  },
  "zh-Hant": {
    title: "分區控制",
    summary: "摘要",
    areas: "分區",
    loading: "載入中...",
    retry: "重試",
    on: "開啟",
    off: "關閉",
    unavailable: "無法使用",
    opened: "開啟",
    closed: "關閉",
    opening: "正在開啟",
    closing: "正在關閉",
    locked: "已鎖定",
    unlocked: "已解鎖",
    locking: "鎖定中",
    unlocking: "解鎖中",
    playing: "播放中",
    paused: "暫停",
    idle: "閒置",
    cleaning: "清掃中",
    docked: "充電中",
    returning: "返回中",
    error: "錯誤",
    enabled: "啟用",
    disabled: "停用",
    detected: "偵測到",
    clear: "無動作",
    occupied: "有人",
    notOccupied: "無人",
    justNow: "剛剛",
    minutesAgo: "分鐘前",
    hoursAgo: "小時前",
    daysAgo: "天前",
    searchPlaceholder: "搜尋裝置...",
    all: "全部",
    back: "返回",
    openSidebar: "開啟側邊欄",
    entities: "個實體",
  },
  "zh-Hans": {
    title: "分区控制",
    summary: "摘要",
    areas: "分区",
    loading: "加载中...",
    retry: "重试",
    on: "开启",
    off: "关闭",
    unavailable: "无法使用",
    opened: "开启",
    closed: "关闭",
    opening: "正在开启",
    closing: "正在关闭",
    locked: "已锁定",
    unlocked: "已解锁",
    locking: "锁定中",
    unlocking: "解锁中",
    playing: "播放中",
    paused: "暂停",
    idle: "闲置",
    cleaning: "清扫中",
    docked: "充电中",
    returning: "返回中",
    error: "错误",
    enabled: "启用",
    disabled: "停用",
    detected: "检测到",
    clear: "无动作",
    occupied: "有人",
    notOccupied: "无人",
    justNow: "刚刚",
    minutesAgo: "分钟前",
    hoursAgo: "小时前",
    daysAgo: "天前",
    searchPlaceholder: "搜索设备...",
    all: "全部",
    back: "返回",
    openSidebar: "打开侧边栏",
    entities: "个实体",
  },
};

const DOMAIN_NAMES = {
  en: {
    light: "Lights", switch: "Switches", climate: "Climate", cover: "Covers",
    fan: "Fans", media_player: "Media", vacuum: "Vacuums", lock: "Locks",
    humidifier: "Humidifiers", automation: "Automations", script: "Scripts",
    scene: "Scenes", button: "Buttons", sensor: "Sensors",
    binary_sensor: "Binary Sensors", input_boolean: "Input Boolean",
    person: "Persons",
  },
  "zh-Hant": {
    light: "燈光", switch: "開關", climate: "溫控", cover: "窗簾",
    fan: "風扇", media_player: "媒體播放器", vacuum: "掃地機", lock: "門鎖",
    humidifier: "加濕器", automation: "自動化", script: "腳本",
    scene: "場景", button: "按鈕", sensor: "感測器",
    binary_sensor: "二元感測器", input_boolean: "輔助開關",
    person: "人員",
  },
  "zh-Hans": {
    light: "灯光", switch: "开关", climate: "温控", cover: "窗帘",
    fan: "风扇", media_player: "媒体播放器", vacuum: "扫地机", lock: "门锁",
    humidifier: "加湿器", automation: "自动化", script: "脚本",
    scene: "场景", button: "按钮", sensor: "传感器",
    binary_sensor: "二元传感器", input_boolean: "辅助开关",
    person: "人员",
  },
};

/**
 * Get the best language key for TRANSLATIONS/DOMAIN_NAMES lookup.
 * Falls back: zh-Hant -> zh-Hant, zh-TW -> zh-Hant, zh-CN -> zh-Hans, zh -> zh-Hant, * -> en
 */
function _getLangKey(hass) {
  const lang = hass?.language || "en";
  if (TRANSLATIONS[lang]) return lang;
  if (lang.startsWith("zh")) {
    if (lang === "zh-Hans" || lang === "zh-CN") return "zh-Hans";
    return "zh-Hant"; // zh-TW, zh, etc.
  }
  return "en";
}

/** Translation helper usable from any context with hass */
function _t(hass, key) {
  const langKey = _getLangKey(hass);
  return TRANSLATIONS[langKey][key] || TRANSLATIONS["en"][key] || key;
}

/** Domain name helper */
function _domainName(hass, domain) {
  const langKey = _getLangKey(hass);
  return (DOMAIN_NAMES[langKey] && DOMAIN_NAMES[langKey][domain]) || DOMAIN_NAMES["en"][domain] || domain;
}

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
 * Falls back to HA default blue (#03a9f4) if unavailable.
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
      // Handle rgb() format
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
};

// DOMAIN_LABELS removed — use _domainName(hass, domain) for i18n lookups

// Domains that show in summary section
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

// ============================================================================
// BASE TILE COMPONENT
// ============================================================================

class BaseTile extends LitElement {
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
    if (this.isUnavailable) return _t(this.hass, "unavailable");
    const state = this.entity?.state;
    if (state === "on") return _t(this.hass, "on");
    if (state === "off") return _t(this.hass, "off");
    if (state === "unavailable") return _t(this.hass, "unavailable");
    return state;
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

    // Climate: use blue for cooling, orange for heating (functional safety colors)
    if (domain === "climate" && this.isOn) {
      const hvacAction = this.entity?.attributes?.hvac_action;
      if (hvacAction === "cooling") return FUNCTIONAL_COLORS.climate_cool;
      if (hvacAction === "heating") return FUNCTIONAL_COLORS.climate_heat;
    }

    // Lock: use green for locked, red for unlocked (functional safety colors)
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

    // Store bound handlers as instance properties for proper cleanup
    this._boundHandleTouchStart = this._handleTouchStart.bind(this);
    this._boundHandleTouchEnd = this._handleTouchEnd.bind(this);

    this.addEventListener("touchstart", this._boundHandleTouchStart);
    this.addEventListener("touchend", this._boundHandleTouchEnd);
    this.addEventListener("touchcancel", this._boundHandleTouchEnd);
  }

  disconnectedCallback() {
    super.disconnectedCallback();

    // Clean up event listeners to prevent memory leaks
    if (this._boundHandleTouchStart) {
      this.removeEventListener("touchstart", this._boundHandleTouchStart);
    }
    if (this._boundHandleTouchEnd) {
      this.removeEventListener("touchend", this._boundHandleTouchEnd);
      this.removeEventListener("touchcancel", this._boundHandleTouchEnd);
    }

    // Clear any pending timer
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
    const colorRgb = this._hexToRgb(color);

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

  _hexToRgb(hex) {
    if (hex.startsWith("rgb")) {
      // Already rgb format
      const match = hex.match(/\d+/g);
      return match ? match.slice(0, 3).join(", ") : "255, 255, 255";
    }
    const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
    return result
      ? `${parseInt(result[1], 16)}, ${parseInt(result[2], 16)}, ${parseInt(result[3], 16)}`
      : "255, 255, 255";
  }
}

customElements.define("base-tile", BaseTile);

// ============================================================================
// LIGHT TILE - compact with brightness percentage
// ============================================================================

class LightTile extends BaseTile {
  get stateDisplay() {
    if (this.isUnavailable) return _t(this.hass, "unavailable");
    if (!this.isOn) return _t(this.hass, "off");
    const brightness = this.entity?.attributes?.brightness;
    if (brightness) {
      return `${Math.round((brightness / 255) * 100)}%`;
    }
    return _t(this.hass, "on");
  }
}

customElements.define("light-tile", LightTile);

// ============================================================================
// CLIMATE TILE - compact with temperature display
// ============================================================================

class ClimateTile extends BaseTile {
  get stateDisplay() {
    if (this.isUnavailable) return _t(this.hass, "unavailable");
    const state = this.entity?.state;
    if (state === "off") return _t(this.hass, "off");
    const currentTemp = this.entity?.attributes?.current_temperature;
    const targetTemp = this.entity?.attributes?.temperature;
    if (currentTemp && targetTemp) return `${currentTemp}°C → ${targetTemp}°C`;
    if (currentTemp) return `${currentTemp}°C`;
    return state;
  }
}

customElements.define("climate-tile", ClimateTile);

// ============================================================================
// COVER TILE - compact with position display
// ============================================================================

class CoverTile extends BaseTile {
  get stateDisplay() {
    if (this.isUnavailable) return _t(this.hass, "unavailable");
    const state = this.entity?.state;
    const position = this.entity?.attributes?.current_position;
    if (position !== undefined) {
      if (position === 0) return _t(this.hass, "closed");
      if (position === 100) return _t(this.hass, "opened");
      return `${position}%`;
    }
    if (state === "open") return _t(this.hass, "opened");
    if (state === "closed") return _t(this.hass, "closed");
    if (state === "opening") return _t(this.hass, "opening");
    if (state === "closing") return _t(this.hass, "closing");
    return state;
  }
}

customElements.define("cover-tile", CoverTile);

// ============================================================================
// FAN TILE - compact with spinning icon
// ============================================================================

class FanTile extends BaseTile {
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
    if (this.isUnavailable) return _t(this.hass, "unavailable");
    if (!this.isOn) return _t(this.hass, "off");
    const percentage = this.entity?.attributes?.percentage;
    if (percentage) return `${percentage}%`;
    return _t(this.hass, "on");
  }

  render() {
    const entity = this.entity;
    if (!entity && !this.entityId) return html``;

    const color = this.tileColor;
    const colorRgb = this._hexToRgb(color);

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

customElements.define("fan-tile", FanTile);

// ============================================================================
// MEDIA PLAYER TILE - compact with status display
// ============================================================================

class MediaPlayerTile extends BaseTile {
  get stateDisplay() {
    if (this.isUnavailable) return _t(this.hass, "unavailable");
    const state = this.entity?.state;
    const mediaTitle = this.entity?.attributes?.media_title;
    if (state === "playing" && mediaTitle) return mediaTitle;
    if (state === "playing") return _t(this.hass, "playing");
    if (state === "paused") return _t(this.hass, "paused");
    if (state === "idle") return _t(this.hass, "idle");
    if (state === "off") return _t(this.hass, "off");
    return state;
  }
}

customElements.define("media-player-tile", MediaPlayerTile);

// ============================================================================
// LOCK TILE - compact with status display
// ============================================================================

class LockTile extends BaseTile {
  get stateDisplay() {
    if (this.isUnavailable) return _t(this.hass, "unavailable");
    const state = this.entity?.state;
    if (state === "locked") return _t(this.hass, "locked");
    if (state === "unlocked") return _t(this.hass, "unlocked");
    if (state === "locking") return _t(this.hass, "locking");
    if (state === "unlocking") return _t(this.hass, "unlocking");
    return state;
  }
}

customElements.define("lock-tile", LockTile);

// ============================================================================
// VACUUM TILE - compact with status display
// ============================================================================

class VacuumTile extends BaseTile {
  get stateDisplay() {
    if (this.isUnavailable) return _t(this.hass, "unavailable");
    const state = this.entity?.state;
    if (state === "cleaning") return _t(this.hass, "cleaning");
    if (state === "docked") return _t(this.hass, "docked");
    if (state === "returning") return _t(this.hass, "returning");
    if (state === "paused") return _t(this.hass, "paused");
    if (state === "idle") return _t(this.hass, "idle");
    if (state === "error") return _t(this.hass, "error");
    return state;
  }
}

customElements.define("vacuum-tile", VacuumTile);

// ============================================================================
// SCENE TILE - compact with last triggered time
// ============================================================================

class SceneTile extends BaseTile {
  get stateDisplay() {
    const lastChanged = this.entity?.last_changed;
    if (!lastChanged) return "";

    const date = new Date(lastChanged);
    const now = new Date();
    const diff = now - date;

    const minutes = Math.floor(diff / 60000);
    const hours = Math.floor(diff / 3600000);
    const days = Math.floor(diff / 86400000);

    if (minutes < 1) return _t(this.hass, "justNow");
    if (minutes < 60) return `${minutes} ${_t(this.hass, "minutesAgo")}`;
    if (hours < 24) return `${hours} ${_t(this.hass, "hoursAgo")}`;
    return `${days} ${_t(this.hass, "daysAgo")}`;
  }

  toggle() {
    if (!this.hass) return;
    this.hass.callService("scene", "turn_on", { entity_id: this.entityId });
  }
}

customElements.define("scene-tile", SceneTile);

// ============================================================================
// SWITCH TILE - simple toggle
// ============================================================================

class SwitchTile extends BaseTile {
  // Uses base implementation - no extra controls needed
}

customElements.define("switch-tile", SwitchTile);

// ============================================================================
// SENSOR TILE - compact with value display
// ============================================================================

class SensorTile extends BaseTile {
  get stateDisplay() {
    if (this.isUnavailable) return _t(this.hass, "unavailable");
    const state = this.entity?.state;
    const unit = this.entity?.attributes?.unit_of_measurement;
    return unit ? `${state} ${unit}` : state;
  }

  toggle() {
    // Sensors don't toggle, open more-info instead
    this.openMoreInfo();
  }
}

customElements.define("sensor-tile", SensorTile);

// ============================================================================
// BINARY SENSOR TILE - display only
// ============================================================================

class BinarySensorTile extends BaseTile {
  get stateDisplay() {
    if (this.isUnavailable) return _t(this.hass, "unavailable");
    const state = this.entity?.state;
    const deviceClass = this.entity?.attributes?.device_class;

    if (deviceClass === "door") return state === "on" ? _t(this.hass, "opened") : _t(this.hass, "closed");
    if (deviceClass === "window") return state === "on" ? _t(this.hass, "opened") : _t(this.hass, "closed");
    if (deviceClass === "motion") return state === "on" ? _t(this.hass, "detected") : _t(this.hass, "clear");
    if (deviceClass === "occupancy") return state === "on" ? _t(this.hass, "occupied") : _t(this.hass, "notOccupied");

    return state === "on" ? _t(this.hass, "on") : _t(this.hass, "off");
  }

  toggle() {
    this.openMoreInfo();
  }
}

customElements.define("binary-sensor-tile", BinarySensorTile);

// ============================================================================
// BUTTON TILE - press action
// ============================================================================

class ButtonTile extends BaseTile {
  get stateDisplay() {
    return "";  // Buttons don't have meaningful state
  }

  toggle() {
    if (!this.hass) return;
    this.hass.callService("button", "press", { entity_id: this.entityId });
  }
}

customElements.define("button-tile", ButtonTile);

// ============================================================================
// SCRIPT TILE - with last triggered
// ============================================================================

class ScriptTile extends SceneTile {
  toggle() {
    if (!this.hass) return;
    this.hass.callService("script", "turn_on", { entity_id: this.entityId });
  }
}

customElements.define("script-tile", ScriptTile);

// ============================================================================
// AUTOMATION TILE
// ============================================================================

class AutomationTile extends SceneTile {
  get stateDisplay() {
    if (this.isUnavailable) return _t(this.hass, "unavailable");
    return this.entity?.state === "on" ? _t(this.hass, "enabled") : _t(this.hass, "disabled");
  }
}

customElements.define("automation-tile", AutomationTile);

// ============================================================================
// HUMIDIFIER TILE - compact with humidity display
// ============================================================================

class HumidifierTile extends BaseTile {
  get stateDisplay() {
    if (this.isUnavailable) return _t(this.hass, "unavailable");
    if (!this.isOn) return _t(this.hass, "off");
    const humidity = this.entity?.attributes?.humidity;
    if (humidity) return `${humidity}%`;
    return _t(this.hass, "on");
  }
}

customElements.define("humidifier-tile", HumidifierTile);

// ============================================================================
// TILE FACTORY
// ============================================================================

function createTileElement(entityId) {
  const domain = entityId.split(".")[0];

  const tileMap = {
    light: "light-tile",
    climate: "climate-tile",
    cover: "cover-tile",
    fan: "fan-tile",
    media_player: "media-player-tile",
    lock: "lock-tile",
    vacuum: "vacuum-tile",
    scene: "scene-tile",
    script: "script-tile",
    automation: "automation-tile",
    switch: "switch-tile",
    input_boolean: "switch-tile",
    sensor: "sensor-tile",
    binary_sensor: "binary-sensor-tile",
    button: "button-tile",
    humidifier: "humidifier-tile",
  };

  const tagName = tileMap[domain] || "base-tile";
  return tagName;
}

// ============================================================================
// DOMAIN SECTION COMPONENT
// ============================================================================

class DomainSection extends LitElement {
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

  toggleExpanded() {
    this.expanded = !this.expanded;
  }

  render() {
    const icon = DOMAIN_ICONS[this.domain] || "mdi:help-circle";
    const label = _domainName(this.hass, this.domain);

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

  renderTile(entityId) {
    const domain = entityId.split(".")[0];

    switch (domain) {
      case "light":
        return html`<light-tile .hass=${this.hass} entity-id=${entityId}></light-tile>`;
      case "climate":
        return html`<climate-tile .hass=${this.hass} entity-id=${entityId}></climate-tile>`;
      case "cover":
        return html`<cover-tile .hass=${this.hass} entity-id=${entityId}></cover-tile>`;
      case "fan":
        return html`<fan-tile .hass=${this.hass} entity-id=${entityId}></fan-tile>`;
      case "media_player":
        return html`<media-player-tile .hass=${this.hass} entity-id=${entityId}></media-player-tile>`;
      case "lock":
        return html`<lock-tile .hass=${this.hass} entity-id=${entityId}></lock-tile>`;
      case "vacuum":
        return html`<vacuum-tile .hass=${this.hass} entity-id=${entityId}></vacuum-tile>`;
      case "scene":
        return html`<scene-tile .hass=${this.hass} entity-id=${entityId}></scene-tile>`;
      case "script":
        return html`<script-tile .hass=${this.hass} entity-id=${entityId}></script-tile>`;
      case "automation":
        return html`<automation-tile .hass=${this.hass} entity-id=${entityId}></automation-tile>`;
      case "switch":
      case "input_boolean":
        return html`<switch-tile .hass=${this.hass} entity-id=${entityId}></switch-tile>`;
      case "sensor":
        return html`<sensor-tile .hass=${this.hass} entity-id=${entityId}></sensor-tile>`;
      case "binary_sensor":
        return html`<binary-sensor-tile .hass=${this.hass} entity-id=${entityId}></binary-sensor-tile>`;
      case "button":
        return html`<button-tile .hass=${this.hass} entity-id=${entityId}></button-tile>`;
      case "humidifier":
        return html`<humidifier-tile .hass=${this.hass} entity-id=${entityId}></humidifier-tile>`;
      default:
        return html`<base-tile .hass=${this.hass} entity-id=${entityId}></base-tile>`;
    }
  }
}

customElements.define("ac-domain-section", DomainSection);

// ============================================================================
// DOMAIN TABS COMPONENT - Horizontal scrollable domain selector
// ============================================================================

class DomainTabs extends LitElement {
  static get properties() {
    return {
      hass: { type: Object },
      domains: { type: Array },        // [{domain, entities, count}]
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
    if (domain === 'all') return _t(this.hass, "all");
    return _domainName(this.hass, domain);
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

customElements.define("domain-tabs", DomainTabs);

// ============================================================================
// SEARCH BAR COMPONENT
// ============================================================================

class SearchBar extends LitElement {
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

customElements.define("search-bar", SearchBar);

// ============================================================================
// DOMAIN SUMMARY COMPONENT
// ============================================================================

class DomainSummary extends LitElement {
  static get properties() {
    return {
      hass: { type: Object },
      domain: { type: String },
      count: { type: Number },
      entities: { type: Array },
    };
  }

  static get styles() {
    return css`
      :host {
        display: block;
      }

      .summary-tile {
        background: var(--card-background-color, rgba(255, 255, 255, 0.05));
        border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
        border-radius: 12px;
        padding: 16px;
        cursor: pointer;
        transition: background 0.2s ease;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 8px;
      }

      .summary-tile:hover {
        background: rgba(255, 255, 255, 0.08);
      }

      .summary-tile.active {
        background: var(--tile-color-bg, rgba(3, 169, 244, 0.2));
      }

      .summary-icon {
        width: 48px;
        height: 48px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        background: rgba(255, 255, 255, 0.1);
        color: var(--secondary-text-color, rgba(255, 255, 255, 0.7));
      }

      .summary-tile.active .summary-icon {
        background: var(--tile-color-bg, rgba(3, 169, 244, 0.3));
        color: var(--tile-color, var(--primary-color, #03a9f4));
      }

      .summary-icon ha-icon {
        --mdc-icon-size: 24px;
      }

      .summary-label {
        font-size: 14px;
        font-weight: 500;
        color: var(--primary-text-color, #fff);
        text-align: center;
      }

      .summary-state {
        font-size: 12px;
        color: var(--secondary-text-color, rgba(255, 255, 255, 0.7));
      }
    `;
  }

  get _totalCount() {
    return this.entities ? this.entities.length : 0;
  }

  get _activeCount() {
    if (!this.entities || !this.hass) return this.count || 0;
    const ON_STATES = ["on", "playing", "open", "unlocked", "heat", "cool", "heat_cool", "auto", "cleaning", "returning", "home"];
    return this.entities.filter(entityId => {
      const state = this.hass.states?.[entityId];
      return state && ON_STATES.includes(state.state);
    }).length;
  }

  get isActive() {
    return this._activeCount > 0;
  }

  handleClick() {
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
    const label = _domainName(this.hass, this.domain);
    const theme = getThemePrimaryColor();
    const totalCount = this._totalCount;
    const activeCount = this._activeCount;

    return html`
      <div
        class="summary-tile ${this.isActive ? "active" : ""}"
        style="--tile-color: ${theme.hex}; --tile-color-bg: rgba(${theme.rgb}, 0.2);"
        @click=${this.handleClick}
      >
        <div class="summary-icon">
          <ha-icon icon=${icon}></ha-icon>
        </div>
        <div class="summary-label">${label}</div>
        <div class="summary-state">${totalCount} ${_t(this.hass, "entities")} · ${activeCount} ${_t(this.hass, "on")}</div>
      </div>
    `;
  }
}

customElements.define("domain-summary", DomainSummary);

// ============================================================================
// AREA CARD COMPONENT
// ============================================================================

class AreaCard extends LitElement {
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
        text-align: center;
        display: flex;
        flex-direction: column;
        align-items: center;
        cursor: pointer;
        transition: background 0.2s ease, transform 0.1s ease;
      }

      .area-card:hover {
        background: rgba(255, 255, 255, 0.08);
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

  handleClick() {
    this.dispatchEvent(
      new CustomEvent("area-selected", {
        bubbles: true,
        composed: true,
        detail: { areaId: this.area.id },
      })
    );
  }

  get _activeCount() {
    if (!this.areaEntities || !this.hass) return 0;
    const ON_STATES = ["on", "playing", "open", "unlocked", "heat", "cool", "heat_cool", "auto", "cleaning", "returning", "home"];
    let count = 0;
    for (const entityIds of Object.values(this.areaEntities)) {
      for (const entityId of entityIds) {
        const state = this.hass.states?.[entityId];
        if (state && ON_STATES.includes(state.state)) {
          count++;
        }
      }
    }
    return count;
  }

  render() {
    const icon = this.area.icon || "mdi:home";
    const name = this.area.name || this.area.id;
    const count = this.area.entity_count || 0;
    const activeCount = this._activeCount;
    const theme = getThemePrimaryColor();

    return html`
      <div class="area-card" @click=${this.handleClick}
           style="--area-icon-bg: rgba(${theme.rgb}, 0.2); --area-icon-color: ${theme.hex};">
        <div class="area-icon">
          <ha-icon icon=${icon}></ha-icon>
        </div>
        <div class="area-name">${name}</div>
        <div class="area-count">${count} ${_t(this.hass, "entities")} · ${activeCount} ${_t(this.hass, "on")}</div>
      </div>
    `;
  }
}

customElements.define("area-card", AreaCard);

// ============================================================================
// MAIN PANEL COMPONENT
// ============================================================================

class HaAreaControlPanel extends LitElement {
  static get properties() {
    return {
      hass: { type: Object },
      narrow: { type: Boolean },
      panel: { type: Object },
      // Internal state
      _view: { type: String },
      _selectedAreaId: { type: String },
      _selectedDomain: { type: String },
      _selectedAreaDomain: { type: String },  // Domain selected within area view
      _areas: { type: Array },
      _areaEntities: { type: Object },
      _loading: { type: Boolean },
      _loadError: { type: String },
      _searchQuery: { type: String },
    };
  }

  constructor() {
    super();
    this._view = "home";
    this._selectedAreaId = null;
    this._selectedDomain = null;
    this._selectedAreaDomain = null;  // Domain selected within area view
    this._areas = [];
    this._areaEntities = {};
    this._loading = true;
    this._areasLoading = false;
    this._loadError = null;
    this._searchQuery = "";
    // Memoization cache for domain counts
    this._cachedDomainCounts = null;
    this._lastHassStatesRef = null;
    this._lastAreaEntitiesRef = null;
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

      /* App Header - matches HA native style */
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

      /* Hide menu button when sidebar is docked */
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

      /* Content */
      .content {
        flex: 1;
        overflow-y: auto;
        padding: 16px;
      }

      /* Home View */
      .summary-section {
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

      .areas-grid {
        display: grid;
        grid-template-columns: repeat(2, 1fr);
        gap: 8px;
      }

      @media (min-width: 600px) {
        .areas-grid {
          grid-template-columns: repeat(3, 1fr);
        }
      }

      @media (min-width: 1024px) {
        .areas-grid {
          grid-template-columns: repeat(4, 1fr);
        }
      }

      /* Domain Section Header - for area view */
      .domain-section-header {
        display: flex;
        align-items: center;
        padding: 12px 4px;
        margin-top: 8px;
        cursor: pointer;
        user-select: none;
      }

      .domain-section-header:hover {
        background: rgba(255, 255, 255, 0.05);
        border-radius: 8px;
      }

      .domain-section-header .section-icon {
        --mdc-icon-size: 20px;
        margin-right: 8px;
        color: var(--primary-text-color, #fff);
      }

      .domain-section-header .section-label {
        flex: 1;
        font-size: 14px;
        font-weight: 500;
        color: var(--primary-text-color, #fff);
      }

      .domain-section-header .section-arrow {
        --mdc-icon-size: 20px;
        color: var(--secondary-text-color, rgba(255, 255, 255, 0.7));
        transition: transform 0.2s ease;
      }

      .domain-section-header .section-arrow.collapsed {
        transform: rotate(-90deg);
      }

      /* Tiles Grid - for area view with domain tabs */
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

      /* Loading */
      .loading {
        display: flex;
        align-items: center;
        justify-content: center;
        height: 200px;
        color: var(--secondary-text-color);
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

  connectedCallback() {
    super.connectedCallback();
    // Don't load here - hass may not be available yet
    // Use updated() to detect when hass is set
  }

  updated(changedProperties) {
    super.updated(changedProperties);
    // Load areas when hass becomes available
    // FIX: Set loading flag BEFORE async call to prevent race condition
    if (changedProperties.has("hass") && this.hass && this._areas.length === 0 && !this._areasLoading) {
      this._areasLoading = true;  // Set flag immediately to prevent duplicate calls
      this._loadAreas();
    }
  }

  async _loadAreas() {
    if (!this.hass) {
      this._areasLoading = false;
      return;
    }
    this._loading = true;
    this._loadError = null;
    try {
      const result = await this.hass.callWS({
        type: "area_control/get_permitted_areas",
      });

      // Validate response format
      if (!result || !Array.isArray(result.areas)) {
        throw new Error("Invalid response format from server");
      }

      this._areas = result.areas;

      // Load all area entities in parallel for better performance
      const loadPromises = this._areas.map((area) =>
        this._loadAreaEntitiesQuiet(area.id)
      );
      await Promise.all(loadPromises);

      // Single requestUpdate after all data is loaded
      this.requestUpdate();
    } catch (err) {
      console.error("Failed to load areas:", err);
      this._loadError = err.message || "Failed to load areas";
      this._areas = [];
    }
    this._loading = false;
    this._areasLoading = false;
  }

  // Silent version - doesn't trigger requestUpdate (for batch loading)
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

  _getDomainCounts() {
    // Memoization: return cached value if neither hass.states nor _areaEntities changed
    if (
      this._cachedDomainCounts &&
      this._lastHassStatesRef === this.hass?.states &&
      this._lastAreaEntitiesRef === this._areaEntities
    ) {
      return this._cachedDomainCounts;
    }
    this._lastHassStatesRef = this.hass?.states;
    this._lastAreaEntitiesRef = this._areaEntities;

    const counts = {};
    const ON_STATES = ["on", "playing", "open", "unlocked", "heat", "cool", "heat_cool", "auto", "cleaning", "returning", "home"];

    for (const domain of SUMMARY_DOMAINS) {
      counts[domain] = 0;
    }

    // Count entities in active states across all areas
    for (const areaId of Object.keys(this._areaEntities)) {
      const entities = this._areaEntities[areaId];
      for (const [domain, entityIds] of Object.entries(entities)) {
        if (!SUMMARY_DOMAINS.includes(domain)) continue;

        for (const entityId of entityIds) {
          const state = this.hass?.states?.[entityId];
          if (state && ON_STATES.includes(state.state)) {
            counts[domain] = (counts[domain] || 0) + 1;
          }
        }
      }
    }

    this._cachedDomainCounts = counts;
    return counts;
  }

  _handleRetry() {
    this._areasLoading = false;
    this._areas = [];
    this._areaEntities = {};
    this._loadError = null;
    this._areasLoading = true;
    this._loadAreas();
  }

  _handleAreaSelected(e) {
    const areaId = e.detail.areaId;
    this._selectedAreaId = areaId;
    this._view = "area";
    this._loadAreaEntities(areaId);
  }

  _handleDomainSelected(e) {
    const domain = e.detail.domain;
    this._selectedDomain = domain;
    this._view = "domain";
  }

  _handleBack() {
    this._view = "home";
    this._selectedAreaId = null;
    this._selectedDomain = null;
    this._selectedAreaDomain = null;
    this._searchQuery = "";
  }

  _handleAreaDomainTabSelected(e) {
    this._selectedAreaDomain = e.detail.domain;
  }

  _handleSearchChanged(e) {
    this._searchQuery = e.detail.value;
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

  _getSelectedArea() {
    return this._areas.find((a) => a.id === this._selectedAreaId);
  }

  render() {
    return html`
      <div class="panel-container">
        ${this._renderHeader()}
        <div class="content">
          ${this._loading
            ? html`<div class="loading">${_t(this.hass, "loading")}</div>`
            : this._loadError
              ? this._renderError()
              : this._renderView()}
        </div>
      </div>
    `;
  }

  _renderError() {
    return html`
      <div class="error-container">
        <ha-icon class="error-icon" icon="mdi:alert-circle"></ha-icon>
        <div class="error-message">${this._loadError}</div>
        <button class="retry-button" @click=${this._handleRetry}>
          ${_t(this.hass, "retry")}
        </button>
      </div>
    `;
  }

  _toggleSidebar() {
    this.dispatchEvent(
      new CustomEvent("hass-toggle-menu", {
        bubbles: true,
        composed: true,
      })
    );
  }

  _renderHeader() {
    let title = _t(this.hass, "title");
    let showBack = false;

    if (this._view === "area") {
      const area = this._getSelectedArea();
      title = area?.name || "Area";
      showBack = true;
    } else if (this._view === "domain") {
      title = _domainName(this.hass, this._selectedDomain);
      showBack = true;
    }

    return html`
      <div class="app-header">
        ${showBack
          ? html`
              <button class="toolbar-icon" @click=${this._handleBack} title=${_t(this.hass, "back")}>
                <ha-icon icon="mdi:arrow-left"></ha-icon>
              </button>
            `
          : html`
              <button class="toolbar-icon menu-btn" @click=${this._toggleSidebar} title=${_t(this.hass, "openSidebar")}>
                <ha-icon icon="mdi:menu"></ha-icon>
              </button>
            `}
        <div class="header-title">${title}</div>
      </div>
    `;
  }

  _renderView() {
    switch (this._view) {
      case "home":
        return this._renderHomeView();
      case "area":
        return this._renderAreaView();
      case "domain":
        return this._renderDomainView();
      default:
        return this._renderHomeView();
    }
  }

  _getDomainEntities() {
    const domainEntities = {};
    for (const domain of SUMMARY_DOMAINS) {
      domainEntities[domain] = [];
    }
    for (const areaId of Object.keys(this._areaEntities)) {
      const entities = this._areaEntities[areaId];
      for (const [domain, entityIds] of Object.entries(entities)) {
        if (!SUMMARY_DOMAINS.includes(domain)) continue;
        if (!domainEntities[domain]) domainEntities[domain] = [];
        domainEntities[domain].push(...entityIds);
      }
    }
    return domainEntities;
  }

  _renderHomeView() {
    // Area entities are now loaded in parallel during _loadAreas()
    const counts = this._getDomainCounts();
    const domainEntities = this._getDomainEntities();
    const activeDomains = SUMMARY_DOMAINS.filter((d) => counts[d] > 0 || true);

    return html`
      <div class="summary-section">
        <div class="section-label">${_t(this.hass, "summary")}</div>
        <div class="summary-grid">
          ${activeDomains.map(
            (domain) => html`
              <domain-summary
                .hass=${this.hass}
                .domain=${domain}
                .count=${counts[domain] || 0}
                .entities=${domainEntities[domain] || []}
                @domain-selected=${this._handleDomainSelected}
              ></domain-summary>
            `
          )}
        </div>
      </div>

      <div class="areas-section">
        <div class="section-label">${_t(this.hass, "areas")}</div>
        <div class="areas-grid">
          ${this._areas.map(
            (area) => html`
              <area-card
                .hass=${this.hass}
                .area=${area}
                .areaEntities=${this._areaEntities[area.id] || {}}
                @area-selected=${this._handleAreaSelected}
              ></area-card>
            `
          )}
        </div>
      </div>
    `;
  }

  _renderAreaView() {
    const entities = this._areaEntities[this._selectedAreaId] || {};

    // Sort domains by entity count (descending) - most entities first
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
    }).filter(d => d.count > 0 || !this._searchQuery);  // Hide empty domains when searching

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
        <search-bar
          .value=${this._searchQuery}
          placeholder=${_t(this.hass, "searchPlaceholder")}
          @search-changed=${this._handleSearchChanged}
        ></search-bar>
        <domain-tabs
          .hass=${this.hass}
          .domains=${domainDataWithAll}
          .selectedDomain=${selectedDomain}
          @domain-tab-selected=${this._handleAreaDomainTabSelected}
        ></domain-tabs>
        ${domainData.map(d => html`
          <ac-domain-section
            .hass=${this.hass}
            .domain=${d.domain}
            .entities=${d.entities}
          ></ac-domain-section>
        `)}
      `;
    }

    // Single domain view
    const selectedEntities = this._filterEntities(entities[selectedDomain] || [], this._searchQuery);
    const sectionIcon = DOMAIN_ICONS[selectedDomain] || 'mdi:help-circle';
    const sectionLabel = _domainName(this.hass, selectedDomain);

    return html`
      <search-bar
        .value=${this._searchQuery}
        placeholder=${_t(this.hass, "searchPlaceholder")}
        @search-changed=${this._handleSearchChanged}
      ></search-bar>
      <domain-tabs
        .hass=${this.hass}
        .domains=${domainDataWithAll}
        .selectedDomain=${selectedDomain}
        @domain-tab-selected=${this._handleAreaDomainTabSelected}
      ></domain-tabs>
      <div class="domain-section-header" @click=${this._toggleDomainExpanded}>
        <ha-icon class="section-icon" icon=${sectionIcon}></ha-icon>
        <span class="section-label">${sectionLabel}</span>
        <ha-icon class="section-arrow" icon="mdi:chevron-down"></ha-icon>
      </div>
      <div class="tiles-grid">
        ${selectedEntities.map(entityId => {
          const domain = entityId.split('.')[0];
          return this._renderTileByDomain(entityId, domain);
        })}
      </div>
    `;
  }

  _toggleDomainExpanded() {
    // Placeholder for future expand/collapse functionality
  }

  _renderTileByDomain(entityId, domain) {
    switch (domain) {
      case "light":
        return html`<light-tile .hass=${this.hass} entity-id=${entityId}></light-tile>`;
      case "climate":
        return html`<climate-tile .hass=${this.hass} entity-id=${entityId}></climate-tile>`;
      case "cover":
        return html`<cover-tile .hass=${this.hass} entity-id=${entityId}></cover-tile>`;
      case "fan":
        return html`<fan-tile .hass=${this.hass} entity-id=${entityId}></fan-tile>`;
      case "media_player":
        return html`<media-player-tile .hass=${this.hass} entity-id=${entityId}></media-player-tile>`;
      case "lock":
        return html`<lock-tile .hass=${this.hass} entity-id=${entityId}></lock-tile>`;
      case "vacuum":
        return html`<vacuum-tile .hass=${this.hass} entity-id=${entityId}></vacuum-tile>`;
      case "scene":
        return html`<scene-tile .hass=${this.hass} entity-id=${entityId}></scene-tile>`;
      case "script":
        return html`<script-tile .hass=${this.hass} entity-id=${entityId}></script-tile>`;
      case "automation":
        return html`<automation-tile .hass=${this.hass} entity-id=${entityId}></automation-tile>`;
      case "switch":
      case "input_boolean":
        return html`<switch-tile .hass=${this.hass} entity-id=${entityId}></switch-tile>`;
      case "sensor":
        return html`<sensor-tile .hass=${this.hass} entity-id=${entityId}></sensor-tile>`;
      case "binary_sensor":
        return html`<binary-sensor-tile .hass=${this.hass} entity-id=${entityId}></binary-sensor-tile>`;
      case "button":
        return html`<button-tile .hass=${this.hass} entity-id=${entityId}></button-tile>`;
      case "humidifier":
        return html`<humidifier-tile .hass=${this.hass} entity-id=${entityId}></humidifier-tile>`;
      default:
        return html`<base-tile .hass=${this.hass} entity-id=${entityId}></base-tile>`;
    }
  }

  _renderDomainView() {
    // Collect all entities of selected domain across all areas
    const allEntities = [];
    for (const areaId of Object.keys(this._areaEntities)) {
      const entities = this._areaEntities[areaId];
      if (entities[this._selectedDomain]) {
        allEntities.push(...entities[this._selectedDomain]);
      }
    }

    return html`
      <ac-domain-section
        .hass=${this.hass}
        .domain=${this._selectedDomain}
        .entities=${allEntities}
      ></ac-domain-section>
    `;
  }
}

customElements.define("ha-area-control-panel", HaAreaControlPanel);
