# Woow n8n MCP Server

獨立 amd64 Home Assistant Add-on：把 n8n 的完整工具以 MCP（Streamable HTTP）提供給 AI client。
目前發佈的版本、映像與在 HA 上的實測結果見 [本產品操作](DOCS.md) 開頭。

- 工具：0.2.1 起完整版，上游 28 個工具全部開放，與原始 MCP server 及 PaaS 版一致；全部工具與寫入預設開啟（新安裝與從 0.1.x 升級），可在管理面板逐一停用或取消寫入
  （[逐名工具對照](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/tool-surface.md)）。
- **風險：網址＝完整後端權限**。拿到權杖或 Claude.ai 密鑰網址的 MCP client（包括 AI 助理誤判時）不需再授權就能建立、修改、刪除與執行 workflow，管理 credentials、data table、資料夾與版本。後端錯誤原文回傳（可能含後端內部資訊，add-on 持有的憑證換成 `[REDACTED]`）；後端帳號權限要設對（只給需要的權限），只保留需要的工具與寫入，外洩時立刻在管理面板重新產生權杖（[說明](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/guide.md#寫入預設開啟)）。
- 連線：n8n 的網址與 Public API key；選填 **MCP Access Token**（n8n 設定 → Instance-level MCP，與 API key 不同），版本歷史、資料表欄位、`n8n_test_workflow` prepare／pinned／direct、`n8n_explore_node_resources`、`n8n_manage_agents` 需要它。
- **webhook／URL SSRF 防護已關閉**（`WEBHOOK_SECURITY_MODE=permissive`，使用者 2026-10-15 決定）：可連 HA 內網的 n8n，但 MCP 也能經 n8n-mcp 連到 add-on 能到的任何內網位址。
- 管理面板在 HA 側邊欄（Ingress），只有 HA 的 owner 或系統管理員能設定後端與管理權杖；為了驗證這個身分，
  Add-on 需要 `homeassistant_api: true`，這個 token 具廣泛的 Core 存取能力。`hassio_api: false`、保護模式開啟、無 host 網路。
- MCP client 連 `8081/mcp` 並帶 Bearer 權杖；預設不對 LAN 開埠（`8081/tcp: null`）。Claude.ai 網頁版自訂連接器不能帶 header，改用管理面板產生的密鑰網址 `…/private_<token>/mcp`（0.1.14 起；網址等同密碼）。
- 0.2.2 起後端還沒設定或暫時連不上時，client（含 Claude.ai 連接器）照樣能連線並列出全部工具；呼叫工具會回錯誤說明原因（未設定／連不上）。

請先看 [本產品操作](DOCS.md)、[變更紀錄](CHANGELOG.md)、[共用繁中指南](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/guide.md)
與 [client 設定](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/clients.md)。
