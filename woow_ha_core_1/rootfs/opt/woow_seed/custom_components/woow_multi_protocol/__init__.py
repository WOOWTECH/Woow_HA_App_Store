"""Woow Multi-Protocol Connect — one integration, one tabbed panel.

Registers a single sidebar panel whose visible tabs are the protocols enabled in
the entry's options, serves the frontend bundle, and exposes the file-editing
seam that KNX / DMX / Modbus share:

* a WebSocket command (``woow_multi_protocol/ws``) carrying a ``protocol`` field,
* the ``list_files`` / ``load_file`` / ``save_file`` / ``apply`` services
  (see ``services.py``), likewise keyed by ``protocol``.

Every file operation is confined to ``<config>/woow_multi_protocol/<protocol>/``
by the two-layer path guard below (ADR-0001), and ``apply`` reloads the
underlying integration rather than restarting HA (ADR-0002). The domain rename
and single-integration shape are ADR-0003.
"""

import logging
import os
import re
import stat
import time

from homeassistant.components import frontend, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
import voluptuous as vol

from .const import (
    BASE_SUBDIR,
    DOMAIN,
    PANEL_COMPONENT_NAME,
    PANEL_ICON,
    PANEL_TITLE,
    PROTOCOLS,
    enabled_protocols,
)

_LOGGER = logging.getLogger(__name__)

# Directories to skip when listing files.
_SKIP_DIRS = {
    ".storage", ".cloud", ".git", "__pycache__", "deps", "tts",
    "node_modules", ".venv",
}

# Allowed file extensions for listing.
_ALLOWED_EXT = {"yaml", "yml", "py", "json", "conf", "js", "txt", "log", "css", "jinja"}


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up from YAML (unused — this integration is config-entry only)."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Woow Multi-Protocol Connect from its singleton config entry."""
    hass.data.setdefault(DOMAIN, {})

    protocols = enabled_protocols(entry.options)

    # Serve the integration's frontend bundle.
    panel_dir = os.path.join(os.path.dirname(__file__), "frontend")
    await hass.http.async_register_static_paths(
        [StaticPathConfig(f"/{DOMAIN}/frontend", panel_dir, cache_headers=False)]
    )

    # Ensure each enabled protocol's sandbox subdirectory exists.
    for protocol in protocols:
        os.makedirs(_scoped_dir(hass, protocol), exist_ok=True)

    # Register the single sidebar panel. The enabled protocols travel in the
    # panel config so the frontend renders exactly those tabs.
    frontend.async_register_built_in_panel(
        hass,
        component_name="custom",
        sidebar_title=PANEL_TITLE,
        sidebar_icon=PANEL_ICON,
        frontend_url_path=DOMAIN,
        require_admin=False,
        config={
            "_panel_custom": {
                "name": PANEL_COMPONENT_NAME,
                "module_url": f"/{DOMAIN}/frontend/{PANEL_COMPONENT_NAME}.js",
                "embed_iframe": False,
            },
            "enabled_protocols": protocols,
        },
    )

    # Translate the sidebar title to match HA's language on every page.
    cache_buster = int(time.time())
    frontend.add_extra_js_url(
        hass, f"/{DOMAIN}/frontend/sidebar-title.js?v={cache_buster}"
    )

    # Register the WebSocket API for YAML file editing (protocol-keyed).
    websocket_api.async_register_command(hass, handle_ws)

    # Register the MCP-facing service layer. Imported lazily to avoid a circular
    # import (services.py reuses the file helpers defined in this module).
    from .services import register_services

    register_services(hass)

    # An Options change (enable/disable a protocol) reloads the entry so the
    # panel's tab set is rebuilt.
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    _LOGGER.info(
        "Woow Multi-Protocol Connect panel registered (protocols: %s)",
        ", ".join(protocols) or "none",
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the config entry and remove the panel."""
    frontend.async_remove_panel(hass, DOMAIN)

    from .services import unregister_services

    unregister_services(hass)

    _LOGGER.info("Woow Multi-Protocol Connect panel removed")
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when its options change, rebuilding the panel tabs."""
    await hass.config_entries.async_reload(entry.entry_id)


# ---------------------------------------------------------------------------
# Path security + file helpers (shared by the WebSocket API and services.py)
# ---------------------------------------------------------------------------

def _scoped_dir(hass: HomeAssistant, protocol: str) -> str:
    """Absolute path of a protocol's sandboxed config subdirectory.

    ``<config>/woow_multi_protocol/<protocol>/`` — the sole directory any file
    operation for that protocol may touch.
    """
    return os.path.join(hass.config.path(BASE_SUBDIR), protocol)


def _sanitize_path(raw: str) -> str:
    """Validate and normalize path, rejecting any traversal attempts (ADR-0001)."""
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
    """Verify resolved path is within the sandbox directory (ADR-0001 layer 2)."""
    real = os.path.realpath(full_path)
    config_real = os.path.realpath(config_dir)
    # Must be within the sandbox and not equal to it (no accessing the dir itself)
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
            except (PermissionError, OSError, AttributeError):
                pass
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        raise


# ---------------------------------------------------------------------------
# WebSocket handler for YAML file editing
# ---------------------------------------------------------------------------

@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/ws",
        vol.Required("protocol"): vol.In(PROTOCOLS),
        vol.Required("action"): vol.In(["list", "load", "save"]),
        vol.Optional("path", default=""): str,
        vol.Optional("content", default=""): str,
        vol.Optional("depth", default=10): int,
        vol.Optional("ext", default="yaml"): str,
    }
)
@websocket_api.async_response
async def handle_ws(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    """Handle WebSocket commands for file editing.

    Every operation is scoped to the requested protocol's subdirectory
    (``<config>/woow_multi_protocol/<protocol>/``) so one protocol's files can
    never reach another's.
    """
    action = msg["action"]
    protocol = msg["protocol"]
    scoped_dir = _scoped_dir(hass, protocol)

    if action == "list":
        ext = msg["ext"]
        if ext not in _ALLOWED_EXT and ext != "all":
            ext = "yaml"
        try:
            files = await hass.async_add_executor_job(
                _list_files, scoped_dir, ext, msg["depth"]
            )
            connection.send_result(msg["id"], {"files": files})
        except Exception as err:  # noqa: BLE001 - surfaced to the caller
            _LOGGER.exception("Failed to list files")
            connection.send_error(msg["id"], "list_failed", str(err))

    elif action == "load":
        raw_path = _sanitize_path(msg["path"])
        if not raw_path:
            connection.send_error(msg["id"], "invalid_path", "Path is empty")
            return
        full_path = os.path.join(scoped_dir, raw_path)
        if not _is_safe_path(full_path, scoped_dir):
            connection.send_error(
                msg["id"], "invalid_path", f"Path outside {protocol}/ directory"
            )
            return
        try:
            content = await hass.async_add_executor_job(_read_file, full_path)
            connection.send_result(msg["id"], {"content": content, "path": raw_path})
        except FileNotFoundError:
            connection.send_error(msg["id"], "file_not_found", f"File not found: {raw_path}")
        except UnicodeDecodeError:
            connection.send_error(msg["id"], "decode_error", f"Cannot read (not UTF-8): {raw_path}")
        except Exception as err:  # noqa: BLE001 - surfaced to the caller
            _LOGGER.exception("Failed to load file: %s", raw_path)
            connection.send_error(msg["id"], "load_failed", str(err))

    elif action == "save":
        raw_path = _sanitize_path(msg["path"])
        if not raw_path:
            connection.send_error(msg["id"], "invalid_path", "Path is empty")
            return
        full_path = os.path.join(scoped_dir, raw_path)
        if not _is_safe_path(full_path, scoped_dir):
            connection.send_error(
                msg["id"], "invalid_path", f"Path outside {protocol}/ directory"
            )
            return
        content = msg["content"]
        try:
            # Preserve original file permissions if it exists
            orig = None
            if os.path.exists(full_path):
                orig = os.stat(full_path)
            await hass.async_add_executor_job(_write_file, full_path, content, orig)
            connection.send_result(msg["id"], {"success": True, "path": raw_path})
            _LOGGER.info("Saved file: %s/%s/%s", BASE_SUBDIR, protocol, raw_path)
        except Exception as err:  # noqa: BLE001 - surfaced to the caller
            _LOGGER.exception("Failed to save file: %s/%s/%s", BASE_SUBDIR, protocol, raw_path)
            connection.send_error(msg["id"], "save_failed", str(err))
