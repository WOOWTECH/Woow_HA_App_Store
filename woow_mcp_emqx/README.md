# Woow EMQX MCP Server

獨立 amd64 Home Assistant Add-on：把 EMQX 的部分工具以 MCP（Streamable HTTP）提供給 AI client。
目前發佈的版本、映像與在 HA 上的實測結果見 [本產品操作](DOCS.md) 開頭。

- 工具：上游 39 個中支援 11 個，預設只開讀取；寫入須由 HA 管理員逐項授權，其餘明列不支援
  （[逐名工具對照](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/tool-surface.md)）。
- 連線：EMQX 網址（不含 /api/v5）與 API key／secret。
- 管理面板在 HA 側邊欄（Ingress），只有 HA 的 owner 或系統管理員能設定後端與管理權杖；為了驗證這個身分，
  Add-on 需要 `homeassistant_api: true`，這個 token 具廣泛的 Core 存取能力。`hassio_api: false`、保護模式開啟、無 host 網路。
- MCP client 連 `8081/mcp` 並帶 Bearer 權杖；預設不對 LAN 開埠（`8081/tcp: null`）。

請先看 [本產品操作](DOCS.md)、[變更紀錄](CHANGELOG.md)、[共用繁中指南](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/guide.md)
與 [client 設定](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/clients.md)。
