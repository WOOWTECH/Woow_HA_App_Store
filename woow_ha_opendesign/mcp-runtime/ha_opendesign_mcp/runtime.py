"""Management process of the built-in OpenDesign MCP server (uid mcp, after management.py's guard).

Adapted from the vendored mcp_admin_core.run_product.run; the gateway apps, store, policy, child supervisor,
health monitor and HA admin verifier are the vendored ones. Local differences:

1. Fixed backend: the OpenDesign daemon in this container (BACKEND_URL). It is written into the state on every
   start and the admin API refuses PUT /api/backend, so there is no connection setting to get wrong.
2. The gateway talks to its child over CHILD_SOCKET (a Unix socket only uid mcp can open), not 127.0.0.1:3000.
   The child still sees Host 127.0.0.1:3000, which its DNS-rebinding guard accepts.
3. Administration listens on ADMIN_SOCKET. nginx (8099, the add-on's Ingress port) forwards /mcp-admin/ to it
   only from the Supervisor peer; IngressSocketPeer turns "came through that socket" into the peer address the
   vendored admin_identity() checks, which still requires one valid X-Remote-User-Id (set by Supervisor Ingress)
   and the CSRF token. Owner decision 2026-10-14: NO per-request Home Assistant role lookup (no
   homeassistant_api): the role provider passed to the vendored make_apps() is ingress_user(), which accepts every
   user Supervisor Ingress authenticated. Accepted risk: any HA user who can open this add-on's Ingress can reach
   /mcp-admin/ (the same gate as OpenDesign itself and its ttyd terminal).
4. MCP clients use 0.0.0.0:8081 exactly as with the standalone add-on: Bearer on /mcp, and the token in the path
   on /private_<token>/mcp where the pinned gateway supports it.
5. 0.2.1: the OpenDesign tool table is the PaaS server's 15 tools (surface.install(), before the store is opened),
   and the three writers are granted once by default (defaults.apply(), before any listener starts).
6. 0.2.6 (runtime 0.4.0): the state stays schema 3 (state.BuiltinStore, never the vendored ProductStore, which
   migrates to schema 4 with every write granted and every disabled tool enabled again); the gateway gets no tool
   listing of its own (listing=None: a client always reaches the real child, as before); the child is started as the
   vendored run_product starts it (through backend_changed, which records the configuration being applied for the
   MCP Server page; a start failure leaves administration up); product.runtime_version stays in the capability
   contract (capability_snapshot below).
"""
import asyncio
import dataclasses
import os
from pathlib import Path
import re
import signal

import httpx
import uvicorn
from starlette.responses import JSONResponse

from mcp_admin_core import VERSION, capabilities, gateway, redact
from mcp_admin_core.config import ConfigError
from mcp_admin_core.capabilities import ManagementOptions
from mcp_admin_core.configuration import ConfigurationState
from mcp_admin_core.gateway import make_apps
from mcp_admin_core.ha_role import valid_user_id
from mcp_admin_core.health import HealthMonitor
from mcp_admin_core.lifecycle import Supervisor
from mcp_admin_core.products import INSTRUCTIONS, TOOLS, child_spec
from mcp_admin_core.run_product import Listener

from . import ADMIN_SOCKET, BACKEND_URL, CHILD_SOCKET, DATA_DIR, INGRESS_PEER, MCP_HOST, MCP_PORT, PRODUCT
from . import defaults, surface
from .state import BuiltinStore

surface.install()
VENDORED_SNAPSHOT = capabilities.capability_snapshot


def capability_snapshot(options, state, health, catalog, **kwargs):
    """0.2.4: product.runtime_version, the pinned runtime's version (mcp_admin_core.VERSION, 0.4.0 since 0.2.6), next to
    product.version (the add-on's own, WOOW_ADDON_VERSION). The runtime pinned since 0.2.6 reports id and version only
    (the shared v1 contract); the built-in contract keeps the field it documents."""
    snapshot = VENDORED_SNAPSHOT(options, state, health, catalog, **kwargs)
    return {**snapshot, 'product': {**snapshot['product'], 'runtime_version': VERSION}}


gateway.capability_snapshot = capability_snapshot  # the name make_apps' capabilities() looks up when it answers

CHILD_ENTRY = Path(__file__).with_name('child.py')
BACKEND_WRITE = re.compile(r'(?:^|/)api/backend$')


def pin_backend(store):
    """Make the stored connection the fixed loopback daemon (first start, or state restored from elsewhere)."""
    state = store.load()
    if state.connection is None or state.connection.url != BACKEND_URL:
        store.update(connection={'url': BACKEND_URL})
    return store.load()


async def ingress_user(user_id):
    """Role provider for the vendored admin app: Ingress login is the authority (owner decision 2026-10-14).

    The vendored admin_identity() has already required the Supervisor peer and exactly one X-Remote-User-Id; this
    only re-checks its shape. No Supervisor/Core API call is made and no SUPERVISOR_TOKEN is needed.
    """
    return valid_user_id(user_id)


def builtin_child_spec(state, directory):
    """The vendored opendesign child spec (env, cwd, venv python), started through child.py on CHILD_SOCKET."""
    spec = child_spec(state, directory)
    if spec is None:
        return None
    return dataclasses.replace(spec, argv=(spec.argv[0], str(CHILD_ENTRY)),
                               env={**spec.env, 'HA_OD_MCP_CHILD_SOCKET': str(CHILD_SOCKET)})


class IngressSocketPeer:
    """ASGI wrapper used ONLY for the ADMIN_SOCKET listener.

    A Unix-socket connection has no peer address (scope client None); only nginx's group can open the socket and
    nginx forwards only the Supervisor peer, so such a request is presented to the vendored admin app as coming
    from INGRESS_PEER. A request WITH a peer address (never expected on this listener) is refused. PUT
    /api/backend is refused because the backend is fixed.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return  # lifespan is off; no WebSocket route exists on the admin app
        if scope.get('client') is not None:
            await JSONResponse({'error': 'request denied'}, status_code=403)(scope, receive, send)
            return
        if scope.get('method') == 'PUT' and BACKEND_WRITE.search(scope.get('path', '')):
            await JSONResponse({'error': 'request denied'}, status_code=403,
                               headers={'Cache-Control': 'no-store'})(scope, receive, send)
            return
        await self.app({**scope, 'client': INGRESS_PEER}, receive, send)


def management_options():
    return ManagementOptions(kind='builtin', authority='ha-ingress', backend_mode='fixed',
                             backend_can_edit=False, product_version=os.environ.get('WOOW_ADDON_VERSION', 'unknown'))


async def run():
    store = BuiltinStore(DATA_DIR)
    manager = None
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    try:
        pin_backend(store)
        record = defaults.apply(store)
        if record is not None:
            print('[ha-opendesign-mcp] tool defaults applied: granted %s; left disabled %s'
                  % (','.join(record['granted']) or 'none', ','.join(record['left_disabled']) or 'none'), flush=True)
        manager = Supervisor(None)  # started below through backend_changed, as the vendored run_product does
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)
        # With an explicit transport, connection limits belong to the transport (as run_product's client limits).
        transport = httpx.AsyncHTTPTransport(uds=str(CHILD_SOCKET), limits=httpx.Limits(max_connections=40))
        async with httpx.AsyncClient(transport=transport, trust_env=False, follow_redirects=False,
                                     timeout=httpx.Timeout(10, connect=3)) as child:
            health = HealthMonitor(store, manager, child)
            configuration = ConfigurationState(store, manager, health)

            async def backend_changed(new_state):
                # The first start and the MCP Server page's restart; a backend change is unreachable for the built-in
                # server (PUT /api/backend is refused). As the vendored run_product's.
                configuration.begin(new_state)
                health.backend = 'unknown'
                try:
                    await manager.stop()
                    manager.spec = builtin_child_spec(new_state, store.directory)
                    await manager.start()
                except Exception:
                    configuration.failed('child_start_failed')
                    raise

            admin, mcp = make_apps(store, TOOLS[PRODUCT], child,
                                   verify_admin=ingress_user,
                                   management=management_options(),
                                   backend_check=health.test_saved, restart_child=backend_changed,
                                   diagnostics=manager.diagnostics, configuration=configuration,
                                   health=health.snapshot, backend_changed=backend_changed,
                                   server_name='woow-mcp-' + PRODUCT, instructions=INSTRUCTIONS.get(PRODUCT))
            common = dict(proxy_headers=False, access_log=False, log_level='warning', server_header=False,
                          lifespan='off', limit_concurrency=64, timeout_keep_alive=5)
            servers = [Listener(uvicorn.Config(IngressSocketPeer(admin), uds=str(ADMIN_SOCKET), **common)),
                       Listener(uvicorn.Config(mcp, host=MCP_HOST, port=MCP_PORT, **common))]
            # The path of /private_<token>/mcp is a secret: scrub every log record (vendored redact).
            redact.install()
            redact.guard_handlers(*redact.UVICORN_LOGGERS)
            try:
                await backend_changed(store.load())
            except Exception:
                # Administration stays up to report the failed start (the MCP Server page) and retry it; no exception
                # text is shown (vendored run_product).
                pass
            tasks = [asyncio.create_task(server.serve()) for server in servers]
            monitor = asyncio.create_task(health.run())
            stopping = asyncio.create_task(stop.wait())
            try:
                done, _ = await asyncio.wait([*tasks, monitor, stopping], return_when=asyncio.FIRST_COMPLETED)
                if monitor in done or any(t in done for t in tasks):
                    raise RuntimeError('runtime component stopped') from None
            finally:
                for server in servers:
                    server.should_exit = True
                monitor.cancel()
                stopping.cancel()
                await asyncio.gather(monitor, stopping, return_exceptions=True)
                try:
                    async with asyncio.timeout(5):
                        await asyncio.gather(*tasks)
                except TimeoutError:
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        if manager is not None:
            await manager.stop()
        store.close()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(sig)


def main():
    try:
        asyncio.run(run())
    except (ConfigError, RuntimeError):
        raise SystemExit('built-in MCP runtime unavailable; local recovery required') from None


if __name__ == '__main__':
    main()
