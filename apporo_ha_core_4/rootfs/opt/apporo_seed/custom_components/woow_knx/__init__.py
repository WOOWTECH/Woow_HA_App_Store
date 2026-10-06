"""Woow KNX Setup Guide - Sidebar panel with built-in YAML editor."""

import logging
import os
import stat
import time

import voluptuous as vol

from homeassistant.components import frontend, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONFIG_SUBDIR, DOMAIN, PANEL_ICON, PANEL_TITLE

_LOGGER = logging.getLogger(__name__)

# Directories to skip when listing files
_SKIP_DIRS = {
    ".storage", ".cloud", ".git", "__pycache__", "deps", "tts",
    "node_modules", ".venv",
}

# Allowed file extensions for listing
_ALLOWED_EXT = {"yaml", "yml", "py", "json", "conf", "js", "txt", "log", "css", "jinja"}


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Woow KNX component from yaml (unused, config_flow only)."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Woow KNX Setup Guide from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Register the frontend panel files
    panel_dir = os.path.join(os.path.dirname(__file__), "frontend")
    await hass.http.async_register_static_paths(
        [StaticPathConfig(f"/{DOMAIN}/frontend", panel_dir, cache_headers=False)]
    )

    # Register sidebar panel
    frontend.async_register_built_in_panel(
        hass,
        component_name="custom",
        sidebar_title=PANEL_TITLE,
        sidebar_icon=PANEL_ICON,
        frontend_url_path=DOMAIN,
        require_admin=False,
        config={
            "_panel_custom": {
                "name": f"woow-{CONFIG_SUBDIR}-panel",
                "module_url": f"/{DOMAIN}/frontend/woow-{CONFIG_SUBDIR}-panel.js",
                "embed_iframe": False,
            }
        },
    )

    # Load sidebar title translation script on every HA page
    cache_buster = int(time.time())
    frontend.add_extra_js_url(hass, f"/{DOMAIN}/frontend/sidebar-title.js?v={cache_buster}")

    # Ensure the component's config subdirectory exists
    subdir = hass.config.path(CONFIG_SUBDIR)
    os.makedirs(subdir, exist_ok=True)

    # Register WebSocket API for YAML file editing
    websocket_api.async_register_command(hass, handle_woow_knx_ws)

    _LOGGER.info("Woow KNX Setup Guide panel registered (config dir: %s/)", CONFIG_SUBDIR)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    frontend.async_remove_panel(hass, DOMAIN)
    _LOGGER.info("Woow KNX Setup Guide panel removed")
    return True


# ---------------------------------------------------------------------------
# WebSocket handler for YAML file editing
# ---------------------------------------------------------------------------

def _sanitize_path(raw: str) -> str:
    """Validate and normalize path, rejecting any traversal attempts."""
    import re
    # Reject null bytes
    if "\x00" in raw:
        return ""
    # Reject absolute paths
    if raw.startswith("/") or raw.startswith("\\"):
        return ""
    # Reject URL-encoded sequences (e.g., %2e, %2f, %5c)
    if re.search(r"%[0-9a-fA-F]{2}", raw):
        return ""
    # Normalize backslashes
    normalized = raw.replace("\\", "/")
    parts = normalized.split("/")
    # Reject '..' traversal and any component with consecutive dots (3+)
    for part in parts:
        if part == "..":
            return ""
        if re.match(r"^\.{3,}$", part):
            return ""
    # Strip leading/trailing slashes after validation
    sanitized = normalized.strip("/")
    return sanitized


def _is_safe_path(full_path: str, config_dir: str) -> bool:
    """Verify resolved path is within the HA config directory."""
    real = os.path.realpath(full_path)
    config_real = os.path.realpath(config_dir)
    # Must be within config dir and not equal to it (no accessing config dir itself)
    return real.startswith(config_real + os.sep) or real == config_real


def _list_files(config_dir: str, ext: str, depth: int) -> list[str]:
    """List files matching extension in config directory."""
    results = []
    config_dir = os.path.realpath(config_dir)

    for dirpath, dirnames, filenames in os.walk(config_dir):
        # Calculate current depth relative to config_dir
        rel = os.path.relpath(dirpath, config_dir)
        if rel == ".":
            current_depth = 0
        else:
            current_depth = rel.count(os.sep) + 1

        # Prune directories we don't want to descend into
        dirnames[:] = [
            d for d in dirnames
            if d not in _SKIP_DIRS and not d.startswith(".")
            and current_depth < depth
        ]

        for fname in filenames:
            if ext == "all":
                if not any(fname.endswith("." + e) for e in _ALLOWED_EXT):
                    continue
            else:
                if not (fname.endswith("." + ext) or
                        (ext == "yaml" and fname.endswith(".yml"))):
                    continue

            rel_path = os.path.relpath(os.path.join(dirpath, fname), config_dir)
            results.append(rel_path)

    results.sort()
    return results


def _read_file(filepath: str) -> str:
    """Read file content as UTF-8."""
    with open(filepath, encoding="utf-8") as f:
        return f.read()


def _write_file(filepath: str, content: str, orig_stat=None) -> None:
    """Write file safely with temp file + atomic rename."""
    tmp_path = filepath + ".woow_tmp"
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, filepath)
        if orig_stat:
            os.chmod(filepath, stat.S_IMODE(orig_stat.st_mode))
            try:
                os.chown(filepath, orig_stat.st_uid, orig_stat.st_gid)
            except (PermissionError, OSError):
                pass
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        raise


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/ws",
        vol.Required("action"): vol.In(["list", "load", "save"]),
        vol.Optional("path", default=""): str,
        vol.Optional("content", default=""): str,
        vol.Optional("depth", default=10): int,
        vol.Optional("ext", default="yaml"): str,
    }
)
@websocket_api.async_response
async def handle_woow_knx_ws(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    """Handle WebSocket commands for file editing.

    All operations are scoped to the component's subdirectory
    (config_dir/CONFIG_SUBDIR/) to prevent cross-component file access.
    """
    action = msg["action"]
    config_dir = hass.config.path()
    scoped_dir = os.path.join(config_dir, CONFIG_SUBDIR)

    if action == "list":
        ext = msg["ext"]
        if ext not in _ALLOWED_EXT and ext != "all":
            ext = "yaml"
        try:
            files = await hass.async_add_executor_job(
                _list_files, scoped_dir, ext, msg["depth"]
            )
            connection.send_result(msg["id"], {"files": files})
        except Exception as err:
            _LOGGER.exception("Failed to list files")
            connection.send_error(msg["id"], "list_failed", str(err))

    elif action == "load":
        raw_path = _sanitize_path(msg["path"])
        if not raw_path:
            connection.send_error(msg["id"], "invalid_path", "Path is empty")
            return
        full_path = os.path.join(scoped_dir, raw_path)
        if not _is_safe_path(full_path, scoped_dir):
            connection.send_error(msg["id"], "invalid_path",
                                  f"Path outside {CONFIG_SUBDIR}/ directory")
            return
        try:
            content = await hass.async_add_executor_job(_read_file, full_path)
            connection.send_result(msg["id"], {"content": content, "path": raw_path})
        except FileNotFoundError:
            connection.send_error(msg["id"], "file_not_found", f"File not found: {raw_path}")
        except UnicodeDecodeError:
            connection.send_error(msg["id"], "decode_error", f"Cannot read (not UTF-8): {raw_path}")
        except Exception as err:
            _LOGGER.exception("Failed to load file: %s", raw_path)
            connection.send_error(msg["id"], "load_failed", str(err))

    elif action == "save":
        raw_path = _sanitize_path(msg["path"])
        if not raw_path:
            connection.send_error(msg["id"], "invalid_path", "Path is empty")
            return
        full_path = os.path.join(scoped_dir, raw_path)
        if not _is_safe_path(full_path, scoped_dir):
            connection.send_error(msg["id"], "invalid_path",
                                  f"Path outside {CONFIG_SUBDIR}/ directory")
            return
        content = msg["content"]
        try:
            # Preserve original file permissions if it exists
            orig = None
            if os.path.exists(full_path):
                orig = os.stat(full_path)
            await hass.async_add_executor_job(_write_file, full_path, content, orig)
            connection.send_result(msg["id"], {"success": True, "path": raw_path})
            _LOGGER.info("Saved file: %s/%s", CONFIG_SUBDIR, raw_path)
        except Exception as err:
            _LOGGER.exception("Failed to save file: %s/%s", CONFIG_SUBDIR, raw_path)
            connection.send_error(msg["id"], "save_failed", str(err))
