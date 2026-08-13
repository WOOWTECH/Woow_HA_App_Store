"""Service handlers for Blueprint Manager."""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.helpers import config_validation as cv

from .blueprint_parser import parse_blueprint_inputs
from .const import BLUEPRINT_META, CATEGORIES, DOMAIN

_LOGGER = logging.getLogger(__name__)

# Blueprint source directories
_AUTO_DIR = Path(__file__).parent / "blueprints" / "automation"
_SCRIPT_DIR = Path(__file__).parent / "blueprints" / "script"

# Service names
SVC_LIST_BLUEPRINTS = "list_blueprints"
SVC_GET_BLUEPRINT_DETAIL = "get_blueprint_detail"
SVC_LIST_INSTANCES = "list_instances"
SVC_GET_INSTANCE_DETAIL = "get_instance_detail"
SVC_CREATE_INSTANCE = "create_instance"
SVC_UPDATE_INSTANCE = "update_instance"
SVC_DELETE_INSTANCE = "delete_instance"
SVC_TOGGLE_INSTANCE = "toggle_instance"
SVC_RECOMMEND_BLUEPRINT = "recommend_blueprint"
SVC_GET_SYSTEM_STATUS = "get_system_status"

ALL_SERVICES = [
    SVC_LIST_BLUEPRINTS,
    SVC_GET_BLUEPRINT_DETAIL,
    SVC_LIST_INSTANCES,
    SVC_GET_INSTANCE_DETAIL,
    SVC_CREATE_INSTANCE,
    SVC_UPDATE_INSTANCE,
    SVC_DELETE_INSTANCE,
    SVC_TOGGLE_INSTANCE,
    SVC_RECOMMEND_BLUEPRINT,
    SVC_GET_SYSTEM_STATUS,
]


def _get_blueprint_yaml_path(blueprint_key: str) -> Path | None:
    """Find the YAML file for a blueprint key."""
    meta = BLUEPRINT_META.get(blueprint_key)
    if not meta:
        return None
    domain = meta.get("domain", "automation")
    src_dir = _SCRIPT_DIR if domain == "script" else _AUTO_DIR
    path = src_dir / f"{blueprint_key}.yaml"
    return path if path.is_file() else None


def _load_config_index(hass: HomeAssistant) -> dict[str, dict]:
    """Build an index of automation_id/script_id -> blueprint_path from config files.

    Returns dict like: {"automation_id_or_script_id": {"domain": "automation", "bp_path": "woowtech/adalight.yaml"}}
    """
    import yaml
    config_dir = Path(hass.config.path())
    index: dict[str, dict] = {}

    # Automations
    auto_file = config_dir / "automations.yaml"
    if auto_file.is_file():
        try:
            content = auto_file.read_text(encoding="utf-8")
            automations = yaml.safe_load(content) or []
            for auto in automations:
                if not isinstance(auto, dict):
                    continue
                bp = auto.get("use_blueprint", {})
                if bp and isinstance(bp, dict):
                    bp_path = bp.get("path", "")
                    auto_id = auto.get("id", "")
                    if auto_id and bp_path:
                        index[auto_id] = {"domain": "automation", "bp_path": bp_path}
        except Exception:
            _LOGGER.debug("Could not parse automations.yaml", exc_info=True)

    # Scripts
    script_file = config_dir / "scripts.yaml"
    if script_file.is_file():
        try:
            content = script_file.read_text(encoding="utf-8")
            scripts = yaml.safe_load(content) or {}
            for script_id, config in scripts.items():
                if not isinstance(config, dict):
                    continue
                bp = config.get("use_blueprint", {})
                if bp and isinstance(bp, dict):
                    bp_path = bp.get("path", "")
                    if bp_path:
                        index[script_id] = {"domain": "script", "bp_path": bp_path}
        except Exception:
            _LOGGER.debug("Could not parse scripts.yaml", exc_info=True)

    return index


def _count_instances_from_index(index: dict[str, dict], blueprint_key: str) -> int:
    """Count instances for a blueprint from the pre-loaded config index."""
    bp_path = f"woowtech/{blueprint_key}.yaml"
    return sum(1 for v in index.values() if v["bp_path"] == bp_path)


def _build_woow_instances(
    hass: HomeAssistant, index: dict[str, dict], type_filter: str | None = None
) -> list[dict[str, Any]]:
    """Build instance list from config index + live states. Must run in event loop."""
    instances = []

    for config_id, info in index.items():
        bp_path = info["bp_path"]
        domain = info["domain"]

        if not bp_path.startswith("woowtech/"):
            continue
        if type_filter and domain != type_filter:
            continue

        bp_key = bp_path.replace("woowtech/", "").replace(".yaml", "")
        meta = BLUEPRINT_META.get(bp_key, {})

        # Find matching entity in HA states
        entity_id = None
        if domain == "automation":
            for state in hass.states.async_all("automation"):
                if state.attributes.get("id") == config_id:
                    entity_id = state.entity_id
                    break
        else:
            entity_id = f"script.{config_id}"

        state = hass.states.get(entity_id) if entity_id else None

        instances.append({
            "entity_id": entity_id or f"{domain}.{config_id}",
            "type": domain,
            "name": state.attributes.get("friendly_name", config_id) if state else config_id,
            "state": state.state if state else "unknown",
            "blueprint_key": bp_key,
            "blueprint_name_zh": meta.get("name_zh", bp_key),
            "blueprint_name_en": meta.get("name_en", bp_key),
            "last_triggered": state.attributes.get("last_triggered") if state else None,
        })

    return instances


# ---------------------------------------------------------------------------
# Service handlers
# ---------------------------------------------------------------------------


async def async_handle_list_blueprints(call: ServiceCall) -> dict[str, Any]:
    """List all available WOOW blueprints grouped by category."""
    hass = call.hass
    index = await hass.async_add_executor_job(_load_config_index, hass)
    categories_out = []
    total = 0

    for cat_key, cat_data in CATEGORIES.items():
        bp_list = []
        for bp_key in cat_data["blueprints"]:
            meta = BLUEPRINT_META.get(bp_key, {})
            domain = meta.get("domain", "automation")
            count = _count_instances_from_index(index, bp_key)
            bp_list.append({
                "key": bp_key,
                "domain": domain,
                "version": meta.get("version", "1.0.0"),
                "name_zh": meta.get("name_zh", bp_key),
                "name_en": meta.get("name_en", bp_key),
                "desc_zh": meta.get("desc_zh", ""),
                "desc_en": meta.get("desc_en", ""),
                "instance_count": count,
            })
            total += 1

        categories_out.append({
            "key": cat_key,
            "name_zh": cat_data["name_zh"],
            "name_en": cat_data["name_en"],
            "icon": cat_data.get("icon", ""),
            "blueprints": bp_list,
        })

    return {"total": total, "categories": categories_out}


async def async_handle_get_blueprint_detail(call: ServiceCall) -> dict[str, Any]:
    """Get full parameter definitions for a single blueprint."""
    bp_key = call.data["blueprint_key"]
    meta = BLUEPRINT_META.get(bp_key)
    if not meta:
        return {"error": True, "message_zh": f"找不到藍圖 '{bp_key}'", "message_en": f"Blueprint '{bp_key}' not found"}

    yaml_path = _get_blueprint_yaml_path(bp_key)
    if not yaml_path:
        return {"error": True, "message_zh": f"藍圖檔案不存在: {bp_key}", "message_en": f"Blueprint file not found: {bp_key}"}

    parsed = await call.hass.async_add_executor_job(parse_blueprint_inputs, yaml_path)

    return {
        "key": bp_key,
        "domain": meta.get("domain", "automation"),
        "version": meta.get("version", "1.0.0"),
        "name_zh": meta.get("name_zh", bp_key),
        "name_en": meta.get("name_en", bp_key),
        "desc_zh": meta.get("desc_zh", ""),
        "desc_en": meta.get("desc_en", ""),
        "inputs": parsed["inputs"],
        "input_sections": parsed["input_sections"],
    }


async def async_handle_list_instances(call: ServiceCall) -> dict[str, Any]:
    """List all WOOW automation/script instances."""
    hass = call.hass
    type_filter = call.data.get("type")
    index = await hass.async_add_executor_job(_load_config_index, hass)
    instances = _build_woow_instances(hass, index, type_filter)
    return {"total": len(instances), "instances": instances}


async def async_handle_get_instance_detail(call: ServiceCall) -> dict[str, Any]:
    """Get current parameter values of an existing automation or script."""
    hass = call.hass
    entity_id: str = call.data["entity_id"]
    domain = entity_id.split(".")[0]

    state = hass.states.get(entity_id)
    if not state:
        return {"error": True, "message_zh": f"找不到實體 '{entity_id}'", "message_en": f"Entity '{entity_id}' not found"}

    # Determine config_id for index lookup
    if domain == "automation":
        config_id = state.attributes.get("id", "")
    else:
        config_id = entity_id.replace("script.", "")

    # Use config index to find blueprint path
    index = await hass.async_add_executor_job(_load_config_index, hass)
    info = index.get(config_id, {})
    bp_path = info.get("bp_path", "")
    bp_key = bp_path.replace("woowtech/", "").replace(".yaml", "") if bp_path.startswith("woowtech/") else ""

    result: dict[str, Any] = {
        "entity_id": entity_id,
        "type": domain,
        "name": state.attributes.get("friendly_name", entity_id),
        "state": state.state,
        "blueprint_key": bp_key,
        "blueprint_path": bp_path,
        "last_triggered": state.attributes.get("last_triggered"),
        "current_values": {},
    }

    # Read current input values from config files
    try:
        if domain == "automation":
            auto_id = state.attributes.get("id")
            if auto_id:
                config = await _read_automation_config(hass, auto_id)
                if config and "use_blueprint" in config:
                    result["current_values"] = config["use_blueprint"].get("input", {})
        elif domain == "script":
            script_id = entity_id.replace("script.", "")
            config = await _read_script_config(hass, script_id)
            if config and "use_blueprint" in config:
                result["current_values"] = config["use_blueprint"].get("input", {})
    except Exception:
        _LOGGER.debug("Could not read config for %s", entity_id, exc_info=True)

    return result


async def async_handle_create_instance(call: ServiceCall) -> dict[str, Any]:
    """Create a new automation or script from a WOOW blueprint."""
    hass = call.hass
    bp_key: str = call.data["blueprint_key"]
    name: str = call.data["name"]
    input_data: dict = call.data["input"]

    meta = BLUEPRINT_META.get(bp_key)
    if not meta:
        return {"error": True, "message_zh": f"找不到藍圖 '{bp_key}'", "message_en": f"Blueprint '{bp_key}' not found"}

    domain = meta.get("domain", "automation")
    bp_path = f"woowtech/{bp_key}.yaml"

    if domain == "automation":
        auto_id = str(uuid.uuid4())
        config = {
            "id": auto_id,
            "alias": name,
            "use_blueprint": {
                "path": bp_path,
                "input": input_data,
            },
        }
        success = await _write_automation_config(hass, auto_id, config)
        if success:
            return {
                "success": True,
                "type": "automation",
                "name": name,
                "blueprint_key": bp_key,
                "message_zh": f"已成功建立自動化「{name}」",
                "message_en": f"Successfully created automation '{name}'",
            }
    else:
        # Script
        script_id = re.sub(r"[^a-z0-9_]", "_", name.lower().strip())
        if not script_id:
            script_id = f"{bp_key}_{uuid.uuid4().hex[:6]}"
        config = {
            "alias": name,
            "use_blueprint": {
                "path": bp_path,
                "input": input_data,
            },
        }
        success = await _write_script_config(hass, script_id, config)
        if success:
            return {
                "success": True,
                "entity_id": f"script.{script_id}",
                "type": "script",
                "name": name,
                "blueprint_key": bp_key,
                "message_zh": f"已成功建立腳本「{name}」",
                "message_en": f"Successfully created script '{name}'",
            }

    return {
        "error": True,
        "message_zh": f"建立{domain}失敗",
        "message_en": f"Failed to create {domain}",
    }


async def async_handle_update_instance(call: ServiceCall) -> dict[str, Any]:
    """Update parameter values of an existing automation or script."""
    hass = call.hass
    entity_id: str = call.data["entity_id"]
    input_data: dict = call.data["input"]
    new_name: str | None = call.data.get("name")
    domain = entity_id.split(".")[0]

    if domain == "automation":
        auto_id = None
        state = hass.states.get(entity_id)
        if state:
            auto_id = state.attributes.get("id")
        if not auto_id:
            return {"error": True, "message_zh": "找不到自動化 ID", "message_en": "Automation ID not found"}

        config = await _read_automation_config(hass, auto_id)
        if not config or "use_blueprint" not in config:
            return {"error": True, "message_zh": "無法讀取自動化設定", "message_en": "Cannot read automation config"}

        # Merge input
        existing_input = config["use_blueprint"].get("input", {})
        existing_input.update(input_data)
        config["use_blueprint"]["input"] = existing_input

        if new_name:
            config["alias"] = new_name

        success = await _write_automation_config(hass, auto_id, config)

    elif domain == "script":
        script_id = entity_id.replace("script.", "")
        config = await _read_script_config(hass, script_id)
        if not config or "use_blueprint" not in config:
            return {"error": True, "message_zh": "無法讀取腳本設定", "message_en": "Cannot read script config"}

        existing_input = config["use_blueprint"].get("input", {})
        existing_input.update(input_data)
        config["use_blueprint"]["input"] = existing_input

        if new_name:
            config["alias"] = new_name

        success = await _write_script_config(hass, script_id, config)
    else:
        return {"error": True, "message_zh": f"不支援的類型: {domain}", "message_en": f"Unsupported type: {domain}"}

    if success:
        return {
            "success": True,
            "entity_id": entity_id,
            "type": domain,
            "updated_fields": list(input_data.keys()),
            "message_zh": f"已更新 {len(input_data)} 個參數",
            "message_en": f"Updated {len(input_data)} parameters",
        }

    return {"error": True, "message_zh": "更新失敗", "message_en": "Update failed"}


async def async_handle_delete_instance(call: ServiceCall) -> dict[str, Any]:
    """Delete an automation or script."""
    hass = call.hass
    entity_id: str = call.data["entity_id"]
    domain = entity_id.split(".")[0]

    state = hass.states.get(entity_id)
    name = state.attributes.get("friendly_name", entity_id) if state else entity_id

    if domain == "automation":
        auto_id = state.attributes.get("id") if state else None
        if not auto_id:
            return {"error": True, "message_zh": "找不到自動化 ID", "message_en": "Automation ID not found"}
        success = await _delete_automation_config(hass, auto_id)
    elif domain == "script":
        script_id = entity_id.replace("script.", "")
        success = await _delete_script_config(hass, script_id)
    else:
        return {"error": True, "message_zh": f"不支援的類型: {domain}", "message_en": f"Unsupported type: {domain}"}

    if success:
        type_zh = "自動化" if domain == "automation" else "腳本"
        return {
            "success": True,
            "entity_id": entity_id,
            "type": domain,
            "message_zh": f"已刪除{type_zh}「{name}」",
            "message_en": f"Deleted {domain} '{name}'",
        }

    return {"error": True, "message_zh": "刪除失敗", "message_en": "Delete failed"}


async def async_handle_toggle_instance(call: ServiceCall) -> dict[str, Any]:
    """Enable or disable an automation or script."""
    hass = call.hass
    entity_id: str = call.data["entity_id"]
    action: str = call.data.get("action", "toggle")
    domain = entity_id.split(".")[0]

    state = hass.states.get(entity_id)
    if not state:
        return {"error": True, "message_zh": f"找不到實體 '{entity_id}'", "message_en": f"Entity '{entity_id}' not found"}

    name = state.attributes.get("friendly_name", entity_id)

    # Map action to HA service
    if action == "enable":
        svc = f"{domain}.turn_on"
    elif action == "disable":
        svc = f"{domain}.turn_off"
    else:
        svc = f"{domain}.toggle"

    svc_domain, svc_name = svc.split(".")
    await hass.services.async_call(svc_domain, svc_name, {"entity_id": entity_id})

    # Read new state
    new_state = hass.states.get(entity_id)
    new_state_val = new_state.state if new_state else "unknown"

    state_zh = "啟用" if new_state_val == "on" else "停用"
    state_en = "Enabled" if new_state_val == "on" else "Disabled"
    type_zh = "自動化" if domain == "automation" else "腳本"

    return {
        "success": True,
        "entity_id": entity_id,
        "type": domain,
        "new_state": new_state_val,
        "message_zh": f"已{state_zh}{type_zh}「{name}」",
        "message_en": f"{state_en} {domain} '{name}'",
    }


async def async_handle_recommend_blueprint(call: ServiceCall) -> dict[str, Any]:
    """Recommend blueprints based on a natural language description."""
    description: str = call.data["description"].lower()

    # Build keyword index from blueprint metadata
    recommendations = []

    for bp_key, meta in BLUEPRINT_META.items():
        score = 0
        # Check keywords against all text fields
        searchable = " ".join([
            meta.get("name_zh", ""),
            meta.get("name_en", ""),
            meta.get("desc_zh", ""),
            meta.get("desc_en", ""),
            bp_key,
        ]).lower()

        # Word-level matching
        desc_words = re.findall(r"[\w\u4e00-\u9fff]+", description)
        for word in desc_words:
            if word in searchable:
                score += 1

        # Domain keywords
        domain = meta.get("domain", "automation")
        if domain == "script" and any(w in description for w in ["腳本", "script", "loop", "循環"]):
            score += 2
        if domain == "automation" and any(w in description for w in ["自動", "auto", "trigger", "觸發"]):
            score += 1

        # Specific feature keywords
        keyword_map = {
            "adalight": ["色溫", "亮度", "adaptive", "光", "light", "日夜", "circadian"],
            "switch_trigger_lights": ["開關", "switch", "燈", "light"],
            "binary_sensor_trigger_light": ["感測", "sensor", "motion", "人體", "移動"],
            "scenes_loop_detail": ["場景", "scene", "loop", "循環", "進階"],
            "scenes_loop_simple": ["場景", "scene", "loop", "循環", "簡易"],
            "adascene_multi": ["場景", "scene", "adaptive", "時段", "多場景"],
            "adascene_single": ["場景", "scene", "adaptive", "時段", "單場景"],
            "entity_state_trigger_notify": ["通知", "notify", "狀態", "state"],
            "todo_trigger_notify": ["待辦", "todo", "通知", "notify"],
            "greenhouse": ["溫室", "greenhouse", "植物", "plant"],
            "sync_climate": ["冷氣", "climate", "溫控", "temperature", "空調"],
            "light_sync_cover_and_fan": ["窗簾", "cover", "風扇", "fan", "燈", "同步"],
            "switch_trigger_things": ["開關", "switch", "設備", "device"],
            "binary_sensor_trigger_things": ["感測", "sensor", "設備", "device"],
            "calendar_trigger_things": ["行事曆", "calendar", "日程"],
            "time_pattern_trigger_things_simple": ["時間", "time", "排程", "schedule", "定時"],
            "time_pattern_trigger_things_complex": ["時間", "time", "排程", "schedule", "多時段", "進階"],
            "voice_trigger_things": ["語音", "voice", "助手", "assistant"],
            "light_loop": ["燈光", "light", "循環", "loop", "RGB", "派對", "party"],
            "scene_loop": ["場景", "scene", "循環", "loop"],
        }

        extra_keywords = keyword_map.get(bp_key, [])
        for kw in extra_keywords:
            if kw.lower() in description:
                score += 2

        if score > 0:
            confidence = "high" if score >= 5 else "medium" if score >= 3 else "low"
            recommendations.append({
                "blueprint_key": bp_key,
                "domain": domain,
                "confidence": confidence,
                "score": score,
                "name_zh": meta.get("name_zh", bp_key),
                "name_en": meta.get("name_en", bp_key),
                "desc_zh": meta.get("desc_zh", ""),
                "desc_en": meta.get("desc_en", ""),
            })

    # Sort by score descending, take top 5
    recommendations.sort(key=lambda x: x["score"], reverse=True)
    for r in recommendations:
        del r["score"]

    return {"recommendations": recommendations[:5]}


async def async_handle_get_system_status(call: ServiceCall) -> dict[str, Any]:
    """Get overall system status."""
    hass = call.hass

    auto_blueprints = sum(1 for m in BLUEPRINT_META.values() if m.get("domain", "automation") == "automation")
    script_blueprints = sum(1 for m in BLUEPRINT_META.values() if m.get("domain") == "script")
    auto_categories = sum(1 for c in CATEGORIES.values() if any(
        BLUEPRINT_META.get(bp, {}).get("domain", "automation") == "automation" for bp in c["blueprints"]
    ))
    script_categories = sum(1 for c in CATEGORIES.values() if any(
        BLUEPRINT_META.get(bp, {}).get("domain") == "script" for bp in c["blueprints"]
    ))

    # Count instances via config index
    index = await hass.async_add_executor_job(_load_config_index, hass)
    auto_instances = _build_woow_instances(hass, index, "automation")
    script_instances = _build_woow_instances(hass, index, "script")

    auto_enabled = sum(1 for i in auto_instances if i["state"] == "on")
    script_enabled = sum(1 for i in script_instances if i["state"] == "on")

    return {
        "version": "1.0.0",
        "blueprints": {
            "automation": {"deployed": auto_blueprints, "categories": auto_categories},
            "script": {"deployed": script_blueprints, "categories": script_categories},
        },
        "instances": {
            "automation": {
                "total": len(auto_instances),
                "enabled": auto_enabled,
                "disabled": len(auto_instances) - auto_enabled,
            },
            "script": {
                "total": len(script_instances),
                "enabled": script_enabled,
                "disabled": len(script_instances) - script_enabled,
            },
        },
    }


# ---------------------------------------------------------------------------
# HA config read/write helpers (internal REST-like API)
# ---------------------------------------------------------------------------


async def _read_automation_config(hass: HomeAssistant, auto_id: str) -> dict | None:
    """Read automation config from HA storage."""
    try:
        component = hass.data.get("automation")
        if not component:
            return None
        for entity in component.entities:
            if getattr(entity, "unique_id", None) == auto_id:
                raw = entity.action_script.raw_config if hasattr(entity, "action_script") else None
                # Try to get from referenced_blueprint
                if hasattr(entity, "referenced_blueprint") and entity.referenced_blueprint:
                    # Reconstruct config from entity
                    config: dict[str, Any] = {"id": auto_id}
                    if hasattr(entity, "_raw_config"):
                        return entity._raw_config
                    return config
    except Exception:
        _LOGGER.debug("Could not read automation config for %s", auto_id, exc_info=True)

    # Fallback: read from automations.yaml
    try:
        config_dir = Path(hass.config.path())
        auto_file = config_dir / "automations.yaml"
        if auto_file.is_file():
            import yaml
            content = await hass.async_add_executor_job(auto_file.read_text, "utf-8")
            automations = yaml.safe_load(content) or []
            for auto in automations:
                if isinstance(auto, dict) and auto.get("id") == auto_id:
                    return auto
    except Exception:
        _LOGGER.debug("Could not read automations.yaml for %s", auto_id, exc_info=True)

    return None


async def _write_automation_config(hass: HomeAssistant, auto_id: str, config: dict) -> bool:
    """Write automation config via HA internal API."""
    try:
        import yaml
        config_dir = Path(hass.config.path())
        auto_file = config_dir / "automations.yaml"

        def _write() -> bool:
            automations = []
            if auto_file.is_file():
                content = auto_file.read_text(encoding="utf-8")
                automations = yaml.safe_load(content) or []

            # Find and replace or append
            found = False
            for i, auto in enumerate(automations):
                if isinstance(auto, dict) and auto.get("id") == auto_id:
                    automations[i] = config
                    found = True
                    break
            if not found:
                automations.append(config)

            auto_file.write_text(
                yaml.dump(automations, default_flow_style=False, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            return True

        result = await hass.async_add_executor_job(_write)
        # Reload automations
        await hass.services.async_call("automation", "reload")
        return result
    except Exception:
        _LOGGER.exception("Failed to write automation config for %s", auto_id)
        return False


async def _delete_automation_config(hass: HomeAssistant, auto_id: str) -> bool:
    """Delete automation config."""
    try:
        import yaml
        config_dir = Path(hass.config.path())
        auto_file = config_dir / "automations.yaml"

        def _delete() -> bool:
            if not auto_file.is_file():
                return False
            content = auto_file.read_text(encoding="utf-8")
            automations = yaml.safe_load(content) or []
            new_list = [a for a in automations if not (isinstance(a, dict) and a.get("id") == auto_id)]
            if len(new_list) == len(automations):
                return False
            auto_file.write_text(
                yaml.dump(new_list, default_flow_style=False, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            return True

        result = await hass.async_add_executor_job(_delete)
        if result:
            await hass.services.async_call("automation", "reload")
        return result
    except Exception:
        _LOGGER.exception("Failed to delete automation config for %s", auto_id)
        return False


async def _read_script_config(hass: HomeAssistant, script_id: str) -> dict | None:
    """Read script config from scripts.yaml."""
    try:
        import yaml
        config_dir = Path(hass.config.path())
        script_file = config_dir / "scripts.yaml"
        if not script_file.is_file():
            return None

        content = await hass.async_add_executor_job(script_file.read_text, "utf-8")
        scripts = yaml.safe_load(content) or {}
        return scripts.get(script_id)
    except Exception:
        _LOGGER.debug("Could not read script config for %s", script_id, exc_info=True)
        return None


async def _write_script_config(hass: HomeAssistant, script_id: str, config: dict) -> bool:
    """Write script config to scripts.yaml."""
    try:
        import yaml
        config_dir = Path(hass.config.path())
        script_file = config_dir / "scripts.yaml"

        def _write() -> bool:
            scripts: dict = {}
            if script_file.is_file():
                content = script_file.read_text(encoding="utf-8")
                scripts = yaml.safe_load(content) or {}

            scripts[script_id] = config
            script_file.write_text(
                yaml.dump(scripts, default_flow_style=False, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            return True

        result = await hass.async_add_executor_job(_write)
        await hass.services.async_call("script", "reload")
        return result
    except Exception:
        _LOGGER.exception("Failed to write script config for %s", script_id)
        return False


async def _delete_script_config(hass: HomeAssistant, script_id: str) -> bool:
    """Delete script config from scripts.yaml."""
    try:
        import yaml
        config_dir = Path(hass.config.path())
        script_file = config_dir / "scripts.yaml"

        def _delete() -> bool:
            if not script_file.is_file():
                return False
            content = script_file.read_text(encoding="utf-8")
            scripts = yaml.safe_load(content) or {}
            if script_id not in scripts:
                return False
            del scripts[script_id]
            script_file.write_text(
                yaml.dump(scripts, default_flow_style=False, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            return True

        result = await hass.async_add_executor_job(_delete)
        if result:
            await hass.services.async_call("script", "reload")
        return result
    except Exception:
        _LOGGER.exception("Failed to delete script config for %s", script_id)
        return False


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

_SCHEMAS: dict[str, vol.Schema] = {
    SVC_LIST_BLUEPRINTS: vol.Schema({}),
    SVC_GET_BLUEPRINT_DETAIL: vol.Schema({
        vol.Required("blueprint_key"): cv.string,
    }),
    SVC_LIST_INSTANCES: vol.Schema({
        vol.Optional("type"): vol.In(["automation", "script"]),
    }),
    SVC_GET_INSTANCE_DETAIL: vol.Schema({
        vol.Required("entity_id"): cv.string,
    }),
    SVC_CREATE_INSTANCE: vol.Schema({
        vol.Required("blueprint_key"): cv.string,
        vol.Required("name"): cv.string,
        vol.Required("input"): dict,
    }),
    SVC_UPDATE_INSTANCE: vol.Schema({
        vol.Required("entity_id"): cv.string,
        vol.Required("input"): dict,
        vol.Optional("name"): cv.string,
    }),
    SVC_DELETE_INSTANCE: vol.Schema({
        vol.Required("entity_id"): cv.string,
    }),
    SVC_TOGGLE_INSTANCE: vol.Schema({
        vol.Required("entity_id"): cv.string,
        vol.Optional("action", default="toggle"): vol.In(["toggle", "enable", "disable"]),
    }),
    SVC_RECOMMEND_BLUEPRINT: vol.Schema({
        vol.Required("description"): cv.string,
    }),
    SVC_GET_SYSTEM_STATUS: vol.Schema({}),
}

_HANDLERS = {
    SVC_LIST_BLUEPRINTS: async_handle_list_blueprints,
    SVC_GET_BLUEPRINT_DETAIL: async_handle_get_blueprint_detail,
    SVC_LIST_INSTANCES: async_handle_list_instances,
    SVC_GET_INSTANCE_DETAIL: async_handle_get_instance_detail,
    SVC_CREATE_INSTANCE: async_handle_create_instance,
    SVC_UPDATE_INSTANCE: async_handle_update_instance,
    SVC_DELETE_INSTANCE: async_handle_delete_instance,
    SVC_TOGGLE_INSTANCE: async_handle_toggle_instance,
    SVC_RECOMMEND_BLUEPRINT: async_handle_recommend_blueprint,
    SVC_GET_SYSTEM_STATUS: async_handle_get_system_status,
}


async def async_register_services(hass: HomeAssistant) -> None:
    """Register all Blueprint Manager services."""
    for svc_name in ALL_SERVICES:
        if hass.services.has_service(DOMAIN, svc_name):
            continue
        hass.services.async_register(
            DOMAIN,
            svc_name,
            _HANDLERS[svc_name],
            schema=_SCHEMAS[svc_name],
            supports_response=SupportsResponse.ONLY,
        )
    _LOGGER.info("Blueprint Manager: registered %d services", len(ALL_SERVICES))


def async_unregister_services(hass: HomeAssistant) -> None:
    """Unregister all Blueprint Manager services."""
    for svc_name in ALL_SERVICES:
        hass.services.async_remove(DOMAIN, svc_name)
    _LOGGER.info("Blueprint Manager: unregistered services")
