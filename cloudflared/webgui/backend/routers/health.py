"""GET /api/health — supervisor connectivity, add-on state, tunnel status."""
from fastapi import APIRouter

from .. import metrics
from ..instances import supervisor
from ..models import HealthResponse
from ..supervisor import SupervisorError

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    addon_version = None
    addon_state = None
    connected = False
    try:
        info = await supervisor.self_info()
        connected = True
        addon_version = info.get("version")
        addon_state = info.get("state")
    except SupervisorError:
        connected = await supervisor.ping()

    tunnel = await metrics.tunnel_status()
    return HealthResponse(
        status="ok",
        supervisor_connected=connected,
        addon_version=addon_version,
        addon_state=addon_state,
        tunnel=tunnel,
        restart_error=supervisor.last_restart_error,
    )
