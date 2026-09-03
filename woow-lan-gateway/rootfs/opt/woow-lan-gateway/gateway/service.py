from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from ipaddress import ip_address, ip_network
from typing import Callable


@dataclass(frozen=True)
class GatewayConfig:
    lan_interface: str
    wan_interface: str
    source_cidr: str
    heartbeat_interval: int
    lease_timeout: int

    @classmethod
    def fixed_topology(cls) -> "GatewayConfig":
        return cls("enp4s0", "enp2s0", "192.168.50.0/24", 15, 45)

    def validate(self) -> None:
        if self.lease_timeout <= 2 * self.heartbeat_interval:
            raise ConfigurationError(
                "lease_timeout must be greater than twice heartbeat_interval"
            )


class ConfigurationError(ValueError):
    pass


class Decision(Enum):
    ALLOW = "allow"
    DROP = "drop"
    UNMANAGED = "unmanaged"


@dataclass(frozen=True)
class Flow:
    input_interface: str
    output_interface: str
    source: str
    destination: str
    connection_state: str = "new"

    @classmethod
    def forward(
        cls,
        input_interface: str,
        output_interface: str,
        source: str,
        destination: str,
        connection_state: str = "new",
    ) -> "Flow":
        return cls(
            input_interface,
            output_interface,
            source,
            destination,
            connection_state,
        )


@dataclass(frozen=True)
class GatewayStatus:
    state: str
    expires_at: float
    lan_interface: str = ""
    wan_interface: str = ""
    source_cidr: str = ""
    rules_checksum: str = ""


class MemoryFirewall:
    def __init__(self, clock: Callable[[], float]) -> None:
        self.clock = clock
        self.config: GatewayConfig | None = None
        self.expires_at = 0.0

    def enable(self, config: GatewayConfig, expires_at: float) -> None:
        self.config = config
        self.expires_at = expires_at

    def disable(self) -> None:
        self.config = None
        self.expires_at = 0.0

    def simulate_external_rule_loss(self) -> None:
        self.config = None
        self.expires_at = 0.0

    def healthy(self) -> bool:
        return self.config is not None and self.clock() < self.expires_at

    def decision(self, flow: Flow) -> Decision:
        if self.config is None:
            return Decision.UNMANAGED
        source = ip_address(flow.source)
        destination = ip_address(flow.destination)
        source_network = ip_network(self.config.source_cidr)
        active = self.clock() < self.expires_at
        private_destinations = tuple(
            ip_network(cidr)
            for cidr in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
        )
        if flow.input_interface == self.config.lan_interface and source in source_network:
            if flow.output_interface == self.config.lan_interface:
                return Decision.UNMANAGED
            if not active:
                return Decision.DROP
            if (
                flow.output_interface != self.config.wan_interface
                and flow.connection_state in ("established", "related")
            ):
                return Decision.ALLOW
            if flow.output_interface != self.config.wan_interface:
                return Decision.DROP
            if any(destination in network for network in private_destinations):
                return Decision.DROP
            return Decision.ALLOW
        if (
            flow.input_interface == self.config.wan_interface
            and flow.output_interface == self.config.lan_interface
            and destination in source_network
        ):
            if active and flow.connection_state in ("established", "related"):
                return Decision.ALLOW
            return Decision.DROP
        return Decision.UNMANAGED

    def permits(self, flow: Flow) -> bool:
        return self.decision(flow) is Decision.ALLOW


class GatewayService:
    def __init__(self, config: GatewayConfig, firewall: MemoryFirewall, clock: Callable[[], float]) -> None:
        self.config = config
        self.firewall = firewall
        self.clock = clock
        self.desired_enabled = False

    def _status(self, state: str, expires_at: float) -> GatewayStatus:
        rule_identity = "|".join(
            (
                self.config.lan_interface,
                self.config.wan_interface,
                self.config.source_cidr,
                str(self.config.lease_timeout),
            )
        )
        return GatewayStatus(
            state=state,
            expires_at=expires_at,
            lan_interface=self.config.lan_interface,
            wan_interface=self.config.wan_interface,
            source_cidr=self.config.source_cidr,
            rules_checksum=sha256(rule_identity.encode()).hexdigest(),
        )

    def start(self) -> GatewayStatus:
        self.config.validate()
        expires_at = self.clock() + self.config.lease_timeout
        try:
            self.firewall.enable(self.config, expires_at)
        except Exception:
            self.firewall.disable()
            self.desired_enabled = False
            raise
        self.desired_enabled = True
        return self._status("enabled", expires_at)

    def heartbeat(self) -> GatewayStatus:
        return self.start()

    def status(self) -> GatewayStatus:
        if not self.desired_enabled:
            return self._status("disabled", 0.0)
        if not self.firewall.healthy():
            return self._status("degraded", 0.0)
        return self._status("enabled", self.firewall.expires_at)

    def stop(self) -> GatewayStatus:
        self.firewall.disable()
        self.desired_enabled = False
        return self._status("disabled", 0.0)
