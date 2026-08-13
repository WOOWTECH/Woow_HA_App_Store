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
3. **Configure Cloudflare Tunnel** (for external access):
   - Set up a Cloudflare Tunnel pointing to `http://<HA_IP>:5678`
   - Set `WEBHOOK_URL` to your Cloudflare Tunnel HTTPS URL
   - Set `N8N_HOST` to your tunnel domain

## Redis

Redis is running on `localhost` or `127.0.0.1` with port `6379`
