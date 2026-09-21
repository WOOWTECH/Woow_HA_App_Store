# Woow Collabora CODE

Collabora Online / CODE as an independent Home Assistant add-on for Woow Nextcloud Office.

## Roles

- **Direct/WOPI endpoint**: `http://homeassistant:9981`
  - Configure Nextcloud Office (`richdocuments`) to this URL.
  - Used for WOPI discovery, document iframe, WebSocket, and save callbacks.
- **HA Ingress admin UI**: Home Assistant sidebar → Collabora admin console.
  - Admin-only panel by default.
  - For monitoring active documents/sessions and service status.

## Default Nextcloud pairing

Woow Nextcloud direct URL:

```text
http://homeassistant:8000
```

Woow Collabora direct URL:

```text
http://homeassistant:9981
```

The default `aliasgroup1` permits the Woow Nextcloud direct URL.

## Notes

This add-on intentionally keeps Collabora separate from the Nextcloud add-on so it can be restarted, upgraded, and scaled independently.
