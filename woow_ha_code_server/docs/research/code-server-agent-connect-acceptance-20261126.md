# code-server Agent Connect 升級與驗收紀錄

**WIP：尚未完成全面驗收、發布正式版本或更新既有租戶。**

**R3 候選已撤回核可；R4 成品已完成建置、全新安裝三站 47 項與保留資料的升級測試。** HA 成品比較掃描發現
esbuild 內嵌舊 Go binary 新增 19 項漏洞（1 Critical、18 High）。R4 固定 esbuild `0.28.2`
與 Go `1.26.5` binary，實際 SDK 編譯相容性及 360 項 runtime／49 項擴充測試通過。
R4 的 HA 必要升級比較及漏洞比較已通過。
下文 R3 成品結果是升級對照，不能列為 R4 或正式發布的通過證據。
[R3 比對結果](https://github.com/WOOWTECH/Woow_ha_code_server_add_on/actions/runs/45913001509/job/140230408318)、
[已關閉的 R3 核可單](https://git-prod.woowtech.io/woow-paas/paas-odoo-ci/issues/806)。

**2026-11-27 下午補充：**

- 官方 Paseo 前端從 11-27 02:31Z（npm 發布；GitHub release 03:10Z）起為 **0.17.6**。
  本文件 11-27 下午以前的 R3／R4 結果都是在官方 0.17.5、Woowtech／Apporo 0.17.4 的前端取得；晚間重跑與模型驗收的前端版本見下方晚間補充。
  已用零模型核心套件對 0.17.6 補測 R4 canonical 容器：Paseo 15／15 通過，測後已還原官方設定。
  0.17.6 以前端改版為主（設定頁重新分區、模型選單方向鍵），伺服器端僅小修。
  32 項 Web 導覽套件對 R4 的重跑已在晚間完成（見下方補充）。
- PaaS 候選映像 `20261127.0043-pending-approval` 已被平台清除：核可單
  [#808](https://git-prod.woowtech.io/woow-paas/paas-odoo-ci/issues/808) 在 180 分鐘內無人 `/approve`，
  11-27 04:00Z 逾時自動關閉，依平台設計一併刪除候選 tag（JCR 查詢 tag 與 digest 皆 404）。
  沒有 promote，也沒有任何租戶變更。要再使用必須重推 tag 重新建置並重新核可。

**2026-11-27 晚間補充（R4 網頁套件重跑與 Pi 真實模型驗收）：**

- **Smart 兩站在 11-27 約 14:57 至 15:01（台北）被重新部署成 Paseo Web 0.17.5**（新的 entry bundle）；先前收據都記錄為 0.17.4。本輪每份收據都記錄當次看到的版本，下面的結果依版本分開記載，沒有把 0.17.4 的結果套到 0.17.5。
- R4 canonical 容器的 32 項 Web 導覽／偏好套件已重跑，零模型、未建立 agent：官方 0.17.6 為 31 項通過、1 項（N-13，需既有 agent）未驗收；Smart 0.17.4 時 Woowtech、Apporo 各 30 項通過、1 項失敗（N-12 workspace 多選，當時 Smart 前端沒有該功能）、1 項未驗收（N-13）；重新部署後的 Smart 0.17.5 各 31 項通過、1 項未驗收（N-13），**N-12 改為通過**（新 bundle 含多選功能，與官方相同）。官方 0.17.6 把部分設定項目移到新頁面，6 項案例改走新位置（見「R4 Web 導覽套件」）。
- Pi 已用維護者提供的 OpenAI 相容 Chat Completions 閘道，在三站完成真實對話驗收：MODEL-01、02、03、04、TOOL-01、02、MCP-01、02、AUTH-01；Smart 兩站在 0.17.4 與 0.17.5 各跑一輪。每個回覆都帶隨機字串，並由 daemon 端時間軸確認 provider、模型與新回覆，不只看畫面。結果表見「R4 模型驗收結果」。
- Claude 未登入；Codex 的 ChatGPT 帳號用量已達上限。兩者只能驗證 AUTH-01（不可用 provider 要顯示可理解的錯誤，且不能出現成功回覆），官方與 Smart 0.17.5 都通過（Smart 0.17.4 沒跑這一項）；兩者的正向案例**未驗收**。
- 驗收中發現兩項客戶端行為，詳見結果段落：頁面重整後第一次 Enter 在每個客戶端都沒有送出；由另一個客戶端觸發 MCP 更新之後，立刻送出的第一則訊息，畫面會顯示回覆，但「處理中」指示燈可能卡住，重整即恢復。後者用 Paseo 原生更新請求對照也出現，與本分支的 MCP 修補無關。

**2026-11-27 夜間補充（真機驗收）：**

- 叢集儲存已接近上限（Longhorn 只剩一個節點能排新磁碟區，各節點系統碟只剩 18～32 GB），再開測試 VM 會影響 PaaS 開新服務，所以真機驗收改在 GitHub 託管的執行機上做，沒有使用或變更任何公司主機。驗收程式與 workflow 只放在 QA 分支 [`qa/realhost-20261127`](https://github.com/WOOWTECH/Woow_podman_code_server_package/tree/qa/realhost-20261127/qa/realhost)（不合併），每份收據附 run 連結並嵌入證據 JSON。
- **原生 Podman＋systemd**（Ubuntu 24.04.5、podman 4.9.3 rootless＋linger、systemd 255、Quadlet；amd64 與實體 arm64）：README 預設路徑（`scripts/install.sh` 在主機上用 podman 本機建置，amd64 約 189 秒、arm64 約 224 秒）與「main `4.139.1-9` 用 `scripts/upgrade.sh` 升到候選 `4.139.1-10`」兩條路徑，兩個架構都通過：三站核心 47／47、原生面板 3／3、systemd 持久性 6／6。升級保留三個 volume 與工作區資料、登入密碼、備份與回退點；用 main 舊 daemon（Paseo 0.11.2）配對的同一瀏覽器，升級後 server ID 與金鑰相同、免重新配對讀到新內容。
- **真 HA OS＋Supervisor**（HAOS 18.3 在執行機上以 QEMU/KVM 開機，Supervisor 2026.11.0、Core 2026.11.3，全程 supported／healthy）：Supervisor 安裝 0.1.16 → 寫入資料並配對舊 daemon → Supervisor 更新到候選（含更新前備份）→ 三站 47／47、經真實 HA 登入與 Ingress 的原生面板 3／3、持久性 6／6（配對，以及 add-on 重啟、停止再啟動、停用跨重啟、重新啟用、主機重開機 62 秒恢復）→ 還原更新前備份回到 0.1.16 → 再次更新 → 解除安裝後全新安裝（官方 15／15），全部通過。
- **HA aarch64 映像在實體 arm64 上原生執行**（沒有可虛擬化的 arm64 HAOS 主機，改用商店 repo 固定版本的模擬 Supervisor，**不是**真 Supervisor）：真實 `/init` 啟動、R4 runtime 就緒、三站 47／47、重啟持久性 4／4。這是 aarch64 HA 映像第一次實際執行（CI 只建置）。
- 這也補上一條之前沒測過的實際升級路徑：**main／0.1.16 的 Paseo 0.11.2 直接升 R4**（先前 k3s 只測過 0.11.2→R3 與 R3→R4 兩段）。
- 驗收中觀察到 HA 2026.11 與 Supervisor 2026.11 的兩項變化（非本分支缺陷），見「真機驗收」的觀察段落。

候選套件 `4.139.1-10` 保留 code-server 核心 `4.139.1`；擴充為 `0.2.0`。
原有 ID `woowtech.paseo`、指令與設定鍵繼續沿用，顯示名稱改為 Agent Connect。

## 本次升級

- Paseo CLI、server、client、protocol 從 `0.11.2` 升為固定 npm lock 的 `0.17.5`，
  目前 code-server SDK generation 為 `0.17.5-r4-2b20ef5fac0a`，包含 HA root 模式的 Claude 相容處理。
- 三個設定檔同時選定網站、relay、主機品牌與 CORS。設定尚未套用時拒絕配對，
  offer 必須完整符合所選目標，不會將配對連結改寫到另一站。
- 安裝來源移至 `runtime-manifest/`，保留舊版 runtime 的控制能力。
  新版先在 staging 完成 npm、補丁與收據校驗，再原子發布；健康重跑不改寫 generation。
- 保留 code-server 的資料與 provider home 路徑、程序歸屬檢查與手動停止狀態。
  原對話的共享 MCP 更新保留原生 session；忙碌、等待權限及不確定 writer 是否關閉時拒絕更新。
  一般 Web 重新載入維持官方行為。
- R4 另外核對 amd64／arm64 的 compiler archive integrity、JS loader 與兩個 binary 路徑的
  實際 SHA256。R3 的 46 個檔案與五組補丁收據固定保留為控制用途，安裝 R4 不覆寫它。
- 內建瀏覽器驗收工具可明確選三站，沿用所選目標的原始 offer；支援官方 0.17.5 與
  Smart 0.17.4 的兩種既有工作區開啟流程。三站實際配對／開啟目錄及未配對隔離皆已通過，
  該輪使用 R3 對照主機，沒有模型呼叫。

## 正式網站基準

| 目標 | 正式網站 | 本輪版本 | Relay | 安全政策 |
|---|---|---|---|---|
| Paseo 官方，行為基準 | https://app.paseo.sh | 0.17.5（R3／R4 測試期間）；11-27 02:31Z 起 0.17.6 | relay.paseo.sh:443 | protected |
| Woowtech Smart | https://smart.woowtech.io | 0.17.4（R3、R4 先前測試）；11-27 約 15:00（台北）起 0.17.5 | relay.woowtech.io:443 | 既有 Smart 客戶端相容 |
| Apporo Smart | https://smart.apporo.ai | 0.17.4（R3、R4 先前測試）；11-27 約 15:00（台北）起 0.17.5 | relay.apporo.ai:443 | 既有 Smart 客戶端相容 |

每站使用全新瀏覽器 context；沒有把其他 session 的 preview 或歷史測試算作本次通過。

## 來源與發布狀態

本次共用來源 159 個檔案在 Podman、HA、k3s、PaaS build context 逐檔同步。
另核對 standalone k3s 與 PaaS 的整個 build context：固定來源快照的 631 個受 Git 管理檔案
內容與模式完全相同，包含 Dockerfile 及 .dockerignore；這是來源等價證據，不是額外發布過一份 k3s 成品。
GitHub 的三個來源另有 Gitea Git pull mirror；mirror 同步 Git refs，不包含 Release 附件。
四個變更都保留為 Draft PR，尚未合併或發布正式版本。

| 平台 | 本輪來源 | 成品／部署狀態 |
|---|---|---|
| Podman 套件 | [GitHub PR #28](https://github.com/WOOWTECH/Woow_podman_code_server_package/pull/28) | 套件 4.139.1-10、VSIX 0.2.0；R4 候選已實測 |
| HA add-on | [GitHub PR #31](https://github.com/WOOWTECH/Woow_ha_code_server_add_on/pull/31) | add-on 0.1.17 候選；使用唯一 QA tag，尚未發布穩定版 |
| standalone k3s | [GitHub PR #14](https://github.com/WOOWTECH/Woow_k3s_code_server_package/pull/14) | 共用 R4 來源已同步；既有 Chart／正式映像預設值尚未推進 |
| PaaS code-server | [Gitea PR #805](https://git-prod.woowtech.io/woow-paas/paas-odoo-ci/pulls/805) | 候選 20261127.0043-pending-approval 已於 11-27 04:00Z 因核可單逾時被平台清除；重建需重推 tag 並重新核可 |

同事請使用公開的 GHCR 候選（Podman `main-e087b31` amd64／arm64、HA 的 qa tag，digest 見證據 JSON），核對 digest 與 runtime，依各平台 README 建立獨立測試部署。
三站操作見 [Agent Connect 操作說明](https://github.com/WOOWTECH/Woow_podman_code_server_package/blob/feat/code-server-agent-connect-20261126/CONNECTORS.md)。
PaaS 候選目前已不存在（見上方 11-27 補充），請勿使用；PaaS 驗收結果只代表當時存在的候選，不能視為正式預設映像已更新。

## 本輪證據範圍

### R4 成品實測

| 成品／流程 | 已確認的結果 | 限制 |
|---|---|---|
| Podman 套件的 amd64 映像，全新資料卷 | 三站 47／47 通過 | 實際執行於隔離 k3s；原生 Podman 見本表最後三列 |
| 同一資料卷的 R3 → R4 映像升級 | 通過；同一瀏覽器免重新配對，兩次容器重建後資料與停止狀態保留 | 只操作本輪測試部署 |
| amd64／arm64 建置及 manifest／來源標籤 | 兩架構通過 | arm64 原生執行見本表最後三列 |
| HA 實際映像 root／模擬 Supervisor | 真實 `/init` 啟動及三站 47／47 通過；必要升級比較與漏洞比較通過 | 真 HA OS＋Supervisor 見本表最後三列；實體 HA 硬體仍未驗收 |
| PaaS R4 實際候選映像，全新資料卷 | 三站 47／47 通過（測試當時候選存在；現已被平台清除） | 本輪為 fresh 測試；同卷升級未執行，未更新正式租戶 |
| R4 原生面板／操作 | 5 項介面、8 項實際操作通過；另讀取模型目錄 25 筆 | 模型目錄不代表登入；對話驗收見 Pi 結果（Claude／Codex 正向案例未驗收） |
| R4 Skills 管理 | 三站各 12 項，36／36 通過；檔案、權限、aliases 與設定還原通過 | 模型實際執行技能／MCP 另見 Pi 驗收（TOOL-02） |
| R4 Web 導覽／偏好套件（32 項，零模型） | 官方 0.17.6：31 通過、1 未驗收；Smart 0.17.4：各 30 通過、1 失敗（N-12）、1 未驗收；Smart 0.17.5（重新部署後）：各 31 通過、1 未驗收 | N-13 需既有 agent，該 fixture 沒有 agent 且不可建立；N-12 失敗隨 Smart 重新部署（含多選功能）消失，不是本分支修復 |
| Pi 真實模型驗收（三站，Smart 兩個版本各一輪） | MODEL-01／02／03／04、TOOL-01／02、MCP-02 全部通過；MCP-01 產品行為全部通過，畫面同步官方與 Woowtech 0.17.5 通過、其餘未即時更新；AUTH-01 官方與 Smart 0.17.5 通過 | 只有 Pi；Claude 未登入、Codex 帳號用量已滿，正向案例未驗收；MCP-02 的「等待權限」情境 Pi 無此流程，未驗收 |
| 官方 Paseo 0.17.6 補測 | R4 canonical 容器對 0.17.6 前端：Paseo profile 核心 15／15 通過，零模型 | 只測 Paseo profile；32 項 Web 導覽套件對 R4 的重跑見上方兩列 |
| 原生 Podman＋systemd（GitHub 託管 Ubuntu 24.04；amd64 與實體 arm64） | README 本機建置、main 4.139.1-9 → 4.139.1-10 升級，兩架構都通過：三站 47／47、原生面板 3／3、systemd 持久性 6／6；舊版 0.11.2 配對的瀏覽器升級後免重新配對 | 執行機用後即毀，不是公司主機 |
| 真 HA OS＋Supervisor（HAOS 18.3 VM，Supervisor 2026.11.0，Core 2026.11.3） | Supervisor 安裝 0.1.16 → 更新到候選（含備份）→ 三站 47／47、真實登入＋Ingress 原生面板 3／3、持久性 6／6（含主機重開機）、還原備份、再次更新、全新安裝 15／15 | QEMU/KVM 虛擬硬體；本機 add-on（同一 config.yaml 與映像），不是經 WOOW HA App Store 安裝 |
| HA aarch64 映像，實體 arm64＋模擬 Supervisor | 真實 `/init` 啟動、R4 runtime 就緒、三站 47／47、重啟持久性 4／4 | 不是真 Supervisor；沒有 arm64 HAOS 主機 |

R4 成品來源固定為 `e087b314c89bfec8c1331e7c728885c7751ee440`，
amd64 digest 為 `sha256:32421d32e188a7f769762f61b901a5e77fe73e992672d276d31d85fd02175cf6`。
全新安裝沒有 `/opt/woow-connectors` 來源 overlay；managed、state 及執行中 process 均核對為
`0.17.5-r4-2b20ef5fac0a`。Paseo 15 項、Woowtech 16 項、Apporo 16 項均實際執行，沒有模型呼叫。

R3 → R4 升級使用同一組 PVC、配對金鑰、server ID、既有工作區、VSIX 與設定。
第一次重建驗證 enabled 自動恢復，接著明確 Stop、第二次重建並觀察超過 35 秒仍停止，
最後明確 Start。相同瀏覽器先後讀到三份新寫入的伺服器內容，沒有第二次配對，測試 marker 已清理。
[R4 成品建置](https://github.com/WOOWTECH/Woow_podman_code_server_package/actions/runs/45918086296)、
[HA 必要比較](https://github.com/WOOWTECH/Woow_ha_code_server_add_on/actions/runs/45924496884)、
[PaaS 候選建置](https://git-prod.woowtech.io/woow-paas/paas-odoo-ci/actions/runs/50171)、
[PaaS 核可單 #808（已逾時自動關閉）](https://git-prod.woowtech.io/woow-paas/paas-odoo-ci/issues/808)。

PaaS 全新成品獨立核對 R4 SDK、映像／pi-seed digest、正常 VSIX 安裝及空白 provider 登入狀態；
三站 47 項全部通過，最終恢復官方 target、running／reachable，兩項 pending 均為 false。
最終核對曾因 QA helper 匯入入口觸發額外一輪；該輪也為 47／47，與首次結果分別保存，
沒有重算為新的覆蓋範圍。已修正 QA 匯入入口，沒有為此修改產品；R3 對照保留。

### 真機驗收（2026-11-27 夜間）

叢集儲存已接近上限，再開測試 VM 會讓 PaaS 開不了新服務，因此改用 GitHub 託管的執行機（每次用完即毀），沒有動任何公司主機。
驗收程式在 QA 分支 [`qa/realhost-20261127`](https://github.com/WOOWTECH/Woow_podman_code_server_package/tree/qa/realhost-20261127/qa/realhost)，不會合併；所有輸出只含案例 ID、PASS／FAIL、錯誤代碼、雜湊與版本，
配對 URL、密碼與 token 只存在執行中的記憶體。三站核心套件與 k3s 的 47 項相同（transport 由 `kubectl exec` 換成
`podman exec` 或經 QEMU guest agent 的 `docker exec`）。

| 環境 | 主機 | 版本 |
|---|---|---|
| 原生 Podman amd64 | GitHub 託管 `ubuntu-24.04`（x86_64，4 vCPU，16 GB） | Ubuntu 24.04.5、kernel 7.0、systemd 255、podman 4.9.3 rootless＋linger、Quadlet 4.9.3 |
| 原生 Podman arm64 | GitHub 託管 `ubuntu-24.04-arm`（實體 Arm，aarch64，4 vCPU，16 GB） | 同上 |
| 真 HA OS | 上述 x86_64 執行機上的 QEMU/KVM VM（3 vCPU、8 GB、64 GB 磁碟、UEFI） | HAOS 18.3、Supervisor 2026.11.0、Core 2026.11.3 |
| HA aarch64 | `ubuntu-24.04-arm` 上的 Docker | 候選 aarch64 映像＋商店 `.addon-sync/mock_supervisor.py`（固定 commit `421de974`） |

**原生 Podman＋systemd**（[run 45999579311](https://github.com/WOOWTECH/Woow_podman_code_server_package/actions/runs/45999579311)）

| 項目 | amd64 README | amd64 升級 | arm64 README | arm64 升級 |
|---|---|---|---|---|
| 安裝方式 | `install.sh` 本機建置（189 秒） | main `install.sh` → `upgrade.sh`（54 秒） | `install.sh` 本機建置（224 秒） | main `install.sh` → `upgrade.sh`（71 秒） |
| 映像 | 主機上建置的 `localhost/woow-code-server:4.139.1-10` | GHCR `main-a70b33d` → `main-e087b31`（digest 與其他驗收相同，來源標籤核對） | 同 amd64 README | 同 amd64 升級（arm64 manifest） |
| 升級後資料／密碼／備份／回退點 | — | 三個 volume＋工作區不變、密碼不變、備份 1 份、回退快照與舊映像保留 | — | 同左 |
| 舊版 0.11.2 配對的瀏覽器 | — | 升級前讀到工作區；升級後 server ID 與金鑰相同、免重新配對讀到新內容 | — | 同左 |
| 三站核心 | 47／47 | 47／47 | 47／47 | 47／47 |
| 原生面板（啟用、三個網站、狀態讀取） | 3／3 | 3／3 | 3／3 | 3／3 |
| systemd 持久性 | 6／6 | 6／6 | 6／6 | 6／6 |

systemd 持久性的 6 項：配對並讀到工作區，之後依序重啟 unit、`podman kill` 後 `Restart=always` 自動拉起、停用的 Agent Connect 跨重啟保持停用
（重啟後多等 45 秒，超過 connector 服務 30 秒的恢復週期）、重新啟用後同一 server 身分、user manager 重啟（以 linger 模擬開機）；
除了停用那一項，每項都確認 server 身分不變，並由同一瀏覽器免重新配對讀到伺服器內容。
四個 job 結束時 unit、health timer、linger、Quadlet 來源、rootless 都正常。user journal 中含 error 字樣的行：amd64 README 0、
amd64 升級 0、arm64 README 1、arm64 升級 0。
那一行是 code-server 內 VS Code 的檔案監看程序被 SIGTERM 結束、隨即自動重啟的訊息
（`[File Watcher (universal)] restarting watcher after unexpected error: terminated by itself with code null, signal: SIGTERM`），時間落在第一項持久性動作（重啟 unit）停止容器時，是刻意重啟造成的預期訊息。
第三輪（[run 45979273263](https://github.com/WOOWTECH/Woow_podman_code_server_package/actions/runs/45979273263)）同樣四個 job 全部通過（README 建置 261／241 秒、
升級 51／68 秒），當時 amd64 兩個 job 各有 1 行但沒有保存內容；
第四輪重跑只是為了在收據中保留這類行的去敏範例，正式收據取第四輪。

**真 HA OS＋Supervisor**（[run 45996213760](https://github.com/WOOWTECH/Woow_podman_code_server_package/actions/runs/45996213760)）

add-on 以 Supervisor 本機 add-on 提供：檔案取自 HA 候選 commit `314a7126`（與映像同源），版本行改為 QA tag，映像仍是
`ghcr.io/woowtech/woow-ha-code-server-{arch}`。Supervisor 只要「已裝版本 ≠ 目錄版本」就提供更新，所以 0.1.16 → QA tag 是同一 slug、
同一資料目錄的真實 Supervisor 更新。

1. HAOS 開機、Core 安裝並以 API 完成初始設定；Supervisor 2026.11.0 supported／healthy。
2. Supervisor 安裝 0.1.16（manifest digest 與 GHCR 正式版相同），改一個選項後啟動，Ingress 面板建立。
3. 在 add-on 資料、VS Code 資料與 `/share` 寫入標記；舊 daemon（Paseo 0.11.2）配對官方網頁並讀到工作區。
4. Supervisor 更新到候選（含更新前備份 `addon_local_woow_ha_code_server_0.1.16`，約 120 秒）：執行中 manifest digest
   為候選 `sha256:4d531926…`；標記與選項不變；connector 服務自動恢復 0.17.5 R4 daemon；server ID 與金鑰相同；同一瀏覽器免重新配對讀到新內容。
5. 三站核心 47／47。
6. 原生面板經**真實 HA 登入畫面**與 Ingress（HA 2026.11 的 `/app/<slug>`）開啟：工作台、三個網站與狀態讀取 3／3。
7. 持久性 6／6：配對，之後依序 add-on 重啟、停止再啟動、停用跨重啟保持停用（多等 45 秒）、重新啟用、HAOS 主機重開機
   （開機自動啟動，62 秒恢復）；除了停用那一項，每項都確認同一身分並由同一瀏覽器免重新配對重連。
8. 還原更新前備份：回到 0.1.16 且標記仍在；再次更新後 Agent Connect 恢復。
9. 解除安裝（移除資料）後全新安裝候選：沒有舊資料，官方網頁核心 15／15。add-on log 錯誤 0 行，結束時 HAOS 仍 supported／healthy。

**HA aarch64 映像，實體 arm64**（[run 45981173327](https://github.com/WOOWTECH/Woow_podman_code_server_package/actions/runs/45981173327)）：候選 aarch64 映像依 digest 拉取，
真實 `/init` 5 秒內健康；node 回報 `arm64`，R4 runtime 就緒；三站 47／47；持久性 4／4（配對、容器重啟、停用跨重啟、重新啟用）；log 錯誤 0 行。
這裡的 Supervisor 是商店 repo 的模擬 Supervisor，與 amd64 HA 模擬收據相同的安排，不能視為真 Supervisor 驗收。

**舊版直接升 R4。** main（Podman 4.139.1-9）與 HA 0.1.16 內建 Paseo 0.11.2，實際使用者會直接升到 R4。先前 k3s 只驗過 0.11.2 → R3 與 R3 → R4
兩段；這次在原生 Podman（兩架構）與真 HAOS 上都直接從 0.11.2 升 R4，比照 k3s 遷移收據的步驟：升級前同一瀏覽器讀到工作區、
升級後 server ID 與金鑰檔雜湊相同、同一瀏覽器不重新配對讀到升級後才寫入的內容，全部通過。

**觀察（非本分支缺陷）：**

- HA Core 2026.11 在 Supervisor 下的預設 HTTP 埠改為 **80**（本輪新裝的 HAOS 即是如此）；8123 只在初始設定完成前保留為 307 轉址到 80，
  完成後關閉（HA 原始碼 `homeassistant/components/http/config.py`、`server.py`）。本 add-on 的 `DOCS.md` 與 README 以 `http://<HA-IP>:8123`
  為例，說明不要用區網 HTTP 網址開啟（聊天畫面會空白）；這個建議不變，只是新裝主機的區網 HTTP 網址已沒有 `:8123`，例子可在下一版文件順手更新。
- Supervisor 2026.11 對本 add-on 的 `config.yaml` 發出相容性警告：`map` 的 `addons`、`all_addon_configs` 是舊名稱，建議改成 `local_apps`、
  `all_app_configs`。目前仍可運作；改名前需確認 add-on 支援的最低 Supervisor 版本。
- HAOS 的 Docker 使用 containerd 映像儲存，容器的映像 ID 是 manifest digest（本輪以此核對候選 digest）。

**驗收程式的修正。** 前幾輪的失敗都來自驗收程式本身，收據全部保留在證據 JSON：Podman 升級線兩次因為改看主機名稱而誤判（改為 k3s 遷移收據的步驟後通過）；
HAOS 依序修正了只轉送 8123 埠、把暫時頁面的 401 當成就緒、Supervisor 2026.11 的 `apps/local` 目錄、containerd 映像 ID，以及初始設定完成後 onboarding API 會消失（重開機判斷）。
沒有為此修改產品。

**限制。** 執行機是 GitHub 託管的 VM，不是公司主機；HA OS 是 QEMU/KVM 虛擬硬體；沒有實體 HA 主機與 arm64 HAOS；add-on 用本機 add-on 提供，
沒有走 WOOW HA App Store 的安裝／更新；沒有模型呼叫或帳號登入。

### R3 對照與遷移證據

隔離測試使用獨立 namespace、資料卷、密碼、工作區與瀏覽器。
初次升級在舊 PaaS 映像上掛載本次來源，驗證相同路徑的 runtime 準備及切換。
**來源 overlay 測試不等於新建成品映像驗收，也不代表所有 HA、Podman、PaaS、k3s
正式部署已更新。** 各成品仍需自己的建置、新安裝及升級證據。

接續已完成獨立成品測試：amd64 候選映像使用全新資料卷，沒有掛載來源或
`/opt/woow-connectors` overlay，三個正式網站的相同 47 項流程全部通過。
實際映像與執行中的 managed／state／process generation 都有核對。
這證明本次 Podman 成品在隔離 k3s 測試環境的行為；HA 與 PaaS 衍生成品另列驗證。

- 成品建置來源：`537d542efba8416f8d226ba887ac9c2662eb119e`。
- amd64 digest：`sha256:00d75fa221793f18b76d0882db6af34c75cdfad6da9dd7795d10fd197ae98bc0`。
- arm64 已完成建置與公開 manifest 核對；目前沒有 arm64 節點，尚未執行原生硬體驗收。
- [候選建置](https://github.com/WOOWTECH/Woow_podman_code_server_package/actions/runs/45911036930)、
  [逐項去敏證據](code-server-agent-connect-evidence-20261126.json)。

已執行 VSIX 正常升級、實際 npm 安裝、R2 的 20,641 項 generation metadata 不變健康重用、
併發啟動、健康恢復不改寫狀態、停止後不自動啟動，以及舊版升級的穩定身分雜湊核對。
上游每次啟動會重新產生短期 `local-credential`；它與應保持相同的配對金鑰分開檢查。

獨立的舊版遷移測試也已通過：同一瀏覽器 context 從 0.11.2 升到本次 R3，
沒有產生第二個 offer 或重新配對；server ID、金鑰與工作區 ID 保持相同，
網站能讀到升級後才在伺服器寫入的新內容。該輪測試 daemon 與 UUID fixtures 已清理。

另已實際將來源 overlay 的 R3 測試容器換為上述成品映像，移除 overlay，保留同一組
PVC、配對身分、既有工作區、VSIX 內容及 IDE／Agent Connect 設定。
容器重建後背景服務自行恢復，同一瀏覽器讀到重建後的新內容；再明確 Stop 並第二次
重建，觀察超過 35 秒仍保持停止，最後明確 Start 後原瀏覽器再次讀到新內容。
這輪沒有第二次配對，且本輪 marker 已清理。它與前述 0.11.2 SDK 遷移是兩項獨立測試。

| 案例 | Paseo | Woowtech | Apporo |
|---|---|---|---|
| 明確新配對、正確 origin／relay／TLS | 通過 | 通過 | 通過 |
| 工作區讀取 | 通過 | 通過 | 通過 |
| 文字、ZIP、二進位檔真實下載及 SHA256 | 通過 | 通過 | 通過 |
| 瀏覽器重整保留連線 | 通過 | 通過 | 通過 |
| 未配對 context 無法讀取測試檔 | 通過 | 通過 | 通過 |
| 編輯、儲存、刪除及終端完整流程 | 通過 | 通過 | 通過 |
| daemon 重啟後讀取新伺服器資料 | 通過 | 通過 | 通過 |
| 三個 provider 的真實對話及模型切換（R3 當時；R4 見「R4 模型驗收結果」） | 等待測試帳號 | 等待測試帳號 | 等待測試帳號 |
| 技能與 MCP 真實工具呼叫（R3 當時；R4 見「R4 模型驗收結果」） | 等待測試帳號 | 等待測試帳號 | 等待測試帳號 |

上述來源 overlay 流程合計 47 項：Paseo 15、Woowtech 16、Apporo 16。
各站分別核對 managed、state 與實際 daemon process 的 R3 generation。
全新成品的三站流程另執行 47 項；兩輪使用不同的資料卷與瀏覽器 context。
另有 314 項 runtime／安裝器／SDK／CLI／seed 測試與 49 項擴充測試通過，均無跳過。
這是 R3 對照的數量；R4 的目前結果為 360 項 runtime／安裝器／SDK／CLI／seed 與
49 項擴充，均無跳過，另已核對實際 R3 原檔及 R4 健康安裝重用不改寫檔案。

R4 compiler 相容檢查使用實際 SDK plugin compiler 與 OpenCode bridge 編譯函式。
也發現 SDK 既有 server plugin entrypoint 限制：`export default function setup(){...}`
可由正式 loader 載入，default arrow 或先宣告 `const` 再 default export 則失敗；
R3、R4 結果一致。本次沒有改寫該 SDK compiler／loader，不能將這些形式列為已支援。

R3 原生面板已通過啟用、三站選擇、鍵盤操作、214px 面板無水平溢出、44px 控制項，
以及實際 VS Code 明／暗主題；成品映像上的五項介面與八項原生操作也均通過。
原生操作涵蓋保存設定、待套用警示、拒絕未套用配對、Stop／Start、明確新配對與實際檔案讀取。
R3 首次操作測試混淆建置產物的 root 擁有者與執行程序的 coder 身分，已修正測試假設並保留失敗紀錄，
沒有為此修改產品。只讀模型目錄取得 Claude 16、Codex 9、Pi 0 筆，尚未驗證認證。

### R4 原生面板與 Skills 管理

R4 全新成品獨立重驗介面 5／5、原生操作 8／8、三站 Skills 管理 36／36，全部通過。
實際 SDK／daemon generation 為 R4，執行身分 coder UID 1000、預建 SDK 擁有者 root UID 0；
結束後核對原設定 bytes／模式、SDK 模式、managed files／aliases 與 Skills 選擇恢復，沒有模型呼叫。
25 筆只讀模型目錄仍不代表登入成功。

[R4 一般面板截圖](code-server-agent-connect-wide-r4-20261127.png)／
[R4 214px 面板截圖](code-server-agent-connect-narrow-r4-20261127.png)。
設定套用、完整生命週期及舊配對重連分別保留紀錄；
已保存的主機名稱不能當作連線成功證據。模型目錄也不等於模型已登入或已回覆。

### R4 Web 導覽套件（零模型）

同一套 32 項 Web 導覽與偏好流程對 R4 canonical 容器重跑（全新瀏覽器 context，未建立 agent、排程或外掛，結束後還原官方設定）：

| 客戶端 | 版本 | 通過 | 失敗 | 未驗收 |
|---|---|---|---|---|
| Paseo 官方 | 0.17.6 | 31 | 0 | 1（N-13） |
| Woowtech Smart | 0.17.4（15:00 前） | 30 | 1（N-12） | 1（N-13） |
| Apporo Smart | 0.17.4（15:00 前） | 30 | 1（N-12） | 1（N-13） |
| Woowtech Smart | 0.17.5（重新部署後） | 31 | 0 | 1（N-13） |
| Apporo Smart | 0.17.5（重新部署後） | 31 | 0 | 1（N-13） |

N-12 在 Smart 0.17.4 失敗，原因是 Smart 前端沒有 workspace 多選功能（Ctrl、Meta、Shift 都沒有出現勾選列、計數或離開控制）。Smart 於 11-27 約 15:00 重新部署為 0.17.5 後，新 bundle 含 workspace-selection-count／-exit／-toast 與選取 store，N-12 通過。這個部署不是本分支所為，也不是 Agent Connect 的修復；本分支沒有發布任何 Smart 前端。N-13 需要既有 agent，該 fixture 沒有 agent 且套件禁止建立，所以五列都未驗收；後續 Pi 驗收中，每個客戶端都實際看到新建對話的 agent 分頁與重整後的還原，但那不是 N-13 的正式案例。

官方 0.17.6 的設定頁已重新分區：Send shortcut、Default send、Chat display、Terminal scrollback 與 Vim 設定移到 Chat 區；terminal、editor、files、browser 等舊路徑導向 Chat；Files 在沒有檔案面板時整個不顯示。套件改為「依頁面實際載入的控制選區」，舊版客戶端的路徑順序不變，因此 S-01、S-05、K-04、N-06、N-14、N-15 在官方站改走新位置後仍通過。N-15 的官方站通過依據比 R3 弱（R3 是看得到空白狀態卡片，0.17.6 已沒有該卡片，改為確認 Chat 頁已渲染且外掛數為 0），請把它視為「通過但不可與 R3 直接比較」。另有一次只重跑 9 項改版相關案例的官方站收據，9 項全數通過。

### 正式前端的已知差異

另以 R3 對照主機完成每站 32 項 Web 導覽與偏好流程。Paseo 31 項通過、1 項需既有
agent 而未驗收；Smart 兩站的 workspace 多選案例 N-12 失敗。已核對三站實際載入的 JS
SHA256：官方 0.17.5 含 selection handler、store、checkbox 與選取計數；Smart 正式版 0.17.4
尚未包含這些功能。Linux 的 Control 正確，改試 Meta／Shift 也無法補出不存在的介面。
這是本輪固定前端版本的差異；本分支沒有發布 Smart Web 前端，不會把它列為 Agent Connect 已修復。
[多選差異診斷](agent-connect-n12-r3-public.md) 保留當輪 JS hashes、範圍及最小處理建議。**更新：Smart 兩站已在 11-27 約 15:00（台北）重新部署為 0.17.5，新版含上述選取功能，N-12 在 R4 重跑中改為通過；上述診斷描述的是 0.17.4 時期。**
Apporo 初次 Tasks 導覽未完成，後續聚焦重驗已通過，初次紀錄仍保留。

R3 的 Skills 管理另完成三站各 12 項，共 36 項：安裝、更新、解除安裝及狀態傳播，並核對
實際檔案、模式、已知 aliases 與選擇設定，最後恢復原狀。這不等於模型實際使用技能或 MCP。

## 同事實測流程

1. 使用相符 runtime 的候選 code-server，確認 Extensions 顯示 **Agent Connect**，
   ID 為 `woowtech.paseo`。單獨安裝 VSIX 不會替舊映像安裝新版 SDK。
2. 開啟面板，填入容器內工作區路徑、主機名稱及 Web app，按 **Save configuration**。
   如設定待套用，等對話閒置後按 **Stop**、再按 **Start**。
3. 確認 Selected target 與 Active target 相同，再按 **Pair with selected Web app**，
   在對應網站確認 **Connect**。不要將配對 URL 貼入聊天、設定或問題回報。
4. 測試工作區、檔案讀寫與下載、終端、網站重整與 daemon 重啟。
   重連後讀取重啟後才產生的新內容，不能只看舊主機名稱。
5. 分別登入測試部署的 Claude、Codex、Pi，從即時目錄選模型。
   測試新回覆、串流、停止、續聊、同一對話切換第二個模型及技能／MCP 呼叫。
   每個 provider、模型、網站各自記錄；登入與額度錯誤保持失敗狀態。
6. 換網站時重做完整設定及配對，使用新 context，不改寫其他網站的 offer。
   重整頁面後確認訊息真的出現在對話中再等回覆（第一次 Enter 可能沒有送出）；更新共享 MCP 後，已開啟的頁面請等十幾秒再送出訊息，或先重整。
7. 僅清理本輪建立的檔案、終端及對話。關閉面板會保留背景連線；需關閉時明確停止。

回報包含候選映像 digest、套件／擴充版本、實際網站版本、案例 ID、預期與實際結果，
以及去敏截圖。不要附密碼、token、配對 URL、瀏覽器 storage 或原始 provider 診斷。

## 帳號就緒後的模型驗收表

以下案例需在 Paseo 基準站先執行，再以 Woowtech、Apporo 對照。每個網站的 Claude、
Codex、Pi 各自填一份結果；即時模型目錄可讀取不代表帳號可用。

| 案例 ID | 操作 | 通過依據 |
|---|---|---|
| MODEL-01 | 選目前可用模型，開新對話要求回覆本輪隨機字串 | 正確 provider／模型、串流事件及完成回覆 |
| MODEL-02 | 要求較長回覆，串流期間按停止 | 回覆停止，狀態回到可輸入，可接續提問 |
| MODEL-03 | 記住另一個隨機字串，重整網站後要求取回 | 原對話內容保留，可讀取新回覆 |
| MODEL-04 | 同一對話改用第二個可用模型，再追問前文 | 原生對話 ID 保持、模型確實切換、前文可續接 |
| TOOL-01 | 使用只讀工具讀取本輪工作區 fixture | 真實工具事件及 fixture 的實際內容一致 |
| TOOL-02 | 呼叫明確指定的測試技能及 MCP 只讀工具 | 可辨認工具／技能來源，沒有拿文字模擬工具成功 |
| MCP-01 | 閒置時更新共享 MCP，再於同一對話呼叫新增工具 | 原生對話 ID 保持，新工具實際可用 |
| MCP-02 | 回覆忙碌或等待權限時嘗試更新 MCP | 拒絕不安全更新，原對話仍可完成或停止 |
| AUTH-01 | 使用未登入或額度不足的測試狀態 | 顯示可理解的錯誤，不回報模型驗收成功 |

上表各案例已用 Pi 在三個客戶端完成，Claude 與 Codex 的正向案例仍未驗收，結果見下一節。
真實語音／麥克風、需 agent 的 Tasks／排程執行也尚未驗收；本輪僅測 Tasks 搜尋及排程頁面，不含建立或執行。
如某個 provider 沒有第二個可用模型，MODEL-04 記錄為未驗收並保留原因。

## R4 模型驗收結果（2026-11-27，Pi）

### 測試條件

- 隔離 QA 容器，映像 `main-e087b31`（amd64 digest `sha256:32421d32…02175cf6`）、runtime `0.17.5-r4-2b20ef5fac0a`；每個客戶端各用全新瀏覽器 context 重新配對：Paseo 官方（0.17.6）、smart.woowtech.io 與 smart.apporo.ai（先 0.17.4，11-27 約 15:00 重新部署後再以 0.17.5 重跑一輪）。
- Pi 使用維護者提供的 OpenAI 相容 Chat Completions 閘道（端點與金鑰不記錄於公開文件）。模型 A 為維護者指定的 `nvidia/nemotron-3-ultra-550b-a55b:free`；模型 B 為測試者選定的 `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free`，用於 MODEL-04。原先挑的 `nemotron-3-super-120b` 在閘道回 404／429，已留下失敗紀錄並改用模型 B。
- 每個回覆都帶隨機字串；通過依據是 daemon 端時間軸確認 provider、模型與「新的」回覆，並同時看畫面。收據不含對話內容、配對連結或瀏覽器狀態；對話在測後都已封存。
- Claude 未登入；Codex 以 ChatGPT 帳號登入，但該帳號用量已達上限，所以兩者只用於 AUTH-01。
- 測後清理已驗證：Codex 登出並刪除登入檔、Pi 閘道設定刪除（容器內掃描不到金鑰）、技能／MCP 夾具拆除、殘留的測試對話封存、連線設定回到官方且運作中。

### 結果

| 案例 | Paseo 官方 0.17.6 | Woowtech 0.17.4 | Apporo 0.17.4 | Woowtech 0.17.5 | Apporo 0.17.5 | 說明 |
|---|---|---|---|---|---|---|
| MODEL-01 | 通過 | 通過 | 通過 | 通過 | 通過 | 新回覆；provider、模型與串流回覆都由 daemon 確認 |
| MODEL-02 | 通過 | 通過 | 通過 | 通過 | 通過 | 串流中按停止：回覆只含部分輸出，狀態回到可輸入，之後的新提問正常回覆 |
| MODEL-03 | 通過 | 通過 | 通過 | 通過 | 通過 | 重整後歷史仍在；**重整後第一次 Enter 在每個客戶端都沒有送出**，第二次才成功（見下方） |
| MODEL-04 | 通過 | 通過 | 通過 | 通過 | 通過 | 同一對話切換第二模型：原生對話 ID 不變，模型確實切換，前文可續接 |
| TOOL-01 | 通過 | 通過 | 通過 | 通過 | 通過 | 工具事件為 `read`，輸出含只存在於檔案內的隨機字串 |
| TOOL-02 | 通過 | 通過 | 通過 | 通過 | 通過 | 技能＋MCP：夾具紀錄各有 1 次新呼叫，回覆與夾具回傳一致 |
| MCP-01 | 通過 | 產品通過、畫面未即時更新 | 產品通過、畫面未即時更新 | 通過 | 產品通過、畫面未即時更新 | 閒置時更新共享 MCP：產品行為（原生續接、同一對話 ID、歷史保留、新工具實呼叫 1 次）全部通過；畫面同步見下方 |
| MCP-02 | 通過 | 通過 | 通過 | 通過 | 通過 | 忙碌時嘗試更新：先由 daemon 確認對話忙碌，回 `SESSION_BUSY`，原回覆繼續，按停止後同一對話仍可回覆；「等待權限」情境未驗收 |
| AUTH-01 | 通過 | — | — | 通過 | 通過 | Claude 顯示未登入、Codex 顯示額度用盡，皆無成功回覆；Smart 0.17.4 沒跑這一項 |

### 需要注意的客戶端行為

**頁面重整後第一次 Enter 沒有送出。** 第一次 MODEL-03 測試有兩站失敗，讀 daemon 時間軸確認「重整後的提問」從未到達 daemon（歷史訊息裡沒有那一句，Woowtech 那次剛好送出）。改為等歷史訊息還原後再送、並確認客戶端接受送出後，五組客戶端／版本都是第二次 Enter 才成功。判斷是 Web 客戶端重整後的重連時機，不是 daemon 或本分支行為；首次失敗的收據保留在證據 JSON。（Apporo 0.17.5 的第一次 MODEL-02／03 另有一次重整時瀏覽器逾時，重跑通過。）

**由另一個客戶端觸發 MCP 更新後，立刻送出的第一則訊息可能讓「處理中」指示燈卡住。** MCP-01 的產品行為在所有客戶端都完成：閒置時加入共享 MCP、呼叫 `refreshMcp`（原生續接、同一對話 ID、歷史保留），再於同一對話呼叫新加入的工具，夾具紀錄 1 次新呼叫。但更新後立刻送出的提問，畫面常顯示了回覆，卻一直顯示「處理中」，重整後恢復；daemon 端已有完整回覆（Pi 工作階段約 4 秒內完成）。11 次 MCP-01 嘗試中，畫面全程同步 5 次、不同步或逾時 6 次，不綁特定客戶端或版本：官方 0.17.6 兩次同步、一次沒有；Woowtech 0.17.4 一次同步、一次沒有；Woowtech 0.17.5 兩次同步；Apporo 0.17.4 與 0.17.5 各兩次都沒有。為判斷來源，用同一腳本對照本分支的 `refreshMcp` 與 Paseo 原生的 refresh_agent_request：更新後立刻送出時，Apporo 0.17.4 兩種路徑各 3／3、官方 0.17.6 各 1／1 都出現指示燈卡住；更新後先等 12～15 秒再送出，官方 0.17.6 1／1、Apporo 0.17.5 2／2 沒有卡住。因此這不是本分支的 MCP 修補造成，也不影響 daemon 端結果；實際使用時，更新共享 MCP 後建議等十幾秒再於已開啟的頁面送出訊息，或重整頁面。這是客戶端行為，不在本分支修補範圍。

### 仍未驗收

- Claude、Codex 的正向案例（MODEL-01 至 MCP-02）：Claude 未登入，Codex 的 ChatGPT 帳號用量已達上限，需新的測試帳號或等額度恢復。
- MCP-02 的「等待權限」情境：Pi 沒有權限詢問流程，需 Claude 或 Codex。
- 真實語音／麥克風、需 agent 的 Tasks／排程執行，以及 N-13（需既有 agent 的案例）。
- 真機部分已在 GitHub 託管執行機上補驗（見「真機驗收」）；仍未涵蓋實體 HA 硬體、arm64 HA OS（HA aarch64 映像只在實體 arm64 上搭配模擬 Supervisor 驗證）、經 WOOW HA App Store 安裝／更新的路徑（本輪用同一 config.yaml 與映像的本機 add-on）、公司自有主機，以及 PaaS 同卷升級（候選已被清除）。
