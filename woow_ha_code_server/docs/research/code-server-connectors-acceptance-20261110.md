# code-server Paseo／Omnigent 驗收紀錄（2026-11-10）

Podman、HA、PaaS 的 **6 個 Web 組合、每組各 3 個代理**均已取得真實助理回覆、同一代理對話內切換模型、上下文保留，以及共用 skill／MCP 實際調用證據。**PaaS Paseo 的 Codex 完整工具測試使用 Full Access；預設 Auto review 模式的 shell 測試未通過**，限制詳見下文。這是 QA 驗收，相關 PR 尚未合併，主要服務尚未換版。

使用者已完成 PaaS Claude Code 與 Codex 授權。Pi 依使用者指定改用 LiteLLM API key，預設為 `woow-litellm/apporo/gpt-6-sol`，不需要 Pi OAuth。PaaS qa6 換版後，三份登入檔的位元組、Pi 預設與模型設定，以及原 Omnigent host 身分均保留；沒有複製其他環境的登入檔。

## Web 真實模型與工具驗收

| 環境與 Web | Claude Code | Codex | Pi Agent | 同一對話模型切換、上下文、skill／MCP |
| --- | --- | --- | --- | --- |
| Podman QA／Paseo Web | PASS | PASS | PASS | PASS |
| HA QA／Paseo Web | PASS | PASS | PASS | PASS |
| Podman QA／Omnigent Web | PASS | PASS | PASS | PASS |
| HA QA／Omnigent Web | PASS | PASS | PASS | PASS |
| PaaS QA／Paseo Web | PASS | PASS（Full Access） | PASS（LiteLLM） | PASS，保留預設模式限制 |
| PaaS QA／Omnigent Web | PASS | PASS | PASS（LiteLLM） | PASS |

PaaS Paseo 的三代理對話使用 qa5；Omnigent Claude／Codex 使用 qa5，Pi 使用修正後的 qa6。Podman、HA 的原始模型驗收保留其當次版本，不把後續安裝套件或不呼叫模型的檢查當成重新執行全部對話。

| Web | 代理 | 實際測試的第一模型 → 第二模型 |
| --- | --- | --- |
| Paseo | Claude Code | `claude-sonnet-5-5` → `claude-opus-5-5` |
| Paseo | Codex | `gpt-6.1-sol` → `gpt-6-sol` |
| Omnigent | Claude Code | `haiku` → `sonnet`，實際為 `claude-haiku-4-5-20251001` → `claude-sonnet-5-5` |
| Omnigent | Codex | `gpt-6.1-sol` → `gpt-6-astra` |
| PaaS，兩個 Web | Pi | `woow-litellm/apporo/gpt-6-sol` → `woow-litellm/apporo/gpt-6.1-sol` |
| Podman／HA，Paseo | Pi | `openai-codex/gpt-6.1-sol` → `openai-codex/gpt-6-sol` |
| Podman／HA，Omnigent | Pi | `openai-codex/gpt-6.1-sol` → `openai-codex/gpt-6-astra` |

每次驗收核對新產生的 **assistant** 訊息、後端有效模型與先前上下文；提示文字回顯、模型清單與 host 在線都不算成功。模型切換範圍是同一代理、同一 session；改選 Claude／Codex／Pi 可建立另一個 session，本輪沒有證明不同代理引擎自動共用完整對話歷史。

共用來源是同部署的 `/data/pi-agent/skills` 與 `/data/pi-agent/shared/mcp.json`，修改 registry 後執行 `woow-agent-sync`，並建立新代理 session。驗收的 `woow-connector-proof` skill 與 `woow_connector_proof` MCP 會為每次呼叫產生新證明，核對實際工具端紀錄與助理回覆。技能證據來自完成的 Skill 工具／檔案讀取及其回傳內容，不能只靠助理聲稱已載入。公開時間線不足時，另核對對應的原生 transcript。PaaS Omnigent 初版驗收程式漏認原生紀錄，原始失敗 receipt 保留，校正後以原生 skill 內容及 MCP call/output 補足證據，未因此重複 Claude／Codex 模型測試。

PaaS Paseo Codex 在 Auto review 模式無法建立 bubblewrap user namespace，shell 讀取 skill 失敗。僅該次測試 session 改選 Web 提供的 Full Access 後，重新完成雙模型、上下文、skill 及 MCP 證明；未變更 Pod 安全設定或全域預設。**預設模式完整工具能力仍未通過，不宣稱所有權限模式都已可用。** 其他原有 MCP server 的每項外部功能與 OAuth 也未逐一驗收。

## 套件、修正與部署

兩個插件為 **WOOW Paseo 0.1.4**、**WOOW Omnigent 0.1.4**，已能在 Extensions 頁面看到、安裝及開啟設定／連線面板。可由 [GitHub Actions VSIX 建置](https://github.com/WOOWTECH/Woow_podman_code_server_package/actions/runs/42700359698)下載已核對過的套件；本輪 backend 更新沒有變更 VSIX。

- Paseo VSIX SHA-256：`c09813dad4615ac0a13e44733212c377be311986192d9c0fb519d6acc4677bd7`。
- Omnigent VSIX SHA-256：`c103f205378770c681166aa8f522b29fdd71792d2b9449afa045a756a13ee119`。
- 原生 CLI：Claude Code **2.1.285**、Codex **0.167.0**、Pi **0.99.1**；Paseo **0.11.2**、Omnigent SDK **0.16.0**。

本輪功能來源固定於 `49ef49a`，包含 Omnigent 自訂 Pi 模型目錄修正。原 SDK 只讀 `models-store.json`，漏掉 LiteLLM 等 `models.json` 自訂 provider；修正後只列出原生 auth 中已設定的 provider，保留完整巢狀模型 ID，不把 URL 或憑證加入目錄。兩項回歸在修正前失敗、修正後通過；完整 **30 項 Python（零跳過）、39 項 Node、28 項 extension** 測試通過。PaaS qa6 的實際 Web 模型切換另證明此修正有效。

HA 升版比較曾攔下 23 項新增、可修正的 Critical／High 弱點；已將 CPython 改為 **3.12.16**、uv **0.13.7**，並鎖定 esbuild **0.28.2**。Paseo 相容性測試通過。[新映像的升版比較與 runtime 啟動檢查均已通過](https://github.com/WOOWTECH/Woow_ha_code_server_add_on/actions/runs/42721240766)，沒有以豁免或舊 SBOM 當成修正通過。

| QA 環境 | 目前部署與驗證 |
| --- | --- |
| PaaS | Helm revision 11，`20261110.connectors-paas-qa6@sha256:710f82be57ac0c8547b988a4f37e14230fc8dcee7095c1da037710e29a90a362`；映像內 39 Node＋30 Python 通過。換版後三代理授權與 Pi 設定保留，8 項插件 UI 通過、53 個 backend 檔案符合固定來源；原 host 在線且只有一個 kit supervisor。 |
| HA | `20261110.connectors-ha-qa7`，映像 `sha256:7e6e95c354809135acdac135bf1e7179793468587ef3d4ed8e00d1e2122918c5`；映像內 28 extension＋39 Node＋30 Python 通過。換版後 HTTP、原 host、53 個來源檔案與真正 Ingress 的 8 項 UI 檢查通過，原 QA6 保留作為回復容器。 |
| Podman | 保留 QA3 基底映像與同一容器，原地更新至 `49ef49a`，Python／uv／esbuild 已對齊；暫存與換版後各 97 項測試通過、56 個來源檔案核對通過，共用登入設定及主要容器身分保留。最低剩餘空間約 3.01 GB，原 runtime 的備份與回復程序保留。最終 8 項插件 UI 通過，兩個 connector 在線；Paseo 原配對仍可在瀏覽器開啟工作目錄與新對話輸入框，未再呼叫模型。 |

Podman 原地更新的備份／回復程序另有 8 項回歸測試。一次換版後的測試將暫存檔放在 `/opt` 下，被私有配對計畫的目錄保護檢查攔下；更新程序已實際自動回復並核對雜湊。將測試暫存位置改到 `/tmp` 後重試，97 項換版後測試全部通過，原始失敗與回復證據均保留。

Podman 完整新映像換版先前因 ID-mapped storage copy 所需空間超過容量而回滾，原 QA3 已恢復。保留容器更新不等同新映像；重建容器必須重套更新，或待空間足夠時使用完整映像。Podman QA 與原 code-server 共用代理資料卷，因此不宣稱正式資料完全隔離；本輪沒有更換主要服務映像。

HA 已驗證真正 Supervisor Ingress：經本輪手動啟動的隔離 nginx proxy add-on 連到 QA code-server。主要 add-on 仍為原版本。真實 Ingress 的插件介面檢查通過；先前 VSIX 0.1.3 的兩插件共 6 次 Verify 均有實際模型回覆，0.1.4 修正成功 receipt 顯示與依代理篩選模型後，14 項 UI 檢查通過。Verify 只是單次回覆檢查，完整雙模型與工具證明由上述 Web 測試提供。

預裝 receipt 儲存於各自的 `<extensionsDir>/.woow-connector-seed.json`。實際 code-server CLI 已驗證：兩個獨立 extension store 共用代理資料仍各自安裝；使用者解除安裝後不強制裝回；新建 store 能重新 seed，另一個 store 不受影響。PaaS kit 的唯讀 ConfigMap 以私有 overlay 修正，停止／restore／重啟測試保留原 host，未新增第二個 supervisor。

PaaS 的本輪 proof fixture 已移除並同步三代理。換版後保留原有 `woow_shared_probe`，重啟後另可見 8 個 cloud MCP 配置；三代理的 9 個 server 名稱相同、skills 解析至同一目錄，臨時 proof server 不在其中。此項是配置共用檢查，不等於逐項驗證 9 個服務的外部功能。

整理證據時，子代理曾將 QA IDE 密碼帶入工具輸出；已更換該 QA 密碼並確認舊密碼無法取得登入 cookie、新密碼可登入。Helm revision 11 僅完成此密碼更換與 QA Pod 重啟，映像不變；三代理登入檔、Pi 設定及原 host 身分再次核對保留。LiteLLM key 未涉及此事件。新 QA 存取值僅保留在工作區私有設定中。

## 證據與發布狀態

所有私有 receipt 位於本輪工作區 `connector-qa/`；登入檔、API key、配對連結及原生對話原文未提交到儲存庫。儲存庫內較早的 integration JSON 為該次來源固定時的快照；本報告提供後續實機結果。

| 項目 | 私有 receipt |
| --- | --- |
| Podman／HA Paseo 完整 Web 驗收 | `paseo-web-podman-result.json`、`paseo-web-ha-result.json` |
| Podman／HA Omnigent 完整 Web 驗收 | `omnigent-podman-acceptance.json`、`omnigent-ha-acceptance.json` |
| PaaS Paseo 完整驗收與權限限制 | `paseo-web-paas-qa5-final-result.json`、`paseo-web-paas-qa5-final-skill-audit.json` |
| PaaS Omnigent 三代理及校正證據 | `omnigent-paas-acceptance.json`、`omnigent-paas-claude-codex-finalized.json`、`omnigent-paas-runs/` |
| PaaS 換版、授權與來源保留 | `paas-rollout.json`、`paas-auth-after-restart.json`、`omnigent-paas-49ef49a-readonly.json` |
| Podman 原地更新、實際回復與最終成功 | `podman-refresh49/result-refresh49-5ef55bbc2fb9-apply.json`、`podman-refresh49/result-refresh49-88c6c1a32ab3-apply.json`、`podman-refresh49-v2-rollback-evidence.tar.gz` |
| HA qa7 換版與真正 Ingress | `ha-qa7-rollout.json`、`omnigent-ha-49ef49a-readonly.json`、`runtime-49ef49a-ui/ha-final-image-browser-report.json` |
| PaaS 更新後插件 UI | `runtime-49ef49a-ui/paas-candidate-ui.json` |
| Podman 更新後插件 UI 與原配對 | `runtime-49ef49a-ui/podman-candidate-ui.json`、`paseo-web-podman-49ef49a-persistence.json` |
| PaaS QA IDE 密碼更換與最終持久性 | `qa-ide-password-rotation.json`、`paas-final-persistence.json`、`paas-final-shared-tools.json` |
| HA 真實 Ingress／Verify | `ha-ingress-isolated/completion-receipt.json`、`ha-ingress-isolated/ui-verification/six-valid-receipts-summary.json` |
| VSIX 可重現打包／GitHub 產物 | `vsix-0.1.4/package-report.json`、`github-vsix-0.1.4-verified.json` |

來源已推送至 [Podman PR #16](https://github.com/WOOWTECH/Woow_podman_code_server_package/pull/16)、[HA PR #16](https://github.com/WOOWTECH/Woow_ha_code_server_add_on/pull/16)、[PaaS image PR #622](https://git-prod.woowtech.io/woow-paas/paas-odoo-ci/pulls/622)、[PaaS chart PR #330](https://git-prod.woowtech.io/woow-paas/woow-paas-charts/pulls/330) 及 [k3s PR #6](https://github.com/WOOWTECH/Woow_k3s_code_server_package/pull/6)。尚未合併或正式發版。arm64 有依賴解析與映像建置證據，沒有三代理 runtime 實機驗收；Open VSX 公開上架未完成。QA 存取沿用私有轉送／已驗證 Ingress，沒有新增公開 QA IDE 入口。操作方式見 [CONNECTORS.md](../../CONNECTORS.md)。
