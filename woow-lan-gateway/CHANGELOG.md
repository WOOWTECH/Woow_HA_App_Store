# Changelog

## 0.1.6

- Change the default interfaces to LAN `enp2s0` and WAN `enp1s0`, matching the measured J6412 and N2840 hosts (`enp1s0` is the port cabled to the router). The previous defaults were `enp4s0` and `enp2s0`.
- Existing installs that never set `lan_interface`/`wan_interface` in their options pick up the new defaults after upgrading. Installs with explicit options are unchanged.
- The topology check is unchanged: on a host where the interfaces do not match, the App still refuses to start without touching NAT or firewall rules.

## 0.1.5

- Show "LAN Gateway" as the sidebar title (no Woow prefix).
- Add the add-on icon and logo.
- Published as a stable GitHub Release; the App Store now ships only Releases.

## 0.1.4

- Publish Woow LAN Gateway as a standalone WOOWTECH Home Assistant App.
- Enforce fail-closed, Internet-only forwarding with expiring nftables leases.
- Add health reporting, automatic rule repair, and persistent lifecycle notifications.
