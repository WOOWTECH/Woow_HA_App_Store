# Headscale Add-on changelog

## 0.4.13 — first release candidate

- Add a Headscale MCP Add-on with a Home Assistant administrator panel on Ingress 8099, optional bearer-protected MCP on 8081, and a private child on loopback 3000.
- Use the existing 0.4.13 shared management and image base contracts. Headscale has its own slug, image name and Release tag; the seven existing Add-ons keep their 0.4.13 versions and published tags.
- Keep source, image, security, licensing, Store and real Home Assistant acceptance gates closed until their own evidence is produced. No image or HA acceptance is claimed by this source change.
