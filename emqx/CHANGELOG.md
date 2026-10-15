# Changelog

## v5.9.1

Add-on 5.9.1; EMQX broker 5.8.9 (the last Apache-2.0 open-source release;
5.9+ is the Business Source License enterprise edition and is not used).

- Add-on and broker versions are now stated separately everywhere
  (add-on 5.9.x ships EMQX 5.8.9)
- Erlang cookie: each installation now generates its own random cookie on
  first start and keeps it in `/data/emqx/node.cookie` (mode 600). It used to
  be the Home Assistant hostname, which anyone on the LAN could guess
- Node name is pinned in `/data/emqx/node.name`. Existing installations keep
  the node name their database already uses, so all data (users,
  authentication, ACL, rules) is kept; renaming the Home Assistant host no
  longer switches EMQX to an empty database. New installations use
  `emqx@127.0.0.1`
- The node name's host is mapped to 127.0.0.1 so `emqx ctl` keeps working
- The add-on log no longer prints `env_vars` values, only their names
- Add a Supervisor watchdog on `/api/v5/status`
- Build: EMQX and ngrok downloads retry on flaky networks, and are verified
  against pinned SHA-256 checksums before they are unpacked; a mismatch fails
  the build
- Build: ngrok is pinned to 3.39.11 (it used to follow the floating "stable"
  build)
- Build: `procps` is no longer pinned to a Debian point release, which broke
  local builds after a Debian 13 update
- Base image `ghcr.io/hassio-addons/debian-base` 9.2.0 → 9.5.0 (still Debian 13)
- CI: reject any EMQX other than 5.8.x and check that versions agree
- Docs: correct MQTT broker host names (`a0d7b954-emqx` is the community
  add-on's name and does not apply here), and warn about anonymous MQTT, the
  default Dashboard login and ngrok exposure
- Unchanged on purpose: anonymous MQTT access and the default Dashboard
  login `admin` / `public` behave as before

## v5.9.0

Add-on 5.9.0; EMQX broker **5.8.9** (unchanged). The "5.9.0" is the add-on
version only. It is not EMQX 5.9.0, which was never released as open source.

- Add built-in ngrok TCP tunnel for raw MQTT on port 1883
- Log the resolved public ngrok URL to the add-on log
- New options: `ngrok_enabled`, `ngrok_authtoken`, `ngrok_tcp_addr`
- MQTT-over-WebSocket (8083) remains out of scope (use Cloudflare Tunnel)

## v5.8.9

- Initial WOOWTECH fork of hassio-addons/addon-emqx
- EMQX v5.8.9
- Traditional Chinese translations and documentation
- WOOWTECH branding
