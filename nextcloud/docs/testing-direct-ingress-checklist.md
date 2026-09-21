# Nextcloud Direct / Ingress 測試報告與 Checklist

> 目的：驗證 Woow Nextcloud 在區網 direct port 與 Home Assistant ingress adapter 兩個入口的核心行為一致性；Cloudflare/public hostname 不納入本輪驗收。

## 0. 2026-09-21 實測摘要

| 項目 | 結果 |
| --- | --- |
| Add-on | `1b7b4ce7_woow-nextcloud` |
| Add-on version | `33.0.7` |
| Direct base | `http://homeassistant:8000` |
| Ingress adapter | `http://172.30.33.6:8090` + `X-Ingress-Path` |
| 測試帳號 | `admin` |
| Ingress allow restore | 已恢復：`allow 172.30.32.2; deny all;` |
| Cloudflare/public | 不納入本輪 |

### 0.1 已安裝並啟用的測試 Apps

本輪依需求安裝/啟用先前 N/A 的 Nextcloud apps：

| App | 狀態 / 版本 | 備註 |
| --- | --- | --- |
| Notes | enabled `6.1.0` | API create/list/delete smoke PASS |
| Calendar | enabled `6.6.1` | UI + CalDAV list PASS |
| Contacts | enabled `8.9.0` | UI + CardDAV list PASS |
| Deck | enabled `1.17.5` | UI + boards API smoke PASS |
| Forms | enabled `5.4.0` | UI + forms API smoke PASS |
| Memories | enabled `8.1.0` | UI endpoint PASS；部分 albums API path returned 404 equally direct/ingress |
| Talk / Spreed | enabled `23.0.11` | UI + room OCS API PASS；完整通話需 TURN/HPB 等外部服務另測 |
| Office / richdocuments | enabled `10.3.1` | Nextcloud Office integration app installed |
| Collabora CODE / richdocumentscode | removed | Identified as Collabora-provided built-in CODE server for local/non-production use, not Nextcloud-owned. It also cannot run in the current LSIO Alpine/musl container (`no_glibc`), so it was disabled/removed from the app directory. Full Office editing requires an external Collabora/CODE backend or a future glibc-compatible packaging strategy. |

### 0.2 Direct vs Ingress 實測結果

| 類別 | 測試項目 | 結果 |
| --- | --- | --- |
| Core | `/status.php`, `/login` | PASS |
| Assets | CSS / JS / favicon / theming asset hash | PASS |
| Auth UI | Files, Photos, Activity, Admin settings, User settings | PASS |
| Ingress rewrite | `_oc_webroot`, root URL leak, cookie path prefix | PASS |
| Root redirect | `/` no-follow → `/api/hassio_ingress/<token>/login` | PASS |
| WebDAV | MKCOL, PUT, GET, COPY, MOVE, DELETE, PROPFIND | PASS |
| Large upload | 50MB direct upload → ingress download, SHA match | PASS |
| Chunk upload | 5 x 10MB DAV upload v2 → ingress download, SHA match | PASS |
| Sharing | create direct, list ingress, public share page direct/ingress, delete ingress | PASS |
| DAV extra | `/remote.php/dav/`, principals, calendars root, addressbooks root | PASS |
| New app UI | Notes, Calendar, Contacts, Deck, Forms, Memories, Talk | PASS |
| New app API | Notes, Deck, Forms, Talk | PASS |
| Detailed app functions | Notes create/update/delete, Calendar ICS create/read/delete, Contacts VCF create/read/delete, Deck board/stack create/list/delete, Forms create/list/delete, Memories JPEG upload + UI, Talk room/create message/delete | PASS |
| Office / Collabora | Nextcloud Office (`richdocuments`) installed; built-in CODE removed; direct/ingress equivalent for installed app state | PARTIAL |

### 0.3 注意事項

- raw test clients must not follow the ingress root redirect when validating `/`; follow mode may request the prefixed URL against the adapter directly and produce a misleading 404. Correct validation is `curl --max-redirs 0` and expecting `Location: /api/hassio_ingress/<token>/login`.
- Talk is enabled and direct/ingress UI + room API pass. Full production calling still needs TURN/HPB/signaling validation.
- Notes, Calendar, Contacts, Deck, Forms, Memories, Talk, and Nextcloud Office were downloaded/installed from Nextcloud apps.
- Collabora built-in CODE (`richdocumentscode`) was checked. Its app metadata identifies it as `Collabora Online - Built-in CODE Server` by `Collabora Productivity`, for local/non-production use. Because it is not Nextcloud-owned and does not run in the current Alpine/musl container (`no_glibc`), it was removed. Full Office editing requires an external Collabora/CODE backend or a future glibc-compatible packaging strategy.
- All temporary ingress allow rules used for tests were removed after validation.

## 1. 測試環境

| 項目 | 值 / 填寫欄位 |
| --- | --- |
| Repository | `Woow_ha_nextcloud` |
| Add-on | `nextcloud/` |
| 測試日期 | `YYYY-MM-DD` |
| 測試人員 | `TBD` |
| Add-on 版本 / commit | `TBD` |
| Home Assistant / Supervisor 版本 | `TBD` |
| Nextcloud 版本 | `TBD` |
| 測試帳號 | `TBD`（避免使用個人正式帳號） |
| 測試資料夾 | `/WOOW_EQ_<run-id>` 或等效一次性路徑 |
| direct base | `http://homeassistant:8000`（或實際 host port 80 對外映射） |
| ingress base | `http://172.30.33.6:8090`（add-on ingress adapter 內部 port） |
| ingress path | `/api/hassio_ingress/<token>` |
| public base | `https://<public-nextcloud-host>` |

## 2. 範圍說明

### 2.1 Direct

- 指直接打到 Nextcloud add-on port 80 / host 映射 port 的入口。
- 預期不套用 HA ingress prefix rewrite。
- 用於基準行為比對：狀態頁、登入頁、資源檔、WebDAV、OCS share、app modules。

### 2.2 Ingress

- 指 Home Assistant Supervisor 透過 `/api/hassio_ingress/<token>` 代理至 add-on ingress adapter `:8090`。
- adapter 預期只允許 Supervisor 來源，並透過 `X-Ingress-Path` 驗證與改寫：
  - root-relative URL / assets / form action 保持在 ingress prefix 下。
  - redirect location 保持在 ingress prefix 下。
  - cookie path 改寫至 ingress prefix。
  - Direct/public 行為不可被 ingress 改寫污染。

### 2.3 Public

- 指正式公開入口，例如 public hostname 或 tunnel 後方的 Nextcloud URL。
- 本輪只做 Nextcloud 應用層 public endpoint 是否仍可用的基本比對。
- **Cloudflare 本身的 Access、WAF、cache、tunnel 穩定性與規則驗證不納入本輪測試**；若 public 結果受 Cloudflare policy 影響，需在報告中標註為外部因素，不作為 ingress adapter 阻擋條件。

## 3. 測試前置 Checklist

- [ ] 確認 add-on 已安裝並成功啟動。
- [ ] 確認 direct URL 可開啟 `/status.php` 與 `/login`。
- [ ] 確認 HA ingress UI 可從側邊欄進入 Nextcloud。
- [ ] 準備測試帳號與密碼，具備檔案讀寫與分享權限。
- [ ] 設定環境變數，避免密碼進入 shell history 或測試報告：

```bash
export NEXTCLOUD_USER='<test-user>'
export NEXTCLOUD_PASS='<test-password>'
export DIRECT_BASE='http://homeassistant:8000'
export INGRESS_BASE='http://172.30.33.6:8090'
export INGRESS_PATH='/api/hassio_ingress/<token>'
export PUBLIC_BASE='https://<public-nextcloud-host>'
```

- [ ] 確認測試會使用一次性資料夾，測試後可安全刪除。
- [ ] 確認目前不是備份、升級、資料庫維護或大量同步時段。
- [ ] 若需從 Supervisor 外部直接打 `:8090`，先完成「臨時 ingress allow」並安排 restore。

## 4. 臨時 Ingress Allow 操作與 Restore

> 原則：`8090` ingress adapter 預設只應允許 Home Assistant Supervisor 來源（目前設定包含 `allow 172.30.32.2; deny all;`）。任何為測試新增的來源 IP 都必須是短時間、最小範圍、可追蹤，測試後立即還原。

### 4.1 建議流程

1. 記錄測試 client IP、時間、操作者與原因。
2. 備份目前 ingress adapter 設定或保留原始檔內容。
3. 僅加入單一測試 client IP，例如：

```nginx
allow 172.30.32.2;      # Home Assistant Supervisor
allow <test-client-ip>; # TEMP TEST ONLY, remove after test
deny all;
```

4. reload / restart 相關 nginx 或 add-on 服務，使設定生效。
5. 執行測試。
6. 立即移除 `allow <test-client-ip>;`。
7. reload / restart 相關 nginx 或 add-on 服務。
8. 驗證非 Supervisor / 非允許來源再次被拒絕。
9. 在測試報告中記錄 restore 完成時間。

### 4.2 Restore Checklist

- [ ] 已移除所有臨時 `allow <test-client-ip>;`。
- [ ] `deny all;` 仍存在且位於 allow 規則之後。
- [ ] `:8090` 未被 add-on `ports` 對外發布。
- [ ] 非允許來源直接存取 `http://<addon-ip>:8090/` 預期為拒絕或不可達。
- [ ] HA ingress UI 仍可正常使用。

## 5. 安全注意事項

- 不要提交、貼上或保存正式密碼、session cookie、ingress token、share token。
- 測試帳號應使用最小權限；測試後移除測試檔案與公開分享。
- 測試資料避免包含個資、客戶資料或不可公開內容。
- public endpoint 測試不可為了通過而放寬 Cloudflare / DNS / tunnel 安全規則。
- 大檔與 chunk upload 測試需控制大小，避免耗盡儲存空間、觸發備份或影響正式同步。
- 若測試中發現 root URL leak、跨入口 cookie path 異常、redirect 跳出 ingress prefix，應視為 ingress 安全/隔離問題並停止擴大測試。

## 6. 測試矩陣

結果欄建議填：`PASS` / `FAIL` / `N/A` / `BLOCKED`。每項需記錄 direct、ingress、public 的 HTTP code、關鍵 header、必要時附簡短 log。

| 類別 | 測試項目 | Direct | Ingress | Public | 預期 / 驗收重點 | 結果 | 備註 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Core | `GET /status.php` | [ ] | [ ] | [ ] | HTTP code 與 JSON 結構合理；ingress 不應要求錯誤 prefix |  |  |
| Core | `GET /login` | [ ] | [ ] | [ ] | 登入頁可載入；ingress HTML 內 root-relative URL 已加 prefix |  |  |
| Core | root `/` redirect | [ ] | [ ] | [ ] | ingress redirect 留在 `/api/hassio_ingress/<token>/login` |  |  |
| Assets | `GET /core/css/server.css` | [ ] | [ ] | [ ] | content-type、cache-control 與狀態碼合理；ingress asset URL 不漏 root |  |  |
| Assets | `GET /core/img/favicon.ico` | [ ] | [ ] | [ ] | 圖示可載入；不應出現錯誤 rewrite |  |  |
| UI | 登入後 Files app | [ ] | [ ] | [ ] | `/index.php/apps/files/` 可開啟，JS/CSS/XHR 不跳出入口 |  |  |
| UI | Navigation / app switcher | [ ] | [ ] | [ ] | 點選 app 不產生 root URL leak 或 public hostname 誤跳 |  |  |
| WebDAV | `PROPFIND /remote.php/dav/files/<user>/` | [ ] | [ ] | [ ] | 回應 207；基本目錄可列出 |  |  |
| WebDAV | `MKCOL` 測試資料夾 | [ ] | [ ] | [ ] | 建立或已存在皆需符合預期 code |  |  |
| WebDAV | direct `PUT` → ingress `GET` | [ ] | [ ] | N/A | 內容一致；驗證共用後端資料 |  |  |
| WebDAV | ingress `PUT` → direct `GET` | [ ] | [ ] | N/A | 內容一致；驗證 ingress request body 與 streaming |  |  |
| WebDAV | `COPY` / `MOVE` / `DELETE` | [ ] | [ ] | [ ] | DAV method、Destination header、cleanup 正常 |  |  |
| Share | OCS create public share | [ ] | [ ] | [ ] | share API 成功，回傳 share id / URL |  |  |
| Share | OCS list/delete share | [ ] | [ ] | [ ] | 可列出並刪除測試 share；測試後不得殘留公開分享 |  |  |
| Large file | 單檔 upload / download | [ ] | [ ] | [ ] | 建議 50–200 MB；hash 一致；無 timeout |  |  |
| Chunk upload | Nextcloud chunked upload | [ ] | [ ] | [ ] | chunk assembly 成功；大檔 hash 一致 |  |  |
| DAV clients | Desktop / mobile DAV smoke test | [ ] | [ ] | [ ] | 若有支援 client，登入與同步一個小檔 |  |  |
| Apps modules | Calendar / Contacts DAV | [ ] | [ ] | [ ] | 若啟用，CalDAV/CardDAV endpoint 可讀寫測試項 |  |  |
| Apps modules | Photos / Media preview | [ ] | [ ] | [ ] | 若啟用，縮圖/預覽資源在 ingress 下不漏 root URL |  |  |
| Apps modules | OnlyOffice / Collabora / external apps | [ ] | [ ] | [ ] | 若啟用，frame/callback URL 與 CSP 不因 ingress 破壞 |  |  |
| Security | `:8090` access control | N/A | [ ] | N/A | 非 Supervisor / 非臨時 allow client 不可直接使用 |  |  |
| Security | Missing/invalid `X-Ingress-Path` | N/A | [ ] | N/A | 預期 HTTP 400 或拒絕；不可 fallback 到 root |  |  |

## 7. N/A 模組判定規則

可標示 `N/A` 的情況：

- 該 app / module 未安裝、未啟用，且本輪變更不涉及啟用該功能。
- 測試環境缺少外部相依服務，例如 OnlyOffice / Collabora server、LDAP、S3 external storage。
- public endpoint 因 Cloudflare Access / WAF / tunnel policy 被擋，但 direct 與 ingress 測項可完整驗證；需在備註寫明「Cloudflare 不納入本輪」。
- 測項只適用 direct/ingress 的跨入口一致性，例如 `direct PUT → ingress GET`，public 可標示 N/A。
- 大檔或 chunk 測試若受測試環境容量限制可標示 `BLOCKED` 或 `N/A`，但需記錄限制原因與建議補測條件。

不可標示 `N/A` 的情況：

- Core、login、assets、基本 WebDAV 在目標環境本應存在但失敗。
- Ingress prefix rewrite、redirect、cookie path、`X-Ingress-Path` 驗證等本輪核心驗收項。
- 測試前置未完成但可修復者；應先標 `BLOCKED`，修復後再測。

## 8. 建議自動化入口

目前可用腳本：

```bash
cd /home/woowtechcluster1/Woow_ha_nextcloud
NEXTCLOUD_USER='<test-user>' \
NEXTCLOUD_PASS='<test-password>' \
DIRECT_BASE='http://homeassistant:8000' \
INGRESS_BASE='http://172.30.33.6:8090' \
INGRESS_PATH='/api/hassio_ingress/<token>' \
PUBLIC_BASE='https://<public-nextcloud-host>' \
./nextcloud/test/live-direct-ingress-equivalence.sh
```

補充：此腳本涵蓋 core/assets/WebDAV/share/ingress prefix smoke test；UI 操作、app modules、large/chunk upload 仍需人工或後續自動化補強。

## 9. 測試報告摘要模板

```text
測試日期：
測試人員：
Add-on commit / version：
Direct base：
Ingress base/path：
Public base：
Cloudflare：不納入本輪（僅記錄 public endpoint 結果）

Summary:
- PASS:
- FAIL:
- N/A:
- BLOCKED:

主要風險 / 發現：
1.
2.

Ingress allow restore：已完成 / 未完成（時間：）
殘留測試資料：無 / 有（位置：）
後續補測：
```

## 10. 2026-09-21 Collabora / Nextcloud Office integration result

Result: PASS

Implemented and deployed independent Woow Collabora CODE add-on:

```text
slug: 1b7b4ce7_woow-collabora
version: 26.04.4.1.1
direct/WOPI URL: http://homeassistant:9981
HA Ingress admin URL: /api/hassio_ingress/<token>/browser/dist/admin/admin.html
```

Nextcloud `richdocuments` was configured to:

```text
wopi_url: http://homeassistant:9981
public_wopi_url: http://homeassistant:9981
```

`occ richdocuments:activate-config` passed and detected:

```text
Collabora Online Development Edition 26.04.4.1
```

Validation summary:

| Area | Result |
| --- | --- |
| Collabora `/hosting/discovery` | PASS, `200 text/xml` |
| Collabora `/hosting/capabilities` | PASS, `200 application/json` |
| Collabora admin direct auth | PASS, `401` without auth and `200` with admin auth |
| Collabora conversion worker | PASS, `/cool/convert-to/pdf` returned generated PDF |
| HA Ingress panel | PASS, `ingress_panel: true`, admin URL generated |
| Nextcloud Office config activation | PASS |
| Nextcloud Office admin/settings direct vs ingress | PASS, both `200` |
| Ingress test allowlist restore | PASS, restored to Supervisor-only allowlist |

Design note: Collabora admin GUI uses HA Ingress; Nextcloud Office/WOPI uses the stable direct/public Collabora endpoint. Do not configure Nextcloud Office to use the HA ingress token URL.
