# Home Assistant Add-on: Woow n8n by WOOWTECH

**n8n** is a workflow automation platform that gives technical teams the flexibility of code with the speed of no-code. With 400+ integrations, native AI capabilities, and a fair-code license, n8n lets you build powerful automations while maintaining full control over your data and deployments.

## All-in-One Components

This monolithic package includes:

- **n8n**: workflow automations
- **Redis**: Real-time notifications and caching

[Official n8n Documentation](https://docs.n8n.io/)

---

## Key Difference: HTTP-Only for LAN

This is a fork of [fabio-garavini/hassio-addons](https://github.com/fabio-garavini/hassio-addons) with the following modification:

- **SSL/HTTPS has been removed** for local network (LAN) access
- The web UI runs on plain HTTP at port 5678
- For external HTTPS access, use **Cloudflare Tunnel** to establish a secure connection

This design simplifies the setup for users who access n8n only within their home network, while relying on Cloudflare Tunnel for secure external access.

---

## Installation Guide

1. **Install the Add-on**:
   - Navigate to **Home Assistant Supervisor** > **Add-on Store**
   - Add the WOOWTECH repository URL
   - Search for "Woow n8n" > Click **Install**
2. **Initial Setup**:
   - Start the add-on
   - Click **OPEN WEB UI** and follow the first-run wizard
3. **Configure Cloudflare Tunnel** (for complete external UI/API/WebSocket access):
   - Set up a Cloudflare Tunnel public hostname pointing to `http://<HA_IP>:5678` (or the Home Assistant internal hostname and port)
   - Configure the add-on:
     ```yaml
     N8N_HOST: n8n.example.com
     N8N_EDITOR_BASE_URL: https://n8n.example.com
     N8N_WEBHOOK_URL: https://n8n.example.com
     WEBHOOK_URL: https://n8n.example.com
     N8N_PROXY_HOPS: 1
     N8N_SECURE_COOKIE: true
     ```
   - Restart the add-on.

The current bundled n8n uses the legacy `WEBHOOK_URL`; the add-on mirrors it with `N8N_WEBHOOK_URL` for forward compatibility with n8n 2.35 and later. Keep `N8N_PROTOCOL=http`: TLS terminates at Cloudflare while the add-on origin remains HTTP.

Cloudflare Tunnel supports WebSockets, so the editor's `/rest/push` connection works on the same public HTTPS hostname. This publishes the complete n8n entry point; protect the n8n owner account with a strong password. Cloudflare Access on the same hostname needs explicit bypass rules for public webhook paths.

The add-on also enables Home Assistant Ingress on port 5690. **Open Web UI** and the optional HA sidebar panel use this authenticated ingress adapter, including WebSocket and streaming support. The direct 5678 origin remains available for Cloudflare at the domain root, so both entrances work concurrently.

## Prebuilt add-on images and release order

Supervisor pulls the versioned prebuilt image rather than building this add-on on the host: `ghcr.io/woowtech/woow-ha-n8n-amd64:X.Y.Z` or `ghcr.io/woowtech/woow-ha-n8n-aarch64:X.Y.Z`. The matching GHCR tag is required before that add-on version can install. Repository owners must keep both GHCR packages public because Supervisor does not supply registry credentials.

Maintainers update `n8n/config.yaml` and `n8n/CHANGELOG.md`, merge the release version change to `main`, then wait for **Publish n8n add-on images** to publish and verify both architecture tags before announcing the update. Use **Run workflow** on the release revision to rebuild its images; it derives the tag from `n8n/config.yaml`.

## Redis

Redis is running on `localhost` or `127.0.0.1` with port `6379`
