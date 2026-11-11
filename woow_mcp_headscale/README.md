# Woow Headscale MCP Server

**0.4.13 已發布並進入 WOOW HA App Store；0.4.14 是 HA Core 2026.11 相容性更新。** 0.4.13 的公開映像、隔離 HAOS 2026.10.4 驗收及 Stable Release 證據見 [發佈決策](../../docs/operations/release-decision-headscale-0.4.13.md)；隔離 HAOS 2026.11.1 實測確認 0.4.13 管理面板會依安全規則拒絕未審核 Core 版本。0.4.14 須完成映像與新版 HAOS 驗收後才能發布。其他七項產品維持各自已發布的 0.4.13 映像。

這個 amd64 Home Assistant Add-on 預計透過 MCP（Streamable HTTP）管理一台 Headscale 控制伺服器。HA owner 或系統管理員在 Ingress 面板設定 Headscale 網址與**專用 API key**；MCP 用戶端以另一把 Bearer 權杖連接 `8081/mcp`，但 8081 預設不對 LAN 開埠。子程序的 3000 埠只在容器內的 loopback 監聽。

Headscale v0.29.4 的 29 個原生 API 操作由 11 個已審查工具提供。新安裝時工具與寫入授權預設開啟，管理員可在面板逐一停用。**取得 MCP 權杖的用戶端可使用已設定 API key 的權限管理節點、路由、使用者、金鑰及政策；發給用戶端前請先檢查面板中的工具與寫入授權。** 本版不假設 Headscale API key 本身能設定細分權限。

設定、權限與版本限制見 [本產品操作說明](DOCS.md)；版本變更見 [CHANGELOG](CHANGELOG.md)。
