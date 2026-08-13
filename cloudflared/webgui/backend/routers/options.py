"""Read/write the add-on's Supervisor options — the single source of truth.

PUT semantics for ``tunnel_token``:
- field omitted or ``null``  → keep the currently stored token (if any)
- empty string ``""``        → remove the token (switch to local-managed mode)
- non-empty string           → store the new token (remote-managed mode)

The Supervisor validates the options against the add-on schema on write; a
schema rejection surfaces as an HTTP error with the Supervisor's message.
"""
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from ..instances import supervisor
from ..models import AddonOptions, OptionsRead
from ..supervisor import SupervisorError

router = APIRouter(prefix="/api", tags=["options"])

MINIMAL_CONFIG_MSG = (
    "Cannot run without tunnel_token, external_hostname, additional_hosts, "
    "catch_all_service or nginx_proxy_manager. Please set at least one of "
    "these options."
)


def ensure_minimal_config(options: dict) -> None:
    """Reject configurations the forked prepare script cannot run with.

    Runs AFTER the stored token has been merged in, so token-mode users can
    save unrelated changes without re-entering their token.
    """
    if (options.get("tunnel_token") or "").strip():
        return
    if (
        (options.get("external_hostname") or "").strip()
        or options.get("additional_hosts")
        or (options.get("catch_all_service") or "").strip()
        or options.get("nginx_proxy_manager")
    ):
        return
    raise HTTPException(422, MINIMAL_CONFIG_MSG)


@router.get("/options", response_model=OptionsRead)
async def get_options() -> OptionsRead:
    try:
        options = await supervisor.get_options()
    except SupervisorError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    return OptionsRead.from_supervisor(options)


@router.put("/options")
async def put_options(
    body: AddonOptions,
    background: BackgroundTasks,
    restart: bool = Query(
        default=False,
        description="Restart the add-on after saving so the options take "
        "effect (identical to pressing SAVE + RESTART on the HA "
        "configuration page).",
    ),
) -> dict:
    try:
        current = await supervisor.get_options()
    except SupervisorError as exc:
        raise HTTPException(exc.status, str(exc)) from exc

    options = body.to_supervisor_options()

    # Token keep/remove/replace semantics (see module docstring).
    if body.tunnel_token is None:
        existing = (current.get("tunnel_token") or "").strip()
        if existing:
            options["tunnel_token"] = existing

    ensure_minimal_config(options)

    try:
        await supervisor.set_options(options)
    except SupervisorError as exc:
        raise HTTPException(exc.status, str(exc)) from exc

    restarting = False
    if restart:
        restarting = True
        # Restart AFTER the response is sent, so the GUI reliably receives
        # the save confirmation before this backend goes down.
        background.add_task(supervisor.restart_self)

    return {"result": "ok", "restarting": restarting}


@router.post("/restart")
async def restart_addon(background: BackgroundTasks) -> dict:
    """Restart the whole add-on (prepare re-runs, config re-applies)."""
    background.add_task(supervisor.restart_self)
    return {"result": "ok", "restarting": True}
