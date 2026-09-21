# Woow Collabora CODE Live Test Report

Date: 2026-09-21
Environment: Home Assistant host `homeassistant`
Add-on slug: `1b7b4ce7_woow-collabora`
Version: `26.04.4.1.1`
Container: `app_1b7b4ce7_woow-collabora`
Direct/WOPI URL: `http://homeassistant:9981`
Ingress admin URL: `/api/hassio_ingress/<token>/browser/dist/admin/admin.html`
Nextcloud add-on: `1b7b4ce7_woow-nextcloud`
Nextcloud direct URL: `http://homeassistant:8000`

## Deployment

Result: PASS

- Added Woow Collabora add-on to `WOOWTECH/Woow_HA_App_Store/collabora`.
- Installed from Woow HA App Store.
- Enabled Ingress panel via Supervisor.
- Stopped and uninstalled the temporary third-party `db21ed7f_collabora` add-on to avoid two Collabora services.

Final running container:

```text
app_1b7b4ce7_woow-collabora 0.0.0.0:9981->9980/tcp
```

Final important options:

```text
username: admin
password: WoowCollabora-2026-A9x7!
ssl: false
ssl_termination: false
server_name: homeassistant:9981
aliasgroup1: http://homeassistant:8000
extra_params: --o:ssl.enable=false --o:ssl.termination=false --o:user_interface.use_integration_theme=false --o:net.proto=IPv4
```

## Collabora direct endpoint tests

Result: PASS

```text
GET http://homeassistant:9981/hosting/discovery
=> 200 text/xml, 42453 bytes

GET http://homeassistant:9981/hosting/capabilities
=> 200 application/json, 533 bytes

GET http://homeassistant:9981/browser/dist/admin/admin.html
=> 401 without basic auth
=> 200 with admin auth, 13690 bytes
```

## Collabora document conversion smoke test

Result: PASS

Command submitted a text file to Collabora conversion endpoint:

```text
POST http://homeassistant:9981/cool/convert-to/pdf
=> 200 application/octet-stream
=> Content-Disposition: attachment; filename="hello.pdf"
=> Output size: 11469 bytes
```

This verifies the office engine can launch document-processing workers, not only serve HTTP health endpoints.

## Home Assistant Ingress

Result: PASS for add-on integration / panel availability

Supervisor reports:

```text
ingress: true
ingress_panel: true
ingress_url: /api/hassio_ingress/<token>/browser/dist/admin/admin.html
state: started
```

Design decision:

- Ingress is used for the Collabora admin console only.
- Nextcloud Office uses the stable direct/public WOPI URL, not the HA ingress token URL.

## Nextcloud Office integration

Result: PASS

Configured in Nextcloud `richdocuments`:

```text
wopi_url: http://homeassistant:9981
public_wopi_url: http://homeassistant:9981
callback URL: autodetected
```

`occ richdocuments:activate-config` result:

```text
✓ Fetched /hosting/discovery endpoint
✓ Valid mimetype response
✓ Valid capabilities entry
✓ Fetched /hosting/capabilities endpoint
✓ Detected WOPI server: Collabora Online Development Edition 26.04.4.1
```

## Nextcloud direct vs Ingress checks with Office enabled

Result: PASS

Temporary test allowlist was added for HA host source IP and restored after testing.

```text
GET /index.php/settings/admin/richdocuments
Direct  => 200
Ingress => 200

GET /index.php/apps/richdocuments/
Direct  => 404
Ingress => 404

GET /index.php/apps/richdocuments/ajax/settings
Direct  => 404
Ingress => 404
```

The important admin/settings route loads in both entry modes, and unsupported routes are equivalent.

Ingress config restored to:

```text
allow 172.30.32.2;
deny all;
```

## Known limitation

A full browser document-open/edit/save flow requires an authenticated Nextcloud browser session with request tokens and iframe/WebSocket handling. The CLI/curl route for document open returns CSRF protection errors without a real browser session, which is expected. The tested server-side integration and Collabora worker conversion are successful.

## Final result

PASS: Woow Collabora CODE add-on is installed, running, reachable by direct WOPI URL, exposed in HA Ingress for admin GUI, and successfully integrated with Nextcloud Office.
