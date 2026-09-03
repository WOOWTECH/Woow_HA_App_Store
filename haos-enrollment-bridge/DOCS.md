# HAOS Enrollment Bridge documentation

The App listens to the Dnsmasq-DHCP WebSocket lease feed and emits a `haos_dhcp_candidate` Home Assistant event when it observes a new MAC address in the configured target network.

## Prerequisites

- A reachable Dnsmasq-DHCP WebSocket endpoint.
- Home Assistant API access, supplied to the App by Supervisor.
- The downstream automation is optional and is installed separately from the repository's companion scripts.

## Configuration

- `dnsmasq_ws_url`: WebSocket URL that publishes lease snapshots.
- `ingress_path`: WebSocket path appended when required by the source.
- `target_cidr`: Only IPv4 candidates inside this network are accepted.
- `event_type`: Home Assistant event type to emit.
- `bootstrap_targets`: Optional IP addresses to re-arm once for controlled commissioning. Clear this after verification.
- `log_level`: `debug`, `info`, `warning`, or `error`.

## Delivery behavior

The initial lease snapshot primes the durable ledger without emitting events. New MAC addresses are persisted before delivery. Failed Home Assistant event deliveries remain pending and are retried after later snapshots. DHCP renewals and IP changes for an already-known MAC do not create duplicate candidates.

Do not edit `/data/state.json` directly. Stop the App before uninstalling it; uninstalling the App removes its own durable ledger but does not modify Dnsmasq leases or target hosts.
