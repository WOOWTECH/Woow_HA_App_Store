# Woow Headscale MCP Server

**0.4.19 已發布並進入 WOOW HA App Store；0.4.20 是 2026-11-25 的維修版：管理面板接受 HA Core 2026.11.3，並自動放行已審查月份的後續修補版。** 0.4.19 只認到 Core 2026.11.2，在 2026.11.3 上拒絕每個管理面板請求（MCP 端點不受影響）。0.4.20 的映像由 GitHub 託管的發版流程建置並驗收，已發佈的 digest 與驗收結果見 [發佈紀錄](../../docs/operations/release-decision-headscale-0.4.20.md)；0.4.19 的發佈紀錄見 [0.4.19 發佈決策](../../docs/operations/release-decision-headscale-0.4.19.md)，輸出 schema 見 [0.4.18 發佈決策](../../docs/operations/release-decision-headscale-0.4.18.md)；正式可用狀態以 Release 和商店版號為準，其他產品的版號各自獨立。

這個 amd64 Home Assistant Add-on 預計透過 MCP（Streamable HTTP）管理一台 Headscale 控制伺服器。HA owner 或系統管理員在 Ingress 面板設定 Headscale 網址與**專用 API key**；MCP 用戶端以另一把 Bearer 權杖連接 `8081/mcp`，但 8081 預設不對 LAN 開埠。子程序的 3000 埠只在容器內的 loopback 監聽。

Headscale v0.29.4 的 29 個原生 API 操作由 11 個已審查工具提供。新安裝時工具與寫入授權預設開啟，管理員可在面板逐一停用。**取得 MCP 權杖的用戶端可使用已設定 API key 的權限管理節點、路由、使用者、金鑰及政策；發給用戶端前請先檢查面板中的工具與寫入授權。** 本版不假設 Headscale API key 本身能設定細分權限。

設定、權限與版本限制見 [本產品操作說明](DOCS.md)；版本變更見 [CHANGELOG](CHANGELOG.md)。
