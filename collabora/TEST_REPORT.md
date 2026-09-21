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

## 2026-09-21 correct production HA instance retest

Requested production HA URLs:

```text
HA UI: https://woowtech-ha.woowtech.io
SSH:   woowtech-ssh.woowtech.io via cloudflared access ssh
```

TDD sequence:

1. Ran live visibility test first on `woowtech-ssh.woowtech.io`.
2. Expected failure occurred:

```text
AssertionError: 1b7b4ce7_woow-collabora missing from installed applications list
```

3. Installed and configured `1b7b4ce7_woow-collabora` on the correct HA instance.
4. Enabled `ingress_panel: true`.
5. Installed/enabled Nextcloud `richdocuments` on the correct Nextcloud instance and configured:

```text
wopi_url: http://homeassistant:9981
public_wopi_url: http://homeassistant:9981
```

6. `occ richdocuments:activate-config` passed and detected:

```text
Collabora Online Development Edition 26.04.4.1
```

7. Re-ran live visibility test with public hostname assertion:

```bash
EXPECTED_HA_PUBLIC_HOST=woowtech-ha.woowtech.io bash /tmp/live-ha-collabora-visibility.sh
```

Final result:

```text
HA installed/store/ingress metadata passed
Checking Collabora direct endpoints...
Checking Nextcloud pairing target...
Checking expected public HA hostname woowtech-ha.woowtech.io...
Woow Collabora live visibility checks passed for 1b7b4ce7_woow-collabora
```

Correct production instance status:

```text
slug: 1b7b4ce7_woow-collabora
stage: stable
state: started
ingress_panel: true
ingress_url: /api/hassio_ingress/<token>/browser/dist/admin/admin.html
```

## 2026-09-21 Cloudflare / sidebar blank-page fix

Problem observed from `https://woowtech-ha.woowtech.io`:

- Clicking Collabora from the HA sidebar rendered a blank page.

Root cause:

- The raw Collabora admin console is not suitable for direct HA iframe ingress.
- It returns CSP containing `frame-ancestors 'none'`.
- It also emits absolute `/browser/...` asset URLs, which escape the HA ingress token path when loaded through Cloudflare/HA sidebar.
- Therefore a plain `ingress_port: 9980` panel can show as a blank page even though direct `/hosting/discovery` and direct admin basic-auth work.

Fix implemented:

- Added a dedicated HA Ingress admin proxy add-on:

```text
slug: 1b7b4ce7_woow-collabora-admin
name: Woow Collabora
version: 0.1.1
ingress_panel: true
```

- The proxy:
  - injects the configured Collabora admin Basic auth header server-side;
  - replaces Collabora's CSP with an HA/Cloudflare iframe-compatible policy;
  - rewrites absolute `/browser/...` and `/cool/...` URLs to the active HA ingress prefix;
  - keeps Nextcloud Office/WOPI on the direct engine URL `http://homeassistant:9981`.

Production state on `woowtech-ssh.woowtech.io` / `https://woowtech-ha.woowtech.io`:

```text
Woow Collabora app: 1b7b4ce7_woow-collabora-admin
state: started
stage: stable
version: 0.1.1
ingress_panel: true
```

Runtime Collabora CODE engine:

```text
container: woow-collabora-code-manual
port: 9981 -> 9980
```

Note: the manual engine container is a temporary fallback because pulling `ghcr.io/alexbelgium/collabora-amd64:26.04.4.1.1` repeatedly stalled on one layer from the production HA host. The user-facing HA app/sidebar is the `Woow Collabora` ingress proxy, and Nextcloud Office points to the stable direct engine URL.

Validation after fix:

```text
GET http://homeassistant:9981/hosting/discovery
=> 200, 42453 bytes

GET http://homeassistant:9981/hosting/capabilities
=> 200, 533 bytes

Admin proxy with X-Ingress-Path test:
=> HTTP/1.1 200 OK
=> HTML size 13864
=> ingress-prefixed /browser assets: 5
=> raw root /browser assets: 0
=> CSP contains frame-ancestors allowing HA/Cloudflare iframe

Public hostname:
woowtech-ha.woowtech.io resolves from the production HA host
```

## 2026-09-22 mobile Cloudflare ingress screenshots investigation

User screenshots showed two symptoms when browsing from Cloudflare/phone:

1. Nextcloud panel showed browser error: redirect count too high.
2. Collabora panel loaded the dashboard but opened a modal: `伺服器已關閉；請重新載入頁面。`

Important observation: the screenshots' address bar shows `tech-ha.woowtech.io`, while the production hostname under test is `woowtech-ha.woowtech.io`. On the production HA host, Cloudflared config only routes `woowtech-ha.woowtech.io` to HA. `tech-ha.woowtech.io` does not resolve from the HA host and should not be used for this deployment.

Findings and fixes:

### Nextcloud

The production Nextcloud Ingress config was not applying `sub_filter` to HTML responses, only to CSS/JS/XML/JSON. That left some login page root-relative links insufficiently handled under HA Ingress/Cloudflare.

Fix:

```nginx
sub_filter_types *;
```

Deployed version:

```text
Woow Nextcloud 33.0.8
state: started
```

Live config verified inside container:

```text
/config/nginx/site-confs/woow-nextcloud-ingress.conf
sub_filter_types *;
```

### Collabora

The Collabora dashboard modal was caused by the admin websocket being rejected by Collabora. Logs showed:

```text
Rejecting origin [https://woowtech-ha.woowtech.io] expected [http://homeassistant:9981] instead
Rejecting admin WebSocket upgrade due to disallowed origin
```

The admin proxy previously proxied the admin HTML correctly, but it forwarded the upstream local host/proto (`homeassistant:9981`, `http`) to Collabora. Collabora validates `/cool/adminws` websocket origin against this perceived external URL, so the websocket was closed and the UI showed `伺服器已關閉`.

Fix in `Woow Collabora` admin proxy:

```nginx
proxy_set_header Host "<public-ha-host>";
proxy_set_header X-Forwarded-Proto https;
```

Deployed version:

```text
Woow Collabora 0.1.2
state: started
ingress_panel: true
```

Validation:

```text
GET http://homeassistant:9981/hosting/discovery => 200
GET http://homeassistant:9981/hosting/capabilities => 200
Collabora admin websocket with Origin https://woowtech-ha.woowtech.io => HTTP/1.1 101 Switching Protocols
```

Current production add-ons:

```text
Woow Nextcloud: 33.0.8 started
Woow Collabora: 0.1.2 started
```
