# Headscale 操作說明

## 目前狀態

**0.4.17 已發布並上架；0.4.18 是輸出 schema 發布候選版。** 0.4.17 包含 Core 2026.11 相容性、密鑰網址 Origin 防護及多 DNS 位址連線退避；0.4.18 再讓 11 支 Headscale 工具公開已審查的物件輸出 schema，不變更 29 項原生操作、輸入或權限。正式可用狀態以 [Release](https://github.com/WOOWTECH/Woow_ha_mcp_addons/releases) 和商店版號為準。

## 從商店安裝

在 Home Assistant「設定 → Add-ons → Add-on 商店」加入自訂來源 `https://github.com/WOOWTECH/Woow_HA_App_Store`，重新整理商店，搜尋 **Woow Headscale MCP Server**。0.4.18 完成正式 Release 與商店同步後，確認商店版本為 0.4.18，再按「安裝」與「啟動」，開啟 Web UI。同步前商店顯示已發布的 0.4.17；安裝與更新狀態以 Home Assistant 顯示為準。

## 連線與權限

在 HA 的 Ingress 管理面板填入一台 Headscale 控制伺服器的網址及**專用 API key**。網址填伺服器 origin，例如 `https://headscale.example.com`，也可填該 origin 的 `/api/v1`；不要填其他路徑、查詢參數或使用者資訊。子程序會自行加上 `/api/v1`，並拒絕 loopback 後端、轉址及未通過 TLS 驗證的連線。請優先使用 HTTPS，妥善保管 API key。連線設定及 MCP 政策保存在 `/data/mcp`，不是 HA Add-on options。

管理面板只允許 HA owner 或系統管理員進入。Add-on 為驗證身分使用 `homeassistant_api: true`，其 Supervisor token 具有廣泛的 HA Core 權限，只交給管理程序，不交給 Headscale 子程序。`hassio_api`、host 網路及 Docker API 均未啟用。

新安裝時，11 個工具與 21 個寫入 grant 預設開啟；管理員可在面板逐一停用工具或撤銷寫入。這些工具涵蓋使用者、節點、註冊、預先授權金鑰、API 金鑰、ACL 政策、核准路由及健康檢查等 Headscale v0.29.4 操作。`headscale_routes_replace` **整組取代**節點已核准的路由，傳入空清單會撤銷全部；政策寫入也可能影響整個網路的存取。MCP 權杖代表所設定 API key 可執行的權限，請先在面板限制不需要的工具與寫入，再把權杖交給用戶端。本版不假設 Headscale API key 本身能設定細分權限。完整工具與參數以 [工具對照](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/tool-surface.md) 為準。

## 網路與日常操作

- `8099` 僅供 HA Ingress 管理面板使用，不映射到主機，也不是 MCP 端點。
- `8081/mcp` 是需要 Bearer 權杖的 Streamable HTTP 端點；`8081/tcp: null` 表示預設不對 LAN 開放。只有確實需要外部 MCP 用戶端時才設定主機映射。不能帶 Authorization header 的用戶端可使用面板產生的 `…/private_<token>/mcp` 密鑰網址；網址等同密碼。Headscale 密鑰網址接受沒有 Origin 的原生用戶端及 `https://claude.ai`，其他瀏覽器 Origin 回 403。Origin 不取代權杖；對外開埠時仍須 HTTPS 與網路來源限制。
- `3000` 是容器內的私有子程序埠，只監聽 loopback，不可對外映射。

後端尚未設定或暫時連不上時，管理面板仍可用，MCP 用戶端可 initialize 並列出目前允許的工具，但工具呼叫會回設定或連線錯誤。後端健康檢查只在 Headscale 回報 `databaseConnectivity: true` 時視為成功；斷線時 readiness 回 503，不會因此重啟 Add-on。更換連線或政策可能重啟子程序並使舊 MCP session 失效，用戶端須重新 initialize。

更新前請做冷備份。備份包含 Headscale API key、MCP 權杖及工具政策，應按密碼保護；還原到另一台主機後應輪替憑證。這是新產品，只接受現行 v4 狀態，沒有舊版 Headscale 設定遷移路徑。發佈與實機驗收狀態應以 [發佈關卡](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/release.md) 及本產品正式 Release 為準。
