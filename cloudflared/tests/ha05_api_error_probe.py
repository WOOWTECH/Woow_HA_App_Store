#!/usr/bin/env python3
"""Isolated HTTP/WS probe. All Supervisor data is synthetic; no HA connection.
Only summaries and marker counts leave this process. Runtime dependencies are
already provided by the addon image. Optional argv[1] is a source webgui path.
"""
import asyncio, base64, contextlib, json, logging, os, socket, sys
os.environ["SUPERVISOR_TOKEN"] = ""
os.environ["SUPERVISOR_API"] = "http://127.0.0.1:1"
os.environ["WEBGUI_DEV"] = "0"
os.environ["ADDON_DATA"] = "/nonexistent-ha05-synthetic"
os.environ["WEBGUI_MARKER_DIR"] = "/nonexistent-ha05-synthetic"
if len(sys.argv) > 1: sys.path.insert(0, sys.argv[1])
else: sys.path.insert(0, "/opt/webgui")
logging.disable(logging.CRITICAL)
import aiohttp, uvicorn
from backend.main import app
from backend.instances import supervisor, logwatcher
from backend.supervisor import SupervisorError, SupervisorClient
from backend import metrics
from backend.models import TunnelStatus

async def main():
    marker = "HA05_SYNTHETIC_PRIVATE_MARKER_20261022"
    token = base64.b64encode(json.dumps({"a":"synthetic", "t":"synthetic", "s":marker}).encode()).decode()
    needles = [marker, token]
    storage = {"external_hostname":"", "additional_hosts":[], "tunnel_token":token}
    mode = {"fail":False, "writes":0}
    async def get_options():
        if mode["fail"]: raise SupervisorError(marker + " " + token, 400)
        return dict(storage)
    async def set_options(value):
        if mode["fail"]: raise SupervisorError(marker + " " + token, 400)
        mode["writes"] += 1
        storage.clear(); storage.update(value)
    async def info(): return {"version":"synthetic", "state":"started", "options":dict(storage)}
    async def ping(): return True
    async def tunnel_status(): return TunnelStatus(status="stopped", ready_connections=0, metrics_reachable=False)
    async def noop(): pass
    async def reject_restart(*args, **kwargs): raise SupervisorError(marker + " " + token, 400)
    supervisor.get_options=get_options; supervisor.set_options=set_options
    supervisor.self_info=info; supervisor.ping=ping; supervisor._request=reject_restart
    logwatcher.start=noop; logwatcher.stop=noop; metrics.tunnel_status=tunnel_status
    logwatcher._lines.clear()
    logwatcher._ingest("cloudflared run --token=" + token)
    logwatcher._ingest('{"TunnelSecret":"' + marker + '"}')
    cases=[]
    def record(name, status, body, expected, **checks):
        count=sum(body.count(n) for n in needles)
        cases.append({"case":name,"http_status":status,"marker_count":count,
                      "passed":status==expected and count==0 and all(checks.values()), **checks})
    sock=socket.socket(); sock.bind(("127.0.0.1",0)); sock.listen(32)
    port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(app, log_config=None, access_log=False, lifespan="off"))
    task=asyncio.create_task(server.serve(sockets=[sock]))
    try:
        for _ in range(200):
            if server.started: break
            await asyncio.sleep(.01)
        if not server.started: raise RuntimeError("startup")
        async with aiohttp.ClientSession(base_url=f"http://127.0.0.1:{port}") as client:
            async def check(name, method, path, expected, payload=None, **checks):
                async with client.request(method,path,json=payload) as resp:
                    body=await resp.text(); record(name,resp.status,body,expected,**checks)
            await check("masked_options", "GET", "/api/options", 200)
            await check("invalid_token_validation", "PUT", "/api/options", 422, {"tunnel_token":marker})
            await check("cross_field_validation", "PUT", "/api/options", 422,
                        {"tunnel_token":token,"catch_all_service":"http://example.invalid","nginx_proxy_manager":True})
            await check("invalid_hostname_validation", "PUT", "/api/options", 422,
                        {"tunnel_token":token,"external_hostname":"https://"+marker})
            await check("invalid_parameter_validation", "PUT", "/api/options", 422,
                        {"tunnel_token":token,"run_parameters":["--not-allowed="+marker]})
            cases.append({"case":"validation_no_write","marker_count":0,"passed":mode["writes"]==0})
            mode["fail"]=True
            await check("supervisor_get_error", "GET", "/api/options",400)
            mode["fail"]=False
            original_set=supervisor.set_options
            async def reject_set(value): raise SupervisorError(marker+" "+token,400)
            supervisor.set_options=reject_set
            await check("supervisor_save_error", "PUT", "/api/options",400,{"log_level":"debug"})
            supervisor.set_options=original_set
            await check("save_preserves_token", "PUT", "/api/options",200,{"log_level":"debug"})
            cases.append({"case":"stored_token_unchanged","marker_count":0,"passed":storage.get("tunnel_token")==token})
            await check("logs_snapshot", "GET", "/api/logs",200)
            async with client.ws_connect("/api/logs/stream") as ws:
                msgs=[(await ws.receive(timeout=3)).data for _ in range(2)]
                record("logs_websocket",101,"\n".join(msgs),101)
            await supervisor.restart_self()
            await check("restart_error_health", "GET", "/api/health",200)
            await check("wizard_state", "GET", "/api/wizard/state",200)
            if os.path.isdir(os.environ.get("WEBGUI_STATIC","/opt/webgui/static")):
                await check("frontend_static_root", "GET", "/",200)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError): await task
        sock.close()
        await supervisor.close()
    print(json.dumps({"scope":"isolated HTTP/WS with synthetic Supervisor; no live HA", "cases":cases,
                      "passed":all(c["passed"] for c in cases),"raw_responses_saved":False,"raw_logs_saved":False},sort_keys=True))
    return 0 if all(c["passed"] for c in cases) else 1
if __name__=="__main__":
    try: raise SystemExit(asyncio.run(main()))
    except Exception as exc:
        print(json.dumps({"passed":False,"error_class":type(exc).__name__})); raise SystemExit(2)
