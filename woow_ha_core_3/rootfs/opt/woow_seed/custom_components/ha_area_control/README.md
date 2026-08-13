<p align="center">
  <img src="https://brands.home-assistant.io/_/homeassistant/icon.png" alt="Area Control" width="80"/>
</p>

<h1 align="center">Home Assistant Area Control</h1>

<p align="center">
  <strong>Browse and control entities organized by Home Assistant areas with domain summaries</strong>
</p>

<p align="center">
  <a href="#features">Features</a> &bull;
  <a href="#screenshots">Screenshots</a> &bull;
  <a href="#supported-domains">Domains</a> &bull;
  <a href="#installation">Installation</a> &bull;
  <a href="#websocket-api">API</a> &bull;
  <a href="README_CN.md">简体中文</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/HACS-Custom-41BDF5.svg?logo=homeassistant" alt="HACS Custom"/>
  <img src="https://img.shields.io/badge/Home%20Assistant-2024.1.0%2B-41BDF5.svg?logo=homeassistant" alt="HA 2024.1+"/>
  <img src="https://img.shields.io/badge/version-1.0.3-blue.svg" alt="Version 1.0.3"/>
  <img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="MIT License"/>
  <img src="https://img.shields.io/badge/Lit-3.1.0-purple" alt="Lit 3.1.0"/>
</p>

> **Part of the [HA Permission & Control Suite](../)** — works standalone or with [Permission Manager](../ha_permission_manager/) for per-user area filtering.

---

## Overview

A Home Assistant custom component that provides a sidebar panel for controlling entities organized by areas. Features an intuitive three-view architecture with domain summary cards, area navigation, and interactive entity tiles supporting 16 device domains.

---

## Features

- **Area-based Entity Control** — View and control entities grouped by their assigned areas
- **Permission-aware** — Integrates with Permission Manager to show only permitted areas (standalone mode supported)
- **Multi-language Support** — English, Traditional Chinese (zh-Hant), and Simplified Chinese (zh-Hans)
- **Native HA Style UI** — Clean, responsive interface matching Home Assistant's modern design
- **Domain Summary Dashboard** — 3x3 grid showing 9 domain categories (Lights, Climate, Covers, Fans, Media, Locks, Vacuums, Switches, Input Boolean)
- **Domain Detail View** — Click domain summary cards to see all entities of that domain across all areas
- **Area Detail View** — Click area cards to see all entities in that area, organized by domain
- **Compact Domain Tabs** — Horizontal scrollable tabs showing domain icons and entity counts
- **Search Functionality** — Real-time filtering of entities by name or entity ID
- **Interactive Entity Tiles** — Domain-specific controls (see [Supported Domains](#supported-domains))
- **Real-time Updates** — Entity states update in real-time via `hass.states` subscription
- **Optimized Performance** — Parallel data loading for fast initial render
- **Self-contained Lit 3.1.0** — Bundled ESM module (15.9KB), no CDN dependency
- **Memoization Cache** — Dual-reference tracking for hass.states and areaEntities collections
- **Event-driven Sync** — Subscribes to `permission_manager_updated` events when Permission Manager is available (no polling)
- **Conditional Handler Registration** — Skips standalone WebSocket handler when `ha_permission_manager` is loaded to avoid collision

---

## Screenshots

### Home View — Domain Summary + Area Cards

<p align="center">
  <img src="https://raw.githubusercontent.com/WOOWTECH/Woow_ha_permission_control/main/screenshots/area-control-panel.png" alt="Area Control Panel" width="720"/>
</p>

### Chinese Interface

<p align="center">
  <img src="https://raw.githubusercontent.com/WOOWTECH/Woow_ha_permission_control/main/screenshots/area-control-zh.png" alt="Area Control - Chinese" width="720"/>
</p>

### Three-View Architecture

1. **Home View** — Domain summary section (3x3 grid) + Area cards grid with entity counts
2. **Domain View** — Click a domain summary card to see all entities of that domain across all areas
3. **Area View** — Click an area card to see all entities in that area, organized by domain with compact tabs

---

## Supported Domains

The panel provides specialized tile controls for **16 domains**:

| Domain | Features |
|--------|----------|
| `light` | Toggle, brightness slider, RGB color support |
| `climate` | Toggle, temperature +/- buttons, current temp display |
| `cover` | Open/Stop/Close buttons, position display |
| `fan` | Toggle, speed slider |
| `media_player` | Previous/Play-Pause/Next buttons |
| `lock` | Lock/Unlock buttons |
| `vacuum` | Start/Pause/Return buttons |
| `switch` | Toggle |
| `input_boolean` | Toggle |
| `scene` | Activate, last triggered time |
| `script` | Activate, last triggered time |
| `automation` | Toggle enable/disable |
| `sensor` | Display value with unit, 24h history sparkline chart |
| `binary_sensor` | Display state |
| `button` | Press action |
| `humidifier` | Toggle, humidity slider |

---

## Requirements

- Home Assistant **2024.1.0** or newer
- [Permission Manager](../ha_permission_manager/) integration (optional — works standalone)

---

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click the three dots → **Custom repositories**
3. Add `https://github.com/WOOWTECH/Woow_ha_permission_control` as **Integration**
4. Search for "Area Control" and install
5. Restart Home Assistant

### Manual Installation

1. Download the latest release from the [releases page](https://github.com/WOOWTECH/Woow_ha_permission_control/releases)
2. Copy the contents to `custom_components/ha_area_control/` in your HA config directory
3. Restart Home Assistant

### From Consolidated Repository

```bash
git clone https://github.com/WOOWTECH/Woow_ha_permission_control.git
mkdir -p /config/custom_components/ha_area_control
cp Woow_ha_permission_control/ha_area_control/*.py \
   Woow_ha_permission_control/ha_area_control/*.json \
   /config/custom_components/ha_area_control/
cp -r Woow_ha_permission_control/ha_area_control/frontend \
   Woow_ha_permission_control/ha_area_control/translations \
   /config/custom_components/ha_area_control/
```

---

## Configuration

1. Go to **Settings** > **Devices & Services**
2. Click **+ Add Integration**
3. Search for "Area Control"
4. Click to add it

After installation, a new **Area Control** panel will appear in your sidebar.

---

## How It Works

### For Admin Users
Admin users see all areas defined in Home Assistant with full access.

### For Non-Admin Users
When Permission Manager is installed, non-admin users see only the areas they have been granted access to:

| Level | Value | Description |
|-------|-------|-------------|
| **Closed** | 0 | Area hidden from user |
| **View** | 1 | Area visible, entities accessible |

### Standalone Mode
Without Permission Manager installed, all users see all areas (no filtering).

---

## WebSocket API

The integration exposes two WebSocket commands:

| Command | Description |
|---------|-------------|
| `area_control/get_permitted_areas` | Returns areas the current user can access |
| `area_control/get_area_entities` | Returns entities grouped by domain for a specific area |

> **Note:** When `ha_permission_manager` is loaded, Area Control skips registering its own WebSocket handlers to avoid collision — it uses the Permission Manager's handlers instead.

---

## Architecture

```mermaid
graph TD
    AC["ha_area_control\nv1.0.3"] --> PM["ha_permission_manager\noptional dependency"]
    AC --> HA["Home Assistant Core"]
    AC --> FE["Frontend"]

    FE --> LIT["lit.js\nLit 3.1.0 — 15.9KB"]
    FE --> PANEL["ha-area-control-panel.js\n62.7KB"]

    PANEL --> HV["Home View\nDomain Summary + Area Grid"]
    PANEL --> DV["Domain View\nCross-area Domain Entities"]
    PANEL --> AV["Area View\nDomain Tabs + Entity Tiles"]

    style AC fill:#388e3c,color:#fff
    style PM fill:#1976d2,color:#fff
```

### File Structure

```
ha_area_control/
├── __init__.py           # Integration setup, conditional handler registration
├── manifest.json         # Component manifest (v1.0.3)
├── config_flow.py        # Configuration flow
├── const.py              # Constants (DOMAIN, PANEL_VERSION, PANEL_URL)
├── panel.py              # WebSocket API handlers + panel registration
├── strings.json          # Default strings
├── frontend/
│   ├── lit.js            # Lit 3.1.0 ESM bundle (self-contained)
│   └── ha-area-control-panel.js  # Full frontend panel (62.7KB)
├── translations/
│   ├── en.json           # English
│   ├── zh-Hant.json      # Traditional Chinese
│   └── zh-Hans.json      # Simplified Chinese
├── docs/
│   └── plans/
│       ├── 2026-01-28-area-control-home-dashboard-redesign.md
│       └── 2026-01-28-area-control-implementation-plan.md
├── hacs.json             # HACS configuration
├── LICENSE               # MIT License
├── README.md             # English documentation (this file)
└── README_CN.md          # Simplified Chinese documentation
```

---

## Changelog

### v1.0.3 (2026-04)

- **Fix (P0):** Conditional `_has_permission_manager()` check — skips standalone WebSocket handler registration when Permission Manager is loaded, preventing handler collision
- **Enhancement:** Bundled Lit 3.1.0 locally (15.9KB ESM) — no CDN dependency
- **Enhancement:** Unified `isOn` / `TOGGLEABLE_DOMAINS` logic (covers `climate`, `humidifier`)
- **Enhancement:** Replaced polling with event-driven `subscribeEvents("permission_manager_updated")`
- **Enhancement:** i18n support with `TRANSLATIONS` object (`en`, `zh-Hant`, `zh-Hans`) and `_t()`, `_domainName()`, `_getLangKey()` helpers
- **Enhancement:** Memoization cache with dual-reference tracking for `hass.states` and `areaEntities`
- **Enhancement:** Synchronized `PANEL_VERSION` with `manifest.json`

### v1.0.2

- Added compact horizontal domain tabs replacing collapsible sections
- Added search bar for filtering entities by name or ID
- Added 24h history sparkline charts on sensor tiles
- Fixed card width consistency with uniform sizing

### v1.0.1
- Performance optimization: parallel loading for area entities
- Reduced UI jitter on initial load

### v1.0.0
- Native HA style UI redesign
- Domain summary dashboard with 3x3 grid
- Interactive entity tiles with embedded controls

---

## Related Packages

| Package | Description | Link |
|---------|-------------|------|
| **ha_permission_manager** | Core permission management | [View](../ha_permission_manager/) |
| **ha_label_control** | Label-based entity control panel | [View](../ha_label_control/) |
| **Suite Root** | Full docs, screenshots & architecture | [View](../) |

---

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

---

<p align="center">
  <sub>Built by <a href="https://github.com/WOOWTECH">WOOWTECH</a> &bull; Powered by Home Assistant</sub>
</p>
