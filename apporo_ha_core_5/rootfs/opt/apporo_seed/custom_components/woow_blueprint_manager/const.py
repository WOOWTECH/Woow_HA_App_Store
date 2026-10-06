"""Constants for Blueprint Manager."""

DOMAIN = "woow_blueprint_manager"
PANEL_URL = "/woow-blueprints"
PANEL_TITLE = "藍圖管理器"
PANEL_ICON = "mdi:puzzle"

BLUEPRINT_DEST_DIR = "blueprints/automation/woowtech"

# Category definitions (by functional purpose)
CATEGORIES = {
    "lighting": {
        "name_zh": "燈光控制",
        "name_en": "Lighting",
        "icon": "mdi:lightbulb-group",
        "blueprints": [
            "adalight",
            "switch_trigger_lights",
            "binary_sensor_trigger_light",
        ],
    },
    "scene": {
        "name_zh": "場景循環",
        "name_en": "Scene Loop",
        "icon": "mdi:palette",
        "blueprints": [
            "scenes_loop_detail",
            "scenes_loop_simple",
            "adascene_multi",
            "adascene_single",
        ],
    },
    "notify": {
        "name_zh": "通知提醒",
        "name_en": "Notification",
        "icon": "mdi:bell-ring",
        "blueprints": [
            "entity_state_trigger_notify",
            "todo_trigger_notify",
        ],
    },
    "climate": {
        "name_zh": "環境控制",
        "name_en": "Climate",
        "icon": "mdi:thermostat",
        "blueprints": [
            "greenhouse",
            "sync_climate",
            "light_sync_cover_and_fan",
        ],
    },
    "device": {
        "name_zh": "設備控制",
        "name_en": "Device Control",
        "icon": "mdi:devices",
        "blueprints": [
            "switch_trigger_things",
            "binary_sensor_trigger_things",
            "calendar_trigger_things",
            "time_pattern_trigger_things_simple",
            "time_pattern_trigger_things_complex",
            "voice_trigger_things",
        ],
    },
    "script": {
        "name_zh": "腳本控制",
        "name_en": "Script Control",
        "icon": "mdi:script-text",
        "blueprints": [
            "light_loop",
            "scene_loop",
        ],
    },
}

# Blueprint metadata for panel display
BLUEPRINT_META = {
    "adalight": {
        "version": "1.0.0",
        "domain": "automation",
        "name_zh": "自適應燈光",
        "name_en": "Adaptive Lighting",
        "desc_zh": "根據一天中 6 個時段自動調整燈光亮度與色溫",
        "desc_en": "Auto-adjust brightness and color temperature across 6 daily time periods",
    },
    "switch_trigger_lights": {
        "version": "1.0.0",
        "domain": "automation",
        "name_zh": "開關觸發燈光",
        "name_en": "Switch Trigger Lights",
        "desc_zh": "多切開關控制燈光實體，支援同步切換",
        "desc_en": "Multi-switch controls light entities with synchronized toggle",
    },
    "binary_sensor_trigger_light": {
        "version": "1.0.0",
        "domain": "automation",
        "name_zh": "感測器觸發燈光",
        "name_en": "Binary Sensor Trigger Light",
        "desc_zh": "二元感測器觸發燈光自動開關",
        "desc_en": "Binary sensor triggers automatic light on/off",
    },
    "scenes_loop_detail": {
        "version": "1.0.0",
        "domain": "automation",
        "name_zh": "場景循環（進階）",
        "name_en": "Scene Loop (Detail)",
        "desc_zh": "進階場景循環播放，支援自訂時間與轉場",
        "desc_en": "Advanced scene loop with custom timing and transitions",
    },
    "scenes_loop_simple": {
        "version": "1.0.0",
        "domain": "automation",
        "name_zh": "場景循環（簡易）",
        "name_en": "Scene Loop (Simple)",
        "desc_zh": "簡易場景循環播放",
        "desc_en": "Simple scene loop playback",
    },
    "adascene_multi": {
        "version": "1.0.0",
        "domain": "automation",
        "name_zh": "自適應場景（多場景）",
        "name_en": "Adaptive Scene (Multi)",
        "desc_zh": "根據時段自動切換多個場景",
        "desc_en": "Auto-switch multiple scenes based on time period",
    },
    "adascene_single": {
        "version": "1.0.0",
        "domain": "automation",
        "name_zh": "自適應場景（單場景）",
        "name_en": "Adaptive Scene (Single)",
        "desc_zh": "根據時段自動套用單一場景",
        "desc_en": "Auto-apply single scene based on time period",
    },
    "entity_state_trigger_notify": {
        "version": "1.0.0",
        "domain": "automation",
        "name_zh": "實體狀態觸發通知",
        "name_en": "Entity State Trigger Notify",
        "desc_zh": "實體狀態變化時發送通知",
        "desc_en": "Send notification when entity state changes",
    },
    "todo_trigger_notify": {
        "version": "1.0.0",
        "domain": "automation",
        "name_zh": "待辦事項觸發通知",
        "name_en": "Todo Trigger Notify",
        "desc_zh": "待辦事項更新時觸發通知",
        "desc_en": "Trigger notification when todo item updates",
    },
    "greenhouse": {
        "version": "1.0.0",
        "domain": "automation",
        "name_zh": "溫室自動控制",
        "name_en": "Greenhouse Control",
        "desc_zh": "溫室環境自動監控與控制",
        "desc_en": "Automated greenhouse environment monitoring and control",
    },
    "sync_climate": {
        "version": "1.0.0",
        "domain": "automation",
        "name_zh": "同步溫控",
        "name_en": "Sync Climate",
        "desc_zh": "多台冷氣同步控制溫度與模式",
        "desc_en": "Synchronize temperature and mode across multiple climate devices",
    },
    "light_sync_cover_and_fan": {
        "version": "1.0.0",
        "domain": "automation",
        "name_zh": "燈光同步窗簾風扇",
        "name_en": "Light Sync Cover & Fan",
        "desc_zh": "燈光狀態同步控制窗簾與風扇",
        "desc_en": "Sync cover and fan control based on light state",
    },
    "switch_trigger_things": {
        "version": "1.0.0",
        "domain": "automation",
        "name_zh": "開關觸發動作",
        "name_en": "Switch Trigger Things",
        "desc_zh": "多切開關觸發各種實體動作",
        "desc_en": "Multi-switch triggers various entity actions",
    },
    "binary_sensor_trigger_things": {
        "version": "1.0.0",
        "domain": "automation",
        "name_zh": "感測器觸發動作",
        "name_en": "Binary Sensor Trigger Things",
        "desc_zh": "二元感測器觸發各種實體動作",
        "desc_en": "Binary sensor triggers various entity actions",
    },
    "calendar_trigger_things": {
        "version": "1.0.0",
        "domain": "automation",
        "name_zh": "行事曆觸發動作",
        "name_en": "Calendar Trigger Things",
        "desc_zh": "行事曆事件觸發各種實體動作",
        "desc_en": "Calendar events trigger various entity actions",
    },
    "time_pattern_trigger_things_simple": {
        "version": "1.0.0",
        "domain": "automation",
        "name_zh": "時間模式觸發動作（簡易）",
        "name_en": "Time Pattern Trigger (Simple)",
        "desc_zh": "依照設定的時間模式觸發指定動作",
        "desc_en": "Trigger actions based on time patterns",
    },
    "time_pattern_trigger_things_complex": {
        "version": "1.0.0",
        "domain": "automation",
        "name_zh": "時間模式觸發動作（進階）",
        "name_en": "Time Pattern Trigger (Complex)",
        "desc_zh": "進階時間模式觸發，支援多時段與條件",
        "desc_en": "Advanced time pattern trigger with multiple periods and conditions",
    },
    "voice_trigger_things": {
        "version": "1.0.0",
        "domain": "automation",
        "name_zh": "語音觸發動作",
        "name_en": "Voice Trigger Things",
        "desc_zh": "語音助手觸發各種實體動作",
        "desc_en": "Voice assistant triggers various entity actions",
    },
    "light_loop": {
        "version": "1.0.0",
        "domain": "script",
        "name_zh": "燈光循環控制",
        "name_en": "Light Loop Control",
        "desc_zh": "以12組可自訂模式依序循環控制多盞燈，支援同步/非同步、RGB與色溫",
        "desc_en": "Cycles through up to 12 user-defined modes on multiple lights with sync/async, RGB and color-temp support",
    },
    "scene_loop": {
        "version": "1.0.0",
        "domain": "script",
        "name_zh": "場景循環控制",
        "name_en": "Scene Loop Control",
        "desc_zh": "依序或同時執行多個場景，支援循環次數與過渡時間設定",
        "desc_en": "Sequentially or simultaneously activates multiple scenes with configurable loops and transitions",
    },
}
