"""Executable product boundary (Odoo, Odoo Manage, Hermes, OpenDesign, EMQX, LiteLLM, Nextcloud) with approved, fail-closed HA admin verification.

PYTHONPATH=packages/mcp-admin-core .venv/bin/python -m mcp_admin_core.run_product emqx
GUI owns typed connection/token/policy. CLI owns deployment fields only.
"""
import argparse
import asyncio
from contextlib import contextmanager
from pathlib import Path
import signal

import httpx
import uvicorn

from . import redact
from .config import ConfigError
from .configuration import ConfigurationState
from .capabilities import ManagementOptions
from .gateway import make_apps
from .ha_role import make_ha_admin_verifier
from .health import HealthMonitor
from .lifecycle import Supervisor
from .products import INSTRUCTIONS, PRODUCTS, ProductStore, TOOLS, child_spec
from .surface import FULL_PRODUCTS, listing


class Listener(uvicorn.Server):
    @contextmanager
    def capture_signals(self):
        yield


async def run(args):
    from .upgrade import run_upgrade_review
    if not await run_upgrade_review(args, args.product):
        return
    store = ProductStore(args.data, args.product)
    manager = None
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    try:
        manager = Supervisor(None)
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)
        async with httpx.AsyncClient(trust_env=False, follow_redirects=False,
                                    timeout=httpx.Timeout(10, connect=3),
                                    limits=httpx.Limits(max_connections=40)) as child:
            health = HealthMonitor(store, manager, child)
            configuration = ConfigurationState(store, manager, health)

            async def backend_changed(state):
                configuration.begin(state)
                health.backend = 'unknown'
                try:
                    # Stop before validating a replacement: old credentials must
                    # never continue serving newly saved state after a failure.
                    await manager.stop()
                    manager.spec = child_spec(state, store.directory)
                    await manager.start()
                except Exception:
                    configuration.failed('child_start_failed')
                    raise

            admin, mcp = make_apps(store, TOOLS[args.product], child,
                                  verify_admin=make_ha_admin_verifier(),
                                  health=health.snapshot, backend_changed=backend_changed, configuration=configuration,
                                  management=ManagementOptions(kind="ha-addon", authority="ha-admin"),
                                  backend_check=getattr(health, "test_saved", None), restart_child=backend_changed, diagnostics=getattr(manager, "diagnostics", None),
                                  server_name='woow-mcp-' + args.product, instructions=INSTRUCTIONS.get(args.product),
                                  # 0.2.2: clients connect without a backend or a running child (Odoo Manage: unchanged)
                                  listing=listing(args.product) if args.product in FULL_PRODUCTS else None,
                                  availability=health.availability)
            servers = [Listener(uvicorn.Config(app, host=args.host, port=port,
                proxy_headers=False, access_log=False, log_level='warning', server_header=False,
                lifespan='off', limit_concurrency=64, timeout_keep_alive=5))
                for app, port in ((admin, args.admin_port), (mcp, args.mcp_port))]
            # 0.1.12: /private_<token>/mcp puts the token in the request path. access_log stays False; every record
            # (uvicorn's error log, tracebacks, any library) is scrubbed to /private_[REDACTED]/ when created and
            # again by uvicorn's handlers.
            redact.install()
            redact.guard_handlers(*redact.UVICORN_LOGGERS)
            try:
                await backend_changed(store.load())
            except Exception:
                # Keep authenticated management available to report/retry a
                # fixed launch failure; never echo third-party exception text.
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('product', choices=PRODUCTS)
    parser.add_argument('--data', type=Path, default=Path('/data/mcp'))
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--admin-port', type=int, default=8099)
    parser.add_argument('--mcp-port', type=int, default=8081)
    args = parser.parse_args()
    if args.admin_port == args.mcp_port or 3000 in (args.admin_port, args.mcp_port):
        parser.error('listeners must be distinct and cannot use child port 3000')
    try:
        asyncio.run(run(args))
    except (ConfigError, RuntimeError):
        raise SystemExit('runtime unavailable; local recovery required') from None


if __name__ == '__main__':
    main()
