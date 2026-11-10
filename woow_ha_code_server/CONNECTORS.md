# Paseo 與 Omnigent extensions

這個版本提供兩個可安裝的 VS Code 工作區插件：`woowtech.paseo`、
`woowtech.omnigent`。映像內包含對應 runtime；第一次啟動會安裝 VSIX，
因此在 code-server 的 **Extensions → Installed** 可以看到、停用及移除。
移除後不會在下次啟動強制裝回。手動安裝較新的版本也不會被映像降版。

## 安裝與開啟

完整映像會自動安裝插件。單獨安裝 VSIX 時，在 Extensions 的 `…` 選單選擇
**Install from VSIX…**，或在該 code-server 的終端執行：

```sh
code-server --install-extension woowtech.paseo-0.1.4.vsix
code-server --install-extension woowtech.omnigent-0.1.4.vsix
```

CLI 必須指向目前 IDE 使用的 extension store。HA add-on 請在兩個指令加上
`--extensions-dir /data/vscode/extensions`；其他部署若自訂目錄，也要帶入相同參數。
直接使用目前 IDE 的 **Install from VSIX…** 可避免裝入另一個目錄。

VSIX 本身只提供介面；既有的普通 code-server 映像還需要安裝本儲存庫的
runtime。缺少 runtime 時介面會明確顯示，不會宣稱已連線。
需要從原始碼打包時使用 `npm ci --ignore-scripts --prefix extensions`，
接著執行 `npm run package --prefix extensions`；輸出在 `extensions/dist/`。

從左側 **WOOW Paseo** 或 **WOOW Omnigent** 開啟面板，也可在 Command Palette
搜尋 `WOOW Paseo` 或 `WOOW Omnigent`。設定使用目前部署的工作區絕對路徑。

## 連接 Paseo Web

1. 在 Paseo 插件設定工作區及容易識別的主機名稱。
2. 啟動服務，查看本機 daemon 狀態。
3. 選擇配對，使用產生的連結開啟官方 Paseo Web，確認信任此主機。
4. 在 Web 開啟工作區，選擇 Claude Code、Codex 或 Pi，再從即時目錄選擇模型。

配對連結含連線授權資料；插件只在明確點選配對時取得它，不把它放進面板記錄。
本機 daemon 可用與 Web 已配對是不同的狀態。`Verify` 會產生模型請求，
只有助理實際回覆後才會記錄驗證結果。

## 連接 Omnigent

1. 在插件設定 Omnigent 後端 URL、工作區及主機名稱。若瀏覽器需要不同的公開入口，另填 Web URL。
2. 選擇登入，輸入該 **Omnigent 服務** 的帳號及密碼。
3. 檢查主機是否在線，再開啟該 Omnigent Web。
4. 在新對話選擇此主機與 Claude Code、Codex 或 Pi，選擇可用模型後送出訊息。

服務密碼經 stdin 傳到 runtime，不寫入 VS Code 設定、命令列或輸出記錄。
SDK 會在本部署的私有資料卷保存登入 token。公開服務使用 HTTPS；明確設定的
內網 IP、Kubernetes service 或同機容器服務可以使用 HTTP。

PaaS 使用既有 Omnigent host kit 和同一個 host 身分；不會另起第二個 host。
停止會保存停止狀態，重新啟動 code-server 也不會擅自連回。斷線會登出目前
設定的 Omnigent 服務；模型供應商登入不受影響。

## 模型登入、skills 與 MCP

每個部署各自保有模型登入。Paseo 配對、Omnigent 服務登入都不等於模型帳號登入。
請在同一個 code-server 終端登入：

```sh
claude auth login
codex login --device-auth
pi
# 在 Pi 輸入 /login
```

Pi 也可以使用 LiteLLM 等 OpenAI 相容閘道，不必執行 OAuth `/login`。
在本部署的 `/data/pi-agent/models.json` 設定 provider 與模型，並將 API key
保存在私有 `auth.json` 的同名 provider；不要把 key 寫入 VSIX 或 Git。
Omnigent 會列出已設定原生授權的自訂 provider，模型 ID 保留完整的
`provider/model` 路徑。登入完成後重載即時模型目錄，再驗證真實回覆。

三代理共用 `/data/pi-agent/skills` 及 `/data/pi-agent/shared/mcp.json`。
修改 MCP 後，在擴充面板或命令選單選擇 **Refresh shared MCP**，輸入原對話 ID。
此操作會同步共用設定，保留原對話與模型／權限／登入設定，並移除已從共用 registry
刪除的工具。Paseo 的 Claude、Codex、Pi 會在閒置時恢復同一個原生 session；
若有執行中回合或待處理授權，更新會拒絕且不打斷對話。已回收的 session 請先在
Paseo 開啟原對話再更新。舊 daemon 需由操作人員安排閒置升級，按鈕不會重啟服務。
Omnigent Codex 使用原生 MCP reload，顯示已排入下一個回合邊界；工具成功執行須另行驗證。
Omnigent Pi 在同一個原生程序內準備新的 MCP 連線，確認仍閒置後替換工具目錄；
失敗會保留原工具，成功會回報目錄已更新，並不表示已逐項驗證工具執行。
升級前已開啟的 Pi 對話需要先由操作人員安排一次閒置的原生 `/reload`，載入新版
橋接擴充；未載入時會明確拒絕，不會自動重啟或另開對話。詳見
[Pi 原生更新與既有對話準備](connectors/omnigent/pi_mcp_refresh.md)。
Omnigent Claude Code 2.1.285 使用原生佇列的 `/reload-plugins --force`，並以停用的無功能定義淘汰已刪除工具，避免舊工具繼續可用。
介面會區分排隊中、原生 reload 已完成與送出狀態不明；reload 完成不等於工具目錄或實際調用已驗證。
原生程序已停止的既有對話，須先由操作人員以 [嚴格接回流程](connectors/omnigent/claude_strict_resume.md) 驗證並恢復原檔案；更新按鈕不會自行另開對話。
同步／恢復失敗會顯示錯誤，不會另開對話或宣稱已驗證工具。
原生 Claude、Codex、Pi 仍保有自己的登入及個別設定；不會把供應商憑證複製到其他部署。
Omnigent 的私人 session home 會繼承本部署的共用工具設定。
完整共用設定格式見 [THREE_AGENTS.md](THREE_AGENTS.md)。

在同一個代理對話中切換模型，應確認第二輪仍能讀取先前的對話內容。
選擇另一個代理可能建立新的 session，不能假設不同代理會自動承接全部對話。
可用模型以各代理和當下登入帳號回傳的目錄為準。

## 操作與持久化

插件提供狀態、啟動、停止、即時模型目錄及明確觸發的對話驗證。
runtime 狀態位於 `/data/pi-agent/connectors/`，隨既有資料卷備份。
請勿把此目錄加入 Git、映像或公開故障報告。

實作來源、版本及限制見 [研究設計](docs/plans/2026-11-10-paseo-omnigent-extensions.md)、
[Paseo runtime](connectors/paseo/README.md)、[Omnigent runtime](connectors/omnigent/README.md)。
單元測試或主機在線不代表三代理真實對話、模型切換及工具調用均已通過；
部署驗收必須記錄各環境的實際結果。

本輪實際測試範圍與待完成項目見[驗收紀錄](docs/research/code-server-connectors-acceptance-20261110.md)。
