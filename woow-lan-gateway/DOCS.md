# Woow LAN Gateway documentation

> This App is purpose-built for the WOOWTECH factory-enrollment topology. Its default interfaces and network must be verified on the host before starting it.

## Default topology

- Enrollment LAN: `192.168.50.0/24`
- Gateway address: `192.168.50.1`
- LAN interface: `enp4s0`
- WAN interface: `enp2s0`

## Configuration

- `lan_interface`: Host interface connected to the enrollment LAN.
- `wan_interface`: Host interface connected to the public uplink.
- `source_cidr`: Enrollment client IPv4 network.
- `heartbeat_interval`: Seconds between policy verification and lease renewal.
- `lease_timeout`: Seconds before the kernel policy fails closed after an unclean stop.

The lease timeout must remain safely greater than the heartbeat interval. Unsafe settings are rejected and cleaned up rather than leaving forwarding open.

## Operation

Starting the App installs an nftables guard, a Docker-compatible iptables forwarding adapter, and NAT for public IPv4 destinations. RFC1918 destinations and new WAN-to-LAN connections are blocked. Normal stop removes the App-owned rules immediately; an unclean stop loses egress when the expiring nftables lease ends.

The ingress health page reports lifecycle state, lease expiry, interfaces, CIDR, rule checksum, and counters. Supervisor watchdog should remain enabled.

## Removal

1. Stop the App.
2. Confirm `table inet woow_lan_gateway` and `WOOW_LAN_FORWARD` are absent.
3. Uninstall the App.

Stopping or uninstalling does not modify Dnsmasq configuration, NetworkManager profiles, or client files.
