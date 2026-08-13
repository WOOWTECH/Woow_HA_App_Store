"""Trust-boundary tests.

The guard has two failure modes with very different costs: letting another
add-on in (a security hole) and locking the real user out of their own GUI
(a dead product). Both are covered here.
"""
import logging

from backend.ingress_guard import INGRESS_GATEWAY, IngressGuard


class TestAllowList:
    def test_well_known_gateway_allowed(self, monkeypatch):
        monkeypatch.setattr("backend.ingress_guard.DEV_MODE", False)
        assert IngressGuard().allows(INGRESS_GATEWAY)

    def test_loopback_allowed(self, monkeypatch):
        monkeypatch.setattr("backend.ingress_guard.DEV_MODE", False)
        g = IngressGuard()
        assert g.allows("127.0.0.1")
        assert g.allows("::1")

    def test_other_addon_rejected(self, monkeypatch):
        # A neighbouring add-on on the hassio network — the exact case a
        # spoofed X-Ingress-Path header would otherwise buy access with.
        monkeypatch.setattr("backend.ingress_guard.DEV_MODE", False)
        assert not IngressGuard().allows("172.30.33.7")

    def test_unknown_peer_rejected(self, monkeypatch):
        monkeypatch.setattr("backend.ingress_guard.DEV_MODE", False)
        assert not IngressGuard().allows("")

    def test_resolved_supervisor_address_is_allowed(self, monkeypatch):
        # Guards against locking users out when the Supervisor is not at the
        # well-known 172.30.32.2 (regression: v1.0.3).
        monkeypatch.setattr("backend.ingress_guard.DEV_MODE", False)
        monkeypatch.setattr(
            "backend.ingress_guard._resolve_supervisor", lambda: {"10.42.0.9"}
        )
        assert IngressGuard().allows("10.42.0.9")

    def test_dns_failure_falls_back_to_well_known_gateway(self, monkeypatch):
        monkeypatch.setattr("backend.ingress_guard.DEV_MODE", False)
        monkeypatch.setattr("backend.ingress_guard._resolve_supervisor", lambda: set())
        g = IngressGuard()
        assert g.allows(INGRESS_GATEWAY)
        assert not g.allows("172.30.33.7")

    def test_dev_mode_bypasses(self, monkeypatch):
        monkeypatch.setattr("backend.ingress_guard.DEV_MODE", True)
        assert IngressGuard().allows("203.0.113.5")


class TestRejectionDiagnostics:
    def test_rejection_is_logged_with_context(self, monkeypatch, caplog):
        monkeypatch.setattr("backend.ingress_guard.DEV_MODE", False)
        g = IngressGuard()
        with caplog.at_level(logging.WARNING, logger="backend.ingress_guard"):
            g.reject("172.30.33.7", "GET /api/health")
        assert "172.30.33.7" in caplog.text
        # The allow-list must be in the message, or a lockout is undebuggable.
        assert INGRESS_GATEWAY in caplog.text

    def test_repeated_rejections_log_once_per_peer(self, monkeypatch, caplog):
        monkeypatch.setattr("backend.ingress_guard.DEV_MODE", False)
        g = IngressGuard()
        with caplog.at_level(logging.WARNING, logger="backend.ingress_guard"):
            for _ in range(5):
                g.reject("172.30.33.7", "GET /api/health")
            g.reject("172.30.33.8", "GET /api/health")
        # A polling neighbour must not flood the add-on log: one line per
        # distinct peer, however many requests it makes.
        blocked = [r for r in caplog.records if "Blocked" in r.getMessage()]
        assert len(blocked) == 2


class TestEndToEnd:
    def test_api_rejects_non_ingress_peer(self, client, monkeypatch):
        # TestClient presents 'testclient' as the peer; with the guard armed
        # that must be refused.
        monkeypatch.setattr("backend.main.guard.allows", lambda client: False)
        res = client.get("/api/health")
        assert res.status_code == 403
        assert "Ingress" in res.json()["detail"]
