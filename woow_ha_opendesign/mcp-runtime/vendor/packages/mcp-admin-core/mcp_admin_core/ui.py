"""Fixed, self-hosted management build. No fixture or configurable document root."""
from pathlib import Path
import os
import re
import stat

from starlette.responses import Response

UI_ROOT = Path(__file__).resolve().parents[2] / "mcp-admin-ui" / "dist"
HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; connect-src 'self'; img-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'self'",
}
PAGES = {"/", "/overview", "/backend", "/tools", "/access"}
TYPES = {".js": "text/javascript", ".css": "text/css", ".woff": "font/woff", ".woff2": "font/woff2", ".ttf": "font/ttf", ".eot": "application/vnd.ms-fontobject", ".txt": "text/plain"}


def response(path, base):
    page = path in PAGES
    relative = "index.html" if page else path.lstrip("/")
    if not page and (not path.startswith(("/assets/", "/licenses/")) or
                     not re.fullmatch(r"(?:[A-Za-z0-9_-]+/)+[A-Za-z0-9_.-]+", relative) or
                     any(p in (".", "..") for p in relative.split("/")) or
                     Path(relative).suffix not in TYPES):
        return Response(status_code=404)
    # Walk directory descriptors: no symlink, including the dist root. No open of
    # arbitrary data paths, and no FileResponse reopen race after authorization.
    fds = []
    try:
        fd = os.open(UI_ROOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        fds.append(fd)
        parts = relative.split("/")
        for part in parts[:-1]:
            fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            fds.append(fd)
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        fds.append(fd)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > 8 * 1024 * 1024:
            return Response(status_code=503)
        with os.fdopen(os.dup(fd), "rb") as stream:
            content = stream.read(8 * 1024 * 1024 + 1)
        if len(content) > 8 * 1024 * 1024:
            return Response(status_code=503)
        if page:
            content = content.decode("utf-8")
            if "__MCP_UI_BASE__" not in content:
                return Response(status_code=503)
            content = content.replace("__MCP_UI_BASE__", base)
        return Response(content, media_type="text/html" if page else TYPES[Path(relative).suffix])
    except (OSError, UnicodeError):
        return Response(status_code=503 if page else 404)
    finally:
        for fd in reversed(fds):
            os.close(fd)


class SecurityHeaders:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        async def secured(message):
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message.get("headers", []) if k.decode().lower() not in {h.lower() for h in HEADERS}]
                message["headers"] = headers + [(k.lower().encode(), v.encode()) for k, v in HEADERS.items()]
            await send(message)
        await self.app(scope, receive, secured)
