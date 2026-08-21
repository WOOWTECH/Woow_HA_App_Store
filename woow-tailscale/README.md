# Woow Tailscale Home Assistant Add-on

[![WOOWTECH App Store][repository-shield]][repository]
[![Open this add-on][addon-shield]][addon]

Woow Tailscale is a Home Assistant add-on for connecting Home Assistant to
Tailscale's official control plane or a Headscale-compatible control plane.
Using Headscale does not require a Tailscale account; use the account or user
configured by the Headscale administrator.

> **Upstream attribution:** This WOOWTECH-maintained add-on is an
> MIT-licensed fork of
> [`hassio-addons/app-tailscale`](https://github.com/hassio-addons/app-tailscale)
> at upstream commit `24464c97a779bdd64c9975f514bff6e1d9058cca`.

## Documentation

See [DOCS.md](DOCS.md) for configuration, the HAOS migration procedure, and
recovery guidance. When migrating from the official add-on, stop
`a0d7b954_tailscale` before starting Woow Tailscale; never run both add-ons at
the same time.

[addon-shield]: https://my.home-assistant.io/badges/supervisor_addon.svg
[addon]: https://my.home-assistant.io/redirect/supervisor_addon/?addon=woow-tailscale&repository_url=https%3A%2F%2Fgithub.com%2FWOOWTECH%2FWoow_HA_App_Store
[repository-shield]: https://img.shields.io/badge/WOOWTECH-App%20Store-blue.svg
[repository]: https://github.com/WOOWTECH/Woow_HA_App_Store
