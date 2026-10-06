# Gate 1／Gate 2：候選映像投遞與普通容器真啟動（2026-10-06）

範圍：`woow-k3s` / `nextcloud-ha-upgrade-rehearsal`，全新合成 `/data`、`/share` 與 options。**不是 HAOS／Supervisor 驗收、不是升級或還原驗收、未接觸任何正式 HA/PaaS 資料。**

## Gate 1 — 投遞（使用者核准方案：叢集內 traefik＋正式 TLS）

| 項目 | 值 |
|---|---|
| 來源 | `cb5cf41`，context SHA256 `246bf39d…`，Kaniko 產物 tar（PVC `build-artifacts` UID `a8f63952…`） |
| tar | 1,068,663,296 bytes，SHA256 `684686787df3…c500c358`（發佈 Job 的 init 容器重新驗證 OK） |
| 傳送 | 同一 crane digest、同一 registry 帳密；`hostAliases` 指向 traefik ClusterIP，TLS 照常驗 `jcr-prod.woowtech.io` 正式憑證；臨時 egress NetworkPolicy 只對發佈 Pod、只到 traefik 8443，Job 完成後刪除 |
| 結果 | 12 秒推完，無 413；`…/nextcloud-ha-office-rehearsal@sha256:d44cf5df8f0900d000b139904330964456ca97169e1acdfb51c825687eb426fc`（docker v2 manifest） |
| 核對 | 經一般公網路徑取回 manifest：config `sha256:e44cb7b6…` 與 tar 相同；6 層 digest 與 tar 內壓縮層逐一相同 |
| 註 | Kaniko 本地 digest `ee2c6714…` 是另一種 manifest 序列化；內容（config＋各層）相同 |

## Gate 2 — 普通容器真啟動

部署：Deployment `ha-cand`（Recreate）、PVC `ha-cand-data` 8Gi／`ha-cand-share` 4Gi、`/tmp` memory tmpfs、避開 59mqj。root＋**預設 container capabilities**（CapEff `a80425fb`），無 privileged、無 SYS_ADMIN、無 host mount。options 由 init 容器在首次開機寫入（重啟不覆寫），`NEXTCLOUD_PUBLIC_URL`／`HA_PUBLIC_URL` 明確設為隔離網址；隨機密碼只在私密目錄。kubelet 以 digest 拉取映像約 56 秒。

| 檢查 | 結果 |
|---|---|
| s6 `/init` | 所有 init/svc 成功，`legacy-services` 完成 |
| OS／libc／ICU | Debian 13 trixie、glibc 2.41-12+deb13u4、libicu76 76.1-4 |
| PHP | CLI 與 FPM 皆 8.4.26；所需 modules（pdo_pgsql、redis、apcu、imagick、intl…）載入；FPM socket `/run/php/php8.4-fpm.sock`（www-data 660）、PID 檔一致 |
| nginx | 1.26.3，`nginx -t` 通過 |
| PostgreSQL | 16.15（PGDG）；`nextcloud`／`template1`／`postgres` 皆 libc provider `C.UTF-8`，`datcollversion` 空（無版本化 collation）、UTF8 |
| Redis | 8.0.2，unix socket PONG |
| Nextcloud | `occ status`：33.0.0.16 installed、非 maintenance、needsDbUpgrade=false；status.php 200；login 頁 200；8090 `/healthz` 200 |
| Apps | richdocuments 10.3.2、files_trashbin、files_versions 啟用 |
| 真實操作 | 普通帳戶（groups=[]）WebDAV MKCOL/PUT 201、GET SHA256 一致；錯誤密碼 401 |
| CODE | 26.04.4.2 啟動並產生 kit child；discovery 200；`/cool/convert-to/pdf` 實際轉出 PDF（12,302 bytes，`%PDF-`）—**未加 SYS_ADMIN** |
| 一般重啟 | 刪 Pod 重開：admin 原密碼仍可用（DAV 207）、檔案 hash、options hash、目錄權限（PGDATA 700、config.php 640、data 770）與版本前後**逐字相同** |
| 升級失敗 | 將合成 config.php 版本改為 99.0.0.0 並放 sentinel：`init-nextcloud-config` 印「upgrade failed; stopping initialization」exit 1；之後的設定變更未執行（sentinel 保留）、nginx／CODE 未啟動（8000/8090/9980 無監聽，healthz 失敗） |
| 還原 | 放回備份 config.php 重開：全部恢復，與基準逐字相同 |

### 發現

1. 升級失敗時容器仍維持 Running（s6 預設 `S6_BEHAVIOUR_IF_STAGE2_FAILS=0`）。HAOS watchdog 以 8090 `/healthz` 可偵測；在 k8s 上需另加 probe。
2. Dockerfile 下載 Nextcloud tarball 時原本沒有 checksum／簽章驗證。已修正：`build/verify-nextcloud.sh` 檢查固定 SHA256 並以固定發行金鑰（`28806A87…A724937A`）驗 `.asc`；以真實 33.0.0 tarball 測：正確通過，錯 SHA／竄改後同步改 SHA／他版簽章／錯指紋皆失敗。回溯核對：本候選映像 25,237 個核心檔與已驗證官方 33.0.0 tarball 逐檔雜湊相同。
3. richdocuments（1,261 檔）於開機時由 app store 安裝到容器層 `apps/`，不是持久的 `custom_apps`：每次開機重新下載，依賴 app store 可用；Gate 3 需處理 app 版本相容。

## 未完成

Gate 3（33 修補版→34→35 與完整回退）、ARM、HAOS/Supervisor、CODE 在瀏覽器實際開檔編輯（本次只驗 convert-to 與 discovery）。

證據（私密研究目錄）：`research/nextcloud-ha-upgrade-runtime/lan-publish-20261006/`、`gate2-20261006/`。
