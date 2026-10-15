# Woow Odoo MCP Server

獨立 amd64 Home Assistant Add-on：把 Odoo 的完整工具以 MCP（Streamable HTTP）提供給 AI client。
目前發佈的版本、映像與在 HA 上的實測結果見 [本產品操作](DOCS.md) 開頭。

- 工具：0.2.1 起完整版，上游 41 個工具全部開放，與原始 MCP server 及 PaaS 版一致；全部工具與寫入預設開啟（新安裝與從 0.1.x 升級），可在管理面板逐一停用或取消寫入
  （[逐名工具對照](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/tool-surface.md)）。
- **風險：網址＝完整後端權限**。拿到權杖或 Claude.ai 密鑰網址的 MCP client（包括 AI 助理誤判時）不需再授權就能用 `execute_method` 直接新增、修改、刪除任何 Odoo 紀錄並呼叫任何方法（含 `action_confirm`、`action_post` 等未審查的副作用方法），`chatter_post` 直接送出訊息。後端錯誤原文回傳（可能含後端內部資訊，add-on 持有的憑證換成 `[REDACTED]`）；後端帳號權限要設對（只給需要的權限），只保留需要的工具與寫入，外洩時立刻在管理面板重新產生權杖（[說明](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/guide.md#寫入預設開啟)）。
- 連線：Odoo 網址、資料庫、帳號與密碼（或 API key），建議用最小權限的帳號；後端狀態只代表能否登入。
- 管理面板在 HA 側邊欄（Ingress），只有 HA 的 owner 或系統管理員能設定後端與管理權杖；為了驗證這個身分，
  Add-on 需要 `homeassistant_api: true`，這個 token 具廣泛的 Core 存取能力。`hassio_api: false`、保護模式開啟、無 host 網路。
- MCP client 連 `8081/mcp` 並帶 Bearer 權杖；預設不對 LAN 開埠（`8081/tcp: null`）。Claude.ai 網頁版自訂連接器不能帶 header，改用管理面板產生的密鑰網址 `…/private_<token>/mcp`（0.1.14 起；網址等同密碼）。

請先看 [本產品操作](DOCS.md)、[變更紀錄](CHANGELOG.md)、[共用繁中指南](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/guide.md)
與 [client 設定](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/clients.md)。
