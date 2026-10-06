# Gate 3：NC 33.0.0 → 33.0.9 → 34.0.4 → 35.0.1 逐版升級與完整回退（2026-10-06）

範圍：`nextcloud-ha-upgrade-rehearsal` 普通 k8s 容器（root＋預設 capabilities，無 SYS_ADMIN），全新合成資料。**不是 HAOS／Supervisor 驗收，未接觸正式 HA/PaaS。** PostgreSQL 全程 16.15，未與核心升級綁在一起。

## 映像（皆由 `fe7be12` 建置，Nextcloud tarball 於建置時驗證 SHA256＋發行簽章）

| NC | registry digest | config |
|---|---|---|
| 33.0.0（Gate 1，`cb5cf41`；事後逐檔比對官方簽章 tarball 相同） | `sha256:d44cf5df8f09…` | `e44cb7b6…` |
| 33.0.9 | `sha256:d1a83501905f…` | `ae0120fc…` |
| 34.0.4 | `sha256:940934dfb554…` | `61b32aa5…` |
| 35.0.1 | `sha256:bf060cccafd9…` | `d8752bdc…` |

投遞：使用者核准沿用叢集內 traefik＋正式 TLS 方式；每次臨時 NetworkPolicy 只給發佈 Pod、Job 結束即刪；經公網路徑取回 manifest，config 與各層 digest 皆與 tar 相同。

## 合成資料與每階段快照

admin＋兩個普通帳戶（各自原密碼 DAV 登入）、marker 檔 hash、一個有 2 個舊版本的檔案、user→user2 唯讀分享、app 設定值、richdocuments 版本、CODE discovery、PGDATA／config.php／data 權限、PG 與 PHP 版本。快照腳本 `snapshot.sh`（私密研究目錄）。

## 流程與結果

| 步驟 | 結果 |
|---|---|
| B0 冷備份（縮到 0，tar＋逐檔 sha＋權限清單） | 262 MB；恢復開機後快照與基準逐字相同 |
| 33.0.0 → 33.0.9 | Update successful；快照只有版本改變 |
| B1 → 34.0.4 | Update successful；只有版本與 richdocuments（10.3.2→11.1.2）改變 |
| B2 → 35.0.1 | Update successful；只有版本與 richdocuments（→12.0.1）改變；CODE 轉 PDF 正常 |
| 製造差異 | 新檔 `after-35.txt`（200）、app 設定改為 `changed-after-35` |
| **只換回 34 映像** | 開機拒絕：`Downgrading Nextcloud from 35.0.1.1 to 34.0.4.1 is not supported`，init 停止、無服務監聽、資料未被改動 → 只換映像不是回退 |
| **完整回退到 34**（B2 還原＋34 映像） | tar sha 驗證、還原後逐檔 sha 與權限清單完全相符；快照與升 35 前**逐字相同**（after-35 404、設定還原、三帳戶原密碼可登入） |
| **完整回退到 33.0.0**（B0＋原映像） | 快照與最初基準**逐字相同** |

## 發現

1. richdocuments 不在持久的 `custom_apps`：每次換映像升級時先被「Disabled incompatible app」，再由開機流程從 app store 安裝當前相容版本。功能上可恢復，但升級與開機依賴 app store 可用，且版本不受鎖定。建議改裝到 `custom_apps` 或於映像內固定版本。
2. PG 資料庫 locale 為 `C.UTF-8`（libc provider，無 collation version）；本次 PG 不換大版本、glibc 同為 2.41，未見 collation 警告。來源 HA（bookworm／glibc 2.36）PGDATA 搬到 trixie 的情境**未在此驗證**（本次是全新 initdb）。
3. 升級失敗與降版都會讓 init 停止；容器仍維持 Running（HAOS 由 watchdog 偵測，k8s 需 probe）。

## 未完成

- 以**舊 HA（bookworm／PHP 8.2）產生的資料**升到新封裝（含 glibc／ICU 變化對 PG 索引的影響）；本次起點是新封裝自己的 33.0.0。
- HAOS／Supervisor（ingress、add-on 備份還原、啟停）、ARM、CODE 瀏覽器開檔編輯、正式維護窗口。

## 追加（2026-10-06）：richdocuments 改為持久安裝（使用者核准）

修改：`init-nextcloud-config` 寫入 `apps.config.php`，只讓持久的 `custom_apps` 可寫；`init-richdocuments-config` 只在元件缺少時安裝、在升級後被判不相容時才 `app:update`，routes 修補只在檔案真的改變時才重新啟用。

以 ConfigMap 疊加新腳本到叢集候選實測：

| 情境 | 結果 |
|---|---|
| 舊安裝（元件在非持久 `apps/`）換上新腳本 | 自動安裝到 `/data/nextcloud/custom_apps/richdocuments`（10.3.2），routes 修補套用 |
| 一般重開機 | 無安裝／更新，`info.xml` mtime 不變，CODE discovery 200 |
| 換映像 33.0.0→33.0.9 | 元件原封不動（仍 10.3.2），不再「停用→重下載」 |
| 主版本 33→34 | Nextcloud 判不相容停用 → 腳本 `app:update` 到 11.1.2 → 啟用；34 上重開機 mtime 不變 |

測試後已移除疊加並以 B0 還原，快照與基準逐字相同。
