import base64
import json

import pytest
from pydantic import ValidationError

from backend.models import AddonOptions, AdditionalHost, OptionsRead

# A structurally valid Cloudflare tunnel token: base64 JSON with a/t/s keys.
# (base64 of a JSON object starting with {"a" always begins with "eyJ".)
VALID_TOKEN = (
    base64.b64encode(
        json.dumps({"a": "account", "t": "tunnel-uuid", "s": "secret"}).encode()
    )
    .decode()
    .rstrip("=")
)


def make(**kw):
    base = {"external_hostname": "ha.example.com", "additional_hosts": []}
    base.update(kw)
    return AddonOptions(**base)


class TestHostnameValidation:
    def test_valid_hostname(self):
        assert make().external_hostname == "ha.example.com"

    @pytest.mark.parametrize(
        "bad",
        ["https://ha.example.com", "ha.example.com:8123", "HA.EXAMPLE.COM", "-bad.tld"],
    )
    def test_invalid_hostname(self, bad):
        with pytest.raises(ValidationError):
            make(external_hostname=bad)

    def test_empty_hostname_allowed_with_other_config(self):
        opts = AddonOptions(
            external_hostname="",
            additional_hosts=[{"hostname": "a.example.com", "service": "http://x"}],
        )
        assert opts.external_hostname == ""

    def test_additional_host_hostname_validated(self):
        with pytest.raises(ValidationError):
            AdditionalHost(hostname="http://bad", service="http://x")

    def test_additional_host_service_required(self):
        with pytest.raises(ValidationError):
            AdditionalHost(hostname="a.example.com", service="  ")


class TestRunParameters:
    def test_allowed(self):
        opts = make(run_parameters=["--loglevel=debug", "--region=us"])
        assert opts.run_parameters == ["--loglevel=debug", "--region=us"]

    @pytest.mark.parametrize(
        "bad", ["--evil=1", "--token=x", "loglevel=debug", "--loglevel debug"]
    )
    def test_rejected(self, bad):
        with pytest.raises(ValidationError):
            make(run_parameters=[bad])


class TestCrossChecks:
    def test_npm_and_catch_all_mutually_exclusive(self):
        with pytest.raises(ValidationError, match="mutually exclusive"):
            make(catch_all_service="http://x", nginx_proxy_manager=True)

    def test_empty_config_allowed_at_model_level(self):
        # The minimal-config check lives in the router (after the stored
        # token merge) — the model must NOT reject an empty body, or
        # token-mode users could never save (regression: v1.0.1).
        opts = AddonOptions(external_hostname="", additional_hosts=[])
        assert opts.external_hostname == ""

    def test_token_only_config_allowed(self):
        opts = AddonOptions(
            external_hostname="", additional_hosts=[], tunnel_token=VALID_TOKEN
        )
        assert opts.tunnel_token == VALID_TOKEN


class TestTunnelTokenValidation:
    def test_valid_token_accepted(self):
        opts = make(tunnel_token=VALID_TOKEN)
        assert opts.tunnel_token == VALID_TOKEN

    def test_token_extracted_from_install_command(self):
        pasted = f"cloudflared service install {VALID_TOKEN}"
        opts = make(tunnel_token=pasted)
        assert opts.tunnel_token == VALID_TOKEN

    def test_token_with_whitespace_trimmed(self):
        opts = make(tunnel_token=f"  {VALID_TOKEN}\n")
        assert opts.tunnel_token == VALID_TOKEN

    def test_garbled_token_rejected(self):
        with pytest.raises(ValidationError, match="tunnel token"):
            make(tunnel_token="definitely-not-a-token")

    def test_truncated_token_rejected(self):
        with pytest.raises(ValidationError, match="tunnel token"):
            make(tunnel_token=VALID_TOKEN[: len(VALID_TOKEN) // 4])

    def test_empty_string_means_remove(self):
        opts = make(tunnel_token="   ")
        assert opts.tunnel_token == ""


class TestToSupervisorOptions:
    def test_unset_optionals_omitted(self):
        result = make().to_supervisor_options()
        assert result == {
            "external_hostname": "ha.example.com",
            "additional_hosts": [],
        }

    def test_set_values_included(self):
        result = make(
            tunnel_name="mytunnel",
            post_quantum=True,
            log_level="debug",
            run_parameters=["--loglevel=debug"],
        ).to_supervisor_options()
        assert result["tunnel_name"] == "mytunnel"
        assert result["post_quantum"] is True
        assert result["log_level"] == "debug"
        assert result["run_parameters"] == ["--loglevel=debug"]

    def test_disable_chunked_encoding_omitted_when_none(self):
        opts = AddonOptions(
            external_hostname="",
            additional_hosts=[{"hostname": "a.example.com", "service": "http://x"}],
        )
        host = opts.to_supervisor_options()["additional_hosts"][0]
        assert "disableChunkedEncoding" not in host


class TestOptionsRead:
    def test_token_masked(self):
        read = OptionsRead.from_supervisor(
            {"external_hostname": "", "additional_hosts": [], "tunnel_token": "s3cret"}
        )
        assert read.tunnel_token_set is True
        assert "s3cret" not in read.tunnel_token_masked

    def test_no_token(self):
        read = OptionsRead.from_supervisor(
            {"external_hostname": "", "additional_hosts": []}
        )
        assert read.tunnel_token_set is False
        assert read.tunnel_token_masked == ""
