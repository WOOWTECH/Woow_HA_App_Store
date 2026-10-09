# Woow Nextcloud MCP Server

獨立 amd64 Home Assistant Add-on：把一個 Nextcloud 帳號的檔案、行事曆與任務以 MCP（Streamable HTTP）提供給 AI client。
0.1.7 起發佈（本產品第一個版本）；目前發佈的版本、映像與在 HA 上的實測狀態見 [本產品操作](DOCS.md) 開頭。

- 工具：上游 9 個全部支援。預設只開 5 個讀取（檔案樹、讀文字檔、行事曆、任務）；4 個寫入
  （建立／更新文字檔、上傳、刪除）必須由 HA 管理員逐項授權，其中上傳與刪除特別預設關閉
  （[逐名工具對照](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/tool-surface.md)）。
- 連線：Nextcloud 根網址、使用者名稱與 **App 密碼**（Nextcloud「個人設定 → 安全性 → 裝置與工作階段」建立，不要用登入密碼）。
- 管理面板在 HA 側邊欄（Ingress），只有 HA 的 owner 或系統管理員能設定後端與管理權杖；為了驗證這個身分，
  Add-on 需要 `homeassistant_api: true`，這個 token 具廣泛的 Core 存取能力。`hassio_api: false`、保護模式開啟、無 host 網路。
- MCP client 連 `8081/mcp` 並帶 Bearer 權杖；預設不對 LAN 開埠（`8081/tcp: null`）。

請先看 [本產品操作](DOCS.md)、[變更紀錄](CHANGELOG.md)、[共用繁中指南](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/guide.md)
與 [client 設定](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/clients.md)。
