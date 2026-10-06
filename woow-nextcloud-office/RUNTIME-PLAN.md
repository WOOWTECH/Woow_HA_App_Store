# HA PHP8.4 封裝原型（未發布、未建映像）

更新：2026-10-05 UTC。核准設計見
[`docs/plans/2026-10-05-ha-php84-design.md`](../docs/plans/2026-10-05-ha-php84-design.md)。

## 本輪實作

隔離分支採 `debian:trixie-slim` + Debian 官方 PHP8.4；PGDG suite 改為
`trixie-pgdg`（HTTPS），仍只要求 `postgresql-16 postgresql-client-16`。
16 個 PHP 套件、CLI/FPM ini、s6 `php-fpm8.4`、nginx socket 及 Office 重啟
PID 一次對齊。Samba client library 使用 trixie 的實體套件 `libsmbclient0`。

**Nextcloud 預設仍為 33.0.0，沒有直接預設 35，也未執行任何升級。**
NC35 v35.0.1 官方 composer 宣告 PHP `^8.3`，原有 PHP8.2 不足。
本輪沒有新增第三方 PHP 來源、修改 add-on 版本或發布；原 HA/PaaS 未更動。

CODE 來源延續 `abc0da3` 的固定 keyring SHA256 和 `signed-by`：

- Fingerprint：`7EB1530818B7683284483B7BD8915E456E7C440E`
- SHA256：`b77f959916c0ec2072b72860d80f9c066910d9bddd2f69534b488f4b4d5ca4dd`
- 前輪已實際 gpgv 驗證 CODE InRelease；本輪沒有重新驗簽成功的宣稱。
- 不使用 `trusted=yes`、不跳過簽章檢查；checksum 不符仍中止 build。

## 公開套件證據（amd64，非安裝／完整 solver 驗證）

| 候選／重要依賴 | 2026-10-05 公開索引觀察 |
| --- | --- |
| Debian PHP CLI/FPM | `8.4.24-1~deb13u1`；所需 16 套件皆存在，包含 imagick/redis/apcu |
| PGDG server/client 16 | `16.15-1.pgdg13+2`；保留 PG16，不引入 PG17/18 server |
| CODE coolwsd / coolwsd-deprecated | 兩者 amd64 `26.04.4.2-1`；對應 collaboraoffice `26.04.4-2` |
| glibc | trixie `libc6 2.41-12+deb13u4`，PHP/PG 要求 >=2.38 |
| ICU / SSL | `libicu76 76.1-4`；`libssl3t64 3.5.7-1~deb13u2`（Provides libssl3） |
| CODE libgcc1 | `libgcc-s1 14.2.0-19` Provides `libgcc1 (= 1:14.2.0-19)`，不是缺套件 |
| Samba library | `libsmbclient0 2:4.22.11+dfsg-0+deb13u1` Provides libsmbclient |

PG16、client16、CODE、deprecated 的直接 Depends 名稱／替代 provider
均可在索引找到；**未完整解析版本限制、transitive dependencies、Conflicts
或 maintainer scripts**。PG16 server、CODE、deprecated 的實際 `.deb` URL
HEAD 查詢均 exit 0。這支持本地原型，不證明可安裝或可執行。

另外下載官方 `php8.4-fpm` deb、比對 Packages 宣告 SHA256 後僅解開 data
（沒有安裝或執行腳本），確認：

- `php-fpm.conf`: `pid = /run/php/php8.4-fpm.pid`
- `pool.d/www.conf`: `listen = /run/php/php8.4-fpm.sock`
- pool 與 socket owner/group 皆為 `www-data`。

### 來源與原始紀錄

本機證據目錄：
`/data/pi-agent/home/research/nextcloud-ha-upgrade-runtime/php84-prototype/`

- `public-packages.json`：來源 URL、index hash、套件宣告。
- `artifact-head-checks.json`、`declaration-check.json`：可取得性與名稱檢查。
- `fpm-package/etc/php/8.4/fpm/`：未執行的套件配置內容。
- `package-check.log` / `.exit`：APT 阻擋（下節）。
- `php-runtime-red.log` / `.exit`、`php-runtime-green.log` / `.exit`：紅綠測試。

公開 indexes 及本輪取得的 SHA256：

- https://deb.debian.org/debian/dists/trixie/main/binary-amd64/Packages.xz
  — `7778d3e3f303b7ddb8ce0fe7c8d57473a076c6bf2e8f241f75421d2396352498`
- https://apt.postgresql.org/pub/repos/apt/dists/trixie-pgdg/main/binary-amd64/Packages.gz
  — `768f21147f0508610bb86a48cfda359edef4220c0ffdb371abd1532e03f1d19c`
- https://www.collaboraoffice.com/repos/CollaboraOnline/CODE-deb/Packages.bz2
  — `31b61ce083d574effec876c18a8346d003ffddfe7e4b185cb869ca39a6a537c7`
- https://raw.githubusercontent.com/nextcloud/server/v35.0.1/composer.json
- https://collaboraoffice.com/downloads/gpg/collaboraonline-release-keyring.gpg

### 精確阻擋

隔離 APT state 的 `apt-get update` 在本機 apt-key 階段回報
`cannot create /dev/null: Permission denied`，整體 exit **100**；依賴模擬
未執行。已停止該動作，沒有改權限、停用 sandbox、切換身分或放寬信任。
後續獨立 HTTPS 查詢僅是公開套件宣告檢視，不是繞過 APT 的驗簽／安裝。
須由使用者提供／批准可正常驗簽的隔離 build 環境後再接續此 gate。

## 本地測試邊界

`test/test-php-runtime.py` 的七項測試先對舊程式 exit 1（六個 test method
失敗，其中 stale-path subtests 使報表計九個 failures），修改後 exit 0。
涵蓋套件與 ini、一致路徑、實際 shell 的 FPM 執行選擇、nginx 配置生成、
Office PID 重啟及 Office 停用分支。所有服務／signal 都 stub，不是真 FPM。
本輪最終驗證（`php84-prototype/verification.json`）：

| 命令／範圍 | 結果 |
| --- | --- |
| `python3 woow-nextcloud-office/test/test-php-runtime.py` | 7 tests，exit 0 |
| `python3 woow-nextcloud-office/test/test-upgrade-guard.py` | 4 tests，exit 0 |
| `python3 woow-nextcloud-office/test/test-static-config.py` | exit 0 |
| `bash -n` 全部 rootfs run/up 與 usr/local/bin scripts | 24 files，exit 0 |
| `git diff --check` | exit 0 |

以上只驗證本地程式／stub control flow，沒有建置映像或完成 HAOS 驗收。

## 新增：離線 candidate inventory gate（2026-10-05 續作）

`qa/candidate_inventory.py` 與 [輸入規格／範例](qa/CANDIDATE-INVENTORY.md)
提供獨立、純本地的 fail-closed JSON 證據檢查。涵蓋 CLI/FPM PHP8.4
版本、modules/ini、FPM socket/PID、nginx、CODE observations，以及
source/candidate PG16 libc/ICU/locale/database/collation inventory。
缺漏、型別錯誤、失敗觀察、版本不符與 drift 都拒絕；不提供 refresh／
reindex 或忽略 drift 的開關。CLI/FPM patch 不同與 default collation
繼承處理曾以行為測試重現 2 failures，再修正。

**這不是 runtime collector。** 它只讀指定 JSON；不執行命令、網路、DB、
Docker/K8s/SSH 或服務操作。`qa/fixtures/candidate-inventory.stub.json`
僅合成測試，digest 為假設格式值，不是建好的映像。exit0 只代表輸入
一致；所有結果的 runtime/HAOS/production flags 固定 false。
真正 bookworm→trixie libc/ICU 變更預期仍會被 gate 阻擋，需要另行核准
的 migration/index-rebuild/full rollback 證據，不是本工具自行批准。

此新增不解除下列 build/runtime gates，不改動既有 Dockerfile 或服務腳本。

## 尚未完成的 gates（不得跳過）

1. **來源／artifact**：在批准環境完成 fresh signed APT update 與完整解析；
   pin base digest、套件／外部 artifact manifest，建不可變隔離映像。
   本輪 base tag、APT 候選與 Nextcloud/s6/bashio/tempio 下載未完整鎖版驗收。
2. **glibc／locale／PG collation**：bookworm→trixie 改變 libc/ICU，PG major
   不變不代表索引排序相容。現有 initdb 仍用 `C.UTF-8`，不能据此推定所有
   DB/column collation 都安全。只用合成備份，記錄源／目標 libc、ICU、
   locale、DB locale provider、datcollversion 和實際版本，以及各 collation。
   若不一致，先評估並重建受影響索引，再依 PG 文件 refresh version；
   **禁止只 refresh 版本消除警告，禁止把原 HA PGDATA 掛到候選映像。**
3. **PHP／CODE runtime**：CLI/FPM modules、ini、socket、PID、nginx、s6
   startup、Office discovery/WOPI/websocket/編輯保存、CODE jail/security
   與既有 `--version` 啟動參數都須真 runtime 檢查，不能由靜態通過代替。
4. **逐版升級與完整還原**：隔離合成 NC33→34→35，各階段先符合官方
   升級要求／維護版本，驗證應用相容與資料，再作下一 major；保留並演練
   DB + files + config/custom_apps + 匹配映像的完整 rollback。不走 33→35。
5. **ARM／HAOS**：本輪僅 amd64 metadata；config 列有 aarch64 不是 CODE
   ARM 套件或執行證據。ARM 完整依賴／映像／runtime 另驗；普通容器成功
   也不是 HAOS/Supervisor（ingress、啟停、備份還原、權限）驗收完成。

禁止將此原型發布或掛載現有資料，直到以上門檻及另行正式維護批准齊備。
