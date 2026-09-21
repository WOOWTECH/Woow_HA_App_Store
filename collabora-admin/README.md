# Woow Collabora Admin

Ingress-safe Home Assistant sidebar proxy for the Woow Collabora CODE admin console.

The Collabora admin page sends `frame-ancestors 'none'` and uses absolute `/browser/...` assets, so direct HA Ingress to Collabora can render as a blank page. This proxy:

- injects the configured Collabora admin Basic auth header;
- removes/replaces Collabora CSP so HA can iframe it;
- prefixes absolute `/browser` and `/cool` asset paths with the HA ingress path.

Nextcloud Office still uses the Collabora engine directly at `http://homeassistant:9981`.
