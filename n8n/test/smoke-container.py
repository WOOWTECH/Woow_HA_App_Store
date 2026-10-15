#!/usr/bin/env python3
"""Smoke-test a built Woow n8n add-on image the way Supervisor runs it.

Usage: smoke-container.py <image> [--browser]

Checks, against the real image:
  * n8n becomes healthy and ready; the Supervisor watchdog endpoint answers
    from the Supervisor address only
  * the ingress rewrites hit the editor bundle this image actually serves
    (test-ingress-bundle-seam.py on the processed static files)
  * a webhook workflow runs a JavaScript and a native Python Code node in the
    external task runners; $env keeps user variables but not the Supervisor
    or task broker tokens
  * the task broker and Redis listen on loopback only, the broker token is a
    root-only per-installation file, and option secrets are not logged
  * after a restart the same token is reused and the workflow still answers
With --browser (needs Playwright + Chromium) it also signs in through a
Supervisor-like ingress proxy in headless Chromium and checks the editor.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from smoke_lib import (
    ADDON_IP,
    FAKE_SUPERVISOR_TOKEN,
    OWNER,
    SECRET_OPTION_VALUE,
    SUPERVISOR_IP,
    Addon,
    N8nClient,
    activate,
    assert_code_nodes,
    call_webhook,
    docker,
    smoke_workflow,
)

TEST_DIR = Path(__file__).resolve().parent
INGRESS_PATH = "/api/hassio_ingress/abcdefghijklmnop0123"
# Any other container on the hassio network (another add-on, HA Core).
OTHER_CLIENT_IP = "172.30.33.99"

# Every process of the add-on (skipping `docker exec` sessions such as this
# one, whose parent is outside the container) with the token-like variables
# its environment holds.
PROCESS_ENV_SCRIPT = r"""
for p in /proc/[0-9]*; do
  ppid=$(sed -n 's/^PPid:[[:space:]]*//p' "$p/status" 2>/dev/null) || continue
  [ "${p#/proc/}" != 1 ] && [ "$ppid" = 0 ] && continue
  cmd=$(tr '\0' ' ' < "$p/cmdline" 2>/dev/null) || continue
  [ -n "$cmd" ] || continue
  vars=$(tr '\0' '\n' < "$p/environ" 2>/dev/null | sed -n 's/^\([A-Z_]*TOKEN[A-Z_]*\)=.*/\1/p' | tr '\n' ',')
  printf '%s\t%s\t%s\n' "${p#/proc/}" "$cmd" "$vars"
done
"""


def check_processes(addon: Addon) -> list[str]:
    rows = [
        (line.split("\t") + ["", ""])[:3]
        for line in addon.exec(PROCESS_ENV_SCRIPT).splitlines()
        if line.strip()
    ]
    seen = []
    for _pid, cmd, names in rows:
        tokens = {name for name in names.split(",") if name}
        assert not tokens & {"SUPERVISOR_TOKEN", "HASSIO_TOKEN"}, (
            f"{cmd!r} can see the Supervisor token ({tokens})"
        )
        if "n8n start" in cmd or "start.js" in cmd or "src.main" in cmd:
            assert "N8N_RUNNERS_AUTH_TOKEN" not in tokens, (
                f"{cmd!r} has the task broker token in its environment"
            )
        seen.append(cmd.strip())
    assert any("n8n start" in cmd for cmd in seen), f"n8n process not found: {rows}"
    assert any("redis-server" in cmd for cmd in seen), f"Redis not found: {rows}"
    assert any("nginx" in cmd for cmd in seen), f"nginx not found: {rows}"
    leftover = addon.exec(
        "ls /run/s6/container_environment | grep -E '^(SUPERVISOR|HASSIO)_TOKEN$' || true"
    ).strip()
    assert not leftover, f"s6 container environment still holds {leftover}"
    assert any("task-runner-launcher" in cmd for cmd in seen), f"launcher not found: {rows}"
    return seen


def check_listeners(addon: Addon) -> None:
    listening = addon.exec("netstat -ltn")
    sockets = [line.split()[3] for line in listening.splitlines() if "LISTEN" in line]
    broker = [s for s in sockets if s.endswith(":5679")]
    redis = [s for s in sockets if s.endswith(":6379")]
    assert broker == ["127.0.0.1:5679"], f"task broker listens on {broker}"
    assert redis and set(redis) <= {"127.0.0.1:6379", "::1:6379"}, f"Redis listens on {redis}"


def check_secret_hygiene(addon: Addon) -> None:
    mode = addon.exec("stat -c '%a %U' /data/n8n-runners-auth-token").strip()
    assert mode == "600 root", f"task broker token file is {mode}"
    token = addon.exec("cat /data/n8n-runners-auth-token").strip()
    assert len(token) == 64 and token != "n8n-runner", "task broker token is not per-install"
    logs = addon.logs()
    for secret in (SECRET_OPTION_VALUE, token, FAKE_SUPERVISOR_TOKEN):
        assert secret not in logs, "a secret value appears in the add-on log"
    leftovers = addon.exec(
        f"grep -l -e '{SECRET_OPTION_VALUE}' /.env /etc/environment /root/.bashrc 2>/dev/null || true"
    ).strip()
    assert not leftovers, f"option secrets copied into {leftovers}"


def check_watchdog_and_ingress(addon: Addon) -> None:
    status, body = addon.supervisor_get("/_woow/watchdog")
    assert status == 200 and json.loads(body) == {"status": "ok"}, (status, body)
    denied = docker(
        "run", "--rm", "--network", addon.network, "--ip", OTHER_CLIENT_IP,
        "--entrypoint", "curl", addon.image,
        "-s", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "10",
        f"http://{ADDON_IP}:5690/_woow/watchdog",
    ).strip()
    assert denied == "403", f"ingress port answered a non-Supervisor client with {denied}"

    status, html = ingress_get(addon, "/signin")
    assert status == 200, status
    assert f'<base href="{INGRESS_PATH}/">' in html, "ingress <base> not injected"
    assert f'src="{INGRESS_PATH}/assets/' in html, "asset URLs not prefixed"
    status, base_path = ingress_get(addon, "/static/base-path.js")
    assert base_path.strip() == f"window.BASE_PATH = '{INGRESS_PATH}/';", base_path
    app = next(
        part.split('"')[0]
        for part in html.split(f'href="{INGRESS_PATH}/assets/')[1:]
        if part.startswith("app-") and '.js"' in part.split(">")[0]
    )
    status, script = ingress_get(addon, f"/assets/{app}")
    assert status == 200, status
    assert script.count("function(e){return(window.BASE_PATH||`/`)+e}") == 1, (
        "preload builder not rewritten in the served app bundle"
    )
    assert "function(e){return`/`+e}" not in script


def ingress_get(addon: Addon, path: str) -> tuple[int, str]:
    out = docker(
        "run", "--rm", "--network", addon.network, "--ip", SUPERVISOR_IP,
        "--entrypoint", "curl", addon.image,
        "-s", "-H", f"X-Ingress-Path: {INGRESS_PATH}", "-o", "/dev/stdout",
        "-w", "\n%{http_code}", "--max-time", "20", f"http://{ADDON_IP}:5690{path}",
    )
    body, _, code = out.rpartition("\n")
    return int(code), body


def check_csp(addon: Addon) -> None:
    result = subprocess.run(
        ["curl", "-s", "-D", "-", "-o", "/dev/null", addon.url("/signin")],
        capture_output=True, text=True, check=True,
    )
    headers = [line.split(":", 1)[0].lower() for line in result.stdout.splitlines() if ":" in line]
    assert "content-security-policy" not in headers, (
        "n8n now enforces a Content-Security-Policy; the inline ingress shim and "
        "<base> would be blocked under Ingress"
    )


def check_proxy_logs(addon: Addon) -> None:
    """Proxied requests (cloudflared-like) must not trip n8n's rate limiter
    validation, and the add-on must not set the deprecated WEBHOOK_URL."""
    subprocess.run(
        ["curl", "-s", "-o", "/dev/null", "-H", "X-Forwarded-For: 203.0.113.9",
         addon.url("/rest/settings")],
        check=True,
    )
    time.sleep(1)
    logs = addon.logs()
    assert "ERR_ERL_UNEXPECTED_X_FORWARDED_FOR" not in logs, (
        "n8n does not trust the proxy hop (N8N_PROXY_HOPS)"
    )
    assert "WEBHOOK_URL -> Use N8N_WEBHOOK_URL" not in logs, (
        "the add-on still sets the deprecated WEBHOOK_URL"
    )


def check_seam(addon: Addon, workdir: Path) -> None:
    public = workdir / "public"
    docker("cp", f"{addon.name}:/config/.cache/n8n/public", str(public))
    subprocess.run(
        [sys.executable, str(TEST_DIR / "test-ingress-bundle-seam.py"), str(public)],
        check=True,
    )


def browser_check(addon: Addon, workdir: Path, workflow_id: str) -> None:
    """Sign in through a Supervisor-like ingress proxy in headless Chromium."""
    from playwright.sync_api import sync_playwright

    conf = workdir / "supervisor-ingress.conf"
    conf.write_text(
        "daemon off; pid /tmp/sim.pid; error_log /dev/stderr warn;\n"
        "events {}\nhttp {\n"
        "  map $http_upgrade $connection_upgrade { default upgrade; '' close; }\n"
        "  server { listen 8099;\n"
        f"    location {INGRESS_PATH}/ {{\n"
        f"      proxy_pass http://{ADDON_IP}:5690/;\n"
        "      proxy_http_version 1.1;\n"
        "      proxy_set_header Host $http_host;\n"
        f"      proxy_set_header X-Ingress-Path {INGRESS_PATH};\n"
        # HA Core and Supervisor each append their peer to X-Forwarded-For.
        "      proxy_set_header X-Forwarded-For \"$remote_addr, 172.30.32.1\";\n"
        "      proxy_set_header Upgrade $http_upgrade;\n"
        "      proxy_set_header Connection $connection_upgrade;\n"
        "      proxy_buffering off;\n"
        "    }\n  }\n}\n"
    )
    sim = f"{addon.name}-supervisor"
    docker(
        "run", "-d", "--name", sim, "--network", addon.network, "--ip", SUPERVISOR_IP,
        "-p", "127.0.0.1::8099", "-v", f"{conf}:/sim.conf:ro",
        "--entrypoint", "nginx", addon.image, "-c", "/sim.conf",
    )
    try:
        port = int(docker("port", sim, "8099/tcp").strip().splitlines()[0].rsplit(":", 1)[1])
        base = f"http://127.0.0.1:{port}{INGRESS_PATH}"
        failures: list[str] = []
        sockets: list[str] = []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.on("pageerror", lambda error: failures.append(f"pageerror {error}"))
            page.on(
                "response",
                lambda r: failures.append(f"{r.status} {r.url}")
                if r.status >= 400 and r.request.resource_type in {"script", "stylesheet", "font"}
                else None,
            )
            page.on("websocket", lambda ws: sockets.append(ws.url))
            page.goto(f"{base}/signin", wait_until="networkidle")
            page.fill('input[type="email"]', OWNER["email"])
            page.fill('input[type="password"]', OWNER["password"])
            page.keyboard.press("Enter")
            page.wait_for_url(f"{base}/home/**", timeout=60_000)
            page.wait_for_load_state("networkidle")
            # The editor opens its push connection (/rest/push) in the canvas.
            page.goto(f"{base}/workflow/{workflow_id}", wait_until="networkidle")
            page.wait_for_selector(".vue-flow__node", timeout=60_000)
            deadline = time.monotonic() + 30
            while not sockets and time.monotonic() < deadline:
                page.wait_for_timeout(500)
            nodes = page.locator(".vue-flow__node").count()
            metrics = page.evaluate(
                """() => {
                  const sheets = [...document.querySelectorAll('link[rel="stylesheet"]')].map(l => l.href);
                  const dupes = sheets.filter((h, i) => sheets.indexOf(h) !== i);
                  const outside = [...document.querySelectorAll('link[href],script[src]')]
                    .map(e => e.href || e.src)
                    .filter(u => new URL(u).origin === location.origin && !new URL(u).pathname.startsWith(window.__INGRESS_PATH__));
                  const app = document.querySelector('#n8n-app') || document.querySelector('#app');
                  return {path: location.pathname, duplicates: dupes, outside,
                          appHeight: app ? app.getBoundingClientRect().height : 0,
                          viewport: innerHeight};
                }"""
            )
            browser.close()
        evidence = {**metrics, "canvasNodes": nodes, "websockets": sockets, "failures": failures}
        print("browser evidence:", json.dumps(evidence))
        assert metrics["path"] == f"{INGRESS_PATH}/workflow/{workflow_id}", metrics
        assert nodes == 3, f"canvas shows {nodes} nodes, expected the 3 smoke nodes"
        assert not metrics["duplicates"], f"duplicate stylesheets: {metrics['duplicates']}"
        assert not metrics["outside"], f"assets loaded outside the ingress prefix: {metrics['outside']}"
        assert abs(metrics["appHeight"] - metrics["viewport"]) <= 1, metrics
        assert any(f"{INGRESS_PATH}/rest/push" in url for url in sockets), (
            f"editor push WebSocket did not use the ingress prefix: {sockets}"
        )
        assert not failures, failures
    finally:
        docker("rm", "-f", sim, check=False)


def main() -> None:
    args = sys.argv[1:]
    browser = "--browser" in args
    images = [arg for arg in args if not arg.startswith("--")]
    if len(images) != 1:
        raise SystemExit(__doc__)
    with tempfile.TemporaryDirectory(prefix="woow-n8n-smoke-") as tmp_name:
        workdir = Path(tmp_name)
        addon = Addon(images[0], workdir)
        try:
            addon.start()
            timings = addon.wait_ready()
            print(f"ready: {timings}")
            check_watchdog_and_ingress(addon)
            check_csp(addon)
            check_seam(addon, workdir)

            client = N8nClient(addon.url(""))
            client.setup_owner()
            workflow = client.ok("POST", "/rest/workflows", smoke_workflow("woow-smoke"))
            activate(client, workflow)
            result = call_webhook(addon, "woow-smoke")
            print("code nodes:", json.dumps(result))
            assert_code_nodes(result)

            processes = check_processes(addon)
            print("processes checked:", len(processes))
            check_listeners(addon)
            check_secret_hygiene(addon)
            if browser:
                browser_check(addon, workdir, str(workflow["id"]))
            check_proxy_logs(addon)

            token = addon.exec("cat /data/n8n-runners-auth-token").strip()
            addon.restart()
            restarted = addon.wait_ready()
            assert addon.exec("cat /data/n8n-runners-auth-token").strip() == token, (
                "task broker token changed across a restart"
            )
            assert_code_nodes(call_webhook(addon, "woow-smoke"))
            print(f"restart: {restarted}")
        except BaseException:
            print(addon.logs()[-8000:], file=sys.stderr)
            raise
        finally:
            addon.destroy()
            # Files written by the container are root-owned.
            docker(
                "run", "--rm", "-v", f"{workdir}:/w", "--entrypoint", "sh", addon.image,
                "-c", "rm -rf /w/data /w/config /w/public", check=False,
            )
    print("container smoke test passed")


if __name__ == "__main__":
    main()
