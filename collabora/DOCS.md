# Woow Collabora CODE Documentation

## Configuration

| Option | Purpose |
| --- | --- |
| `username` / `password` | Collabora admin console basic-auth credentials |
| `aliasgroup1` | Allowed Nextcloud URL, e.g. `http://homeassistant:8000` |
| `server_name` | Browser-facing Collabora host/port, e.g. `homeassistant:9981` |
| `ssl` / `ssl_termination` | TLS mode. For LAN tests keep both `false`. |
| `extra_params` | Extra `coolwsd` runtime options |

## Nextcloud Office integration

Inside the Nextcloud container:

```bash
occ config:app:set richdocuments wopi_url --value='http://homeassistant:9981'
occ config:app:set richdocuments public_wopi_url --value='http://homeassistant:9981'
occ richdocuments:activate-config
```

Expected result:

```text
Fetched /hosting/discovery endpoint
Fetched /hosting/capabilities endpoint
Detected WOPI server: Collabora Online Development Edition
```

## Ingress

The ingress panel opens the Collabora admin console:

```text
/browser/dist/admin/admin.html
```

The ingress panel is for administration only. Configure Nextcloud Office with the direct/public Collabora endpoint, not the HA ingress token URL.
