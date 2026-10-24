"""PaaS onboarding contracts through the public Ingress API."""
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.parse import parse_qs

import pytest


@pytest.fixture()
def fake_paas(monkeypatch, tmp_path):
    class Requests(list):
        fail_release = False
        fail_claim = False
        device_error = None
        detail = {
            "id": 25,
            "workspace_id": 7,
            "name": "家用 HA",
            "state": "active",
            "tunnel_id": "tunnel-25",
            "binding_state": "unbound",
            "binding_conflict": False,
            "connector_count": 0,
            "subscription": {"state": "in_progress", "plan_name": "1 route"},
            "routes": [{
                "hostname": "ha.example.com",
                "service_url": "http://homeassistant:8123",
                "is_protected": True,
                "access_configuration_ready": True,
                "access_protection_lost": False,
                "access_publish_pending": False,
                "access_unresolved_idp_types": "",
                "login_email_otp": True,
                "login_google": False,
                "access_policies": [{"decision": "allow", "include": [{"rule_type": "email_list", "rule_value": "alice@example.com"}]}],
            }],
        }

    received = Requests()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            body = parse_qs(self.rfile.read(length).decode())
            received.append((self.path, body))
            if self.path == "/oauth2/device_authorization":
                payload = {
                    "device_code": "PRIVATE_DEVICE_CODE",
                    "user_code": "ABCD-EFGH",
                    "verification_uri": f"http://127.0.0.1:{self.server.server_port}/device",
                    "verification_uri_complete": f"http://127.0.0.1:{self.server.server_port}/device?user_code=ABCD-EFGH",
                    "expires_in": 900,
                    "interval": 1,
                }
            elif self.path == "/oauth2/token":
                payload = {"error": received.device_error} if received.device_error else {
                    "access_token": "PRIVATE_ACCESS_TOKEN",
                    "refresh_token": "PRIVATE_REFRESH_TOKEN",
                    "expires_in": 3600,
                    "token_type": "Bearer",
                }
            elif self.path == "/oauth2/revoke":
                payload = {}
            else:
                payload = {"error": "unknown_path"}
            data = json.dumps(payload).encode()
            self.send_response(400 if self.path == "/oauth2/token" and received.device_error else (200 if self.path in ("/oauth2/device_authorization", "/oauth2/token", "/oauth2/revoke") else 404))
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            received.append((self.path, self.headers.get("Authorization", "")))
            if self.path == "/api/security-access/workspaces":
                payload = {"workspaces": [{"id": 7, "name": "家用工作區"}]}
            elif self.path == "/api/security-access/workspaces/7/accesses":
                payload = {"accesses": [{"id": 25, "name": "家用 HA", "state": "active"}]}
            elif self.path == "/api/security-access/accesses/25":
                payload = {"access": received.detail}
            elif self.path == "/api/security-access/accesses/25/status":
                payload = {"access": received.detail}
            elif self.path.startswith("/api/security-access/accesses/25/tunnel-token?"):
                payload = {"error": "already_bound", "detail": "Another device holds this tunnel"} if received.fail_claim else {"tunnel_token": "PRIVATE_TUNNEL_TOKEN", "tunnel_id": "tunnel-25"}
            else:
                payload = {"error": "Not Found"}
            data = json.dumps(payload).encode()
            self.send_response(409 if payload.get("error") == "already_bound" else (200 if "error" not in payload else 404))
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_DELETE(self):
            received.append((self.path, self.headers.get("Authorization", "")))
            data = b'{"binding_state":"unbound"}' if not received.fail_release else b'{"error":"temporary"}'
            self.send_response(200 if not received.fail_release else 503)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("PAAS_API_BASE", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setenv("PAAS_LINK_STATE", str(tmp_path / "link.json"))
    yield received
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def test_unlinked_addon_offers_real_portal_entry(client):
    response = client.get("/api/paas/bootstrap")
    assert response.status_code == 200
    assert response.json() == {
        "authorized": False,
        "portal_url": "https://aiot.woowtech.io/woow#/workspaces",
        "connection": None,
        "release_pending": False,
    }


def test_device_authorization_hides_device_code_and_requests_only_sa_scopes(client, fake_paas):
    response = client.post("/api/paas/authorization")
    assert response.status_code == 200
    body = response.json()
    assert body["user_code"] == "ABCD-EFGH"
    assert body["verification_url"].endswith("/device?user_code=ABCD-EFGH")
    assert "PRIVATE_DEVICE_CODE" not in str(body)
    assert fake_paas[0][0] == "/oauth2/device_authorization"
    assert fake_paas[0][1]["scope"] == [
        "workspace:read security-access:read security-access:tunnel"
    ]


def test_device_poll_respects_interval_and_persists_tokens_privately(client, fake_paas, tmp_path):
    assert client.post("/api/paas/authorization").status_code == 200
    early = client.get("/api/paas/authorization/status")
    assert early.status_code == 200
    assert early.json()["status"] == "waiting"
    assert len(fake_paas) == 1  # No early token request.
    time.sleep(5.1)
    done = client.get("/api/paas/authorization/status")
    assert done.status_code == 200
    assert done.json() == {"status": "authorized"}
    assert "PRIVATE_ACCESS_TOKEN" not in done.text
    assert "PRIVATE_REFRESH_TOKEN" not in done.text
    link_file = tmp_path / "link.json"
    assert link_file.stat().st_mode & 0o777 == 0o600
    assert json.loads(link_file.read_text())["refresh_token"] == "PRIVATE_REFRESH_TOKEN"
    assert "device_code" not in link_file.read_text()


def test_subscription_list_and_review_are_read_only(client, fake_paas, tmp_path):
    (tmp_path / "link.json").write_text(json.dumps({
        "access_token": "PRIVATE_ACCESS_TOKEN",
        "refresh_token": "PRIVATE_REFRESH_TOKEN",
        "expires_at": time.time() + 3600,
    }))
    assert client.get("/api/paas/workspaces").json()["workspaces"][0]["id"] == 7
    assert client.get("/api/paas/workspaces/7/accesses").json()["accesses"][0]["id"] == 25
    review = client.get("/api/paas/accesses/25/review")
    assert review.status_code == 200
    assert review.json()["ready"] is True
    assert review.json()["access"]["routes"][0]["hostname"] == "ha.example.com"
    assert all("tunnel-token" not in path for path, _ in fake_paas)


def test_zero_seat_plan_explains_purchase_before_connect(client, fake_paas, tmp_path):
    (tmp_path / "link.json").write_text(json.dumps({
        "access_token": "PRIVATE_ACCESS_TOKEN", "refresh_token": "PRIVATE_REFRESH_TOKEN",
        "expires_at": time.time() + 3600,
    }))
    fake_paas.detail["subscription"].update(ac_max_access_seats=0, ac_used_access_seats=0)
    review = client.get("/api/paas/accesses/25/review").json()
    assert review["ready"] is False
    assert any("至少 1 席" in issue for issue in review["issues"])
    assert review["access"]["subscription"]["ac_max_access_seats"] == 0
    assert client.post("/api/paas/accesses/25/connect").status_code == 409
    assert all("tunnel-token" not in path for path, _ in fake_paas)


def test_protected_subscription_claims_and_installs_token(client, fake_paas, fake_supervisor, tmp_path):
    (tmp_path / "link.json").write_text(json.dumps({
        "access_token": "PRIVATE_ACCESS_TOKEN",
        "refresh_token": "PRIVATE_REFRESH_TOKEN",
        "expires_at": time.time() + 3600,
    }))
    response = client.post("/api/paas/accesses/25/connect")
    assert response.status_code == 200
    assert response.json()["connected"] is True
    assert "PRIVATE_TUNNEL_TOKEN" not in response.text
    assert fake_supervisor.options["tunnel_token"] == "PRIVATE_TUNNEL_TOKEN"
    assert fake_supervisor.restarted is True
    assert any("tunnel-token?instance_uid=" in path for path, _ in fake_paas)
    state = json.loads((tmp_path / "link.json").read_text())
    assert state["connection"]["access_id"] == 25
    assert state["instance_uid"]
    assert "PRIVATE_TUNNEL_TOKEN" not in (tmp_path / "link.json").read_text()


def test_config_cannot_remove_managed_token(client, fake_paas, fake_supervisor, tmp_path):
    (tmp_path / "link.json").write_text(json.dumps({
        "access_token": "PRIVATE_ACCESS_TOKEN", "refresh_token": "PRIVATE_REFRESH_TOKEN",
        "expires_at": time.time() + 3600,
    }))
    assert client.post("/api/paas/accesses/25/connect").status_code == 200
    fake_supervisor.restarted = False
    assert client.get("/api/options").json()["tunnel_token_managed_by_paas"] is True
    res = client.put("/api/options?restart=true", json={
        "external_hostname": "ha.example.com", "tunnel_token": "",
    })
    assert res.status_code == 409
    assert "解除綁定" in res.json()["detail"]
    assert fake_supervisor.options["tunnel_token"] == "PRIVATE_TUNNEL_TOKEN"
    assert not fake_supervisor.restarted
    assert client.get("/api/paas/bootstrap").json()["connection"]["access_id"] == 25
    # Unrelated advanced settings still work without resending credentials.
    assert client.put("/api/options", json={"log_level": "debug"}).status_code == 200
    assert fake_supervisor.options["tunnel_token"] == "PRIVATE_TUNNEL_TOKEN"


def test_config_cannot_restart_local_route_during_pending_release(client, fake_paas, fake_supervisor, tmp_path):
    (tmp_path / "link.json").write_text(json.dumps({"release_pending": True}))
    before = dict(fake_supervisor.options)
    assert client.put("/api/options?restart=true", json={
        "external_hostname": "ha.example.com",
    }).status_code == 409
    assert fake_supervisor.options == before
    assert not fake_supervisor.restarted


def test_supervisor_rejection_releases_new_binding(client, fake_paas, fake_supervisor, tmp_path, monkeypatch):
    from backend.instances import supervisor
    from backend.supervisor import SupervisorError

    (tmp_path / "link.json").write_text(json.dumps({
        "access_token": "PRIVATE_ACCESS_TOKEN",
        "refresh_token": "PRIVATE_REFRESH_TOKEN",
        "expires_at": time.time() + 3600,
    }))

    async def rejected(_options):
        raise SupervisorError("rejected", 400)

    monkeypatch.setattr(supervisor, "set_options", rejected)
    response = client.post("/api/paas/accesses/25/connect")
    assert response.status_code == 502
    assert any("/tunnel-binding?instance_uid=" in path for path, _ in fake_paas)
    assert fake_supervisor.restarted is False


def test_unprotected_route_blocks_connect_without_claiming_token(client, fake_paas, tmp_path):
    (tmp_path / "link.json").write_text(json.dumps({
        "access_token": "PRIVATE_ACCESS_TOKEN",
        "refresh_token": "PRIVATE_REFRESH_TOKEN",
        "expires_at": time.time() + 3600,
    }))
    fake_paas.detail["routes"][0]["is_protected"] = False
    review = client.get("/api/paas/accesses/25/review")
    assert review.status_code == 200
    assert review.json()["ready"] is False
    assert "Access" in review.json()["issues"][0]
    connect = client.post("/api/paas/accesses/25/connect")
    assert connect.status_code == 409
    assert all("tunnel-token" not in path for path, _ in fake_paas)


def test_everyone_policy_or_unresolved_login_blocks_deployment(client, fake_paas, tmp_path):
    (tmp_path / "link.json").write_text(json.dumps({
        "access_token": "PRIVATE_ACCESS_TOKEN",
        "refresh_token": "PRIVATE_REFRESH_TOKEN",
        "expires_at": time.time() + 3600,
    }))
    route = fake_paas.detail["routes"][0]
    route["access_policies"].append({
        "decision": "allow", "include": [{"rule_type": "everyone", "rule_value": None}]
    })
    assert client.get("/api/paas/accesses/25/review").json()["ready"] is False
    route["access_policies"].pop()
    route["access_unresolved_idp_types"] = "google"
    assert client.post("/api/paas/accesses/25/connect").status_code == 409
    assert all("tunnel-token" not in path for path, _ in fake_paas)


def test_unpaid_draft_subscription_blocks_claim(client, fake_paas, tmp_path):
    (tmp_path / "link.json").write_text(json.dumps({
        "access_token": "PRIVATE_ACCESS_TOKEN",
        "refresh_token": "PRIVATE_REFRESH_TOKEN",
        "expires_at": time.time() + 3600,
    }))
    fake_paas.detail["subscription"]["state"] = "draft"
    response = client.post("/api/paas/accesses/25/connect")
    assert response.status_code == 409
    assert all("tunnel-token" not in path for path, _ in fake_paas)


def test_published_access_without_login_method_is_explained_and_blocked(client, fake_paas, tmp_path):
    (tmp_path / "link.json").write_text(json.dumps({
        "access_token": "PRIVATE_ACCESS_TOKEN", "refresh_token": "PRIVATE_REFRESH_TOKEN",
        "expires_at": time.time() + 3600,
    }))
    fake_paas.detail["routes"][0].update(login_email_otp=False, login_google=False)
    review = client.get("/api/paas/accesses/25/review").json()
    assert review["ready"] is False
    assert any("登入方式" in issue for issue in review["issues"])
    assert client.post("/api/paas/accesses/25/connect").status_code == 409
    assert all("tunnel-token" not in path for path, _ in fake_paas)


def test_disconnect_waits_for_restart_and_stopped_tunnel_before_release(client, fake_paas, fake_supervisor, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from backend.routers import paas

    (tmp_path / "link.json").write_text(json.dumps({
        "access_token": "PRIVATE_ACCESS_TOKEN",
        "refresh_token": "PRIVATE_REFRESH_TOKEN",
        "expires_at": time.time() + 3600,
        "instance_uid": "addon-instance-1",
        "connection": {"access_id": 25, "workspace_id": 7, "name": "家用 HA"},
    }))
    fake_supervisor.options["tunnel_token"] = "PRIVATE_TUNNEL_TOKEN"
    start = client.post("/api/paas/disconnect")
    assert start.status_code == 200
    assert "tunnel_token" not in fake_supervisor.options
    assert fake_supervisor.restarted is True
    assert all("tunnel-binding" not in path for path, _ in fake_paas)
    # Supervisor has saved new options, but the old cloudflared process may
    # still be serving traffic until the add-on actually restarts.
    assert client.post("/api/paas/disconnect/finish").status_code == 409
    assert all("tunnel-binding" not in path for path, _ in fake_paas)

    monkeypatch.setattr(paas, "_PROCESS_RUN_ID", "next-addon-process")

    async def running():
        return SimpleNamespace(metrics_reachable=True)

    monkeypatch.setattr(paas.metrics, "tunnel_status", running)
    assert client.post("/api/paas/disconnect/finish").status_code == 409
    assert all("tunnel-binding" not in path for path, _ in fake_paas)

    async def stopped():
        return SimpleNamespace(metrics_reachable=False)

    monkeypatch.setattr(paas.metrics, "tunnel_status", stopped)
    finish = client.post("/api/paas/disconnect/finish")
    assert finish.status_code == 200
    assert finish.json()["released"] is True
    assert any("tunnel-binding?instance_uid=addon-instance-1" in path for path, _ in fake_paas)
    assert json.loads((tmp_path / "link.json").read_text()).get("connection") is None


def test_external_probe_rejects_private_hostname_without_network_call(client, fake_paas, tmp_path):
    (tmp_path / "link.json").write_text(json.dumps({
        "access_token": "PRIVATE_ACCESS_TOKEN",
        "refresh_token": "PRIVATE_REFRESH_TOKEN",
        "expires_at": time.time() + 3600,
        "instance_uid": "addon-instance-1",
        "connection": {"access_id": 25, "workspace_id": 7, "name": "家用 HA"},
    }))
    fake_paas.detail["routes"][0]["hostname"] = "127.0.0.1"
    response = client.get("/api/paas/connection/status?probe=true")
    assert response.status_code == 200
    assert response.json()["external"][0]["status"] == "blocked_private_address"


def test_account_revoke_removes_local_credentials_after_platform_ack(client, fake_paas, tmp_path):
    (tmp_path / "link.json").write_text(json.dumps({
        "access_token": "PRIVATE_ACCESS_TOKEN",
        "refresh_token": "PRIVATE_REFRESH_TOKEN",
        "expires_at": time.time() + 3600,
        "instance_uid": "addon-instance-1",
    }))
    response = client.post("/api/paas/authorization/revoke")
    assert response.status_code == 200
    assert response.json() == {"revoked": True}
    assert any(path == "/oauth2/revoke" for path, _ in fake_paas)
    saved = json.loads((tmp_path / "link.json").read_text())
    assert "refresh_token" not in saved
    assert "access_token" not in saved
    assert saved["instance_uid"] == "addon-instance-1"


def test_failed_release_after_failed_install_can_be_retried(client, fake_paas, tmp_path, monkeypatch):
    from backend.instances import supervisor
    from backend.supervisor import SupervisorError

    (tmp_path / "link.json").write_text(json.dumps({
        "access_token": "PRIVATE_ACCESS_TOKEN",
        "refresh_token": "PRIVATE_REFRESH_TOKEN",
        "expires_at": time.time() + 3600,
    }))
    fake_paas.fail_release = True

    async def rejected(_options):
        raise SupervisorError("rejected", 400)

    monkeypatch.setattr(supervisor, "set_options", rejected)
    assert client.post("/api/paas/accesses/25/connect").status_code == 502
    state = json.loads((tmp_path / "link.json").read_text())
    assert state["release_pending"] is True
    assert state["pending_release_access_id"] == 25
    fake_paas.fail_release = False
    assert client.post("/api/paas/disconnect/finish").json() == {"released": True}
    state = json.loads((tmp_path / "link.json").read_text())
    assert state.get("release_pending") is None


def test_other_installation_binding_conflict_never_writes_supervisor(client, fake_paas, fake_supervisor, tmp_path):
    (tmp_path / "link.json").write_text(json.dumps({
        "access_token": "PRIVATE_ACCESS_TOKEN",
        "refresh_token": "PRIVATE_REFRESH_TOKEN",
        "expires_at": time.time() + 3600,
    }))
    fake_paas.fail_claim = True
    response = client.post("/api/paas/accesses/25/connect")
    assert response.status_code == 409
    assert "PRIVATE_TUNNEL_TOKEN" not in str(fake_supervisor.options)
    assert fake_supervisor.restarted is False


def test_account_cannot_revoke_while_connector_is_bound(client, fake_paas, tmp_path):
    (tmp_path / "link.json").write_text(json.dumps({
        "access_token": "PRIVATE_ACCESS_TOKEN",
        "refresh_token": "PRIVATE_REFRESH_TOKEN",
        "expires_at": time.time() + 3600,
        "connection": {"access_id": 25, "workspace_id": 7, "name": "家用 HA"},
    }))
    assert client.post("/api/paas/authorization/revoke").status_code == 409
    assert not fake_paas


def test_device_slow_down_increases_poll_interval(client, fake_paas):
    fake_paas.device_error = "slow_down"
    assert client.post("/api/paas/authorization").status_code == 200
    time.sleep(5.1)
    result = client.get("/api/paas/authorization/status")
    assert result.status_code == 200
    assert result.json() == {"status": "waiting", "interval": 10}
    assert client.get("/api/paas/authorization/status").json()["status"] == "waiting"
    assert sum(path == "/oauth2/token" for path, _ in fake_paas) == 1
