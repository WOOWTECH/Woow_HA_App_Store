# Home Assistant 標籤控制面板

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/v/release/WOOWTECH/Woow_ha_permission_control)](https://github.com/WOOWTECH/Woow_ha_permission_control/releases)
[![License](https://img.shields.io/github/license/WOOWTECH/Woow_ha_permission_control)](LICENSE)

一個 Home Assistant 自定義組件，提供側邊欄面板來控制按標籤組織的實體。與 [Permission Manager](../ha_permission_manager/) 整合，僅顯示每個用戶有權限訪問的標籤。

**當前版本：2.0.0**

## 功能特色

- **標籤式實體控制**：按標籤分組查看和控制實體
- **權限感知**：與 Permission Manager 整合，僅顯示用戶有權限的標籤
- **多語言支援**：英文、繁體中文 (zh-Hant)、簡體中文 (zh-Hans)
- **原生 HA 風格 UI**：簡潔響應式界面，匹配 Home Assistant 現代設計
- **領域摘要儀表板**：3x3 網格顯示 9 個領域類別（燈光、溫控、窗簾、風扇、媒體、門鎖、掃地機、開關、輔助開關）
- **領域詳情視圖**：點擊領域摘要卡片查看按標籤分組的實體
- **標籤詳情視圖**：點擊標籤卡片查看按領域分組的實體
- **互動式實體磁貼**：燈光亮度滑桿、溫控調節、窗簾按鈕等
- **即時更新**：實體狀態即時更新
- **效能優化**：並行數據載入，快速初始渲染

## 截圖說明

面板包含三個視圖：

1. **首頁視圖**：9 個領域類別摘要卡片 + 標籤卡片網格
2. **領域視圖**：點擊領域摘要卡片，查看該領域所有實體（按標籤分組）
3. **標籤視圖**：點擊標籤卡片，查看該標籤所有實體（按領域分組）

## 系統需求

- Home Assistant 2024.1.0 或更新版本
- [Permission Manager](../ha_permission_manager/) 整合組件（依賴項）

## 安裝方式

### HACS 安裝（推薦）

1. 在 Home Assistant 中開啟 HACS
2. 點擊右上角三個點
3. 選擇「自定義存儲庫」
4. 添加此存儲庫 URL：`https://github.com/WOOWTECH/Woow_ha_permission_control`
5. 選擇「Integration」作為類別
6. 點擊「添加」
7. 搜索「Label Control」並安裝
8. 重啟 Home Assistant

### 手動安裝

1. 從 [releases 頁面](https://github.com/WOOWTECH/Woow_ha_permission_control/releases) 下載最新版本
2. 將 `ha_label_control` 資料夾解壓到 `custom_components` 目錄
3. 重啟 Home Assistant

## 配置設定

1. 前往 **設定** > **裝置與服務**
2. 點擊 **+ 添加整合**
3. 搜索「Label Control」
4. 點擊添加

安裝後，側邊欄將出現「標籤控制」面板。

## 運作原理

### 管理員用戶
管理員用戶可以看到 Home Assistant 中定義的所有標籤，擁有完整訪問權限。

### 非管理員用戶
非管理員用戶僅能看到通過 Permission Manager 授予訪問權限的標籤。權限級別如下：

| 級別 | 數值 | 說明 |
|------|------|------|
| 關閉 (Closed) | 0 | 無訪問權限 |
| 查看 (View) | 1 | 可查看標籤和實體 |
| 有限 (Limited) | 2 | 可查看和有限控制 |
| 編輯 (Edit) | 3 | 完整控制權限 |

## 檔案結構

```
ha_label_control/
├── __init__.py           # 主整合設置
├── manifest.json         # 組件清單
├── config_flow.py        # 配置流程
├── const.py              # 常數定義
├── panel.py              # WebSocket API 處理器
├── strings.json          # 默認字串
├── hacs.json             # HACS 配置
├── frontend/
│   └── ha-label-control-panel.js  # 前端面板 (39KB)
└── translations/
    ├── en.json           # 英文翻譯
    ├── zh-Hant.json      # 繁體中文
    └── zh-Hans.json      # 簡體中文
```

## WebSocket API

整合提供兩個 WebSocket 命令：

### `label_control/get_permitted_labels`
返回當前用戶有權限訪問的標籤列表。

**響應格式：**
```json
{
  "labels": [
    {
      "id": "living_room",
      "name": "客廳",
      "icon": "mdi:sofa",
      "color": "blue",
      "entity_count": 5,
      "permission_level": 3
    }
  ]
}
```

### `label_control/get_label_entities`
返回指定標籤的實體，按領域分組。

**請求參數：**
- `label_id`：標籤 ID（必填）

**響應格式：**
```json
{
  "entities": {
    "light": ["light.living_room_main", "light.living_room_ambient"],
    "switch": ["switch.living_room_tv"],
    "climate": ["climate.living_room_ac"]
  }
}
```

## 支援的領域

面板支援以下實體領域的控制：

| 領域 | 說明 | 圖標 |
|------|------|------|
| light | 燈光 | mdi:lightbulb |
| switch | 開關 | mdi:toggle-switch |
| input_boolean | 輔助開關 | mdi:toggle-switch-outline |
| fan | 風扇 | mdi:fan |
| climate | 溫控 | mdi:thermostat |
| cover | 窗簾 | mdi:window-shutter |
| lock | 門鎖 | mdi:lock |
| vacuum | 掃地機 | mdi:robot-vacuum |
| media_player | 媒體播放器 | mdi:cast |
| automation | 自動化 | mdi:robot |
| script | 腳本 | mdi:script-text |
| scene | 場景 | mdi:palette |
| sensor | 感測器 | mdi:eye |
| binary_sensor | 二進制感測器 | mdi:checkbox-marked-circle |
| button | 按鈕 | mdi:gesture-tap-button |
| person | 人員 | mdi:account |
| camera | 攝像頭 | mdi:cctv |

## 技術細節

- **前端框架**：Lit 3.1.0（透過 jsDelivr CDN 載入）
- **後端 API**：Home Assistant WebSocket API
- **認證**：整合 HA 用戶系統
- **權限**：整合 Permission Manager

## 貢獻指南

歡迎貢獻！請隨時提交 Pull Request。

## 授權條款

本項目採用 MIT 許可證 - 詳見 [LICENSE](LICENSE) 文件。

## 問題回報

如遇到問題或有功能建議，請 [開啟 Issue](https://github.com/WOOWTECH/Woow_ha_permission_control/issues)。

## 開發者

由 [WOOWTECH](https://github.com/WOOWTECH) 開發
