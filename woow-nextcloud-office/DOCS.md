# Woow Nextcloud Office Documentation

Public Nextcloud URL remains the sync/WebDAV/mobile URL. Home Assistant sidebar uses an iframe wrapper and preserves the HA headbar.

Collabora is proxied same-origin under the Nextcloud public host:

- `/hosting/*`
- `/browser/*`
- `/cool/*`
- `/collabora-admin/*`

Backups are cold backups because PostgreSQL, Redis, and Nextcloud data are persisted under `/data` and `/share`.
