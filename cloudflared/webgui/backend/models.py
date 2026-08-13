"""Pydantic models mirroring the add-on's Supervisor options schema.

The schema here is a 1:1 mirror of ``config.yaml`` (which is itself unchanged
from upstream app-cloudflared). The Supervisor remains the final validator —
these models exist to give the GUI fast, friendly error messages and to
replicate the cross-field checks the forked ``prepare`` script enforces.
"""
from __future__ import annotations

import base64
import binascii
import json
import re
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

# Same regex as the forked prepare script (validateConfigAndSetVars).
VALID_HOSTNAME_RE = re.compile(
    r"^(([a-z0-9äöüß]|[a-z0-9äöüß][a-z0-9äöüß\-]*[a-z0-9äöüß])\.)*"
    r"([a-z0-9]|[a-z0-9][a-z0-9\-]*[a-z0-9])$"
)

# Same whitelist as the config.yaml schema for run_parameters.
RUN_PARAMETER_RE = re.compile(
    r"^(--edge-bind-address|--edge-ip-version|--grace-period|--ha-connections"
    r"|--logfile|--loglevel|--pidfile|--protocol|--region|--retries|--tag)=.*$"
)

HOSTNAME_ERROR = (
    "is not a valid hostname. Do not include the protocol (e.g. 'https://') "
    "or a port (e.g. ':8123'), and use lowercase characters only."
)

TOKEN_RE = re.compile(r"eyJ[A-Za-z0-9+/=_-]+")

TOKEN_ERROR = (
    "does not look like a valid Cloudflare tunnel token. Copy the token from "
    "the Cloudflare Zero Trust dashboard (the long text starting with 'eyJ') "
    "— a broken token would prevent the tunnel from starting."
)


def normalize_tunnel_token(raw: str) -> str:
    """Extract and validate a Cloudflare tunnel token from user input.

    Users often paste the full install command
    (``cloudflared service install eyJ...``) or a token with surrounding
    whitespace; a garbled token would make cloudflared exit at startup.
    Accept anything that CONTAINS a well-formed token and store just the
    token. A tunnel token is base64 JSON with account/tunnel/secret fields.
    """
    candidate_match = TOKEN_RE.search(raw)
    if not candidate_match:
        raise ValueError(f"'{raw[:40]}...' {TOKEN_ERROR}")
    candidate = candidate_match.group(0)
    try:
        padded = candidate + "=" * (-len(candidate) % 4)
        data = json.loads(base64.b64decode(padded))
    except (binascii.Error, ValueError):
        raise ValueError(f"The pasted value {TOKEN_ERROR}") from None
    if not isinstance(data, dict) or not {"a", "t", "s"} <= set(data):
        raise ValueError(f"The pasted value {TOKEN_ERROR}")
    return candidate


class LogLevel(str, Enum):
    trace = "trace"
    debug = "debug"
    info = "info"
    notice = "notice"
    warning = "warning"
    error = "error"
    fatal = "fatal"


class AdditionalHost(BaseModel):
    hostname: str
    service: str
    disableChunkedEncoding: Optional[bool] = None

    @field_validator("hostname")
    @classmethod
    def _hostname(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("'hostname' in additional_hosts must not be empty")
        if not VALID_HOSTNAME_RE.match(v):
            raise ValueError(f"'{v}' {HOSTNAME_ERROR}")
        return v

    @field_validator("service")
    @classmethod
    def _service(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("'service' in additional_hosts must not be empty")
        return v

    def to_options(self) -> dict:
        data = {"hostname": self.hostname, "service": self.service}
        if self.disableChunkedEncoding is not None:
            data["disableChunkedEncoding"] = self.disableChunkedEncoding
        return data


class AddonOptions(BaseModel):
    """Write model — request body for PUT /api/options."""

    external_hostname: str = ""
    additional_hosts: List[AdditionalHost] = Field(default_factory=list)
    tunnel_name: Optional[str] = None
    catch_all_service: Optional[str] = None
    nginx_proxy_manager: Optional[bool] = None
    tunnel_token: Optional[str] = None
    post_quantum: Optional[bool] = None
    run_parameters: Optional[List[str]] = None
    log_level: Optional[LogLevel] = None

    @field_validator("external_hostname")
    @classmethod
    def _external_hostname(cls, v: str) -> str:
        v = v.strip()
        if v and not VALID_HOSTNAME_RE.match(v):
            raise ValueError(f"'{v}' {HOSTNAME_ERROR}")
        return v

    @field_validator("tunnel_token")
    @classmethod
    def _tunnel_token(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if not v:
            # Empty string = explicit "remove the token".
            return ""
        return normalize_tunnel_token(v)

    @field_validator("run_parameters")
    @classmethod
    def _run_parameters(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return v
        cleaned = []
        for param in v:
            param = param.strip()
            if not param:
                continue
            if not RUN_PARAMETER_RE.match(param):
                raise ValueError(
                    f"'{param}' is not an allowed run parameter. Allowed flags: "
                    "--edge-bind-address, --edge-ip-version, --grace-period, "
                    "--ha-connections, --logfile, --loglevel, --pidfile, "
                    "--protocol, --region, --retries, --tag (format: --flag=value)"
                )
            cleaned.append(param)
        return cleaned

    @model_validator(mode="after")
    def _cross_checks(self) -> "AddonOptions":
        # Mirror of the prepare script's exit conditions, surfaced early.
        # NOTE: the "minimal configuration" check does NOT live here — a
        # token-mode user keeps their stored token by omitting tunnel_token,
        # so the check can only run after the router merges the stored token
        # (see routers/options.py::ensure_minimal_config).
        if self.catch_all_service and self.nginx_proxy_manager:
            raise ValueError(
                "'nginx_proxy_manager' and 'catch_all_service' are mutually "
                "exclusive. Please remove one of them."
            )
        return self

    def to_supervisor_options(self) -> dict:
        """Build the exact options dict to store via the Supervisor.

        Optional keys that are unset/empty are omitted entirely so the stored
        configuration looks exactly like one written from the HA add-on
        configuration page.
        """
        options: dict = {
            "external_hostname": self.external_hostname,
            "additional_hosts": [h.to_options() for h in self.additional_hosts],
        }
        if (self.tunnel_name or "").strip():
            options["tunnel_name"] = self.tunnel_name.strip()
        if (self.catch_all_service or "").strip():
            options["catch_all_service"] = self.catch_all_service.strip()
        if self.nginx_proxy_manager is not None:
            options["nginx_proxy_manager"] = self.nginx_proxy_manager
        if (self.tunnel_token or "").strip():
            options["tunnel_token"] = self.tunnel_token.strip()
        if self.post_quantum is not None:
            options["post_quantum"] = self.post_quantum
        if self.run_parameters:
            options["run_parameters"] = self.run_parameters
        if self.log_level is not None:
            options["log_level"] = self.log_level.value
        return options


class OptionsRead(BaseModel):
    """Read model — response for GET /api/options (token masked)."""

    external_hostname: str = ""
    additional_hosts: List[AdditionalHost] = Field(default_factory=list)
    tunnel_name: Optional[str] = None
    catch_all_service: Optional[str] = None
    nginx_proxy_manager: Optional[bool] = None
    post_quantum: Optional[bool] = None
    run_parameters: Optional[List[str]] = None
    log_level: Optional[LogLevel] = None
    tunnel_token_set: bool = False
    tunnel_token_masked: str = ""

    @classmethod
    def from_supervisor(cls, options: dict) -> "OptionsRead":
        token = (options.get("tunnel_token") or "").strip()
        hosts = [
            AdditionalHost.model_construct(
                hostname=h.get("hostname", ""),
                service=h.get("service", ""),
                disableChunkedEncoding=h.get("disableChunkedEncoding"),
            )
            for h in options.get("additional_hosts") or []
        ]
        return cls(
            external_hostname=options.get("external_hostname") or "",
            additional_hosts=hosts,
            tunnel_name=options.get("tunnel_name"),
            catch_all_service=options.get("catch_all_service"),
            nginx_proxy_manager=options.get("nginx_proxy_manager"),
            post_quantum=options.get("post_quantum"),
            run_parameters=options.get("run_parameters"),
            log_level=options.get("log_level"),
            tunnel_token_set=bool(token),
            tunnel_token_masked="••••••••" if token else "",
        )


class WizardState(BaseModel):
    mode: str  # "token" | "local"
    has_cert: bool
    has_tunnel: bool
    tunnel_uuid: Optional[str] = None
    login_url: Optional[str] = None
    tunnel_status: str = "unknown"
    unconfigured: bool = False
    prepare_failed: bool = False


class TunnelStatus(BaseModel):
    status: str  # "running" | "starting" | "stopped"
    ready_connections: int = 0
    metrics_reachable: bool = False


class HealthResponse(BaseModel):
    status: str = "ok"
    supervisor_connected: bool
    addon_version: Optional[str] = None
    addon_state: Optional[str] = None
    tunnel: TunnelStatus
    restart_error: Optional[str] = None
