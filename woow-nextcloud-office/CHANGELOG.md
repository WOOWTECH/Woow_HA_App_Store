# Changelog

## 0.2.3

- Nextcloud 35.0.1（大版本 35）；建置時驗證官方 SHA256 與發行簽章。
- **升級順序**：必須先在 34.0.4（0.2.2） 上完成升級並確認正常，才能更新到本版；不可跨大版本。更新前請備份本 add-on 與 `/share/nextcloud`。
- richdocuments 會在升級後自動更新到與 Nextcloud 35 相容的版本。

## 0.2.2

- Nextcloud 34.0.4（大版本 34）；建置時驗證官方 SHA256 與發行簽章。
- **升級順序**：必須先在 33.0.9（0.2.1） 上完成升級並確認正常，才能更新到本版；不可跨大版本。更新前請備份本 add-on 與 `/share/nextcloud`。
- richdocuments 會在升級後自動更新到與 Nextcloud 34 相容的版本。

## 0.2.1

- 執行環境改為 Debian trixie＋PHP 8.4（Nextcloud 34／35 需要 PHP ≥ 8.3）；PostgreSQL 維持 16。
- Nextcloud 33.0.9；建置時驗證官方 SHA256 與發行簽章。
- 改為預建映像 `ghcr.io/woowtech/woow-ha-nextcloud-office-amd64`，Home Assistant 只下載不在裝置上建置；目前僅 amd64。
- richdocuments（Office）安裝在持久的 `custom_apps`，一般開機不再重新下載，只在升級後不相容時更新；舊安裝自動遷移。
- 升級失敗或降版時停止開機流程，不再繼續改設定；不再於開機時重設既有管理員密碼。
- **升級順序**：Nextcloud 不允許跨大版本。請先更新到本版（33.0.9），之後依序更新 34、35。更新前請備份本 add-on 與 `/share/nextcloud`。

## 未發布：升級保護

- Nextcloud 升級失敗時保留非零狀態並停止初始化，不再繼續改設定。
- 既有安裝重啟／升級時不再自動重設管理員密碼；`ADMIN_PASS` 僅用於首次安裝。
- 新增隔離臨時檔案系統的 shell 流程測試；尚未建置新映像或完成 HAOS 升級驗收。
- CODE apt來源移除`trusted=yes`，改用已核對官方簽章的固定checksum keyring與signed-by；封裝runtime候選及下一步見RUNTIME-PLAN.md。

## 0.1.0

- Initial experimental Debian-based all-in-one Nextcloud Office add-on skeleton.
