class TestHealth:
    def test_health(self, client):
        res = client.get("/api/health")
        assert res.status_code == 200
        body = res.json()
        assert body["supervisor_connected"] is True
        assert body["addon_version"] == "1.0.0"
        assert body["tunnel"]["status"] in ("running", "starting", "stopped")


class TestOptionsApi:
    def test_get_options_masks_token(self, client, fake_supervisor):
        fake_supervisor.options["tunnel_token"] = "s3cret"
        res = client.get("/api/options")
        assert res.status_code == 200
        body = res.json()
        assert body["tunnel_token_set"] is True
        assert "s3cret" not in str(body)

    def test_put_options_saves_via_supervisor(self, client, fake_supervisor):
        res = client.put(
            "/api/options",
            json={"external_hostname": "ha.example.com", "additional_hosts": []},
        )
        assert res.status_code == 200
        assert fake_supervisor.options["external_hostname"] == "ha.example.com"
        assert fake_supervisor.restarted is False

    def test_token_mode_user_can_save_without_resending_token(
        self, client, fake_supervisor
    ):
        # Regression (v1.0.1): a token-mode user saving unrelated changes —
        # with no hostname/hosts/catch-all — must not be rejected by the
        # minimal-config check, because the stored token is merged first.
        fake_supervisor.options["tunnel_token"] = "storedtoken"
        res = client.put(
            "/api/options",
            json={
                "external_hostname": "",
                "additional_hosts": [],
                "log_level": "debug",
            },
        )
        assert res.status_code == 200
        assert fake_supervisor.options["tunnel_token"] == "storedtoken"
        assert fake_supervisor.options["log_level"] == "debug"

    def test_empty_config_without_token_rejected(self, client, fake_supervisor):
        res = client.put(
            "/api/options",
            json={"external_hostname": "", "additional_hosts": []},
        )
        assert res.status_code == 422
        assert "Cannot run without" in res.text

    def test_put_options_with_restart(self, client, fake_supervisor):
        res = client.put(
            "/api/options?restart=true",
            json={"external_hostname": "ha.example.com", "additional_hosts": []},
        )
        assert res.status_code == 200
        assert res.json()["restarting"] is True
        assert fake_supervisor.restarted is True

    def test_put_keeps_existing_token_when_omitted(self, client, fake_supervisor):
        fake_supervisor.options["tunnel_token"] = "keepme"
        client.put(
            "/api/options",
            json={"external_hostname": "ha.example.com", "additional_hosts": []},
        )
        assert fake_supervisor.options["tunnel_token"] == "keepme"

    def test_put_empty_string_removes_token(self, client, fake_supervisor):
        fake_supervisor.options["tunnel_token"] = "removeme"
        client.put(
            "/api/options",
            json={
                "external_hostname": "ha.example.com",
                "additional_hosts": [],
                "tunnel_token": "",
            },
        )
        assert "tunnel_token" not in fake_supervisor.options

    def test_put_invalid_options_rejected(self, client, fake_supervisor):
        res = client.put(
            "/api/options",
            json={
                "external_hostname": "ha.example.com",
                "additional_hosts": [],
                "catch_all_service": "http://x",
                "nginx_proxy_manager": True,
            },
        )
        assert res.status_code == 422
        # Nothing must be written when validation fails.
        assert "catch_all_service" not in fake_supervisor.options

    def test_restart_endpoint(self, client, fake_supervisor):
        res = client.post("/api/restart")
        assert res.status_code == 200
        assert fake_supervisor.restarted is True


class TestWizard:
    def test_state_local_mode(self, client):
        res = client.get("/api/wizard/state")
        assert res.status_code == 200
        body = res.json()
        assert body["mode"] == "local"

    def test_state_token_mode(self, client, fake_supervisor):
        fake_supervisor.options["tunnel_token"] = "tok"
        res = client.get("/api/wizard/state")
        assert res.json()["mode"] == "token"


class TestLogs:
    def test_snapshot(self, client):
        res = client.get("/api/logs")
        assert res.status_code == 200
        assert "lines" in res.json()


class TestLogRedaction:
    def test_token_flag_redacted(self):
        from backend.logwatch import clean_line

        line = "cloudflared tunnel --no-autoupdate run --token=eyJhIjoiOWMyN2Y2MjNlZTU5NmUwYjY3YmU1NjI2M2JjYjE5NzQiLCJ0IjoiMzlkMTg3ZjAifQ=="
        out = clean_line(line)
        assert "eyJ" not in out
        assert "--token=<redacted>" in out

    def test_tunnel_secret_redacted(self):
        from backend.logwatch import clean_line

        line = '{"AccountTag":"abc","TunnelSecret":"c2VjcmV0c2VjcmV0","TunnelID":"39d187f0"}'
        out = clean_line(line)
        assert "c2VjcmV0" not in out
        assert '"TunnelSecret":"<redacted>"' in out

    def test_bare_jwt_like_blob_redacted(self):
        from backend.logwatch import clean_line

        out = clean_line("token value: " + "eyJ" + "A" * 60)
        assert "<redacted-token>" in out

    def test_normal_lines_untouched(self):
        from backend.logwatch import clean_line

        line = "2026-08-07T01:42:44Z INF Registered tunnel connection connIndex=0"
        assert clean_line(line) == line
