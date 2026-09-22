# Validation checklist

- `curl http://127.0.0.1:8000/status.php`
- `curl http://127.0.0.1:8000/hosting/discovery`
- `curl http://127.0.0.1:9980/hosting/capabilities`
- websocket handshake to `/cool/adminws`
- HA sidebar iframe preserves HA headbar
- browser opens `.docx`, `.xlsx`, `.pptx`, legacy Office files, CSV; PDF opens in Nextcloud PDF viewer
- WebDAV PROPFIND against public URL
