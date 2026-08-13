"""Setup wizard state.

The wizard itself is passive: all real work (login, tunnel creation, config
generation, DNS routes) is done by the forked ``prepare`` script every time
the add-on (re)starts — identical to upstream app-cloudflared. The GUI only
observes: it surfaces the Cloudflare authorization URL captured from the log
stream, and reports certificate / tunnel-file presence from /data.
"""
import json
import os
from pathlib import Path

from fastapi import APIRouter

from .. import metrics
from ..instances import logwatcher, supervisor
from ..models import WizardState
from ..supervisor import SupervisorError

router = APIRouter(prefix="/api/wizard", tags=["wizard"])

DATA_DIR = Path(os.environ.get("ADDON_DATA", "/data"))
MARKER_DIR = Path(os.environ.get("WEBGUI_MARKER_DIR", "/tmp"))


@router.get("/state", response_model=WizardState)
async def wizard_state() -> WizardState:
    try:
        options = await supervisor.get_options()
    except SupervisorError:
        options = {}

    mode = "token" if (options.get("tunnel_token") or "").strip() else "local"

    cert = DATA_DIR / "cert.pem"
    tunnel_file = DATA_DIR / "tunnel.json"
    has_cert = cert.exists()
    has_tunnel = tunnel_file.exists()
    tunnel_uuid = None
    if has_tunnel:
        try:
            tunnel_uuid = json.loads(tunnel_file.read_text()).get("TunnelID")
        except Exception:
            tunnel_uuid = None

    status = (await metrics.tunnel_status()).status

    return WizardState(
        mode=mode,
        has_cert=has_cert,
        has_tunnel=has_tunnel,
        tunnel_uuid=tunnel_uuid,
        # Only show a login URL while we are actually waiting for one.
        login_url=logwatcher.login_url if (mode == "local" and not has_cert) else None,
        tunnel_status=status,
        unconfigured=(MARKER_DIR / "webgui-unconfigured").exists(),
        prepare_failed=(MARKER_DIR / "webgui-prepare-failed").exists(),
    )
