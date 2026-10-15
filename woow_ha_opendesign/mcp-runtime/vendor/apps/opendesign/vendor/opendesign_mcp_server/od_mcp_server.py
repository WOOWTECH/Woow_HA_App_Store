#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# Copied from woow-mcp-server@614ae663 (app MIT notice retained).
# Original header claimed upstream d6d157a; independent provenance pending.
# Local change: require explicit daemon URL, never use a private default host.
# ---------------------------------------------------------------------------
"""Open Design MCP Server — exposes OD daemon API as MCP tools.

Runs in stdio mode. Supergateway converts to StreamableHttp.
Connects to the explicitly configured daemon at OD_API_BASE.
"""
import json
import os
import uuid

import httpx
from backend_policy import sync_client, backend_errors
from mcp.server.fastmcp import FastMCP

OD_API_BASE = os.environ["OD_API_BASE"]

# Chat operations can take minutes (AI agent generates code)
CHAT_TIMEOUT = float(os.environ.get("OD_CHAT_TIMEOUT", "300"))

mcp = FastMCP("Open Design MCP Server")
_client: httpx.Client | None = None


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = sync_client(base_url=OD_API_BASE, timeout=5.0)
    return _client


def _api_get(path: str) -> dict:
    """GET request to OD daemon API."""
    resp = _get_client().get(path)
    resp.raise_for_status()
    return resp.json()


def _api_post(path: str, data: dict | None = None) -> dict:
    """POST request to OD daemon API."""
    resp = _get_client().post(path, json=data or {})
    resp.raise_for_status()
    return resp.json()


def _api_post_sse(
    path: str,
    data: dict | None = None,
) -> dict:
    """POST request that consumes an SSE (event-stream) response.

    The OD daemon /api/chat returns Server-Sent Events. We stream through
    all events, collecting agent text output, and return a structured result
    once the stream ends.
    """
    client = sync_client(base_url=OD_API_BASE, timeout=httpx.Timeout(CHAT_TIMEOUT, connect=5.0))
    try:
        with client.stream("POST", path, json=data or {}) as resp:
            resp.raise_for_status()

            run_id = None
            project_id = None
            status = "unknown"
            agent_text = []
            errors = []

            for line in resp.iter_lines():
                # SSE data lines: "data: {...}" or "data:{...}"
                if line.startswith("data:"):
                    json_str = line[5:].lstrip()
                    if not json_str:
                        continue
                    try:
                        payload = json.loads(json_str)
                    except json.JSONDecodeError:
                        continue

                    # Extract run metadata from "start" event
                    if "runId" in payload:
                        run_id = payload["runId"]
                        project_id = payload.get("projectId")

                    # Collect agent text deltas
                    if payload.get("type") == "text_delta":
                        agent_text.append(payload.get("delta", ""))

                    # Capture errors
                    if "error" in payload and isinstance(payload["error"], dict):
                        errors.append(payload["error"].get("message", str(payload["error"])))

                    # Capture final status
                    if "status" in payload and "code" in payload:
                        status = payload["status"]

            result = {
                "runId": run_id,
                "projectId": project_id,
                "status": status,
            }
            if agent_text:
                result["agentResponse"] = "".join(agent_text)
            if errors:
                result["errors"] = errors
                result["status"] = "failed"
            return result
    finally:
        client.close()


def _api_delete(path: str) -> dict:
    """DELETE request to OD daemon API."""
    resp = _get_client().delete(path)
    resp.raise_for_status()
    return resp.json()


def _register_project(project_id: str, prompt: str) -> None:
    """Register a project in the daemon's SQLite DB.

    The daemon's /api/chat creates the project directory on disk but does NOT
    insert a row into the projects table. Without registration, the project
    is invisible to list_projects / get_project.
    """
    # Derive a short name from the first line of the prompt (max 80 chars)
    name = prompt.strip().split("\n")[0][:80] or "Untitled Project"
    try:
        _api_post("/api/projects", {"id": project_id, "name": name})
    except httpx.HTTPStatusError:
        # Best-effort: if registration fails (e.g. already registered),
        # the project files still exist and are accessible.
        pass


# ═══════════════════════════════════════════════════════════════════
# Category A: System Tools (4)
# ═══════════════════════════════════════════════════════════════════


@mcp.tool()
@backend_errors
def health() -> dict:
    """Check Open Design daemon health status and version."""
    return _api_get("/api/health")


@mcp.tool()
@backend_errors
def version() -> dict:
    """Get detailed daemon version info (version, channel, platform, arch)."""
    return _api_get("/api/version")


@mcp.tool()
@backend_errors
def list_agents() -> dict:
    """List all available AI agent CLIs (Claude Code, OpenCode, BYOK).

    Returns agent IDs, names, versions, availability status, and paths.
    """
    data = _api_get("/api/agents")
    # Filter to show only available agents for clarity
    available = [a for a in data.get("agents", []) if a.get("available")]
    return {
        "available_agents": available,
        "total_defined": len(data.get("agents", [])),
        "total_available": len(available),
    }


@mcp.tool()
def list_connectors() -> dict:
    """List available external connectors (GitHub, etc.) and their tools."""
    return _api_get("/api/connectors")


# ═══════════════════════════════════════════════════════════════════
# Category B: Project Tools (5)
# ═══════════════════════════════════════════════════════════════════


@mcp.tool()
@backend_errors
def list_projects() -> dict:
    """List all design projects with their status, creation time, and metadata."""
    return _api_get("/api/projects")


@mcp.tool()
@backend_errors
def get_project(project_id: str) -> dict:
    """Get detailed information about a specific project by ID.

    Args:
        project_id: UUID of the project (e.g. '38c010dc-f7c8-4a35-a325-89d6f56e45a4')
    """
    return _api_get(f"/api/projects/{project_id}")


@mcp.tool()
def create_project(prompt: str, agent_id: str = "claude") -> dict:
    """Create a new design project by sending an initial prompt to an AI agent.

    This is a long-running operation — the AI agent will generate code/design
    and the call blocks until completion (up to 5 minutes).

    Args:
        prompt: The initial design prompt (e.g. 'Create a landing page for a coffee shop')
        agent_id: Agent CLI to use ('claude', 'opencode', 'byok-opencode'). Default: 'claude'
    """
    # Generate a project ID upfront so the daemon creates the project directory
    # and the agent writes files there. Without this, the agent writes to
    # /home/opendesign/ and the project is not discoverable.
    project_id = str(uuid.uuid4())
    result = _api_post_sse("/api/chat", {
        "message": prompt,
        "agentId": agent_id,
        "projectId": project_id,
    })
    # Ensure projectId is always set (the daemon echoes it back in the SSE
    # start event, but as a safety net we set it here too).
    if not result.get("projectId"):
        result["projectId"] = project_id

    # Register the project in the daemon's SQLite DB so list_projects /
    # get_project work. The daemon's /api/chat creates the directory but
    # does NOT insert a row into the projects table.
    _register_project(project_id, prompt)

    return result


@mcp.tool()
@backend_errors
def delete_project(project_id: str) -> dict:
    """Permanently delete a project and all its files. This action cannot be undone.

    Args:
        project_id: UUID of the project to delete
    """
    return _api_delete(f"/api/projects/{project_id}")


@mcp.tool()
@backend_errors
def list_project_files(project_id: str) -> dict:
    """List all files in a project directory with metadata (name, size, type, mime).

    Args:
        project_id: UUID of the project
    """
    return _api_get(f"/api/projects/{project_id}/files")


# ═══════════════════════════════════════════════════════════════════
# Category C: File Tools (2)
# ═══════════════════════════════════════════════════════════════════


@mcp.tool()
def read_file(project_id: str, file_path: str) -> str:
    """Read the raw content of a file from a project.

    Args:
        project_id: UUID of the project
        file_path: Relative path of the file within the project (e.g. 'index.html')
    """
    resp = _get_client().get(f"/api/projects/{project_id}/files/{file_path}")
    resp.raise_for_status()
    return resp.text


@mcp.tool()
@backend_errors
def get_file_info(project_id: str, file_path: str) -> dict:
    """Get metadata about a specific file (size, mime type, artifact info).

    Args:
        project_id: UUID of the project
        file_path: Relative path of the file
    """
    data = _api_get(f"/api/projects/{project_id}/files")
    for f in data.get("files", []):
        if f.get("path") == file_path or f.get("name") == file_path:
            return f
    return {"error": f"File '{file_path}' not found in project"}


# ═══════════════════════════════════════════════════════════════════
# Category D: AI Chat Tools (2)
# ═══════════════════════════════════════════════════════════════════


@mcp.tool()
def send_message(
    project_id: str,
    prompt: str,
    agent_id: str = "claude",
) -> dict:
    """Send a follow-up message in an existing project's conversation.

    This is a long-running operation — the AI agent will process the message
    and the call blocks until completion (up to 5 minutes).

    Args:
        project_id: UUID of the project to continue
        prompt: The message to send to the AI agent
        agent_id: Agent CLI to use. Default: 'claude'
    """
    result = _api_post_sse("/api/chat", {
        "message": prompt,
        "agentId": agent_id,
        "projectId": project_id,
    })
    # Ensure projectId is always set for send_message (caller already knows it)
    if not result.get("projectId"):
        result["projectId"] = project_id
    return result


@mcp.tool()
@backend_errors
def list_runs() -> dict:
    """List all active and completed AI agent runs."""
    from output_policy import rows
    return rows(_api_get("/api/runs"), 'runs', ('id', 'projectId', 'status'))


# ═══════════════════════════════════════════════════════════════════
# Category E: Content Tools (2)
# ═══════════════════════════════════════════════════════════════════


@mcp.tool()
@backend_errors
def list_plugins() -> dict:
    """List all available plugins and templates (video, design, etc.)."""
    data = _api_get("/api/plugins")
    # Return summary instead of full plugin data (can be very large)
    plugins = data.get("plugins", [])
    return {
        "total": len(plugins),
        "plugins": [
            {
                "id": p["id"],
                "title": p.get("title", p["id"]),
                "source": p.get("sourceKind", "unknown"),
                "trust": p.get("trust", "unknown"),
            }
            for p in plugins
        ],
    }


@mcp.tool()
@backend_errors
def list_skills() -> dict:
    """List all available design skills and their triggers."""
    data = _api_get("/api/skills")
    skills = data.get("skills", [])
    return {
        "total": len(skills),
        "skills": [
            {
                "id": s["id"],
                "name": s.get("name", s["id"]),
                "description": s.get("description", ""),
                "mode": s.get("mode", ""),
                "surface": s.get("surface", ""),
                "triggers": s.get("triggers", [])[:5],
            }
            for s in skills
        ],
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
