# Woow Nextcloud Office Documentation

Public Nextcloud URL remains the sync/WebDAV/mobile URL. Home Assistant sidebar uses an iframe wrapper and preserves the HA headbar.

Collabora is proxied same-origin under the Nextcloud public host:

- `/hosting/*`
- `/browser/*`
- `/cool/*`
- `/collabora-admin/*`

Backups are cold backups because PostgreSQL, Redis, and Nextcloud data are persisted under `/data` and `/share`.

## 升級保護（未發布）

- `occ upgrade` 失敗時，初始化會立即失敗；不要把容器重新啟動視為修復完成，也不要直接換回舊映像配新資料庫。
- `ADMIN_PASS` 僅設定首次安裝的帳號密碼。既有帳號的密碼在重啟／升級時不自動重設；要修改請使用 Nextcloud 正式密碼管理流程。
- 升級前須確認備份同時涵蓋資料庫、`/data` 的設定／自訂Apps、實際 `/share/nextcloud` 檔案、必要金鑰與版本資訊。不要假設單一DB dump或任意HA備份選項已涵蓋全部；需在隔離儲存實際還原驗證。
- `test/test-upgrade-guard.py` 只驗證真實shell控制流程，外部服務使用stub且路徑改到臨時資料夾；它不是完整映像或HAOS/Supervisor測試。
