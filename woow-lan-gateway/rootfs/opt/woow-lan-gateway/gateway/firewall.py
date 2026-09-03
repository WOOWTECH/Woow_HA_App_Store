import hashlib
import ipaddress
import json
import re
import subprocess
from dataclasses import dataclass
from typing import Callable, Sequence

from .service import GatewayConfig


TABLE = "woow_lan_gateway"
IPTABLES_CHAIN = "WOOW_LAN_FORWARD"
_INTERFACE = re.compile(r"^[A-Za-z0-9_.:-]{1,15}$")


class FirewallError(RuntimeError):
    pass


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class CommandRunner:
    def run(
        self, command: Sequence[str], *, input_text: str | None = None, check: bool = True
    ) -> CommandResult:
        process = subprocess.run(
            list(command),
            input=input_text,
            text=True,
            capture_output=True,
            timeout=15,
        )
        result = CommandResult(process.returncode, process.stdout, process.stderr)
        if check and process.returncode:
            raise FirewallError(
                f"command failed ({process.returncode}): {' '.join(command)}: "
                f"{process.stderr.strip()}"
            )
        return result


class NftablesFirewall:
    """Owns all kernel details behind the gateway lifecycle seam."""

    def __init__(self, clock: Callable[[], float], runner: CommandRunner | None = None):
        self.clock = clock
        self.runner = runner or CommandRunner()
        self.config: GatewayConfig | None = None
        self.expires_at = 0.0
        self._expected_nft_hash: str | None = None

    def enable(self, config: GatewayConfig, expires_at: float) -> None:
        self._validate_topology(config)
        try:
            if not self._structure_healthy(config):
                self._remove_iptables(config, ignore_errors=True)
                self._delete_nft_table(ignore_errors=True)
                self.runner.run(["nft", "-f", "-"], input_text=self._ruleset(config))
                self._expected_nft_hash = self._current_structure_hash()
                if self._expected_nft_hash is None:
                    raise FirewallError("could not verify installed nftables structure")
                self._ensure_iptables(config)
            self._renew_lease(config)
        except Exception:
            self.disable(config=config)
            raise
        self.config = config
        self.expires_at = expires_at

    def disable(self, config: GatewayConfig | None = None) -> None:
        selected = config or self.config
        if selected is not None:
            self._remove_iptables(selected, ignore_errors=True)
        self._delete_nft_table(ignore_errors=True)
        self.config = None
        self.expires_at = 0.0
        self._expected_nft_hash = None

    def healthy(self) -> bool:
        return (
            self.config is not None
            and self.clock() < self.expires_at
            and self._structure_healthy(self.config)
            and self._lease_present("active_a")
            and self._lease_present("active_b")
        )

    def counters(self) -> dict[str, int]:
        result = self.runner.run(
            ["nft", "-j", "list", "table", "inet", TABLE], check=False
        )
        totals = {"outbound": 0, "return": 0, "blocked": 0}
        if result.returncode:
            return totals
        try:
            document = json.loads(result.stdout)
        except json.JSONDecodeError:
            return totals
        for item in document.get("nftables", []):
            rule = item.get("rule", {})
            label = rule.get("comment")
            if label not in totals:
                continue
            for expression in rule.get("expr", []):
                if "counter" in expression:
                    totals[label] += int(expression["counter"].get("packets", 0))
        return totals

    def _validate_topology(self, config: GatewayConfig) -> None:
        for interface in (config.lan_interface, config.wan_interface):
            if not _INTERFACE.fullmatch(interface):
                raise FirewallError(f"unsafe interface name: {interface!r}")
            self.runner.run(["ip", "link", "show", "dev", interface])
        network = ipaddress.ip_network(config.source_cidr, strict=True)
        if network.version != 4:
            raise FirewallError("only IPv4 source_cidr is supported")
        if config.lan_interface == config.wan_interface:
            raise FirewallError("LAN and WAN interfaces must differ")
        forwarding = self.runner.run(["cat", "/proc/sys/net/ipv4/ip_forward"])
        if forwarding.stdout.strip() != "1":
            raise FirewallError("IPv4 forwarding is not enabled by HAOS")
        addresses = self.runner.run(
            ["ip", "-4", "-o", "addr", "show", "dev", config.lan_interface]
        ).stdout
        expected_gateway = str(next(network.hosts()))
        if not any(
            token.split("/", 1)[0] == expected_gateway
            for token in addresses.split()
            if "/" in token
        ):
            raise FirewallError(
                f"{config.lan_interface} does not own expected gateway {expected_gateway}"
            )
        routes = self.runner.run(["ip", "-4", "route", "show", "default"]).stdout
        if f"dev {config.wan_interface}" not in routes:
            raise FirewallError(f"default IPv4 route is not on {config.wan_interface}")

    def _structure_healthy(self, config: GatewayConfig) -> bool:
        table = self.runner.run(
            ["nft", "-j", "list", "table", "inet", TABLE], check=False
        )
        if table.returncode:
            return False
        try:
            document = json.loads(table.stdout)
        except json.JSONDecodeError:
            return False
        names = set()
        for item in document.get("nftables", []):
            for kind in ("table", "chain", "set"):
                if kind in item and item[kind].get("table", TABLE) == TABLE:
                    names.add((kind, item[kind].get("name")))
        expected = {
            ("table", TABLE),
            ("chain", "input_guard"),
            ("chain", "forward_guard"),
            ("chain", "postrouting"),
            ("set", "active_a"),
            ("set", "active_b"),
        }
        if not expected.issubset(names):
            return False
        if self._expected_nft_hash is None:
            return False
        if self._nft_structure_hash(document) != self._expected_nft_hash:
            return False
        forward = self.runner.run(
            ["iptables", "-w", "5", "-S", "FORWARD"], check=False
        )
        if (
            forward.returncode != 0
            or forward.stdout.splitlines().count(
                f"-A FORWARD -j {IPTABLES_CHAIN}"
            )
            != 1
        ):
            return False
        chain = self.runner.run(
            ["iptables", "-w", "5", "-S", IPTABLES_CHAIN], check=False
        )
        expected_rules = [
            f"-N {IPTABLES_CHAIN}",
            (
                f"-A {IPTABLES_CHAIN} -s {config.source_cidr} "
                f"-i {config.lan_interface} -o {config.wan_interface} -j ACCEPT"
            ),
            (
                f"-A {IPTABLES_CHAIN} -d {config.source_cidr} "
                f"-i {config.wan_interface} -o {config.lan_interface} "
                "-m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT"
            ),
            f"-A {IPTABLES_CHAIN} -j RETURN",
        ]
        return chain.returncode == 0 and chain.stdout.splitlines() == expected_rules

    def _current_structure_hash(self) -> str | None:
        result = self.runner.run(
            ["nft", "-j", "list", "table", "inet", TABLE], check=False
        )
        if result.returncode:
            return None
        try:
            return self._nft_structure_hash(json.loads(result.stdout))
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _nft_structure_hash(document: dict) -> str:
        normalized = []
        for item in document.get("nftables", []):
            if "metainfo" in item or "element" in item:
                continue
            clone = json.loads(json.dumps(item))
            for body in clone.values():
                if not isinstance(body, dict):
                    continue
                body.pop("handle", None)
                body.pop("elem", None)
                for expression in body.get("expr", []):
                    counter = expression.get("counter")
                    if isinstance(counter, dict):
                        counter["packets"] = 0
                        counter["bytes"] = 0
            normalized.append(clone)
        payload = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()

    def _lease_present(self, set_name: str) -> bool:
        result = self.runner.run(
            ["nft", "list", "set", "inet", TABLE, set_name], check=False
        )
        if result.returncode:
            return False
        return bool(self.config and self.config.source_cidr in result.stdout)

    def _ensure_iptables(self, config: GatewayConfig) -> None:
        self.runner.run(
            ["iptables", "-w", "5", "-N", IPTABLES_CHAIN], check=False
        )
        self.runner.run(["iptables", "-w", "5", "-F", IPTABLES_CHAIN])
        self.runner.run(
            [
                "iptables", "-w", "5", "-A", IPTABLES_CHAIN,
                "-i", config.lan_interface, "-o", config.wan_interface,
                "-s", config.source_cidr, "-j", "ACCEPT",
            ]
        )
        self.runner.run(
            [
                "iptables", "-w", "5", "-A", IPTABLES_CHAIN,
                "-i", config.wan_interface, "-o", config.lan_interface,
                "-d", config.source_cidr, "-m", "conntrack", "--ctstate",
                "ESTABLISHED,RELATED", "-j", "ACCEPT",
            ]
        )
        self.runner.run(["iptables", "-w", "5", "-A", IPTABLES_CHAIN, "-j", "RETURN"])
        while self.runner.run(
            ["iptables", "-w", "5", "-C", "FORWARD", "-j", IPTABLES_CHAIN],
            check=False,
        ).returncode == 0:
            self.runner.run(
                ["iptables", "-w", "5", "-D", "FORWARD", "-j", IPTABLES_CHAIN]
            )
        self.runner.run(
            ["iptables", "-w", "5", "-I", "FORWARD", "1", "-j", IPTABLES_CHAIN]
        )

    def _remove_iptables(self, config: GatewayConfig, ignore_errors: bool) -> None:
        while self.runner.run(
            ["iptables", "-w", "5", "-C", "FORWARD", "-j", IPTABLES_CHAIN],
            check=False,
        ).returncode == 0:
            self.runner.run(
                ["iptables", "-w", "5", "-D", "FORWARD", "-j", IPTABLES_CHAIN],
                check=not ignore_errors,
            )
        self.runner.run(
            ["iptables", "-w", "5", "-F", IPTABLES_CHAIN], check=False
        )
        self.runner.run(
            ["iptables", "-w", "5", "-X", IPTABLES_CHAIN], check=False
        )

    def _renew_lease(self, config: GatewayConfig) -> None:
        for set_name in ("active_a", "active_b"):
            self.runner.run(
                [
                    "nft", "delete", "element", "inet", TABLE, set_name,
                    f"{{ {config.source_cidr} }}",
                ],
                check=False,
            )
            self.runner.run(
                [
                    "nft", "add", "element", "inet", TABLE, set_name,
                    f"{{ {config.source_cidr} timeout {config.lease_timeout}s }}",
                ]
            )

    def _delete_nft_table(self, ignore_errors: bool) -> None:
        self._expected_nft_hash = None
        self.runner.run(
            ["nft", "delete", "table", "inet", TABLE], check=not ignore_errors
        )

    @staticmethod
    def _ruleset(config: GatewayConfig) -> str:
        return f"""table inet {TABLE} {{
    set active_a {{
        type ipv4_addr
        flags interval,timeout
    }}
    set active_b {{
        type ipv4_addr
        flags interval,timeout
    }}
    chain input_guard {{
        type filter hook input priority -10; policy accept;
        iifname {{ \"{config.lan_interface}\", \"{config.wan_interface}\" }} tcp dport 45987 counter drop comment \"blocked\"
    }}
    chain forward_guard {{
        type filter hook forward priority -10; policy accept;
        iifname \"{config.lan_interface}\" ip saddr @active_a oifname != {{ \"{config.lan_interface}\", \"{config.wan_interface}\" }} ct state established,related counter accept comment \"return\"
        iifname \"{config.lan_interface}\" ip saddr @active_a ip daddr {{ 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16 }} counter drop comment \"blocked\"
        iifname \"{config.lan_interface}\" ip saddr @active_a oifname \"{config.wan_interface}\" counter accept comment \"outbound\"
        iifname \"{config.lan_interface}\" ip saddr @active_b oifname != {{ \"{config.lan_interface}\", \"{config.wan_interface}\" }} ct state established,related counter accept comment \"return\"
        iifname \"{config.lan_interface}\" ip saddr @active_b ip daddr {{ 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16 }} counter drop comment \"blocked\"
        iifname \"{config.lan_interface}\" ip saddr @active_b oifname \"{config.wan_interface}\" counter accept comment \"outbound\"
        iifname \"{config.lan_interface}\" ip saddr {config.source_cidr} oifname != \"{config.lan_interface}\" counter drop comment \"blocked\"
        iifname \"{config.wan_interface}\" oifname \"{config.lan_interface}\" ip daddr @active_a ct state established,related counter accept comment \"return\"
        iifname \"{config.wan_interface}\" oifname \"{config.lan_interface}\" ip daddr @active_b ct state established,related counter accept comment \"return\"
        iifname \"{config.wan_interface}\" oifname \"{config.lan_interface}\" ip daddr {config.source_cidr} counter drop comment \"blocked\"
    }}
    chain postrouting {{
        type nat hook postrouting priority srcnat; policy accept;
        oifname \"{config.wan_interface}\" ip saddr @active_a counter masquerade
        oifname \"{config.wan_interface}\" ip saddr @active_b counter masquerade
    }}
}}
"""
