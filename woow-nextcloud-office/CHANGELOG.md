# Changelog

## 0.2.6

- 一般開機的 `init-nextcloud-config` 縮短：N2840 實測每次開機約 3–3.5 分鐘 → 約 9 秒。原本每次開機都對 Nextcloud 程式目錄、`/data/nextcloud` 與資料目錄做遞迴 `chown`，image 裡的程式目錄因此每次都被整棵複製進容器（約 850 MB）；現在只改擁有者不是 `www-data:www-data` 的檔案，restore 後擁有者錯的檔案仍會修正。13 個 `occ config:system:set` 改成一次寫入 `config.php`，寫入的值和之前相同。
- 開機初期停止被強制結束（exit 137）的時間窗從約 3 分鐘縮到約 10 秒，但還沒消失：在這約 9 秒內停止，加上 Collabora 啟動中收到停止要約 5.7 秒才結束，仍會超過 Supervisor 的 10 秒期限。
- 首次安裝期間停止仍會 137（已知行為）：`maintenance:install` 本身要 1 分鐘以上。下次啟動會丟掉未完成的安裝並重新安裝（0.2.4）。N2840 上首次安裝的這段從約 5 分鐘縮到約 1.2 分鐘。
- Nextcloud 版本不變（35.0.1）。

## 0.2.5

- 停止 add-on 時不再被強制結束（exit 137）。Office（richdocuments）的設定原本是 s6 開機步驟，會等 Collabora 並執行十多個 `occ` 指令；在較慢的機器上這段沒跑完前停止，s6 會等到 Supervisor 的 10 秒期限被 SIGKILL，PostgreSQL、Redis 沒有正常關閉。現在這段設定在背景執行，nginx 起來後開機流程就完成，停止通常約 4 秒內正常結束；Collabora 還在啟動時停止會接近 10 秒期限（實測 9.3 秒）。
- Office 的行為不變：首次安裝會裝好 richdocuments，routes 修補與 WOPI 設定照舊。設定完成時 log 會印 `richdocuments configuration done`。
- 開機初期（`init-nextcloud-config` 那段；較慢的機器上每次開機約 3 分鐘，首次安裝更久）停止仍可能等到期限被強制結束（exit 137）。首次安裝被中斷時，下次啟動會丟掉未完成的安裝並重裝（0.2.4）。
- Nextcloud 版本不變（35.0.1）。

## 0.2.4

- 第一次啟動的安裝若中途被中斷（例：Supervisor 的 watchdog 在安裝期間重啟 add-on、斷電），下次啟動會丟掉未完成的安裝（`config.php` 與資料庫 `nextcloud`）並重新安裝；之前會一直停在「Nextcloud upgrade failed」，port 8000／8090 都不會開。只在 `config.php` 讀得懂且沒有 `installed` 時才這樣做，已安裝完成的資料不受影響。
- Nextcloud 版本不變（35.0.1）。

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
