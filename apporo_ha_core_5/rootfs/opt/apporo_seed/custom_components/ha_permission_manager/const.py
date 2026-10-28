"""Constants for ha_permission_manager."""

DOMAIN = "ha_permission_manager"

# Storage versioning (for hass.helpers.storage.Store)
STORAGE_VERSION = 1
STORAGE_KEY = DOMAIN

PERMISSION_OPTIONS = ["0", "1"]
PERMISSION_LABELS = {
    "0": "Closed",
    "1": "View",
}

# Permission levels (numeric values for comparison)
# Simplified from 4 levels to 2 levels (v1.0.0)
PERM_CLOSED = 0
PERM_VIEW = 1

# Resource type prefixes
PREFIX_AREA = "area_"
PREFIX_LABEL = "label_"
PREFIX_PANEL = "panel_"

# Self-reference resource ID (for bootstrap protection)
SELF_PANEL_ID = f"{PREFIX_PANEL}ha_permission_manager"

# Admin group ID (HA built-in)
ADMIN_GROUP_ID = "system-admin"

# Panel configuration (Permission Manager)
PANEL_TITLE = "Permission Manager"
PANEL_TITLE_ZH = "權限管理器"
PANEL_ICON = "mdi:shield-lock"
PANEL_URL = "ha_permission_manager"

# URL prefix the frontend/ directory is mounted at (see __init__.py).
FRONTEND_URL_BASE = "/ha_permission_manager_frontend"

PANEL_VERSION = "2.0.15"

# Control Panel configuration (unified area/label control)
CONTROL_PANEL_URL = "ha-control-panel"
CONTROL_PANEL_TITLE = "Control Panel"
CONTROL_PANEL_TITLE_ZH = "控制面板"
CONTROL_PANEL_ICON = "mdi:view-dashboard"

# Tab Configuration for Control Panel
CONTROL_PANEL_TABS = ["areas", "labels"]
DEFAULT_TAB = "areas"

# Service names
SERVICE_SET_PERMISSION = "set_permission"
SERVICE_BULK_SET_PERMISSIONS = "bulk_set_permissions"
SERVICE_REMOVE_USER_PERMISSIONS = "remove_user_permissions"
SERVICE_REMOVE_RESOURCE_PERMISSIONS = "remove_resource_permissions"
SERVICE_RESET_ALL_PERMISSIONS = "reset_all_permissions"
SERVICE_GET_PERMISSIONS = "get_permissions"
SERVICE_GET_USERS = "get_users"
SERVICE_GET_RESOURCES = "get_resources"
SERVICE_GET_PERMITTED_AREAS = "get_permitted_areas"
SERVICE_GET_AREA_ENTITIES = "get_area_entities"
SERVICE_GET_PERMITTED_LABELS = "get_permitted_labels"
SERVICE_GET_LABEL_ENTITIES = "get_label_entities"
SERVICE_GET_PANEL_PERMISSIONS = "get_panel_permissions"
SERVICE_GET_ALL_PERMISSIONS = "get_all_permissions"

# Valid resource type filters
RESOURCE_TYPES = ["panel", "area", "label"]
RESOURCE_TYPE_PREFIX_MAP = {
    "panel": PREFIX_PANEL,
    "area": PREFIX_AREA,
    "label": PREFIX_LABEL,
}

# Domain Configuration (for entity grouping in control panel)
DOMAIN_ICONS = {
    "light": "mdi:lightbulb",
    "switch": "mdi:toggle-switch",
    "sensor": "mdi:eye",
    "binary_sensor": "mdi:checkbox-marked-circle",
    "climate": "mdi:thermostat",
    "cover": "mdi:window-shutter",
    "fan": "mdi:fan",
    "lock": "mdi:lock",
    "media_player": "mdi:play-circle",
    "camera": "mdi:camera",
    "vacuum": "mdi:robot-vacuum",
    "automation": "mdi:robot",
    "script": "mdi:script-text",
}

DOMAIN_COLORS = {
    "light": "#FFD700",       # Gold
    "switch": "#4CAF50",      # Green
    "sensor": "#2196F3",      # Blue
    "binary_sensor": "#9C27B0",  # Purple
    "climate": "#FF5722",     # Deep Orange
    "cover": "#795548",       # Brown
    "fan": "#00BCD4",         # Cyan
    "lock": "#F44336",        # Red
    "media_player": "#E91E63",  # Pink
}
